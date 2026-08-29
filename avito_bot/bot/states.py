"""FSM-состояния диалогов бота."""

from aiogram.fsm.state import State, StatesGroup


class Wizard(StatesGroup):
    """Мастер первой настройки: Авито → направление → тексты ответов."""

    client_id = State()
    client_secret = State()
    niche_title = State()
    niche_keywords = State()
    reply_text = State()
    followup_text = State()


class AddDirection(StatesGroup):
    """Добавление нового направления уже после настройки."""

    title = State()
    keywords = State()
    reply_text = State()


class EditField(StatesGroup):
    """Изменение одного поля направления."""

    value = State()


class AddAccount(StatesGroup):
    client_id = State()
    client_secret = State()


class EditNumber(StatesGroup):
    value = State()
