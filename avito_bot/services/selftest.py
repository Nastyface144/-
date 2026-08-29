"""Самопроверка: одной кнопкой прогоняет бота по всей цепочке и отчитывается.

В режиме проверки (DRY_RUN) моделирует обращение клиента и доводит его до
отправки. В боевом режиме ничего не отправляет — только проверяет настройки
и связь с Авито.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..avito.fake import FakeAvitoGateway
from ..db import Database
from ..services import templates as tpl
from .poller import Poller
from .sender import Sender

SELFTEST_PREFIX = "selftest"


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    ok: bool = True

    def good(self, text: str) -> None:
        self.lines.append(f"✅ {text}")

    def bad(self, text: str) -> None:
        self.lines.append(f"❌ {text}")
        self.ok = False

    def note(self, text: str) -> None:
        self.lines.append(f"ℹ️ {text}")

    def render(self) -> str:
        head = "Проверка пройдена" if self.ok else "Есть проблемы"
        body = "\n".join(self.lines)
        tail = (
            "\n\nВсё готово к работе."
            if self.ok
            else "\n\nИсправьте отмеченное ❌ и запустите проверку снова."
        )
        return f"<b>{head}</b>\n\n{body}{tail}"


async def _check_setup(db: Database, sender: Sender, report: Report) -> tuple[object, object]:
    """Общие проверки: аккаунт, направления, лимит, пауза."""
    account = await db.get_active_account()
    if account is None:
        report.bad("Аккаунт Авито не подключён — «Настройки» → «Аккаунт Авито».")
        return None, None
    report.good(f"Аккаунт подключён: {account['title']}")

    niche = None
    empty: list[str] = []
    for candidate in await db.list_niches(only_active=True):
        if await db.primary_template(int(candidate["id"]), "reply") is None:
            empty.append(str(candidate["title"]))
        elif niche is None:
            niche = candidate
    if niche is None:
        report.bad("Нет ни одного направления с текстом ответа — раздел «Ответы».")
        return account, None
    report.good(f"Направление настроено: {niche['title']}")
    if empty:
        report.note(
            "Без текста ответа (бот их не использует): " + ", ".join(empty)
            + ". Допишите текст или удалите — раздел «Ответы»."
        )

    limit = await sender.daily_limit()
    sent = await db.sent_today(int(account["id"]))
    if sent >= limit:
        report.bad(f"Дневной лимит уже исчерпан: {sent} из {limit}.")
    else:
        report.good(f"Лимит на сегодня: отправлено {sent} из {limit}")

    if await sender.is_paused():
        report.bad("Отправка стоит на паузе — «Настройки» → «Включить отправку».")
    else:
        report.good("Отправка включена")
    return account, niche


async def run_self_test(db: Database, poller: Poller, sender: Sender) -> str:
    report = Report()
    account, niche = await _check_setup(db, sender, report)
    if account is None or niche is None:
        return report.render()

    if not poller.pool.dry_run:
        gateway = poller.pool.get(account)
        try:
            user_id = await gateway.get_self_id()
            chats = await gateway.list_chats(limit=20)
        except Exception as exc:  # noqa: BLE001
            report.bad(f"Авито не отвечает: {exc}")
            return report.render()
        report.good(f"Связь с Авито есть (номер профиля {user_id})")
        report.note(f"Сейчас видно чатов: {len(chats)}")
        report.note("Бот отвечает на новые обращения по вашим объявлениям автоматически.")
        return report.render()

    # --- режим проверки: моделируем обращение и доводим его до отправки ---
    gateway = poller.pool.get(account)
    if not isinstance(gateway, FakeAvitoGateway):
        report.bad("Режим проверки недоступен.")
        return report.render()

    account_id = int(account["id"])
    keywords = tpl.split_keywords(niche["keywords"]) or ["объявление"]
    item_title = "Проверка · " + " ".join(keywords)
    chat_id = gateway.add_incoming(
        item_title, "Здравствуйте, ещё актуально?", prefix=SELFTEST_PREFIX
    )
    report.note(f"Создал тестовое обращение по объявлению «{item_title}»")

    try:
        result = await poller.poll_once()
        if result.replies_queued >= 1:
            report.good("Бот распознал обращение и подготовил ответ")
        else:
            report.bad("Бот не подготовил ответ на обращение")
            if result.error:
                report.note(f"Причина: {result.error}")
            else:
                matched = tpl.match_niche(await db.list_niches(), item_title)
                if matched is None:
                    report.note(
                        "Тестовое объявление не подошло ни под одно направление. "
                        "Проверьте слова в разделе «Ответы»."
                    )
                elif int(matched["id"]) != int(niche["id"]):
                    report.note(
                        f"Объявление подошло под другое направление — "
                        f"«{matched['title']}». Уточните слова, чтобы направления "
                        f"не пересекались."
                    )
                else:
                    report.note("У направления нет текста ответа — раздел «Ответы».")
            return report.render()

        outcome = await sender.send_next()
        if outcome.status == "sent":
            report.good("Ответ отправлен (в режиме проверки — реально никуда не ушёл)")
        else:
            report.bad(f"Отправить не удалось: {outcome.detail or outcome.status}")
            return report.render()

        has_followup = await db.primary_template(int(niche["id"]), "followup") is not None
        if has_followup:
            gateway.age_chat(chat_id, hours=48)
            result = await poller.poll_once()
            if result.followups_queued >= 1:
                report.good("Напоминание для молчунов тоже работает")
            else:
                report.bad("Напоминание не сработало")
        else:
            report.note("Напоминание не настроено — это не ошибка.")
    finally:
        # Убираем следы проверки, чтобы не портить отчёт клиенту.
        gateway.remove_chat(chat_id)
        await db.forget_chat(account_id, chat_id)

    return report.render()
