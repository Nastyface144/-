"""Слой хранения: SQLite через aiosqlite."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Iterable, Sequence

import aiosqlite

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL UNIQUE,
    client_id     TEXT    NOT NULL,
    client_secret TEXT    NOT NULL,
    avito_user_id TEXT,
    is_active     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS niches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    slug       TEXT    NOT NULL UNIQUE,
    title      TEXT    NOT NULL,
    keywords   TEXT    NOT NULL DEFAULT '',
    is_default INTEGER NOT NULL DEFAULT 0,
    is_active  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS templates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    niche_id   INTEGER NOT NULL REFERENCES niches(id) ON DELETE CASCADE,
    kind       TEXT    NOT NULL DEFAULT 'reply',
    body       TEXT    NOT NULL,
    is_active  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_templates_niche ON templates(niche_id, kind, is_active);

CREATE TABLE IF NOT EXISTS chats (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id       INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    avito_chat_id    TEXT    NOT NULL,
    item_id          TEXT,
    item_title       TEXT    NOT NULL DEFAULT '',
    interlocutor     TEXT    NOT NULL DEFAULT '',
    niche_id         INTEGER REFERENCES niches(id) ON DELETE SET NULL,
    last_incoming_at TEXT,
    last_outgoing_at TEXT,
    created_at       TEXT    NOT NULL,
    UNIQUE(account_id, avito_chat_id)
);

CREATE TABLE IF NOT EXISTS sends (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    avito_chat_id TEXT    NOT NULL,
    niche_id      INTEGER REFERENCES niches(id) ON DELETE SET NULL,
    template_id   INTEGER REFERENCES templates(id) ON DELETE SET NULL,
    kind          TEXT    NOT NULL DEFAULT 'reply',
    body          TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'queued',
    error         TEXT,
    created_at    TEXT    NOT NULL,
    sent_at       TEXT,
    UNIQUE(account_id, avito_chat_id, kind)
);
CREATE INDEX IF NOT EXISTS idx_sends_status ON sends(status, created_at);
CREATE INDEX IF NOT EXISTS idx_sends_sent ON sends(account_id, sent_at);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def parse_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() не был вызван")
        return self._conn

    async def _exec(self, sql: str, params: Sequence[Any] = ()) -> aiosqlite.Cursor:
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur

    async def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, params) as cur:
            return list(await cur.fetchall())

    async def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    # ---------------- аккаунты ----------------

    async def add_account(self, title: str, client_id: str, client_secret: str) -> int:
        cur = await self._exec(
            "INSERT INTO accounts(title, client_id, client_secret, is_active, created_at)"
            " VALUES(?,?,?,0,?)",
            (title, client_id, client_secret, utcnow()),
        )
        account_id = int(cur.lastrowid)
        if await self.fetch_one("SELECT 1 FROM accounts WHERE is_active=1") is None:
            await self.set_active_account(account_id)
        return account_id

    async def list_accounts(self) -> list[aiosqlite.Row]:
        return await self.fetch_all("SELECT * FROM accounts ORDER BY id")

    async def get_account(self, account_id: int) -> aiosqlite.Row | None:
        return await self.fetch_one("SELECT * FROM accounts WHERE id=?", (account_id,))

    async def get_active_account(self) -> aiosqlite.Row | None:
        return await self.fetch_one("SELECT * FROM accounts WHERE is_active=1 LIMIT 1")

    async def set_active_account(self, account_id: int) -> None:
        await self._exec("UPDATE accounts SET is_active=0", ())
        await self._exec("UPDATE accounts SET is_active=1 WHERE id=?", (account_id,))

    async def set_account_user_id(self, account_id: int, avito_user_id: str) -> None:
        await self._exec(
            "UPDATE accounts SET avito_user_id=? WHERE id=?", (avito_user_id, account_id)
        )

    async def delete_account(self, account_id: int) -> None:
        was_active = await self.fetch_one(
            "SELECT is_active FROM accounts WHERE id=?", (account_id,)
        )
        await self._exec("DELETE FROM accounts WHERE id=?", (account_id,))
        if was_active and was_active["is_active"]:
            nxt = await self.fetch_one("SELECT id FROM accounts ORDER BY id LIMIT 1")
            if nxt:
                await self.set_active_account(int(nxt["id"]))

    # ---------------- ниши ----------------

    async def add_niche(self, slug: str, title: str, keywords: str = "") -> int:
        cur = await self._exec(
            "INSERT INTO niches(slug, title, keywords, created_at) VALUES(?,?,?,?)",
            (slug, title, keywords, utcnow()),
        )
        niche_id = int(cur.lastrowid)
        if await self.fetch_one("SELECT 1 FROM niches WHERE is_default=1") is None:
            await self.set_default_niche(niche_id)
        return niche_id

    async def list_niches(self, only_active: bool = False) -> list[aiosqlite.Row]:
        sql = "SELECT * FROM niches"
        if only_active:
            sql += " WHERE is_active=1"
        return await self.fetch_all(sql + " ORDER BY id")

    async def get_niche(self, niche_id: int) -> aiosqlite.Row | None:
        return await self.fetch_one("SELECT * FROM niches WHERE id=?", (niche_id,))

    async def get_default_niche(self) -> aiosqlite.Row | None:
        return await self.fetch_one(
            "SELECT * FROM niches WHERE is_default=1 AND is_active=1 LIMIT 1"
        )

    async def set_default_niche(self, niche_id: int) -> None:
        await self._exec("UPDATE niches SET is_default=0", ())
        await self._exec("UPDATE niches SET is_default=1 WHERE id=?", (niche_id,))

    async def toggle_niche(self, niche_id: int) -> None:
        await self._exec(
            "UPDATE niches SET is_active = CASE is_active WHEN 1 THEN 0 ELSE 1 END WHERE id=?",
            (niche_id,),
        )

    async def delete_niche(self, niche_id: int) -> None:
        await self._exec("DELETE FROM niches WHERE id=?", (niche_id,))

    # ---------------- клише ----------------

    async def add_template(self, niche_id: int, kind: str, body: str) -> int:
        cur = await self._exec(
            "INSERT INTO templates(niche_id, kind, body, created_at) VALUES(?,?,?,?)",
            (niche_id, kind, body, utcnow()),
        )
        return int(cur.lastrowid)

    async def list_templates(
        self, niche_id: int | None = None, kind: str | None = None, only_active: bool = False
    ) -> list[aiosqlite.Row]:
        sql = "SELECT * FROM templates WHERE 1=1"
        params: list[Any] = []
        if niche_id is not None:
            sql += " AND niche_id=?"
            params.append(niche_id)
        if kind is not None:
            sql += " AND kind=?"
            params.append(kind)
        if only_active:
            sql += " AND is_active=1"
        return await self.fetch_all(sql + " ORDER BY id", params)

    async def get_template(self, template_id: int) -> aiosqlite.Row | None:
        return await self.fetch_one("SELECT * FROM templates WHERE id=?", (template_id,))

    async def delete_template(self, template_id: int) -> None:
        await self._exec("DELETE FROM templates WHERE id=?", (template_id,))

    # ---------------- чаты ----------------

    async def upsert_chat(
        self,
        account_id: int,
        avito_chat_id: str,
        *,
        item_id: str | None,
        item_title: str,
        interlocutor: str,
        niche_id: int | None,
        last_incoming_at: str | None,
        last_outgoing_at: str | None,
    ) -> None:
        await self._exec(
            """
            INSERT INTO chats(account_id, avito_chat_id, item_id, item_title, interlocutor,
                              niche_id, last_incoming_at, last_outgoing_at, created_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(account_id, avito_chat_id) DO UPDATE SET
                item_id=excluded.item_id,
                item_title=excluded.item_title,
                interlocutor=excluded.interlocutor,
                niche_id=COALESCE(excluded.niche_id, chats.niche_id),
                last_incoming_at=COALESCE(excluded.last_incoming_at, chats.last_incoming_at),
                last_outgoing_at=COALESCE(excluded.last_outgoing_at, chats.last_outgoing_at)
            """,
            (
                account_id,
                avito_chat_id,
                item_id,
                item_title,
                interlocutor,
                niche_id,
                last_incoming_at,
                last_outgoing_at,
                utcnow(),
            ),
        )

    async def list_chats(self, account_id: int, limit: int = 50) -> list[aiosqlite.Row]:
        return await self.fetch_all(
            "SELECT * FROM chats WHERE account_id=? ORDER BY last_incoming_at DESC LIMIT ?",
            (account_id, limit),
        )

    # ---------------- очередь отправки ----------------

    async def enqueue(
        self,
        account_id: int,
        avito_chat_id: str,
        niche_id: int | None,
        template_id: int | None,
        kind: str,
        body: str,
    ) -> int | None:
        """Ставит сообщение в очередь. None — если такое уже ставили (дедупликация)."""
        cur = await self._exec(
            """
            INSERT OR IGNORE INTO sends(account_id, avito_chat_id, niche_id, template_id,
                                        kind, body, status, created_at)
            VALUES(?,?,?,?,?,?, 'queued', ?)
            """,
            (account_id, avito_chat_id, niche_id, template_id, kind, body, utcnow()),
        )
        return int(cur.lastrowid) if cur.rowcount else None

    async def next_queued(self, account_id: int) -> aiosqlite.Row | None:
        return await self.fetch_one(
            "SELECT * FROM sends WHERE account_id=? AND status='queued'"
            " ORDER BY created_at, id LIMIT 1",
            (account_id,),
        )

    async def mark_sent(self, send_id: int) -> None:
        await self._exec(
            "UPDATE sends SET status='sent', sent_at=?, error=NULL WHERE id=?",
            (utcnow(), send_id),
        )

    async def mark_failed(self, send_id: int, error: str) -> None:
        await self._exec(
            "UPDATE sends SET status='failed', error=? WHERE id=?", (error[:500], send_id)
        )

    async def requeue(self, send_id: int) -> None:
        await self._exec("UPDATE sends SET status='queued', error=NULL WHERE id=?", (send_id,))

    async def sent_today(self, account_id: int, day: str | None = None) -> int:
        day = day or dt.datetime.now(dt.timezone.utc).date().isoformat()
        row = await self.fetch_one(
            "SELECT COUNT(*) AS c FROM sends"
            " WHERE account_id=? AND status='sent' AND substr(sent_at,1,10)=?",
            (account_id, day),
        )
        return int(row["c"]) if row else 0

    async def queue_size(self, account_id: int) -> int:
        row = await self.fetch_one(
            "SELECT COUNT(*) AS c FROM sends WHERE account_id=? AND status='queued'",
            (account_id,),
        )
        return int(row["c"]) if row else 0

    async def recent_sends(self, account_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        return await self.fetch_all(
            "SELECT * FROM sends WHERE account_id=? ORDER BY id DESC LIMIT ?",
            (account_id, limit),
        )

    async def failed_count(self, account_id: int) -> int:
        row = await self.fetch_one(
            "SELECT COUNT(*) AS c FROM sends WHERE account_id=? AND status='failed'",
            (account_id,),
        )
        return int(row["c"]) if row else 0

    async def has_send(self, account_id: int, avito_chat_id: str, kind: str) -> bool:
        row = await self.fetch_one(
            "SELECT 1 FROM sends WHERE account_id=? AND avito_chat_id=? AND kind=?",
            (account_id, avito_chat_id, kind),
        )
        return row is not None

    # ---------------- настройки ----------------

    async def get_setting(self, key: str, default: str = "") -> str:
        row = await self.fetch_one("SELECT value FROM app_settings WHERE key=?", (key,))
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self._exec(
            "INSERT INTO app_settings(key, value) VALUES(?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    async def get_int_setting(self, key: str, default: int) -> int:
        raw = await self.get_setting(key, "")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    async def seed_defaults(self, niches: Iterable[tuple[str, str, str]]) -> None:
        """Создаёт стартовые ниши, если справочник пуст."""
        if await self.fetch_one("SELECT 1 FROM niches LIMIT 1"):
            return
        for slug, title, keywords in niches:
            await self.add_niche(slug, title, keywords)
