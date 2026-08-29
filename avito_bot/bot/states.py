"""FSM-состояния диалогов бота."""

from aiogram.fsm.state import State, StatesGroup


class AddAccount(StatesGroup):
    title = State()
    client_id = State()
    client_secret = State()


class AddNiche(StatesGroup):
    title = State()
    keywords = State()


class AddTemplate(StatesGroup):
    body = State()


class EditNumber(StatesGroup):
    value = State()


class DemoChat(StatesGroup):
    item_title = State()
