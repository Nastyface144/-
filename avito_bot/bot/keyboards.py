"""Клавиатуры бота."""

from __future__ import annotations

from typing import Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

BTN_ACCOUNTS = "👤 Аккаунты"
BTN_NICHES = "🎯 Ниши"
BTN_TEMPLATES = "💬 Клише"
BTN_STATS = "📊 Статистика"
BTN_SETTINGS = "⚙️ Настройки"
BTN_QUEUE = "📮 Очередь"
BTN_DEMO = "🧪 Демо"


def main_menu(dry_run: bool) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_ACCOUNTS), KeyboardButton(text=BTN_NICHES)],
        [KeyboardButton(text=BTN_TEMPLATES), KeyboardButton(text=BTN_QUEUE)],
        [KeyboardButton(text=BTN_STATS), KeyboardButton(text=BTN_SETTINGS)],
    ]
    if dry_run:
        rows.append([KeyboardButton(text=BTN_DEMO)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def accounts_kb(accounts: Sequence) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for acc in accounts:
        mark = "✅ " if acc["is_active"] else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{acc['title']}", callback_data=f"acc:use:{acc['id']}"
                ),
                InlineKeyboardButton(text="🔌 Проверить", callback_data=f"acc:check:{acc['id']}"),
                InlineKeyboardButton(text="🗑", callback_data=f"acc:del:{acc['id']}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="acc:add")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def niches_kb(niches: Sequence) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for niche in niches:
        flags = "✅" if niche["is_active"] else "⛔️"
        if niche["is_default"]:
            flags += "⭐️"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{flags} {niche['title']}", callback_data=f"niche:show:{niche['id']}"
                ),
                InlineKeyboardButton(text="⭐️", callback_data=f"niche:def:{niche['id']}"),
                InlineKeyboardButton(text="↔️", callback_data=f"niche:toggle:{niche['id']}"),
                InlineKeyboardButton(text="🗑", callback_data=f"niche:del:{niche['id']}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ Добавить нишу", callback_data="niche:add")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def niche_pick_kb(niches: Sequence, action: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=niche["title"], callback_data=f"{action}:{niche['id']}")]
        for niche in niches
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(
        text="Сначала добавьте нишу", callback_data="niche:add"
    )]])


def templates_kb(niche_id: int, templates: Sequence) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for tpl in templates:
        label = "↩️" if tpl["kind"] == "reply" else "⏰"
        preview = tpl["body"][:28].replace("\n", " ")
        rows.append(
            [
                InlineKeyboardButton(text=f"{label} {preview}…", callback_data="noop"),
                InlineKeyboardButton(text="🗑", callback_data=f"tpl:del:{tpl['id']}"),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="➕ Автоответ", callback_data=f"tpl:add:{niche_id}:reply"),
            InlineKeyboardButton(
                text="➕ Follow-up", callback_data=f"tpl:add:{niche_id}:followup"
            ),
        ]
    )
    rows.append([InlineKeyboardButton(text="⬅️ К нишам", callback_data="tpl:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_kb(paused: bool) -> InlineKeyboardMarkup:
    toggle = "▶️ Возобновить отправку" if paused else "⏸ Поставить на паузу"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle, callback_data="set:pause")],
            [InlineKeyboardButton(text="Лимит в сутки", callback_data="set:num:daily_limit")],
            [
                InlineKeyboardButton(
                    text="Пауза между сообщениями", callback_data="set:num:send_interval_seconds"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Период опроса чатов", callback_data="set:num:poll_interval_seconds"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Через сколько часов follow-up",
                    callback_data="set:num:followup_after_hours",
                )
            ],
        ]
    )


def demo_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📨 Новое входящее", callback_data="demo:new")],
            [InlineKeyboardButton(text="🔄 Опросить чаты сейчас", callback_data="demo:poll")],
            [InlineKeyboardButton(text="📤 Отправить из очереди", callback_data="demo:send")],
            [InlineKeyboardButton(text="⏩ Состарить чаты на 48ч", callback_data="demo:age")],
        ]
    )
