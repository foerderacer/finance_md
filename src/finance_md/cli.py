"""Command line interface for finance_md."""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from decimal import Decimal

from . import service
from .errors import FinanceMDError
from .import_md import import_md_workspace
from .models import ACCOUNT_TYPES, parse_iso_date
from .money import format_amount, parse_user_amount
from .workspace import Workspace

PROG = "finance-md"

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _date_type(text: str) -> datetime.date:
    parsed = parse_iso_date(text)
    if parsed is None:
        raise argparse.ArgumentTypeError(f"invalid date {text!r}: expected YYYY-MM-DD")
    return parsed


def _amount_type(text: str) -> Decimal:
    try:
        return parse_user_amount(text)
    except FinanceMDError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _month_type(text: str) -> str:
    if _MONTH_RE.fullmatch(text) is None:
        raise argparse.ArgumentTypeError(f"invalid month {text!r}: expected YYYY-MM")
    return text


def _open_workspace(args: argparse.Namespace) -> Workspace:
    return Workspace.open(getattr(args, "workspace", None))


def _print_table(rows: list[list[str]], right_last: bool = False) -> None:
    width = max(len(row) for row in rows)
    widths = [0] * width
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    for row in rows:
        parts = []
        for i, cell in enumerate(row):
            if right_last and i == len(row) - 1:
                parts.append(cell.rjust(widths[i]))
            else:
                parts.append(cell.ljust(widths[i]))
        print("  ".join(parts).rstrip())


def _cmd_init(args: argparse.Namespace) -> int:
    workspace = Workspace.init(args.directory)
    print(f"Initialized finance_md workspace in {workspace.root}")
    return 0


def _cmd_account_add(args: argparse.Namespace) -> int:
    meta = _open_workspace(args).create_account(args.name, args.type, args.currency)
    print(
        f"Added account {meta.name!r} "
        f"(type={meta.type}, currency={meta.currency}, id={meta.id})"
    )
    return 0


def _cmd_account_list(args: argparse.Namespace) -> int:
    entries = sorted(_open_workspace(args).load_all(), key=lambda entry: entry[0].name.lower())
    if not entries:
        print("No accounts. Add one with 'finance-md account add'.")
        return 0
    rows = [["Name", "Type", "Currency", "Status", "Balance"]]
    for meta, txs in entries:
        balance = sum((tx.amount for tx in txs), Decimal("0"))
        rows.append(
            [
                meta.name,
                meta.type,
                meta.currency,
                "archived" if meta.archived else "active",
                format_amount(balance),
            ]
        )
    _print_table(rows)
    return 0


def _cmd_account_archive(args: argparse.Namespace) -> int:
    meta = _open_workspace(args).archive_account(args.name)
    print(f"Archived account {meta.name!r}")
    return 0


def _cmd_add(args: argparse.Namespace) -> int:
    workspace = _open_workspace(args)
    tx = service.add_tx(
        workspace, args.account, args.date, args.description, args.amount, category=args.category
    )
    print(
        f"Added {tx.ref} {tx.date.isoformat()} {tx.description!r} "
        f"[{tx.category}] {format_amount(tx.amount)}"
    )
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    workspace = _open_workspace(args)
    txs = service.list_txs(workspace, args.account, month=args.month, category=args.category)
    meta, all_txs = workspace.load_account(args.account)
    if not txs:
        print(f"No transactions for account {meta.name!r}.")
        return 0
    rows = [["Ref", "Date", "Description", "Category", "Amount"]]
    for tx in txs:
        rows.append(
            [
                tx.ref or "-",
                tx.date.isoformat(),
                tx.description,
                tx.category,
                format_amount(tx.amount),
            ]
        )
    _print_table(rows, right_last=True)
    balance = sum((tx.amount for tx in all_txs), Decimal("0"))
    print(f"Balance: {format_amount(balance)} {meta.currency}")
    return 0


def _cmd_edit(args: argparse.Namespace) -> int:
    if all(
        value is None
        for value in (args.date, args.description, args.category, args.amount)
    ):
        print(
            f"{PROG}: error: nothing to edit; pass --date, --description, "
            "--category or --amount",
            file=sys.stderr,
        )
        return 2
    workspace = _open_workspace(args)
    tx = service.edit_tx(
        workspace,
        args.account,
        args.ref,
        date=args.date,
        description=args.description,
        category=args.category,
        amount=args.amount,
    )
    print(f"Updated {tx.ref} in account {args.account!r}")
    return 0


def _cmd_delete(args: argparse.Namespace) -> int:
    workspace = _open_workspace(args)
    tx = service.delete_tx(workspace, args.account, args.ref)
    print(f"Deleted {tx.ref} ({tx.date.isoformat()} {tx.description!r}) from {args.account!r}")
    return 0


def _cmd_transfer(args: argparse.Namespace) -> int:
    workspace = _open_workspace(args)
    out_tx, _in_tx = service.transfer(
        workspace,
        args.from_account,
        args.to_account,
        args.amount,
        date=args.date,
        description=args.description,
    )
    _meta, _src_txs = workspace.load_account(args.from_account)
    print(
        f"Transferred {format_amount(args.amount)} {_meta.currency} "
        f"from {_meta.name!r} to {args.to_account!r} (ref {out_tx.ref})"
    )
    return 0


def _summary_rows(items: list[service.AccountSummary], with_month: bool) -> list[list[str]]:
    header = ["Name", "Type", "Currency", "Balance"]
    if with_month:
        header.append("Month net")
    rows = [header]
    for item in items:
        row = [item.meta.name, item.meta.type, item.meta.currency, format_amount(item.balance)]
        if with_month:
            row.append(format_amount(item.month_net) if item.month_net is not None else "-")
        rows.append(row)
    return rows


def _cmd_summary(args: argparse.Namespace) -> int:
    result = service.summary(_open_workspace(args), month=args.month)
    with_month = result.month is not None
    if result.active:
        _print_table(_summary_rows(result.active, with_month), right_last=with_month)
    else:
        print("No accounts.")
    if result.archived:
        print()
        print("Archived:")
        _print_table(_summary_rows(result.archived, with_month), right_last=with_month)
    label = f"Categories ({result.month})" if result.month else "Categories"
    print()
    print(f"{label}:")
    if result.categories:
        rows = [["Category", "Total"]] + [
            [name, format_amount(total)] for name, total in result.categories
        ]
        _print_table(rows, right_last=True)
    else:
        print("(none)")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    workspace = _open_workspace(args)
    issues = service.validate(workspace)
    if not issues:
        print(f"OK: {workspace.db.counts()[0]} account(s) validated")
        return 0
    for issue in issues:
        print(issue)
    return 1


def _cmd_render(args: argparse.Namespace) -> int:
    workspace = _open_workspace(args)
    written = workspace.refresh_views()
    print(f"Rendered {len(written)} view file(s) in {workspace.root}")
    return 0


def _cmd_import_md(args: argparse.Namespace) -> int:
    workspace = import_md_workspace(args.source, args.destination)
    accounts, txs = workspace.db.counts()
    print(
        f"Imported {accounts} account(s) and {txs} transaction(s) "
        f"into {workspace.root} (database: {workspace.db_path})"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse tree for all finance-md commands."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--workspace",
        metavar="PATH",
        default=argparse.SUPPRESS,
        help="workspace directory (default: $FINANCE_MD_WORKSPACE, else current directory)",
    )
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "SQLite-backed finance management: the database is the source of truth, "
            "the .md files are generated views."
        ),
        parents=[common],
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    p_init = subparsers.add_parser("init", parents=[common], help="create a new workspace")
    p_init.add_argument(
        "directory", nargs="?", default="finances", help="directory to create (default: ./finances)"
    )
    p_init.set_defaults(func=_cmd_init)

    p_account = subparsers.add_parser("account", parents=[common], help="manage accounts")
    account_sub = p_account.add_subparsers(dest="account_command", metavar="COMMAND", required=True)

    p_acc_add = account_sub.add_parser("add", parents=[common], help="add an account")
    p_acc_add.add_argument("name", help="account name")
    p_acc_add.add_argument(
        "--type", dest="type", required=True, choices=ACCOUNT_TYPES, help="account type"
    )
    p_acc_add.add_argument("--currency", required=True, help="3-letter currency code, e.g. EUR")
    p_acc_add.set_defaults(func=_cmd_account_add)

    p_acc_list = account_sub.add_parser("list", parents=[common], help="list accounts")
    p_acc_list.set_defaults(func=_cmd_account_list)

    p_acc_arch = account_sub.add_parser("archive", parents=[common], help="archive an account")
    p_acc_arch.add_argument("name", help="account name")
    p_acc_arch.set_defaults(func=_cmd_account_archive)

    p_add = subparsers.add_parser("add", parents=[common], help="add a transaction")
    p_add.add_argument("account", help="account name")
    p_add.add_argument("date", type=_date_type, help="transaction date (YYYY-MM-DD)")
    p_add.add_argument("description", help="free-text description (notes go here)")
    p_add.add_argument(
        "amount", type=_amount_type, help="amount; income positive, expense negative"
    )
    p_add.add_argument("--category", default="other", help="category (default: other)")
    p_add.set_defaults(func=_cmd_add)

    p_list = subparsers.add_parser("list", parents=[common], help="list an account's transactions")
    p_list.add_argument("account", help="account name")
    p_list.add_argument("--month", type=_month_type, default=None, help="filter by month (YYYY-MM)")
    p_list.add_argument("--category", default=None, help="filter by category")
    p_list.set_defaults(func=_cmd_list)

    p_edit = subparsers.add_parser("edit", parents=[common], help="edit a transaction by ref")
    p_edit.add_argument("account", help="account name")
    p_edit.add_argument("ref", help="transaction ref (8 hex characters)")
    p_edit.add_argument("--date", type=_date_type, default=None, help="new date")
    p_edit.add_argument("--description", default=None, help="new description")
    p_edit.add_argument("--category", default=None, help="new category")
    p_edit.add_argument("--amount", type=_amount_type, default=None, help="new amount")
    p_edit.set_defaults(func=_cmd_edit)

    p_delete = subparsers.add_parser("delete", parents=[common], help="delete a transaction by ref")
    p_delete.add_argument("account", help="account name")
    p_delete.add_argument("ref", help="transaction ref (8 hex characters)")
    p_delete.set_defaults(func=_cmd_delete)

    p_transfer = subparsers.add_parser(
        "transfer", parents=[common], help="move money between accounts"
    )
    p_transfer.add_argument("from_account", metavar="FROM", help="source account")
    p_transfer.add_argument("to_account", metavar="TO", help="destination account")
    p_transfer.add_argument("amount", type=_amount_type, help="positive amount to move")
    p_transfer.add_argument("--date", type=_date_type, default=None, help="transfer date")
    p_transfer.add_argument("--description", default=None, help="description for both sides")
    p_transfer.set_defaults(func=_cmd_transfer)

    p_summary = subparsers.add_parser("summary", parents=[common], help="workspace overview")
    p_summary.add_argument("--month", type=_month_type, default=None, help="scope for categories")
    p_summary.set_defaults(func=_cmd_summary)

    p_validate = subparsers.add_parser("validate", parents=[common], help="lint the workspace")
    p_validate.set_defaults(func=_cmd_validate)

    p_render = subparsers.add_parser(
        "render", parents=[common], help="regenerate the .md view files from the database"
    )
    p_render.set_defaults(func=_cmd_render)

    p_import = subparsers.add_parser(
        "import-md", parents=[common], help="import a v0.1 markdown-only workspace"
    )
    p_import.add_argument("source", help="directory of the markdown workspace (with accounts/)")
    p_import.add_argument(
        "destination", nargs="?", default="finances", help="new workspace directory to create"
    )
    p_import.set_defaults(func=_cmd_import_md)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns 0 on success, 1 on error, 2 on usage errors."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except FinanceMDError as exc:
        print(f"{PROG}: error: {exc}", file=sys.stderr)
        return 1
