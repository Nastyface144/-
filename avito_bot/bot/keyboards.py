"""Клавиатуры бота. Формулировки — обычным языком, без внутренних терминов."""

from __future__ import annotations

from typing import Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

BTN_ANSWERS = "✏️ Ответы"
BTN_REPORT = "📊 Отчёт"
BTN_CHECK = "🩺 Проверка"
BTN_SETTINGS = "⚙️ Настройки"
BTN_HELP = "❓ Помощь"

# Готовые направления, чтобы не заставлять клиента придумывать ключевые слова.
PRESETS = [
    ("kv", "Квартиры в аренду", "квартир, сда"),
    ("room", "Комнаты в аренду", "комнат, сда"),
    ("house", "Дома в аренду", "дом, сда"),
]


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ANSWERS), KeyboardButton(text=BTN_REPORT)],
            [KeyboardButton(text=BTN_CHECK), KeyboardButton(text=BTN_SETTINGS)],
            [KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
    )


def start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Настроить за 3 шага", callback_data="wiz:start")]
        ]
    )


def wizard_avito_kb(demo_allowed: bool) -> InlineKeyboardMarkup:
    rows = []
    if demo_allowed:
        rows.append(
            [InlineKeyboardButton(text="Пропустить — сначала посмотрю", callback_data="wiz:demo")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def presets_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=title, callback_data=f"wiz:preset:{slug}")]
        for slug, title, _ in PRESETS
    ]
    rows.append([InlineKeyboardButton(text="Другое — напишу сам", callback_data="wiz:custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def example_kb(callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Взять пример", callback_data=callback)]]
    )


def followup_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Взять пример", callback_data="wiz:example:followup")],
            [InlineKeyboardButton(text="Не нужно напоминание", callback_data="wiz:skip:followup")],
        ]
    )


def directions_kb(niches: Sequence) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for niche in niches:
        mark = "" if niche["is_active"] else "⏸ "
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{niche['title']}", callback_data=f"dir:open:{niche['id']}"
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="➕ Добавить направление", callback_data="dir:add")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def direction_kb(niche_id: int, is_active: bool) -> InlineKeyboardMarkup:
    toggle = "▶️ Включить" if not is_active else "⏸ Выключить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Первый ответ", callback_data=f"dir:edit:{niche_id}:reply"
                ),
                InlineKeyboardButton(
                    text="✏️ Напоминание", callback_data=f"dir:edit:{niche_id}:followup"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔤 Слова", callback_data=f"dir:edit:{niche_id}:keywords"
                ),
                InlineKeyboardButton(
                    text="🏷 Название", callback_data=f"dir:edit:{niche_id}:title"
                ),
            ],
            [
                InlineKeyboardButton(text=toggle, callback_data=f"dir:toggle:{niche_id}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"dir:del:{niche_id}"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="dir:list")],
        ]
    )


def confirm_delete_kb(niche_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, удалить", callback_data=f"dir:delyes:{niche_id}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"dir:open:{niche_id}"),
            ]
        ]
    )


def settings_kb(paused: bool) -> InlineKeyboardMarkup:
    toggle = "▶️ Включить отправку" if paused else "⏸ Остановить отправку"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle, callback_data="set:pause")],
            [InlineKeyboardButton(text="🔌 Аккаунт Авито", callback_data="acc:list")],
            [
                InlineKeyboardButton(
                    text="📈 Сколько сообщений в день", callback_data="set:num:daily_limit"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⏰ Когда напоминать", callback_data="set:num:followup_after_hours"
                )
            ],
        ]
    )


def accounts_kb(accounts: Sequence) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for acc in accounts:
        mark = "✅ " if acc["is_active"] else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{acc['title']}", callback_data=f"acc:use:{acc['id']}"
                ),
                InlineKeyboardButton(text="🗑", callback_data=f"acc:del:{acc['id']}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ Подключить аккаунт", callback_data="acc:add")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="set:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
