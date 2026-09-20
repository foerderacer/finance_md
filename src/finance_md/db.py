"""SQLite persistence: the database is the source of truth.

Every method opens a short-lived connection so no handles linger (this
keeps tmp-dir cleanup working on Windows and makes concurrent CLI usage
safe). Writes go through :meth:`Database.transaction` which takes an
immediate lock, so multi-statement changes are atomic.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .errors import WorkspaceError
from .models import AccountMeta, Transaction, parse_iso_date
from .money import format_amount

DB_NAME = "finance.db"
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    type TEXT NOT NULL,
    currency TEXT NOT NULL,
    created TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1))
);
CREATE TABLE IF NOT EXISTS transactions (
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    ref TEXT NOT NULL,
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    amount TEXT NOT NULL,
    PRIMARY KEY (account_id, ref)
);
"""

_ACCOUNT_COLUMNS = "id, name, type, currency, created, archived"
_TX_COLUMNS = "account_id, ref, date, description, category, amount"


def _connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _meta_from_row(row: sqlite3.Row) -> AccountMeta:
    created = parse_iso_date(str(row["created"]))
    if created is None:
        raise WorkspaceError(f"corrupt database: bad account date {row['created']!r}")
    return AccountMeta(
        id=str(row["id"]),
        name=str(row["name"]),
        type=str(row["type"]),
        currency=str(row["currency"]),
        created=created,
        archived=bool(row["archived"]),
    )


def _parse_stored_amount(text: str, ref: str) -> Decimal:
    value = Decimal(text)
    if not value.is_finite():
        raise WorkspaceError(f"corrupt database: non-finite amount for ref {ref!r}")
    try:
        quantized = value.quantize(Decimal("0.01"))
    except InvalidOperation:
        raise WorkspaceError(
            f"corrupt database: amount for ref {ref!r} has too many decimal places"
        ) from None
    if quantized != value:
        raise WorkspaceError(
            f"corrupt database: amount for ref {ref!r} has too many decimal places"
        )
    return quantized


def _tx_from_row(row: sqlite3.Row) -> Transaction:
    tx_date = parse_iso_date(str(row["date"]))
    if tx_date is None:
        raise WorkspaceError(f"corrupt database: bad transaction date {row['date']!r}")
    ref = str(row["ref"])
    return Transaction(
        ref=ref,
        date=tx_date,
        description=str(row["description"]),
        category=str(row["category"]),
        amount=_parse_stored_amount(str(row["amount"]), ref),
    )


def _tx_row(tx: Transaction) -> tuple[str, str, str, str, str]:
    return (
        tx.ref or "",
        tx.date.isoformat(),
        tx.description,
        tx.category,
        format_amount(tx.amount),
    )


def _account_row(meta: AccountMeta) -> tuple[str, str, str, str, str, int]:
    return (
        meta.id,
        meta.name,
        meta.type,
        meta.currency,
        meta.created.isoformat(),
        1 if meta.archived else 0,
    )


def _insert_account(conn: sqlite3.Connection, meta: AccountMeta) -> None:
    try:
        conn.execute(
            "INSERT INTO accounts (id, name, type, currency, created, archived) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            _account_row(meta),
        )
    except sqlite3.IntegrityError as exc:
        raise WorkspaceError(f"cannot add account {meta.name!r}: {exc}") from exc


class Database:
    """Thin repository over the workspace's ``finance.db``."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @classmethod
    def create(cls, path: str | Path) -> Database:
        """Create the database file with the v1 schema (fails if it exists)."""
        db_path = Path(path)
        if db_path.exists():
            raise WorkspaceError(f"refusing to overwrite existing database {db_path}")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db = cls(db_path)
        conn = _connect(db_path)
        try:
            # executescript runs in autocommit mode (it would commit any open
            # transaction), so do not wrap it in transaction() on a fresh file.
            conn.executescript(_SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except BaseException:
            conn.close()
            db_path.unlink(missing_ok=True)
            raise
        conn.close()
        return db

    @classmethod
    def open(cls, path: str | Path) -> Database:
        """Open an existing database and check its schema version."""
        db_path = Path(path)
        if not db_path.is_file():
            raise WorkspaceError(f"no finance_md database at {db_path}")
        conn = _connect(db_path)
        try:
            try:
                row = conn.execute("PRAGMA user_version").fetchone()
            except sqlite3.DatabaseError as exc:
                raise WorkspaceError(
                    f"{db_path} is not a valid finance_md database ({exc}); "
                    "restore it from a backup or delete it and start over"
                ) from exc
        finally:
            conn.close()
        version = int(row[0]) if row is not None else 0
        if version != SCHEMA_VERSION:
            if version == 0:
                raise WorkspaceError(
                    f"{db_path} is not a finance_md database "
                    "(schema version 0); restore it from a backup or delete it"
                )
            raise WorkspaceError(
                f"database {db_path} has schema version {version}, "
                f"expected {SCHEMA_VERSION}; upgrade finance_md or restore a backup"
            )
        return cls(db_path)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run statements in one atomic transaction (immediate lock)."""
        conn = _connect(self.path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            if conn.in_transaction:
                conn.execute("COMMIT")
        finally:
            conn.close()

    @contextmanager
    def edit_locked(self, account_ids: list[str]) -> Iterator[dict[str, list[Transaction]]]:
        """Locked read-modify-write for the given accounts.

        Takes the write lock first, loads each account's transactions through
        the locked connection, yields ``{account_id: txs}`` (missing ids map
        to an empty list), then writes every touched list back in the same
        transaction. On error nothing is written.
        """
        with self.transaction() as conn:
            snapshot: dict[str, list[Transaction]] = {}
            for account_id in account_ids:
                rows = conn.execute(
                    f"SELECT {_TX_COLUMNS} FROM transactions WHERE account_id = ? "
                    "ORDER BY date, ref",
                    (account_id,),
                ).fetchall()
                snapshot[account_id] = [_tx_from_row(row) for row in rows]
            yield snapshot
            for account_id, txs in snapshot.items():
                conn.execute("DELETE FROM transactions WHERE account_id = ?", (account_id,))
                conn.executemany(
                    "INSERT INTO transactions (account_id, ref, date, description, "
                    "category, amount) VALUES (?, ?, ?, ?, ?, ?)",
                    [(account_id, *_tx_row(tx)) for tx in txs],
                )

    # -- accounts ---------------------------------------------------------

    def list_accounts(self) -> list[AccountMeta]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                f"SELECT {_ACCOUNT_COLUMNS} FROM accounts ORDER BY lower(name)"
            ).fetchall()
        finally:
            conn.close()
        return [_meta_from_row(row) for row in rows]

    def get_account(self, account_id: str) -> AccountMeta | None:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                f"SELECT {_ACCOUNT_COLUMNS} FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
        finally:
            conn.close()
        return _meta_from_row(row) if row is not None else None

    def insert_account(self, meta: AccountMeta) -> None:
        with self.transaction() as conn:
            _insert_account(conn, meta)

    def set_archived(self, account_id: str, archived: bool) -> None:
        with self.transaction() as conn:
            cursor = conn.execute(
                "UPDATE accounts SET archived = ? WHERE id = ?",
                (1 if archived else 0, account_id),
            )
            if cursor.rowcount != 1:
                raise WorkspaceError(f"unknown account id {account_id!r}")

    # -- transactions ------------------------------------------------------

    def list_txs(self, account_id: str) -> list[Transaction]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                f"SELECT {_TX_COLUMNS} FROM transactions WHERE account_id = ? "
                "ORDER BY date, ref",
                (account_id,),
            ).fetchall()
        finally:
            conn.close()
        return [_tx_from_row(row) for row in rows]

    def all_txs(self) -> dict[str, list[Transaction]]:
        """All transactions grouped by account id (sorted date, then ref)."""
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                f"SELECT {_TX_COLUMNS} FROM transactions ORDER BY account_id, date, ref"
            ).fetchall()
        finally:
            conn.close()
        grouped: dict[str, list[Transaction]] = {}
        for row in rows:
            grouped.setdefault(str(row["account_id"]), []).append(_tx_from_row(row))
        return grouped

    def replace_txs(self, account_id: str, txs: list[Transaction]) -> None:
        """Replace all transactions of one account (atomic)."""
        self.replace_txs_multi([(account_id, txs)])

    def replace_txs_multi(self, items: list[tuple[str, list[Transaction]]]) -> None:
        """Replace transactions of several accounts in one atomic transaction."""
        with self.transaction() as conn:
            try:
                for account_id, txs in items:
                    conn.execute(
                        "DELETE FROM transactions WHERE account_id = ?", (account_id,)
                    )
                    conn.executemany(
                        "INSERT INTO transactions (account_id, ref, date, description, "
                        "category, amount) VALUES (?, ?, ?, ?, ?, ?)",
                        [(account_id, *_tx_row(tx)) for tx in txs],
                    )
            except sqlite3.IntegrityError as exc:
                raise WorkspaceError(f"cannot store transactions: {exc}") from exc

    def import_entries(self, entries: list[tuple[AccountMeta, list[Transaction]]]) -> None:
        """Bulk-insert accounts and their transactions in one transaction."""
        with self.transaction() as conn:
            for meta, txs in entries:
                _insert_account(conn, meta)
                try:
                    conn.executemany(
                        "INSERT INTO transactions (account_id, ref, date, description, "
                        "category, amount) VALUES (?, ?, ?, ?, ?, ?)",
                        [(meta.id, *_tx_row(tx)) for tx in txs],
                    )
                except sqlite3.IntegrityError as exc:
                    raise WorkspaceError(
                        f"cannot store transactions for account {meta.name!r}: {exc}"
                    ) from exc

    # -- maintenance -------------------------------------------------------

    def counts(self) -> tuple[int, int]:
        """Return (number of accounts, number of transactions)."""
        conn = _connect(self.path)
        try:
            accounts = int(conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])
            txs = int(conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0])
        finally:
            conn.close()
        return accounts, txs

    def execute_script(self, script: str) -> None:  # pragma: no cover - tests only
        conn = _connect(self.path)
        try:
            conn.executescript(script)
        finally:
            conn.close()
