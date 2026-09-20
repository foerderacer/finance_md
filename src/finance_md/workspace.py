"""Workspace discovery, initialization and database-backed operations.

A workspace is a directory containing ``finance.db`` (the source of truth)
plus the generated ``.md`` view files (``index.md`` and ``accounts/*.md``),
which are refreshed after every change.
"""

from __future__ import annotations

import datetime
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from . import views
from .db import DB_NAME, Database
from .errors import NotFoundError, WorkspaceError
from .models import (
    ACCOUNT_TYPES,
    AccountMeta,
    Transaction,
    new_ref,
    slugify,
    valid_account_type,
    valid_currency,
)
from .views import ACCOUNTS_DIR, INDEX_NAME

Entries = views.Entries


def _v0_1_hint(path: Path) -> str:
    return (
        f"{path} looks like a markdown-only workspace (v0.1); convert it with "
        f"'finance-md import-md {path} DEST'"
    )


def _check_v0_1_layout(root: Path) -> None:
    """Raise a v0.1 import hint when *root* holds an old-style workspace."""
    if (root / INDEX_NAME).is_file() and not (root / DB_NAME).is_file():
        raise WorkspaceError(_v0_1_hint(root))


class Workspace:
    """A directory with ``finance.db`` plus generated ``.md`` view files."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._db: Database | None = None

    @property
    def db_path(self) -> Path:
        return self.root / DB_NAME

    @property
    def accounts_dir(self) -> Path:
        return self.root / ACCOUNTS_DIR

    @property
    def index_path(self) -> Path:
        return self.root / INDEX_NAME

    @property
    def db(self) -> Database:
        if self._db is None:
            self._db = Database.open(self.db_path)
        return self._db

    @classmethod
    def init(cls, path: str | Path) -> Workspace:
        """Create a new workspace directory with ``finance.db`` and views."""
        root = Path(path)
        db_path = root / DB_NAME
        if db_path.exists():
            raise WorkspaceError(f"refusing to init: {db_path} already exists")
        _check_v0_1_layout(root)
        if (root / INDEX_NAME).is_file():
            raise WorkspaceError(f"refusing to init: {root / INDEX_NAME} already exists")
        stray = sorted((root / ACCOUNTS_DIR).glob("*.md")) if (root / ACCOUNTS_DIR).is_dir() else []
        if stray:
            raise WorkspaceError(
                f"refusing to init: {root / ACCOUNTS_DIR} already contains .md files "
                f"({stray[0].name}...); rendering would overwrite them. "
                "Move them away or use 'finance-md import-md'."
            )
        root.mkdir(parents=True, exist_ok=True)
        workspace = cls(root)
        workspace._db = Database.create(db_path)
        workspace.refresh_views()
        return workspace

    @classmethod
    def open(cls, path: str | Path | None = None) -> Workspace:
        """Open a workspace: explicit path, $FINANCE_MD_WORKSPACE, or cwd."""
        if path is not None:
            root = Path(path)
            if (root / DB_NAME).is_file():
                return cls(root)
            _check_v0_1_layout(root)
            raise WorkspaceError(
                f"no finance_md workspace at {root} (missing {DB_NAME}); "
                f"run 'finance-md init {root}'"
            )
        env = os.environ.get("FINANCE_MD_WORKSPACE")
        if env:
            root = Path(env)
            if (root / DB_NAME).is_file():
                return cls(root)
            _check_v0_1_layout(root)
            raise WorkspaceError(
                f"FINANCE_MD_WORKSPACE={env!r} is not a finance_md workspace "
                f"(missing {DB_NAME})"
            )
        root = Path.cwd()
        if (root / DB_NAME).is_file():
            return cls(root)
        _check_v0_1_layout(root)
        raise WorkspaceError(
            f"no finance_md workspace found in {root} (missing {DB_NAME}); "
            "run 'finance-md init' or pass --workspace"
        )

    # -- reads -------------------------------------------------------------

    def load_all(self) -> Entries:
        """All accounts with their transactions, sorted by account name."""
        txs_by_account = self.db.all_txs()
        return [
            (meta, txs_by_account.get(meta.id, [])) for meta in self.db.list_accounts()
        ]

    def load_account(self, name: str) -> tuple[AccountMeta, list[Transaction]]:
        """Find an account by (case-insensitive) name or filename slug.

        Raises NotFoundError when nothing matches and WorkspaceError when a
        slug matches several accounts (ambiguous).
        """
        query = name.strip().lower()
        target_slug = slugify(name)
        by_name: AccountMeta | None = None
        by_slug: list[AccountMeta] = []
        for meta in self.db.list_accounts():
            if meta.name.lower() == query:
                by_name = meta
                break
            if slugify(meta.name) == target_slug:
                by_slug.append(meta)
        if by_name is not None:
            return by_name, self.db.list_txs(by_name.id)
        if len(by_slug) == 1:
            meta = by_slug[0]
            return meta, self.db.list_txs(meta.id)
        if len(by_slug) > 1:
            raise WorkspaceError(f"ambiguous account name {name!r}: matches several accounts")
        available = ", ".join(meta.name for meta in self.db.list_accounts()) or "none"
        raise NotFoundError(f"unknown account {name!r} (known accounts: {available})")

    # -- mutation ----------------------------------------------------------

    @contextmanager
    def edit(self, name: str) -> Iterator[tuple[AccountMeta, list[Transaction]]]:
        """Context manager for read-modify-write on one account.

        Yields ``(meta, txs)`` loaded under the write lock. When the body
        completes without raising, changes are persisted atomically and the
        touched ``.md`` views are refreshed. On error nothing is written.
        """
        with self.edit_multi(name) as pairs:
            (pair,) = pairs
            yield pair

    @contextmanager
    def edit_multi(
        self, *names: str
    ) -> Iterator[list[tuple[AccountMeta, list[Transaction]]]]:
        """Like :meth:`edit`, but for several accounts in one atomic write.

        The write lock is taken before the accounts are read, so concurrent
        writers cannot lose each other's changes. If two names resolve to the
        same account, the operation is rejected.
        """
        if not names:
            raise WorkspaceError("edit_multi() needs at least one account name")
        metas: list[AccountMeta] = []
        for name in names:
            meta, _txs = self.load_account(name)
            if any(meta.id == known.id for known in metas):
                raise WorkspaceError(
                    f"account {name!r} resolves to {meta.name!r}, "
                    "which is already part of this operation"
                )
            metas.append(meta)
        with self.db.edit_locked([meta.id for meta in metas]) as snapshot:
            pairs = [
                (meta, snapshot[meta.id])
                for meta in metas
            ]
            yield pairs
        for meta in metas:
            views.write_account_view(self.root, meta, snapshot[meta.id])
        views.write_index(self.root, self.load_all())

    def create_account(self, name: str, account_type: str, currency: str) -> AccountMeta:
        """Create a new account and refresh the views."""
        clean_name = name.strip()
        if not clean_name:
            raise WorkspaceError("account name must not be empty")
        if "\n" in clean_name or "\r" in clean_name:
            raise WorkspaceError("account name must be a single line")
        if not valid_account_type(account_type):
            raise WorkspaceError(
                f"invalid account type {account_type!r}: "
                f"choose one of {', '.join(ACCOUNT_TYPES)}"
            )
        clean_currency = currency.strip().upper()
        if not valid_currency(clean_currency):
            raise WorkspaceError(
                f"invalid currency {currency!r}: use a 3-letter uppercase code like EUR"
            )
        existing = self.db.list_accounts()
        for meta in existing:
            if meta.name.lower() == clean_name.lower():
                raise WorkspaceError(f"an account named {clean_name!r} already exists")
        target_slug = slugify(clean_name)
        for meta in existing:
            if slugify(meta.name) == target_slug:
                raise WorkspaceError(
                    f"account {clean_name!r} would use the same file as "
                    f"{meta.name!r} ({ACCOUNTS_DIR}/{target_slug}.md)"
                )
        path = self.accounts_dir / f"{target_slug}.md"
        if path.exists():
            raise WorkspaceError(
                f"view file already exists: {ACCOUNTS_DIR}/{path.name}; "
                "run 'finance-md render' to clean it up"
            )
        taken_ids = {meta.id for meta in existing}
        meta = AccountMeta(
            id=new_ref(taken_ids),
            name=clean_name,
            type=account_type,
            currency=clean_currency,
            created=datetime.date.today(),
        )
        self.db.insert_account(meta)
        self.refresh_views()
        return meta

    def archive_account(self, name: str) -> AccountMeta:
        """Mark an account as archived and refresh the views."""
        meta, txs = self.load_account(name)
        self.db.set_archived(meta.id, True)
        meta.archived = True
        views.write_account_view(self.root, meta, txs)
        views.write_index(self.root, self.load_all())
        return meta

    # -- views -------------------------------------------------------------

    def refresh_views(self) -> list[str]:
        """Regenerate ``index.md`` and ``accounts/*.md`` from the database."""
        return views.render(self.root, self.load_all())
