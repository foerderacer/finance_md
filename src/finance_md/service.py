"""High-level operations shared by the CLI and library users."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from decimal import Decimal

from . import views
from .errors import FinanceMDError, NotFoundError
from .models import AccountMeta, Transaction, new_ref
from .money import format_amount, normalize_amount
from .workspace import Workspace

TRANSFER_CATEGORY = "transfer"

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _check_month(month: str | None) -> None:
    if month is not None and _MONTH_RE.fullmatch(month) is None:
        raise FinanceMDError(f"invalid month {month!r}: expected YYYY-MM")


def _check_text(value: str, field: str) -> str:
    if "\n" in value or "\r" in value:
        raise FinanceMDError(f"{field} must be a single line")
    cleaned = value.strip()
    if not cleaned:
        raise FinanceMDError(f"{field} must not be empty")
    return cleaned


def _reject_archived(meta: AccountMeta, action: str) -> None:
    if meta.archived:
        raise FinanceMDError(f"account {meta.name!r} is archived; cannot {action}")


def _find_tx(txs: list[Transaction], ref: str, meta: AccountMeta) -> Transaction:
    for tx in txs:
        if tx.ref == ref:
            return tx
    known = sorted(tx.ref for tx in txs if tx.ref is not None)
    shown = ", ".join(known[:20]) + (", ..." if len(known) > 20 else "")
    raise NotFoundError(
        f"unknown ref {ref!r} in account {meta.name!r} (known refs: {shown or 'none'})"
    )


def add_tx(
    ws: Workspace,
    account: str,
    date: datetime.date,
    description: str,
    amount: Decimal,
    category: str = "other",
) -> Transaction:
    """Append a transaction; the ref is assigned automatically."""
    amount = normalize_amount(amount)
    description = _check_text(description, "description")
    category = _check_text(category, "category")
    tx = Transaction(ref=None, date=date, description=description, category=category, amount=amount)
    with ws.edit(account) as (meta, txs):
        _reject_archived(meta, "add transactions to it")
        tx.ref = new_ref({t.ref for t in txs if t.ref is not None})
        txs.append(tx)
    return tx


def list_txs(
    ws: Workspace,
    account: str,
    month: str | None = None,
    category: str | None = None,
) -> list[Transaction]:
    """List an account's transactions, optionally filtered by month/category."""
    _check_month(month)
    _meta, txs = ws.load_account(account)
    result = []
    for tx in txs:
        if month is not None and tx.date.strftime("%Y-%m") != month:
            continue
        if category is not None and tx.category.lower() != category.lower():
            continue
        result.append(tx)
    return sorted(result, key=lambda tx: (tx.date, tx.ref or ""))


def edit_tx(
    ws: Workspace,
    account: str,
    ref: str,
    *,
    date: datetime.date | None = None,
    description: str | None = None,
    category: str | None = None,
    amount: Decimal | None = None,
) -> Transaction:
    """Edit one transaction identified by its ref."""
    with ws.edit(account) as (meta, txs):
        tx = _find_tx(txs, ref, meta)
        if date is not None:
            tx.date = date
        if description is not None:
            tx.description = _check_text(description, "description")
        if category is not None:
            tx.category = _check_text(category, "category")
        if amount is not None:
            tx.amount = normalize_amount(amount)
    return tx


def delete_tx(ws: Workspace, account: str, ref: str) -> Transaction:
    """Delete one transaction identified by its ref."""
    with ws.edit(account) as (meta, txs):
        tx = _find_tx(txs, ref, meta)
        txs.remove(tx)
    return tx


def transfer(
    ws: Workspace,
    from_account: str,
    to_account: str,
    amount: Decimal,
    date: datetime.date | None = None,
    description: str | None = None,
) -> tuple[Transaction, Transaction]:
    """Move money between two same-currency accounts via a shared ref."""
    amount = normalize_amount(amount)
    if amount <= 0:
        raise FinanceMDError(
            f"transfer amount must be positive, got {format_amount(amount)}"
        )
    src_id = ws.load_account(from_account)[0].id
    if src_id == ws.load_account(to_account)[0].id:
        raise FinanceMDError("cannot transfer to the same account")
    with ws.edit_multi(from_account, to_account) as accounts:
        (src_meta, src_txs), (dst_meta, dst_txs) = accounts
        if src_meta.id == dst_meta.id:
            raise FinanceMDError("cannot transfer to the same account")
        if src_meta.currency != dst_meta.currency:
            raise FinanceMDError(
                f"currency mismatch: {src_meta.name!r} uses {src_meta.currency}, "
                f"{dst_meta.name!r} uses {dst_meta.currency}"
            )
        _reject_archived(src_meta, "transfer from it")
        _reject_archived(dst_meta, "transfer to it")
        tx_date = date if date is not None else datetime.date.today()
        if description is None:
            out_desc = f"Transfer to {dst_meta.name}"
            in_desc = f"Transfer from {src_meta.name}"
        else:
            out_desc = _check_text(description, "description")
            in_desc = out_desc
        used = {tx.ref for tx in src_txs if tx.ref is not None}
        used.update(tx.ref for tx in dst_txs if tx.ref is not None)
        ref = new_ref(used)
        out_tx = Transaction(
            ref=ref, date=tx_date, description=out_desc, category=TRANSFER_CATEGORY, amount=-amount
        )
        in_tx = Transaction(
            ref=ref, date=tx_date, description=in_desc, category=TRANSFER_CATEGORY, amount=amount
        )
        src_txs.append(out_tx)
        dst_txs.append(in_tx)
    return out_tx, in_tx


@dataclass
class AccountSummary:
    """Computed overview of one account."""

    meta: AccountMeta
    balance: Decimal
    month_net: Decimal | None = None


@dataclass
class Summary:
    """Workspace overview: balances, archived accounts, category totals."""

    month: str | None
    active: list[AccountSummary]
    archived: list[AccountSummary]
    categories: list[tuple[str, Decimal]]


def summary(ws: Workspace, month: str | None = None) -> Summary:
    """Compute per-account balances and category totals (month-filterable)."""
    _check_month(month)
    active: list[AccountSummary] = []
    archived: list[AccountSummary] = []
    categories: dict[str, Decimal] = {}
    entries = sorted(ws.load_all(), key=lambda entry: entry[0].name.lower())
    for meta, txs in entries:
        balance = sum((tx.amount for tx in txs), Decimal("0"))
        month_net: Decimal | None = None
        if month is not None:
            month_net = sum(
                (tx.amount for tx in txs if tx.date.strftime("%Y-%m") == month), Decimal("0")
            )
        bucket = archived if meta.archived else active
        bucket.append(AccountSummary(meta=meta, balance=balance, month_net=month_net))
        for tx in txs:
            if month is None or tx.date.strftime("%Y-%m") == month:
                categories[tx.category] = categories.get(tx.category, Decimal("0")) + tx.amount
    return Summary(
        month=month, active=active, archived=archived, categories=sorted(categories.items())
    )


def validate(ws: Workspace) -> list[str]:
    """Check that the generated view files match the database.

    The database is the source of truth, so the only possible problems are
    missing, out-of-sync or orphaned view files (typically caused by hand
    edits). 'finance-md render' (or any mutating command) fixes them.
    """
    issues: list[str] = []
    entries = ws.load_all()
    expected_files: dict[str, str] = {}
    for meta, txs in entries:
        expected_files[views.account_file_name(meta)] = views.account_view_text(meta, txs)

    if ws.index_path.is_file():
        actual = ws.index_path.read_text(encoding="utf-8-sig")
        if actual != views.index_content_from(entries):
            issues.append(
                f"{views.INDEX_NAME} is out of sync with the database; "
                "run 'finance-md render' to regenerate it"
            )
    else:
        issues.append(f"missing {views.INDEX_NAME}; run 'finance-md render' to regenerate it")

    if ws.accounts_dir.is_dir():
        for name in sorted(expected_files):
            path = ws.accounts_dir / name
            if not path.is_file():
                issues.append(
                    f"missing view file {views.ACCOUNTS_DIR}/{name}; "
                    "run 'finance-md render' to regenerate it"
                )
                continue
            if path.read_text(encoding="utf-8-sig") != expected_files[name]:
                issues.append(
                    f"{views.ACCOUNTS_DIR}/{name} is out of sync with the database "
                    "(hand-edits are not read); run 'finance-md render' to regenerate it"
                )
        for existing in sorted(ws.accounts_dir.glob("*.md")):
            if existing.name not in expected_files:
                issues.append(
                    f"orphan view file {views.ACCOUNTS_DIR}/{existing.name}; "
                    "run 'finance-md render' to remove it"
                )
    elif entries:
        issues.append(f"missing {views.ACCOUNTS_DIR}/ directory; run 'finance-md render'")
    return issues
