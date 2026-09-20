"""Rendering of the generated ``.md`` view files from database data.

The ``.md`` files are a *visualization* only: they are regenerated from the
database after every change and hand-edits are not read back. The content
format is identical to the v0.1 ledger format (frontmatter + transaction
table), so the views stay readable, renderable and git-diffable.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from . import store
from .models import AccountMeta, Transaction, slugify
from .money import format_amount

INDEX_NAME = "index.md"
ACCOUNTS_DIR = "accounts"
INDEX_TITLE = "# Finance Workspace"
INDEX_HEADER = "| Account | Type | Currency | Balance | File |"
INDEX_SEPARATOR = "|---|---|---|---:|---|"
VIEW_WARNING = (
    "<!-- GENERATED FILE - do not edit. "
    "The database (finance.db) is the source of truth; "
    "any change here is overwritten by the next finance-md command. -->"
)

Entries = list[tuple[AccountMeta, list[Transaction]]]


def account_file_name(meta: AccountMeta) -> str:
    """The view filename for an account (slug-based, stable)."""
    return f"{slugify(meta.name)}.md"


def account_view_text(meta: AccountMeta, txs: list[Transaction]) -> str:
    """Canonical ``.md`` content for one account view file."""
    return VIEW_WARNING + "\n" + store.serialize_account(meta, txs)


def index_content_from(entries: Entries) -> str:
    """Render the generated ``index.md`` content for the given accounts."""
    lines = [INDEX_TITLE, "", INDEX_HEADER, INDEX_SEPARATOR]
    ordered = sorted(entries, key=lambda entry: entry[0].name.lower())
    for meta, txs in ordered:
        balance = sum((tx.amount for tx in txs), Decimal("0"))
        relative = f"{ACCOUNTS_DIR}/{account_file_name(meta)}"
        lines.append(
            f"| {store.escape_cell(meta.name)} | {meta.type} | {meta.currency} | "
            f"{format_amount(balance)} | {relative} |"
        )
    return "\n".join(lines) + "\n"


def write_text_if_changed(path: Path, content: str) -> bool:
    """Write *content* to *path* with ``\\n`` newlines; skip when unchanged."""
    try:
        if path.read_text(encoding="utf-8-sig") == content:
            return False
    except OSError:
        pass
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return True


def write_account_view(root: str | Path, meta: AccountMeta, txs: list[Transaction]) -> bool:
    """Write one account view file; return True if the file changed."""
    return write_text_if_changed(
        Path(root) / ACCOUNTS_DIR / account_file_name(meta),
        account_view_text(meta, txs),
    )


def write_index(root: str | Path, entries: Entries) -> bool:
    """Write ``index.md`` for the given accounts; return True if it changed."""
    return write_text_if_changed(Path(root) / INDEX_NAME, index_content_from(entries))


def render(root: str | Path, entries: Entries) -> list[str]:
    """Write all view files; return the sorted list of written paths (relative).

    Writes ``index.md`` and one ``accounts/<slug>.md`` per account, then
    removes leftover ``.md`` files in ``accounts/`` that no longer belong to
    any account.
    """
    root_path = Path(root)
    accounts_dir = root_path / ACCOUNTS_DIR
    accounts_dir.mkdir(parents=True, exist_ok=True)

    expected: dict[str, str] = {}
    for meta, txs in entries:
        expected[account_file_name(meta)] = account_view_text(meta, txs)

    for name in sorted(expected):
        write_text_if_changed(accounts_dir / name, expected[name])

    for existing in sorted(accounts_dir.glob("*.md")):
        if existing.name not in expected:
            existing.unlink()

    write_index(root_path, entries)
    return [INDEX_NAME, *[f"{ACCOUNTS_DIR}/{name}" for name in sorted(expected)]]
