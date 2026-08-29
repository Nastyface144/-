"""Хендлеры Telegram-бота: аккаунты, ниши, клише, лимиты, статистика, демо."""

from __future__ import annotations

import html
import re

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from ..avito.client import AvitoError
from ..avito.fake import FakeAvitoGateway
from ..services import templates as tpl
from . import keyboards as kb
from .context import AppContext
from .states import AddAccount, AddNiche, AddTemplate, DemoChat, EditNumber

SETTING_TITLES = {
    "daily_limit": "Лимит сообщений в сутки",
    "send_interval_seconds": "Пауза между сообщениями, секунд",
    "poll_interval_seconds": "Период опроса чатов, секунд",
    "followup_after_hours": "Follow-up через, часов",
}
SETTING_BOUNDS = {
    "daily_limit": (1, 500),
    "send_interval_seconds": (5, 3600),
    "poll_interval_seconds": (10, 3600),
    "followup_after_hours": (1, 720),
}
SLUG_RE = re.compile(r"[^a-z0-9а-яё]+")


def esc(value: object) -> str:
    return html.escape(str(value))


def slugify(title: str) -> str:
    return SLUG_RE.sub("-", title.lower()).strip("-")[:64] or "nisha"


class AdminFilter(BaseFilter):
    async def __call__(self, event: TelegramObject, ctx: AppContext) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user and ctx.settings.is_admin(user.id))


# ---------------------------------------------------------------- старт

async def cmd_start(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    mode = "🧪 DRY-RUN (ничего не уходит в Авито)" if ctx.settings.dry_run else "🚀 боевой режим"
    await message.answer(
        "<b>Бот сообщений Авито</b>\n"
        f"Режим: {mode}\n\n"
        "Бот отвечает клише по нишам на обращения в чатах ваших объявлений "
        "и досылает follow-up тем, кто замолчал.\n\n"
        "Начните с раздела «Аккаунты», затем заведите ниши и клише.",
        reply_markup=kb.main_menu(ctx.settings.dry_run),
    )


async def cmd_help(message: Message, ctx: AppContext) -> None:
    await message.answer(
        "<b>Как это работает</b>\n"
        "1. Добавляете аккаунт Авито (client_id / client_secret из личного кабинета).\n"
        "2. Заводите нишу и ключевые слова — по ним бот определяет, "
        "к какому объявлению относится чат.\n"
        "3. Пишете клише: «Автоответ» — на первое обращение, "
        "«Follow-up» — если человек замолчал.\n"
        "4. Бот опрашивает чаты, ставит сообщения в очередь и шлёт их "
        "не чаще заданного лимита в сутки.\n\n"
        "Плейсхолдеры в клише: " + ", ".join("{" + p + "}" for p in tpl.known_placeholders()) +
        "\n\n/cancel — прервать текущий диалог."
    )


async def cmd_cancel(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=kb.main_menu(ctx.settings.dry_run))


# ---------------------------------------------------------------- аккаунты

async def show_accounts(target: Message, ctx: AppContext) -> None:
    accounts = await ctx.db.list_accounts()
    if not accounts:
        text = "Аккаунтов пока нет. Добавьте первый — он сразу станет активным."
    else:
        lines = ["<b>Аккаунты Авито</b>", ""]
        for acc in accounts:
            mark = "✅ активный" if acc["is_active"] else "—"
            uid = acc["avito_user_id"] or "id не получен"
            lines.append(f"• <b>{esc(acc['title'])}</b> — {mark} ({esc(uid)})")
        lines.append("")
        lines.append("Нажмите на аккаунт, чтобы сделать его активным для рассылки.")
        text = "\n".join(lines)
    await target.answer(text, reply_markup=kb.accounts_kb(accounts))


async def accounts_menu(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    await show_accounts(message, ctx)


async def account_add(call: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    await state.set_state(AddAccount.title)
    await call.message.answer("Название аккаунта (для вас, например «Основной»):")
    await call.answer()


async def account_title(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.update_data(title=(message.text or "").strip())
    await state.set_state(AddAccount.client_id)
    await message.answer("client_id из личного кабинета Авито:")


async def account_client_id(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.update_data(client_id=(message.text or "").strip())
    await state.set_state(AddAccount.client_secret)
    await message.answer(
        "client_secret:\n\n"
        "<i>Сообщение с секретом удалю сразу после сохранения.</i>"
    )


async def account_client_secret(message: Message, ctx: AppContext, state: FSMContext) -> None:
    data = await state.get_data()
    secret = (message.text or "").strip()
    await state.clear()
    try:
        await message.delete()
    except Exception:  # noqa: BLE001 — нет прав на удаление, не критично
        pass
    try:
        await ctx.db.add_account(
            data.get("title", "Аккаунт"), data.get("client_id", ""), ctx.box.encrypt(secret)
        )
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"Не удалось сохранить аккаунт: {esc(exc)}")
        return
    note = "" if ctx.box.enabled else "\n⚠️ SECRET_KEY не задан — секрет лежит в БД открытым."
    await message.answer("Аккаунт сохранён." + note)
    await show_accounts(message, ctx)


async def account_use(call: CallbackQuery, ctx: AppContext) -> None:
    account_id = int(call.data.split(":")[-1])
    await ctx.db.set_active_account(account_id)
    await call.answer("Аккаунт активен")
    await show_accounts(call.message, ctx)


async def account_delete(call: CallbackQuery, ctx: AppContext) -> None:
    account_id = int(call.data.split(":")[-1])
    await ctx.pool.drop(account_id)
    await ctx.db.delete_account(account_id)
    await call.answer("Удалён")
    await show_accounts(call.message, ctx)


async def account_check(call: CallbackQuery, ctx: AppContext) -> None:
    account_id = int(call.data.split(":")[-1])
    account = await ctx.db.get_account(account_id)
    if account is None:
        await call.answer("Аккаунт не найден", show_alert=True)
        return
    await call.answer("Проверяю…")
    gateway = ctx.pool.get(account)
    try:
        user_id = await gateway.get_self_id()
        chats = await gateway.list_chats(limit=5)
    except (AvitoError, Exception) as exc:  # noqa: BLE001
        await call.message.answer(f"❌ Связь не установлена: {esc(exc)}")
        return
    await ctx.db.set_account_user_id(account_id, user_id)
    await call.message.answer(
        f"✅ Связь есть. user_id: <code>{esc(user_id)}</code>, чатов получено: {len(chats)}"
    )


# ---------------------------------------------------------------- ниши

async def show_niches(target: Message, ctx: AppContext) -> None:
    niches = await ctx.db.list_niches()
    lines = ["<b>Ниши</b>", ""]
    if not niches:
        lines.append("Пока пусто.")
    for niche in niches:
        state = "включена" if niche["is_active"] else "выключена"
        default = " ⭐️по умолчанию" if niche["is_default"] else ""
        keywords = niche["keywords"] or "— (только как ниша по умолчанию)"
        lines.append(f"• <b>{esc(niche['title'])}</b> — {state}{default}\n  ключевые слова: {esc(keywords)}")
    lines += [
        "",
        "⭐️ — сделать нишей по умолчанию, ↔️ — вкл/выкл, 🗑 — удалить.",
        "Ниша подбирается по вхождению <b>всех</b> её ключевых слов в заголовок объявления.",
    ]
    await target.answer("\n".join(lines), reply_markup=kb.niches_kb(niches))


async def niches_menu(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    await show_niches(message, ctx)


async def niche_add(call: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    await state.set_state(AddNiche.title)
    await call.message.answer(
        "Название ниши, например: <code>Квартиры · сдача · длительно · собственники</code>"
    )
    await call.answer()


async def niche_title(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.update_data(title=(message.text or "").strip())
    await state.set_state(AddNiche.keywords)
    await message.answer(
        "Ключевые слова через запятую — все они должны встречаться в заголовке "
        "объявления, например: <code>квартира, сдам</code>\n\n"
        "Отправьте <code>-</code>, если ниша нужна только как «по умолчанию»."
    )


async def niche_keywords(message: Message, ctx: AppContext, state: FSMContext) -> None:
    data = await state.get_data()
    raw = (message.text or "").strip()
    keywords = "" if raw in {"-", "—"} else raw
    await state.clear()
    title = data.get("title", "Ниша")
    try:
        await ctx.db.add_niche(slugify(title), title, keywords)
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"Не удалось создать нишу: {esc(exc)}")
        return
    await message.answer("Ниша создана. Теперь добавьте к ней клише в разделе «Клише».")
    await show_niches(message, ctx)


async def niche_default(call: CallbackQuery, ctx: AppContext) -> None:
    await ctx.db.set_default_niche(int(call.data.split(":")[-1]))
    await call.answer("Ниша по умолчанию обновлена")
    await show_niches(call.message, ctx)


async def niche_toggle(call: CallbackQuery, ctx: AppContext) -> None:
    await ctx.db.toggle_niche(int(call.data.split(":")[-1]))
    await call.answer("Готово")
    await show_niches(call.message, ctx)


async def niche_delete(call: CallbackQuery, ctx: AppContext) -> None:
    await ctx.db.delete_niche(int(call.data.split(":")[-1]))
    await call.answer("Удалено")
    await show_niches(call.message, ctx)


# ---------------------------------------------------------------- клише

async def show_templates(target: Message, ctx: AppContext, niche_id: int) -> None:
    niche = await ctx.db.get_niche(niche_id)
    if niche is None:
        await target.answer("Ниша не найдена.")
        return
    rows = await ctx.db.list_templates(niche_id)
    lines = [f"<b>Клише · {esc(niche['title'])}</b>", ""]
    if not rows:
        lines.append("Пока ни одного клише. Добавьте хотя бы автоответ.")
    for item in rows:
        label = "↩️ Автоответ" if item["kind"] == "reply" else "⏰ Follow-up"
        lines.append(f"{label}:\n<blockquote>{esc(item['body'])}</blockquote>")
    lines += ["", "Плейсхолдеры: " + ", ".join("{" + p + "}" for p in tpl.known_placeholders())]
    await target.answer("\n".join(lines), reply_markup=kb.templates_kb(niche_id, rows))


async def templates_menu(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    niches = await ctx.db.list_niches()
    await message.answer(
        "Выберите нишу:", reply_markup=kb.niche_pick_kb(niches, "tpl:show")
    )


async def templates_back(call: CallbackQuery, ctx: AppContext) -> None:
    niches = await ctx.db.list_niches()
    await call.message.answer("Выберите нишу:", reply_markup=kb.niche_pick_kb(niches, "tpl:show"))
    await call.answer()


async def templates_show(call: CallbackQuery, ctx: AppContext) -> None:
    await show_templates(call.message, ctx, int(call.data.split(":")[-1]))
    await call.answer()


async def template_add(call: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    _, _, niche_id, kind = call.data.split(":")
    await state.set_state(AddTemplate.body)
    await state.update_data(niche_id=int(niche_id), kind=kind)
    what = "автоответа" if kind == "reply" else "follow-up"
    await call.message.answer(
        f"Пришлите текст {what}. Можно использовать плейсхолдеры: "
        + ", ".join("{" + p + "}" for p in tpl.known_placeholders())
    )
    await call.answer()


async def template_body(message: Message, ctx: AppContext, state: FSMContext) -> None:
    data = await state.get_data()
    body = (message.text or "").strip()
    await state.clear()
    if not body:
        await message.answer("Пустой текст — не сохранил.")
        return
    await ctx.db.add_template(int(data["niche_id"]), str(data["kind"]), body)
    await message.answer("Клише сохранено.")
    await show_templates(message, ctx, int(data["niche_id"]))


async def template_delete(call: CallbackQuery, ctx: AppContext) -> None:
    template_id = int(call.data.split(":")[-1])
    row = await ctx.db.get_template(template_id)
    await ctx.db.delete_template(template_id)
    await call.answer("Удалено")
    if row:
        await show_templates(call.message, ctx, int(row["niche_id"]))


async def noop(call: CallbackQuery) -> None:
    await call.answer()


# ---------------------------------------------------------------- статистика и очередь

async def stats(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    account = await ctx.db.get_active_account()
    if account is None:
        await message.answer("Активного аккаунта нет — добавьте его в разделе «Аккаунты».")
        return
    account_id = int(account["id"])
    limit = await ctx.sender.daily_limit()
    sent = await ctx.db.sent_today(account_id)
    queued = await ctx.db.queue_size(account_id)
    failed = await ctx.db.failed_count(account_id)
    paused = await ctx.sender.is_paused()
    poll = ctx.poller.last_result
    mode = "DRY-RUN" if ctx.settings.dry_run else "боевой"
    await message.answer(
        f"<b>Статистика</b>\n"
        f"Аккаунт: {esc(account['title'])} · режим: {mode}"
        f"{' · ⏸ пауза' if paused else ''}\n\n"
        f"Отправлено сегодня: <b>{sent}</b> из {limit}\n"
        f"В очереди: {queued}\n"
        f"Ошибок: {failed}\n\n"
        f"Последний опрос: чатов {poll.chats_seen}, "
        f"автоответов в очередь {poll.replies_queued}, "
        f"follow-up {poll.followups_queued}"
        + (f"\n⚠️ {esc(poll.error)}" if poll.error else "")
        + (
            f"\nℹ️ Пропущено без клише: {poll.skipped_no_template}"
            if poll.skipped_no_template
            else ""
        )
    )


async def queue(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    account = await ctx.db.get_active_account()
    if account is None:
        await message.answer("Активного аккаунта нет.")
        return
    rows = await ctx.db.recent_sends(int(account["id"]), limit=10)
    if not rows:
        await message.answer("Очередь пуста и отправок ещё не было.")
        return
    icons = {"queued": "⏳", "sent": "✅", "failed": "❌"}
    lines = ["<b>Последние 10 записей</b>", ""]
    for row in rows:
        kind = "автоответ" if row["kind"] == "reply" else "follow-up"
        stamp = row["sent_at"] or row["created_at"]
        lines.append(
            f"{icons.get(row['status'], '•')} {kind} · чат <code>{esc(row['avito_chat_id'])}</code>"
            f" · {esc(stamp)}"
        )
        lines.append(f"<blockquote>{esc(row['body'][:200])}</blockquote>")
        if row["error"]:
            lines.append(f"⚠️ {esc(row['error'])}")
    await message.answer("\n".join(lines))


# ---------------------------------------------------------------- настройки

async def show_settings(target: Message, ctx: AppContext) -> None:
    paused = await ctx.sender.is_paused()
    values = {
        "daily_limit": await ctx.db.get_int_setting("daily_limit", ctx.settings.daily_limit),
        "send_interval_seconds": await ctx.db.get_int_setting(
            "send_interval_seconds", ctx.settings.send_interval_seconds
        ),
        "poll_interval_seconds": await ctx.db.get_int_setting(
            "poll_interval_seconds", ctx.settings.poll_interval_seconds
        ),
        "followup_after_hours": await ctx.db.get_int_setting(
            "followup_after_hours", ctx.settings.followup_after_hours
        ),
    }
    lines = ["<b>Настройки</b>", ""]
    for key, value in values.items():
        lines.append(f"• {SETTING_TITLES[key]}: <b>{value}</b>")
    lines.append("")
    lines.append("Отправка: " + ("⏸ на паузе" if paused else "▶️ идёт"))
    if ctx.settings.dry_run:
        lines.append("Режим DRY-RUN: сообщения не уходят в Авито.")
    if ctx.settings.proxy_url:
        lines.append("Прокси для запросов к API: задан в PROXY_URL.")
    await target.answer("\n".join(lines), reply_markup=kb.settings_kb(paused))


async def settings_menu(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    await show_settings(message, ctx)


async def settings_pause(call: CallbackQuery, ctx: AppContext) -> None:
    await ctx.sender.set_paused(not await ctx.sender.is_paused())
    await call.answer("Готово")
    await show_settings(call.message, ctx)


async def settings_number(call: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    key = call.data.split(":")[-1]
    if key not in SETTING_TITLES:
        await call.answer("Неизвестная настройка", show_alert=True)
        return
    low, high = SETTING_BOUNDS[key]
    await state.set_state(EditNumber.value)
    await state.update_data(key=key)
    await call.message.answer(f"{SETTING_TITLES[key]} — пришлите число от {low} до {high}:")
    await call.answer()


async def settings_number_value(message: Message, ctx: AppContext, state: FSMContext) -> None:
    data = await state.get_data()
    key = str(data.get("key", ""))
    low, high = SETTING_BOUNDS.get(key, (1, 10**6))
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (low <= int(raw) <= high):
        await message.answer(f"Нужно целое число от {low} до {high}. Попробуйте ещё раз.")
        return
    await state.clear()
    await ctx.db.set_setting(key, raw)
    await message.answer(f"{SETTING_TITLES[key]}: {raw}")
    await show_settings(message, ctx)


# ---------------------------------------------------------------- демо (только DRY-RUN)

async def demo_menu(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    if not ctx.settings.dry_run:
        await message.answer("Демо доступно только в режиме DRY_RUN=1.")
        return
    await message.answer(
        "<b>Проверка работоспособности</b>\n\n"
        "1. «Новое входящее» — симулятор создаёт обращение по объявлению.\n"
        "2. «Опросить чаты» — бот подберёт нишу и поставит клише в очередь.\n"
        "3. «Отправить из очереди» — отправка с учётом лимита (в Авито ничего не уходит).\n"
        "4. «Состарить чаты» — сдвигает время назад, чтобы проверить follow-up.",
        reply_markup=kb.demo_kb(),
    )


def _fake_gateway(ctx: AppContext, account) -> FakeAvitoGateway | None:
    gateway = ctx.pool.get(account)
    return gateway if isinstance(gateway, FakeAvitoGateway) else None


async def demo_new(call: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    await state.set_state(DemoChat.item_title)
    await call.message.answer(
        "Заголовок объявления, по которому «написал клиент», например:\n"
        "<code>Сдам квартиру, 2-к, длительно</code>"
    )
    await call.answer()


async def demo_new_title(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    account = await ctx.db.get_active_account()
    if account is None:
        await message.answer("Сначала добавьте аккаунт (в DRY-RUN подойдут любые значения).")
        return
    gateway = _fake_gateway(ctx, account)
    if gateway is None:
        await message.answer("Демо работает только в DRY_RUN.")
        return
    title = (message.text or "").strip() or "Сдам квартиру, длительно"
    chat_id = gateway.add_incoming(title, "Здравствуйте, квартира ещё сдаётся?")
    await message.answer(
        f"Создано входящее в чате <code>{esc(chat_id)}</code> по объявлению «{esc(title)}».\n"
        "Теперь нажмите «Опросить чаты сейчас».",
        reply_markup=kb.demo_kb(),
    )


async def demo_poll(call: CallbackQuery, ctx: AppContext) -> None:
    await call.answer("Опрашиваю…")
    result = await ctx.poller.poll_once()
    text = (
        f"Опрошено чатов: {result.chats_seen}\n"
        f"Автоответов в очередь: {result.replies_queued}\n"
        f"Follow-up в очередь: {result.followups_queued}"
    )
    if result.skipped_no_template:
        text += f"\nПропущено (нет клише): {result.skipped_no_template}"
    if result.error:
        text += f"\n⚠️ {esc(result.error)}"
    await call.message.answer(text, reply_markup=kb.demo_kb())


async def demo_send(call: CallbackQuery, ctx: AppContext) -> None:
    await call.answer("Отправляю…")
    outcome = await ctx.sender.send_next()
    titles = {
        "sent": "✅ Отправлено",
        "empty": "Очередь пуста",
        "limit": "⛔️ Лимит на сегодня исчерпан",
        "paused": "⏸ Отправка на паузе",
        "no_account": "Нет активного аккаунта",
        "failed": "❌ Ошибка",
    }
    text = titles.get(outcome.status, outcome.status)
    if outcome.detail:
        text += f"\n{esc(outcome.detail)}"
    await call.message.answer(text, reply_markup=kb.demo_kb())


async def demo_age(call: CallbackQuery, ctx: AppContext) -> None:
    account = await ctx.db.get_active_account()
    if account is None:
        await call.answer("Нет аккаунта", show_alert=True)
        return
    gateway = _fake_gateway(ctx, account)
    if gateway is None:
        await call.answer("Только в DRY-RUN", show_alert=True)
        return
    chats = await gateway.list_chats(limit=100)
    for chat in chats:
        gateway.age_chat(chat.id, hours=48)
    await call.answer("Готово")
    await call.message.answer(
        f"Сдвинул время в {len(chats)} чатах на 48 часов назад. "
        "Нажмите «Опросить чаты сейчас» — должен встать в очередь follow-up.",
        reply_markup=kb.demo_kb(),
    )


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

    # Команды.
    on_message(cmd_start, CommandStart())
    on_message(cmd_help, Command("help"))
    on_message(cmd_cancel, Command("cancel"))

    # Кнопки меню идут раньше шагов диалогов: нажатие меню прерывает диалог.
    on_message(accounts_menu, F.text == kb.BTN_ACCOUNTS)
    on_message(niches_menu, F.text == kb.BTN_NICHES)
    on_message(templates_menu, F.text == kb.BTN_TEMPLATES)
    on_message(queue, F.text == kb.BTN_QUEUE)
    on_message(stats, F.text == kb.BTN_STATS)
    on_message(settings_menu, F.text == kb.BTN_SETTINGS)
    on_message(demo_menu, F.text == kb.BTN_DEMO)

    # Шаги диалогов.
    on_message(account_title, AddAccount.title)
    on_message(account_client_id, AddAccount.client_id)
    on_message(account_client_secret, AddAccount.client_secret)
    on_message(niche_title, AddNiche.title)
    on_message(niche_keywords, AddNiche.keywords)
    on_message(template_body, AddTemplate.body)
    on_message(settings_number_value, EditNumber.value)
    on_message(demo_new_title, DemoChat.item_title)

    # Аккаунты.
    on_call(account_add, F.data == "acc:add")
    on_call(account_use, F.data.startswith("acc:use:"))
    on_call(account_delete, F.data.startswith("acc:del:"))
    on_call(account_check, F.data.startswith("acc:check:"))

    # Ниши.
    on_call(niche_add, F.data == "niche:add")
    on_call(niche_default, F.data.startswith("niche:def:"))
    on_call(niche_toggle, F.data.startswith("niche:toggle:"))
    on_call(niche_delete, F.data.startswith("niche:del:"))
    on_call(templates_show, F.data.startswith("niche:show:"))

    # Клише.
    on_call(templates_back, F.data == "tpl:back")
    on_call(templates_show, F.data.startswith("tpl:show:"))
    on_call(template_add, F.data.startswith("tpl:add:"))
    on_call(template_delete, F.data.startswith("tpl:del:"))
    on_call(noop, F.data == "noop")

    # Настройки.
    on_call(settings_pause, F.data == "set:pause")
    on_call(settings_number, F.data.startswith("set:num:"))

    # Демо.
    on_call(demo_new, F.data == "demo:new")
    on_call(demo_poll, F.data == "demo:poll")
    on_call(demo_send, F.data == "demo:send")
    on_call(demo_age, F.data == "demo:age")

    return router
