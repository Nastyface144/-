"""Хендлеры бота. Интерфейс рассчитан на человека, который не разбирается
в устройстве бота: мастер настройки, один экран на направление и обычный язык.
"""

from __future__ import annotations

import html
import re

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from ..services.selftest import run_self_test
from . import keyboards as kb
from .context import AppContext
from .states import AddAccount, AddDirection, EditField, EditNumber, Wizard

SLUG_RE = re.compile(r"[^a-z0-9а-яё]+")

EXAMPLE_REPLY = (
    "Здравствуйте! Спасибо за обращение по объявлению «{item_title}».\n"
    "Вариант свободен. Подскажите, на какой срок планируете и когда удобно посмотреть?"
)
EXAMPLE_FOLLOWUP = (
    "Здравствуйте! Напоминаю про «{item_title}» — вариант ещё актуален.\n"
    "Если интересно, подберу удобное время для просмотра."
)

KEYWORDS_HELP = (
    "Пришлите слова через запятую. Бот ответит, если <b>все</b> они есть "
    "в названии объявления.\n\n"
    "Пишите корень без окончания: <code>квартир</code> подойдёт и к «квартира», "
    "и к «квартиру».\n\n"
    "Пример: <code>квартир, сда</code> — сработает на «Сдам квартиру, 2-к, длительно»."
)
PLACEHOLDER_HELP = (
    "В тексте можно написать <code>{item_title}</code> — бот подставит "
    "название вашего объявления."
)

SETTING_TITLES = {
    "daily_limit": "Сколько сообщений в день",
    "followup_after_hours": "Через сколько часов напоминать",
}
SETTING_BOUNDS = {"daily_limit": (1, 500), "followup_after_hours": (1, 720)}


def esc(value: object) -> str:
    return html.escape(str(value))


def slugify(title: str) -> str:
    return SLUG_RE.sub("-", title.lower()).strip("-")[:64] or "napravlenie"


class AdminFilter(BaseFilter):
    async def __call__(self, event: TelegramObject, ctx: AppContext) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user and ctx.settings.is_admin(user.id))


# ---------------------------------------------------------------- старт и справка

async def cmd_start(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    if await ctx.db.is_configured():
        await message.answer(
            "Бот на связи и отвечает на обращения по вашим объявлениям.\n\n"
            "Внизу — четыре кнопки. Начните с «🩺 Проверка», если хотите убедиться, "
            "что всё работает.",
            reply_markup=kb.main_menu(),
        )
        return
    mode = (
        "\n\n<i>Сейчас включён режим проверки: бот работает на учебных данных, "
        "в Авито ничего не уходит.</i>"
        if ctx.settings.dry_run
        else ""
    )
    await message.answer(
        "<b>Здравствуйте!</b>\n\n"
        "Этот бот сам отвечает людям, которые пишут вам по объявлениям на Авито, "
        "и напоминает о себе тем, кто замолчал.\n\n"
        "Настройка займёт пару минут — я проведу по шагам." + mode,
        reply_markup=kb.start_kb(),
    )


async def cmd_help(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "<b>Как это работает</b>\n\n"
        "Человек пишет вам по объявлению на Авито → бот сразу отвечает вашим текстом. "
        "Если человек не ответил в течение суток — бот напоминает о себе.\n\n"
        "<b>Кнопки</b>\n"
        "✏️ <b>Ответы</b> — что и на какие объявления отвечать.\n"
        "📊 <b>Отчёт</b> — сколько сообщений ушло и кому.\n"
        "🩺 <b>Проверка</b> — бот сам себя проверит и скажет, всё ли в порядке.\n"
        "⚙️ <b>Настройки</b> — аккаунт Авито, лимит в день, пауза.\n\n"
        "Заново настроить всё с нуля — команда /start.\n"
        "Прервать любой вопрос бота — команда /cancel.",
        reply_markup=kb.main_menu(),
    )


async def cmd_cancel(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменил.", reply_markup=kb.main_menu())


# ---------------------------------------------------------------- мастер настройки

async def wiz_start(call: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    await state.set_state(Wizard.client_id)
    await call.message.answer(
        "<b>Шаг 1 из 3 — подключим Авито</b>\n\n"
        "Бот отвечает от имени вашего аккаунта, поэтому ему нужен доступ. "
        "Он выдаётся в кабинете Авито: <b>Настройки → Доступ к API</b>. "
        "Там создаётся приложение, и Авито показывает два кода.\n\n"
        "Пришлите первый — <b>client_id</b>.",
        reply_markup=kb.wizard_avito_kb(ctx.settings.dry_run),
    )
    await call.answer()


async def wiz_demo(call: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    await ctx.db.add_account("Режим проверки", "demo", ctx.box.encrypt("demo"))
    await call.answer("Хорошо, подключим Авито позже")
    await ask_direction(call.message, ctx, state)


async def wiz_client_id(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.update_data(client_id=(message.text or "").strip())
    await state.set_state(Wizard.client_secret)
    await message.answer(
        "Принял. Теперь пришлите второй код — <b>client_secret</b>.\n\n"
        "<i>После отправки удалите своё сообщение: Telegram не разрешает ботам "
        "удалять чужие сообщения.</i>"
    )


async def wiz_client_secret(message: Message, ctx: AppContext, state: FSMContext) -> None:
    data = await state.get_data()
    secret = (message.text or "").strip()
    try:
        await ctx.db.add_account(
            "Мой Авито", data.get("client_id", ""), ctx.box.encrypt(secret)
        )
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"Не удалось сохранить: {esc(exc)}\nПопробуйте ещё раз.")
        return
    await message.answer("Аккаунт сохранён ✅")
    await ask_direction(message, ctx, state)


async def ask_direction(target: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.set_state(None)
    await target.answer(
        "<b>Шаг 2 из 3 — о чём ваши объявления?</b>\n\n"
        "Это нужно, чтобы бот отвечал по делу. Выберите готовый вариант "
        "или напишите свой.",
        reply_markup=kb.presets_kb(),
    )


async def wiz_preset(call: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    slug = call.data.split(":")[-1]
    for preset_slug, title, keywords in kb.PRESETS:
        if preset_slug == slug:
            niche_id = await ctx.db.add_niche(slugify(title), title, keywords)
            await state.update_data(niche_id=niche_id)
            await call.answer()
            await ask_reply_text(call.message, ctx, state)
            return
    await call.answer("Не нашёл такой вариант", show_alert=True)


async def wiz_custom(call: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    await state.set_state(Wizard.niche_title)
    await call.message.answer(
        "Как назовём направление? Это название видите только вы.\n\n"
        "Например: <code>Квартиры в аренду</code>"
    )
    await call.answer()


async def wiz_niche_title(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.update_data(title=(message.text or "").strip() or "Мои объявления")
    await state.set_state(Wizard.niche_keywords)
    await message.answer("Теперь слова, по которым бот узнаёт ваши объявления.\n\n" + KEYWORDS_HELP)


async def wiz_niche_keywords(message: Message, ctx: AppContext, state: FSMContext) -> None:
    data = await state.get_data()
    title = str(data.get("title", "Мои объявления"))
    niche_id = await ctx.db.add_niche(slugify(title), title, (message.text or "").strip())
    await state.update_data(niche_id=niche_id)
    await ask_reply_text(message, ctx, state)


async def ask_reply_text(target: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.set_state(Wizard.reply_text)
    await target.answer(
        "<b>Шаг 3 из 3 — что отвечать?</b>\n\n"
        "Напишите текст, который бот отправит человеку, обратившемуся по объявлению.\n\n"
        + PLACEHOLDER_HELP,
        reply_markup=kb.example_kb("wiz:example:reply"),
    )


async def wiz_example_reply(call: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    await save_wizard_reply(call.message, ctx, state, EXAMPLE_REPLY)
    await call.answer("Взял пример")


async def wiz_reply_text(message: Message, ctx: AppContext, state: FSMContext) -> None:
    body = (message.text or "").strip()
    if not body:
        await message.answer("Текст пустой — пришлите ещё раз.")
        return
    await save_wizard_reply(message, ctx, state, body)


async def save_wizard_reply(
    target: Message, ctx: AppContext, state: FSMContext, body: str
) -> None:
    data = await state.get_data()
    niche_id = int(data.get("niche_id", 0))
    await ctx.db.set_template_body(niche_id, "reply", body)
    await state.set_state(Wizard.followup_text)
    await target.answer(
        "Готово. Последний вопрос: что написать человеку, который прочитал "
        "и не ответил в течение суток?\n\n"
        "Это помогает вернуть тех, кто просто забыл.",
        reply_markup=kb.followup_kb(),
    )


async def wiz_example_followup(call: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    await finish_wizard(call.message, ctx, state, EXAMPLE_FOLLOWUP)
    await call.answer("Взял пример")


async def wiz_skip_followup(call: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    await finish_wizard(call.message, ctx, state, None)
    await call.answer()


async def wiz_followup_text(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await finish_wizard(message, ctx, state, (message.text or "").strip() or None)


async def finish_wizard(
    target: Message, ctx: AppContext, state: FSMContext, followup: str | None
) -> None:
    data = await state.get_data()
    niche_id = int(data.get("niche_id", 0))
    if followup:
        await ctx.db.set_template_body(niche_id, "followup", followup)
    await state.clear()
    note = (
        "\n\n<i>Сейчас включён режим проверки — в Авито ничего не уходит. "
        "Когда будете готовы, подключите настоящий аккаунт в «Настройках».</i>"
        if ctx.settings.dry_run
        else ""
    )
    await target.answer(
        "<b>Всё настроено ✅</b>\n\n"
        "Бот следит за чатами и отвечает сам. Ничего запускать не нужно.\n\n"
        "Нажмите <b>🩺 Проверка</b> — бот прогонит себя по всей цепочке "
        "и покажет, что всё в порядке." + note,
        reply_markup=kb.main_menu(),
    )


# ---------------------------------------------------------------- ответы

async def show_directions(target: Message, ctx: AppContext) -> None:
    niches = await ctx.db.list_niches()
    if not niches:
        await target.answer(
            "Пока не настроено ни одного направления. Нажмите /start — настрою за пару минут.",
            reply_markup=kb.main_menu(),
        )
        return
    lines = ["<b>Ваши ответы</b>", ""]
    incomplete = False
    for niche in niches:
        state = "" if niche["is_active"] else " (выключено)"
        words = niche["keywords"] or "любые объявления"
        has_reply = await ctx.db.primary_template(int(niche["id"]), "reply") is not None
        mark = "" if has_reply else " ⚠️"
        incomplete = incomplete or not has_reply
        lines.append(f"• <b>{esc(niche['title'])}</b>{state}{mark} — {esc(words)}")
    lines += ["", "Нажмите на направление, чтобы посмотреть и изменить тексты."]
    if incomplete:
        lines.append(
            "\n⚠️ — нет текста ответа. Такое направление бот не использует: "
            "допишите текст или удалите его."
        )
    await target.answer("\n".join(lines), reply_markup=kb.directions_kb(niches))


async def show_direction(target: Message, ctx: AppContext, niche_id: int) -> None:
    niche = await ctx.db.get_niche(niche_id)
    if niche is None:
        await target.answer("Направление не найдено.")
        return
    reply = await ctx.db.primary_template(niche_id, "reply")
    followup = await ctx.db.primary_template(niche_id, "followup")
    hours = await ctx.db.get_int_setting(
        "followup_after_hours", ctx.settings.followup_after_hours
    )
    words = niche["keywords"] or "любые объявления, не подошедшие под другие направления"
    text = [
        f"<b>{esc(niche['title'])}</b>",
        "" if niche["is_active"] else "⏸ Сейчас выключено\n",
        "Бот отвечает, если в названии объявления есть:",
        f"<b>{esc(words)}</b>",
        "",
        "<b>Первый ответ:</b>",
        f"<blockquote>{esc(reply['body'])}</blockquote>"
        if reply
        else "⚠️ не задан — без него направление не работает",
        "",
        f"<b>Напоминание через {hours} ч:</b>",
        f"<blockquote>{esc(followup['body'])}</blockquote>" if followup else "не настроено",
    ]
    await target.answer(
        "\n".join(text), reply_markup=kb.direction_kb(niche_id, bool(niche["is_active"]))
    )


async def answers_menu(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    await show_directions(message, ctx)


async def dir_list(call: CallbackQuery, ctx: AppContext) -> None:
    await show_directions(call.message, ctx)
    await call.answer()


async def dir_open(call: CallbackQuery, ctx: AppContext) -> None:
    await show_direction(call.message, ctx, int(call.data.split(":")[-1]))
    await call.answer()


async def dir_toggle(call: CallbackQuery, ctx: AppContext) -> None:
    niche_id = int(call.data.split(":")[-1])
    await ctx.db.toggle_niche(niche_id)
    await call.answer("Готово")
    await show_direction(call.message, ctx, niche_id)


async def dir_delete_ask(call: CallbackQuery, ctx: AppContext) -> None:
    niche_id = int(call.data.split(":")[-1])
    await call.message.answer(
        "Удалить направление вместе с его текстами?",
        reply_markup=kb.confirm_delete_kb(niche_id),
    )
    await call.answer()


async def dir_delete(call: CallbackQuery, ctx: AppContext) -> None:
    await ctx.db.delete_niche(int(call.data.split(":")[-1]))
    await call.answer("Удалено")
    await show_directions(call.message, ctx)


FIELD_PROMPTS = {
    "reply": "Пришлите новый текст первого ответа.\n\n" + PLACEHOLDER_HELP,
    "followup": "Пришлите новый текст напоминания.\n\n" + PLACEHOLDER_HELP,
    "keywords": KEYWORDS_HELP,
    "title": "Пришлите новое название направления.",
}


async def dir_edit(call: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    _, _, niche_id, field = call.data.split(":")
    await state.set_state(EditField.value)
    await state.update_data(niche_id=int(niche_id), field=field)
    await call.message.answer(FIELD_PROMPTS[field])
    await call.answer()


async def dir_edit_value(message: Message, ctx: AppContext, state: FSMContext) -> None:
    data = await state.get_data()
    niche_id = int(data.get("niche_id", 0))
    field = str(data.get("field", ""))
    value = (message.text or "").strip()
    if not value:
        await message.answer("Пусто — пришлите ещё раз.")
        return
    await state.clear()
    if field in {"reply", "followup"}:
        await ctx.db.set_template_body(niche_id, field, value)
    elif field == "keywords":
        await ctx.db.update_niche(niche_id, keywords=value)
    elif field == "title":
        await ctx.db.update_niche(niche_id, title=value)
    await message.answer("Сохранил ✅")
    await show_direction(message, ctx, niche_id)


async def dir_add(call: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    await state.set_state(AddDirection.title)
    await call.message.answer(
        "Как назовём новое направление?\n\nНапример: <code>Комнаты в аренду</code>"
    )
    await call.answer()


async def dir_add_title(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.update_data(title=(message.text or "").strip() or "Новое направление")
    await state.set_state(AddDirection.keywords)
    await message.answer(KEYWORDS_HELP)


async def dir_add_keywords(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.update_data(keywords=(message.text or "").strip())
    await state.set_state(AddDirection.reply_text)
    await message.answer("Что отвечать на обращения по таким объявлениям?\n\n" + PLACEHOLDER_HELP)


async def dir_add_reply(message: Message, ctx: AppContext, state: FSMContext) -> None:
    data = await state.get_data()
    body = (message.text or "").strip()
    if not body:
        await message.answer("Текст пустой — пришлите ещё раз.")
        return
    title = str(data.get("title", "Новое направление"))
    niche_id = await ctx.db.add_niche(slugify(title), title, str(data.get("keywords", "")))
    await ctx.db.set_template_body(niche_id, "reply", body)
    await state.clear()
    await message.answer("Направление добавлено ✅")
    await show_direction(message, ctx, niche_id)


# ---------------------------------------------------------------- отчёт

async def report(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    account = await ctx.db.get_active_account()
    if account is None:
        await message.answer("Бот ещё не настроен. Нажмите /start.", reply_markup=kb.main_menu())
        return
    account_id = int(account["id"])
    limit = await ctx.sender.daily_limit()
    today = await ctx.db.sent_today(account_id)
    total = await ctx.db.total_sent(account_id)
    paused = await ctx.sender.is_paused()
    failed = await ctx.db.failed_count(account_id)

    lines = [
        "<b>Отчёт</b>",
        "",
        f"Сегодня отправлено: <b>{today}</b> из {limit}",
        f"Всего отправлено: {total}",
        "Состояние: " + ("⏸ на паузе" if paused else "▶️ работает"),
    ]
    if failed:
        lines.append(f"Не удалось отправить: {failed}")
    if ctx.settings.dry_run:
        lines.append("<i>Режим проверки: в Авито ничего не уходит.</i>")

    rows = [r for r in await ctx.db.recent_sends(account_id, limit=20) if r["status"] == "sent"]
    if rows:
        lines += ["", "<b>Последние сообщения</b>"]
        for row in rows[:5]:
            kind = "ответ" if row["kind"] == "reply" else "напоминание"
            when = (row["sent_at"] or "")[:16].replace("T", " ")
            lines.append(f"• {esc(when)} · {kind}")
            lines.append(f"<blockquote>{esc(row['body'][:150])}</blockquote>")
    else:
        lines += ["", "Сообщений пока не было."]
    await message.answer("\n".join(lines), reply_markup=kb.main_menu())


# ---------------------------------------------------------------- проверка

async def check(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    waiting = await message.answer("Проверяю…")
    text = await run_self_test(ctx.db, ctx.settings, ctx.poller, ctx.sender)
    try:
        await waiting.edit_text(text)
    except Exception:  # noqa: BLE001 — не вышло отредактировать, пришлём новым
        await message.answer(text)


# ---------------------------------------------------------------- настройки

async def show_settings(target: Message, ctx: AppContext) -> None:
    account = await ctx.db.get_active_account()
    paused = await ctx.sender.is_paused()
    limit = await ctx.sender.daily_limit()
    hours = await ctx.db.get_int_setting(
        "followup_after_hours", ctx.settings.followup_after_hours
    )
    lines = [
        "<b>Настройки</b>",
        "",
        "Аккаунт Авито: " + (esc(account["title"]) if account else "не подключён"),
        f"Сообщений в день: не больше {limit}",
        f"Напоминание: через {hours} ч молчания",
        "Отправка: " + ("⏸ на паузе" if paused else "▶️ работает"),
    ]
    if ctx.settings.dry_run:
        lines += ["", "<i>Включён режим проверки: в Авито ничего не уходит.</i>"]
    await target.answer("\n".join(lines), reply_markup=kb.settings_kb(paused))


async def settings_menu(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    await show_settings(message, ctx)


async def settings_open(call: CallbackQuery, ctx: AppContext) -> None:
    await show_settings(call.message, ctx)
    await call.answer()


async def settings_pause(call: CallbackQuery, ctx: AppContext) -> None:
    await ctx.sender.set_paused(not await ctx.sender.is_paused())
    await call.answer("Готово")
    await show_settings(call.message, ctx)


async def settings_number(call: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    key = call.data.split(":")[-1]
    if key not in SETTING_TITLES:
        await call.answer("Не знаю такую настройку", show_alert=True)
        return
    low, high = SETTING_BOUNDS[key]
    await state.set_state(EditNumber.value)
    await state.update_data(key=key)
    await call.message.answer(f"{SETTING_TITLES[key]} — пришлите число от {low} до {high}.")
    await call.answer()


async def settings_number_value(message: Message, ctx: AppContext, state: FSMContext) -> None:
    data = await state.get_data()
    key = str(data.get("key", ""))
    low, high = SETTING_BOUNDS.get(key, (1, 10**6))
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (low <= int(raw) <= high):
        await message.answer(f"Нужно число от {low} до {high}. Попробуйте ещё раз.")
        return
    await state.clear()
    await ctx.db.set_setting(key, raw)
    await message.answer("Сохранил ✅")
    await show_settings(message, ctx)


# ---------------------------------------------------------------- аккаунты Авито

async def show_accounts(target: Message, ctx: AppContext) -> None:
    accounts = await ctx.db.list_accounts()
    if not accounts:
        text = (
            "<b>Аккаунт Авито</b>\n\n"
            "Пока не подключён. Коды доступа выдаются в кабинете Авито: "
            "<b>Настройки → Доступ к API</b>."
        )
    else:
        lines = ["<b>Аккаунты Авито</b>", ""]
        for acc in accounts:
            mark = "✅ используется" if acc["is_active"] else "—"
            lines.append(f"• <b>{esc(acc['title'])}</b> — {mark}")
        lines += ["", "Нажмите на аккаунт, чтобы бот отвечал от его имени."]
        text = "\n".join(lines)
    await target.answer(text, reply_markup=kb.accounts_kb(accounts))


async def accounts_list(call: CallbackQuery, ctx: AppContext) -> None:
    await show_accounts(call.message, ctx)
    await call.answer()


async def account_add(call: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    await state.set_state(AddAccount.client_id)
    await call.message.answer(
        "Пришлите <b>client_id</b> из кабинета Авито "
        "(<b>Настройки → Доступ к API</b>)."
    )
    await call.answer()


async def account_client_id(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.update_data(client_id=(message.text or "").strip())
    await state.set_state(AddAccount.client_secret)
    await message.answer(
        "Теперь <b>client_secret</b>.\n\n"
        "<i>После отправки удалите своё сообщение: Telegram не разрешает ботам "
        "удалять чужие сообщения.</i>"
    )


async def account_client_secret(message: Message, ctx: AppContext, state: FSMContext) -> None:
    data = await state.get_data()
    secret = (message.text or "").strip()
    await state.clear()
    count = len(await ctx.db.list_accounts())
    try:
        await ctx.db.add_account(
            f"Авито {count + 1}", data.get("client_id", ""), ctx.box.encrypt(secret)
        )
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"Не удалось сохранить: {esc(exc)}")
        return
    await message.answer("Аккаунт подключён ✅ Проверить связь — кнопка «🩺 Проверка».")
    await show_accounts(message, ctx)


async def account_use(call: CallbackQuery, ctx: AppContext) -> None:
    await ctx.db.set_active_account(int(call.data.split(":")[-1]))
    await call.answer("Теперь бот отвечает от этого аккаунта")
    await show_accounts(call.message, ctx)


async def account_delete(call: CallbackQuery, ctx: AppContext) -> None:
    account_id = int(call.data.split(":")[-1])
    await ctx.pool.drop(account_id)
    await ctx.db.delete_account(account_id)
    await call.answer("Удалён")
    await show_accounts(call.message, ctx)


# ---------------------------------------------------------------- сборка роутера

def build_router() -> Router:
    """Новый роутер со всеми хендлерами.

    Роутер нельзя подключить к двум диспетчерам, поэтому собираем его каждый раз
    заново — так бот и тесты не мешают друг другу.
    """
    router = Router(name="admin")
    router.message.filter(AdminFilter())
    router.callback_query.filter(AdminFilter())

    on_message = router.message.register
    on_call = router.callback_query.register

    on_message(cmd_start, CommandStart())
    on_message(cmd_help, Command("help"))
    on_message(cmd_cancel, Command("cancel"))

    # Кнопки меню идут раньше шагов диалогов: нажатие меню прерывает диалог.
    on_message(answers_menu, F.text == kb.BTN_ANSWERS)
    on_message(report, F.text == kb.BTN_REPORT)
    on_message(check, F.text == kb.BTN_CHECK)
    on_message(settings_menu, F.text == kb.BTN_SETTINGS)
    on_message(cmd_help, F.text == kb.BTN_HELP)

    # Шаги мастера настройки.
    on_message(wiz_client_id, Wizard.client_id)
    on_message(wiz_client_secret, Wizard.client_secret)
    on_message(wiz_niche_title, Wizard.niche_title)
    on_message(wiz_niche_keywords, Wizard.niche_keywords)
    on_message(wiz_reply_text, Wizard.reply_text)
    on_message(wiz_followup_text, Wizard.followup_text)

    # Остальные диалоги.
    on_message(dir_edit_value, EditField.value)
    on_message(dir_add_title, AddDirection.title)
    on_message(dir_add_keywords, AddDirection.keywords)
    on_message(dir_add_reply, AddDirection.reply_text)
    on_message(settings_number_value, EditNumber.value)
    on_message(account_client_id, AddAccount.client_id)
    on_message(account_client_secret, AddAccount.client_secret)

    on_call(wiz_start, F.data == "wiz:start")
    on_call(wiz_demo, F.data == "wiz:demo")
    on_call(wiz_preset, F.data.startswith("wiz:preset:"))
    on_call(wiz_custom, F.data == "wiz:custom")
    on_call(wiz_example_reply, F.data == "wiz:example:reply")
    on_call(wiz_example_followup, F.data == "wiz:example:followup")
    on_call(wiz_skip_followup, F.data == "wiz:skip:followup")

    on_call(dir_list, F.data == "dir:list")
    on_call(dir_add, F.data == "dir:add")
    on_call(dir_open, F.data.startswith("dir:open:"))
    on_call(dir_edit, F.data.startswith("dir:edit:"))
    on_call(dir_toggle, F.data.startswith("dir:toggle:"))
    on_call(dir_delete_ask, F.data.startswith("dir:del:"))
    on_call(dir_delete, F.data.startswith("dir:delyes:"))

    on_call(settings_open, F.data == "set:open")
    on_call(settings_pause, F.data == "set:pause")
    on_call(settings_number, F.data.startswith("set:num:"))

    on_call(accounts_list, F.data == "acc:list")
    on_call(account_add, F.data == "acc:add")
    on_call(account_use, F.data.startswith("acc:use:"))
    on_call(account_delete, F.data.startswith("acc:del:"))

    return router
