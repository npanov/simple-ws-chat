#!/usr/bin/env python

import os
import sys
import asyncio
import json
import hashlib
import uuid
import functools
import operator

import websockets

WS_ADDRESS = 'localhost'
WS_PORT = 8765

active_users = dict()


def make_hash(input):
  '''Хэширование паролей'''
  return hashlib.sha224(str(input).encode("utf_8")).hexdigest()

def generate_token():
  '''Генератор токенов сессий'''
  return uuid.uuid4().hex

def ok(d, ok=True):
  '''Статусы ответа сервера, обертка'''
  if ok:
    d['status'] = 'OK'  
  else: 
    d['status'] = 'ERROR'
  return d


'''
TODO: асинхронные функции, работающие с хранилищами
'''
USERS = {}

async def save_new_user(data):
  '''Сохранение нового юзера'''
  USERS[data['name']] = data['hashed_pass']
  return True


async def name_exists(name):
  '''Проверка юзернейма на сущестование (АС)'''
  return name in USERS.keys()


async def check_credentials(name, passw):
  '''Проверка реквизитов'''
  name_already_exists = await name_exists(name)
  if not name_already_exists:
    raise CustomError("username does not exist")
  if USERS[name] != make_hash(passw):
    raise CustomError("wrong password")
  return True
'''
'''

class CustomError(Exception):
  '''Класс исключение с кастомным сообщением для вывода в клиенте'''
  def __init__(self, desc):
    self.desc = desc


actions = {}
def action(action_func):
  '''Регистрирующий декоратор для клиентских экшнов'''
  actions[action_func.__name__] = action_func
  return action_func


def action_log(action_func):
  '''Декоратор, выводящий вызововы в консоль сервера'''
  @functools.wraps(action_func)
  def inner(*args, **kwargs):
    #print(action_func.__name__)
    #print(*args)
    print("REQUEST FROM {}".format(repr(args[0])))
    for k, v in args[1].items():
        print ("{:<8} {:<15}".format(k, str(v)))
    return action_func(*args, **kwargs)
  return inner


async def check_username(name):
  '''Проверка юзернейма при регистрации'''
  
  # здесь должен быть асинхронный запос к БД
  name_already_exists = await name_exists(name)
  if name_already_exists:
    raise CustomError("username already exists")
  # проверка на длину
  if len(name) < 3 or len(name) > 24:
    raise CustomError("username must be 3 to 24 chars long")
  # еще проверка
  profanity = {'fuck', 'shit'}
  if name in profanity:
    raise CustomError("obscene usernames are forbidden")
  # etc.
  return True


'''Контроллеры'''

@action
@action_log
async def register(websocket, data):
  '''Контроллер регистрации пользователя'''
  if not data.get('name') or not data.get('pass'):
    raise CustomError("empty credentials (name or pass)")

  try:
    await check_username(data['name'])
  except CustomError:
    raise

  try:
    await save_new_user({"name": data["name"], "hashed_pass": make_hash(data["pass"])})
  except Exception as exc:
    raise CustomError("could not save new user") from exc # TODO:

  res = dict(data) # для наглядности
  del res['pass']
  return ok(res)


@action
@action_log
async def login(websocket, data):
  '''Контроллер аутентификации пользователя'''
  if not data.get('name') or not data.get('pass'):
    raise CustomError("empty credentials (name or pass)")

  name = data.get('name')
  passw = data.get('pass')

  if name in active_users.keys():
    raise CustomError("user already logged in")

  try:
    await check_credentials(name, passw)
  except CustomError:
    raise

  token = generate_token()
  active_users[name] = {"websocket": websocket, "token": token}
  for _, client_data in active_users.items():
    info = '{} has joined the chat'.format(name)
    await client_data['websocket'].send(str({"info": info}))  

  res = dict(data) # для наглядности
  del res['pass']
  res["token"] = token
  return ok(res)


@action
@action_log
async def logout(websocket, data):

  name = data.get('name')
  if not name:
    raise CustomError("name not specified")

  if name not in active_users.keys():
    raise CustomError("user not logged in")

  if not 'token' in data or active_users[name]['token'] !=  data['token']: # TODO: decent validation
    raise CustomError("wrong token")

  del active_users[name]

  for _, client_data in active_users.items():
    info = '{} has left the chat'.format(name)
    await client_data['websocket'].send(str({"info": info})) 

  res = dict(data) # для наглядности
  del res['token']
  return ok(res)


@action
@action_log
async def list_active(websocket, data):
  '''Список пользователей онлайн, доступен без авторизации'''
  users = list(active_users.keys())
  res = dict(data) # для наглядности
  res["info"] = users
  return ok(res)


@action
@action_log
async def send_msg(websocket, data):
  '''Контроллер отправки сообщений'''

  sender = data.get('name')
  if not sender:
    raise CustomError("sender name missing")

  if not 'token' in data or active_users[sender]['token'] !=  data['token']: # TODO: decent validation
    raise CustomError("wrong token")

  recipients = data.get('to')
  if not recipients:
    '''Если получатель не указан эксплицитно, отправляем всем'''
    recipients = list(active_users.keys())

  if not isinstance(recipients, list): # строго список в данном случае
    raise CustomError("'to' must be a list")

  msg = data.get('msg')
  if not msg:
    raise CustomError("empty message")

  for recipient in recipients: # EAFP во всей красе 
    try:
      client_ws = active_users[recipient]['websocket']
      await client_ws.send(str(ok({"name": sender, "msg": msg})))
    except KeyError:
      await websocket.send(str(ok({"info": "could not deliver to {}, user is offline".format(recipient)}, False)))

  res = dict(data) # для наглядности
  del res['token']
  return ok(res)


async def main_coro(websocket, path):
  '''Главная сопрограмма'''
  print('INFO: new client connection', websocket)
  print('INFO: ({} clients online)'.format(len(active_users)))

  while True:

    try:
      json_data = await websocket.recv()
    except websockets.exceptions.ConnectionClosed:
      #TODO: optimise logout
      for k, v in active_users.items():
        if v['websocket'] == websocket:
          name = k
          break
      if name:
        del active_users[name]
        print('Client closed connection', websocket)
        for _, client_data in active_users.items():
          await client_data['websocket'].send(name + ' has left the chat')
        break
      
    try:
      data = json.loads(json_data)
    except json.decoder.JSONDecodeError:
      res = {"info": "invalid JSON"}
      res = ok(res, False)
    else:

      if 'action' not in data or data['action'] not in actions.keys():
        res = {"info": "action not implemented"}
        res = ok(res, False)
      else:
        action = data['action']
        #print("Action: {}".format(action))
        try:
          res = await actions[action](websocket, data) # диспетчеризация по зарегистрированным экшнам
        except CustomError as exc:
          res = {"info": exc.desc}
          res = ok(res, False)

    print("RESPONSE TO {} : {}".format(websocket, str(res)))
    await websocket.send(str(res))

if __name__ == '__main__':
  # main(*sys.argv[:1])
  loop = asyncio.get_event_loop()
  start_server = websockets.serve(main_coro, WS_ADDRESS, WS_PORT)
  loop.run_until_complete(start_server)
  loop.run_forever()
