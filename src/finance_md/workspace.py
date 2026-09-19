"""Workspace discovery, initialization and account file management."""

from __future__ import annotations

import datetime
import os
import re
from decimal import Decimal
from pathlib import Path

from . import store
from .errors import NotFoundError, WorkspaceError
from .models import (
    ACCOUNT_TYPES,
    AccountMeta,
    Transaction,
    new_ref,
    valid_account_type,
    valid_currency,
)
from .money import format_amount

INDEX_NAME = "index.md"
ACCOUNTS_DIR = "accounts"
INDEX_TITLE = "# Finance Workspace"
INDEX_HEADER = "| Account | Type | Currency | Balance | File |"
INDEX_SEPARATOR = "|---|---|---|---:|---|"

_SLUG_RE = re.compile(r"[^a-z0-9]+")

Entries = list[tuple[Path, AccountMeta, list[Transaction]]]


def slugify(name: str) -> str:
    """Turn an account name into a filename-safe slug."""
    slug = _SLUG_RE.sub("-", name.lower()).strip("-")
    return slug or "account"


def index_content_from(entries: Entries) -> str:
    """Render the generated ``index.md`` content for the given accounts."""
    lines = [INDEX_TITLE, "", INDEX_HEADER, INDEX_SEPARATOR]
    ordered = sorted(entries, key=lambda entry: entry[1].name.lower())
    for path, meta, txs in ordered:
        balance = sum((tx.amount for tx in txs), Decimal("0"))
        relative = f"{ACCOUNTS_DIR}/{path.name}"
        lines.append(
            f"| {store.escape_cell(meta.name)} | {meta.type} | {meta.currency} | "
            f"{format_amount(balance)} | {relative} |"
        )
    return "\n".join(lines) + "\n"


class Workspace:
    """A directory containing ``index.md`` and an ``accounts/`` folder."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def accounts_dir(self) -> Path:
        return self.root / ACCOUNTS_DIR

    @property
    def index_path(self) -> Path:
        return self.root / INDEX_NAME

    @classmethod
    def init(cls, path: str | Path) -> Workspace:
        """Create a new workspace directory with ``index.md`` and ``accounts/``."""
        root = Path(path)
        index = root / INDEX_NAME
        if index.exists():
            raise WorkspaceError(f"refusing to init: {index} already exists")
        root.mkdir(parents=True, exist_ok=True)
        (root / ACCOUNTS_DIR).mkdir(exist_ok=True)
        workspace = cls(root)
        workspace.regenerate_index()
        return workspace

    @classmethod
    def open(cls, path: str | Path | None = None) -> Workspace:
        """Open a workspace: explicit path, $FINANCE_MD_WORKSPACE, or cwd."""
        if path is not None:
            root = Path(path)
            if not (root / INDEX_NAME).is_file():
                raise WorkspaceError(
                    f"no finance_md workspace at {root} (missing {INDEX_NAME}); "
                    f"run 'finance-md init {root}'"
                )
            return cls(root)
        env = os.environ.get("FINANCE_MD_WORKSPACE")
        if env:
            root = Path(env)
            if not (root / INDEX_NAME).is_file():
                raise WorkspaceError(
                    f"FINANCE_MD_WORKSPACE={env!r} is not a finance_md workspace "
                    f"(missing {INDEX_NAME})"
                )
            return cls(root)
        root = Path.cwd()
        if (root / INDEX_NAME).is_file():
            return cls(root)
        raise WorkspaceError(
            f"no finance_md workspace found in {root} (missing {INDEX_NAME}); "
            "run 'finance-md init' or pass --workspace"
        )

    def account_paths(self) -> list[Path]:
        """Sorted paths of all account files in the workspace."""
        if not self.accounts_dir.is_dir():
            return []
        return sorted(self.accounts_dir.glob("*.md"))

    def load_all(self) -> Entries:
        """Load and parse every account file (strictly)."""
        entries: Entries = []
        for path in self.account_paths():
            meta, txs = store.read_account(path)
            entries.append((path, meta, txs))
        return entries

    def load_account(self, name: str) -> tuple[Path, AccountMeta, list[Transaction]]:
        """Find an account by (case-insensitive) name or filename slug."""
        query = name.strip().lower()
        matches: Entries = []
        for entry in self.load_all():
            path, meta, _txs = entry
            if meta.name.lower() == query or path.stem == slugify(name):
                matches.append(entry)
        if not matches:
            available = ", ".join(meta.name for _p, meta, _t in self.load_all()) or "none"
            raise NotFoundError(f"unknown account {name!r} (known accounts: {available})")
        if len(matches) > 1:
            raise WorkspaceError(f"ambiguous account name {name!r}: matches several account files")
        return matches[0]

    def save_account(self, path: Path, meta: AccountMeta, txs: list[Transaction]) -> None:
        """Write an account file and regenerate the index afterwards."""
        store.write_account(path, meta, txs)
        self.regenerate_index()

    def create_account(self, name: str, account_type: str, currency: str) -> AccountMeta:
        """Create a new account file and regenerate the index."""
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
        existing = self.load_all()
        for _path, meta, _txs in existing:
            if meta.name.lower() == clean_name.lower():
                raise WorkspaceError(f"an account named {clean_name!r} already exists")
        path = self.accounts_dir / f"{slugify(clean_name)}.md"
        if path.exists():
            raise WorkspaceError(f"account file already exists: {ACCOUNTS_DIR}/{path.name}")
        taken_ids = {meta.id for _path, meta, _txs in existing}
        meta = AccountMeta(
            id=new_ref(taken_ids),
            name=clean_name,
            type=account_type,
            currency=clean_currency,
            created=datetime.date.today(),
        )
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        store.write_account(path, meta, [])
        self.regenerate_index()
        return meta

    def archive_account(self, name: str) -> AccountMeta:
        """Mark an account as archived and regenerate the index."""
        path, meta, txs = self.load_account(name)
        meta.archived = True
        store.write_account(path, meta, txs)
        self.regenerate_index()
        return meta

    def index_content(self) -> str:
        """Render the ``index.md`` content for the current accounts."""
        return index_content_from(self.load_all())

    def regenerate_index(self) -> None:
        """Rewrite ``index.md`` from the account files (account files win)."""
        with open(self.index_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(self.index_content())
