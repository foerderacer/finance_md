"""Parse and serialize account ``.md`` files (strict, roundtrip-safe)."""

from __future__ import annotations

import datetime
import re
from pathlib import Path

from . import frontmatter
from .errors import ParseError
from .models import (
    ACCOUNT_TYPES,
    AccountMeta,
    Transaction,
    new_ref,
    parse_iso_date,
    valid_account_type,
    valid_currency,
    valid_ref,
)
from .money import format_amount, parse_file_amount

DELIMITER = frontmatter.DELIMITER
TABLE_COLUMNS = ("Ref", "Date", "Description", "Category", "Amount")
TABLE_HEADER = "| " + " | ".join(TABLE_COLUMNS) + " |"
TABLE_SEPARATOR = "|---|---|---|---|---:|"
TRANSACTIONS_HEADING = "## Transactions"
TYPE_COMMENT = "            # bank | cash | credit | savings | other"

_META_FIELDS = ("id", "name", "type", "currency", "created", "archived")
_SEP_RE = re.compile(r":?-{3,}:?")


def escape_cell(text: str) -> str:
    """Escape a string so it is safe inside a single markdown table cell."""
    cleaned = text.replace("\r", " ").replace("\n", " ")
    return cleaned.replace("\\", "\\\\").replace("|", "\\|")


def _unescape_cell(text: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            out.append(text[index + 1])
            index += 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _split_row(line: str) -> list[str]:
    """Split a markdown table row into unescaped, stripped cells."""
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    cells: list[str] = []
    buffer: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            buffer.append(char)
            buffer.append(value[index + 1])
            index += 2
            continue
        if char == "|":
            cells.append("".join(buffer))
            buffer = []
            index += 1
            continue
        buffer.append(char)
        index += 1
    cells.append("".join(buffer))
    return [_unescape_cell(cell.strip()) for cell in cells]


def _yaml_scalar(value: str) -> str:
    dumped = frontmatter.dump_yaml(value)
    return dumped.splitlines()[0] if dumped else "''"


def _dump_frontmatter(meta: AccountMeta) -> str:
    lines = [
        f"id: {_yaml_scalar(meta.id)}",
        f"name: {_yaml_scalar(meta.name)}",
        f"type: {meta.type}{TYPE_COMMENT}",
        f"currency: {meta.currency}",
        f"created: {meta.created.isoformat()}",
        f"archived: {'true' if meta.archived else 'false'}",
    ]
    return "\n".join(lines) + "\n"


def _format_row(tx: Transaction) -> str:
    ref = tx.ref or ""
    return (
        f"| {ref} | {tx.date.isoformat()} | {escape_cell(tx.description)} | "
        f"{escape_cell(tx.category)} | {format_amount(tx.amount)} |"
    )


def serialize_account(meta: AccountMeta, txs: list[Transaction]) -> str:
    """Serialize an account to its canonical markdown form.

    Rows are sorted by date, then ref, so writes are deterministic. All refs
    must be assigned already; use :func:`write_account` to auto-assign them.
    """
    for tx in txs:
        if tx.ref is None:
            raise ValueError("all transactions need a ref before serializing; use write_account()")
    ordered = sorted(txs, key=lambda tx: (tx.date, tx.ref or ""))
    parts = [
        DELIMITER + "\n",
        _dump_frontmatter(meta),
        DELIMITER + "\n\n",
        f"# {meta.name}\n\n",
        TRANSACTIONS_HEADING + "\n\n",
        TABLE_HEADER + "\n",
        TABLE_SEPARATOR + "\n",
    ]
    for tx in ordered:
        parts.append(_format_row(tx) + "\n")
    return "".join(parts)


def _meta_from_yaml(data: dict[str, object], file: str, line: int) -> AccountMeta:
    missing = [field for field in _META_FIELDS if field not in data]
    if missing:
        raise ParseError(file, line, f"frontmatter missing field(s): {', '.join(missing)}")
    unknown = sorted(str(key) for key in data if key not in _META_FIELDS)
    if unknown:
        raise ParseError(file, line, f"unknown frontmatter field(s): {', '.join(unknown)}")

    account_id = data["id"]
    if isinstance(account_id, int) and not isinstance(account_id, bool):
        account_id = str(account_id)
    if not isinstance(account_id, str) or not valid_ref(account_id):
        raise ParseError(file, line, "frontmatter field 'id' must be an 8-hex-character string")

    name = data["name"]
    if not isinstance(name, str) or not name.strip():
        raise ParseError(file, line, "frontmatter field 'name' must be a non-empty string")
    if "\n" in name or "\r" in name:
        raise ParseError(file, line, "frontmatter field 'name' must be a single line")
    clean_name = name.strip()

    account_type = data["type"]
    if not isinstance(account_type, str) or not valid_account_type(account_type):
        raise ParseError(
            file, line, f"frontmatter field 'type' must be one of: {', '.join(ACCOUNT_TYPES)}"
        )

    currency = data["currency"]
    if not isinstance(currency, str) or not valid_currency(currency):
        raise ParseError(
            file, line, "frontmatter field 'currency' must be a 3-letter uppercase code (e.g. EUR)"
        )

    created_raw = data["created"]
    created: datetime.date | None = None
    if isinstance(created_raw, datetime.datetime):
        created = created_raw.date()
    elif isinstance(created_raw, datetime.date):
        created = created_raw
    elif isinstance(created_raw, str):
        created = parse_iso_date(created_raw)
    if created is None:
        raise ParseError(file, line, "frontmatter field 'created' must be a date like 2026-09-19")

    archived = data["archived"]
    if not isinstance(archived, bool):
        raise ParseError(file, line, "frontmatter field 'archived' must be true or false")

    return AccountMeta(
        id=account_id,
        name=clean_name,
        type=account_type,
        currency=currency,
        created=created,
        archived=archived,
    )


def _parse_row(file: str, line_no: int, raw: str, seen: set[str]) -> Transaction:
    cells = _split_row(raw)
    if len(cells) != len(TABLE_COLUMNS):
        raise ParseError(
            file,
            line_no,
            f"expected {len(TABLE_COLUMNS)} table cells "
            f"({' | '.join(TABLE_COLUMNS)}), got {len(cells)}",
        )
    ref_text, date_text, description, category, amount_text = cells
    ref: str | None = None
    if ref_text:
        if not valid_ref(ref_text):
            raise ParseError(file, line_no, f"invalid ref {ref_text!r}: expected 8 hex characters")
        if ref_text in seen:
            raise ParseError(file, line_no, f"duplicate ref {ref_text}")
        seen.add(ref_text)
        ref = ref_text
    if not date_text:
        raise ParseError(file, line_no, "missing date")
    tx_date = parse_iso_date(date_text)
    if tx_date is None:
        raise ParseError(file, line_no, f"invalid date {date_text!r}: expected YYYY-MM-DD")
    if not description:
        raise ParseError(file, line_no, "missing description")
    if not category:
        raise ParseError(file, line_no, "missing category")
    amount = parse_file_amount(amount_text, file, line_no)
    return Transaction(
        ref=ref, date=tx_date, description=description, category=category, amount=amount
    )


def _parse_body(file: str, body: str, closing_line: int) -> list[Transaction]:
    lines = body.split("\n")
    total = len(lines)

    def file_line(index: int) -> int:
        return closing_line + 1 + index

    index = 0
    saw_title = False
    saw_heading = False
    while index < total:
        stripped = lines[index].strip()
        if stripped == "":
            index += 1
            continue
        if not saw_title and stripped.startswith("# "):
            saw_title = True
            index += 1
            continue
        if not saw_heading and stripped == TRANSACTIONS_HEADING:
            saw_heading = True
            index += 1
            continue
        break
    while index < total and lines[index].strip() == "":
        index += 1
    if index >= total:
        raise ParseError(
            file,
            file_line(min(index, total - 1)),
            "transactions table not found "
            f"(expected header '{TABLE_HEADER}')",
        )
    candidate = lines[index].strip()
    if not candidate.startswith("|"):
        raise ParseError(
            file, file_line(index), f"unexpected content before transactions table: {candidate!r}"
        )
    header_cells = _split_row(lines[index])
    if header_cells != list(TABLE_COLUMNS):
        raise ParseError(
            file,
            file_line(index),
            f"transactions table header mismatch: expected '{TABLE_HEADER}'",
        )
    index += 1
    if index >= total or not _is_separator(_split_row(lines[index])):
        raise ParseError(
            file,
            file_line(min(index, total - 1)),
            f"expected table separator row '{TABLE_SEPARATOR}'",
        )
    index += 1
    txs: list[Transaction] = []
    seen: set[str] = set()
    while index < total and lines[index].lstrip().startswith("|"):
        txs.append(_parse_row(file, file_line(index), lines[index], seen))
        index += 1
    while index < total:
        stripped = lines[index].strip()
        if stripped:
            raise ParseError(
                file,
                file_line(index),
                f"unexpected content after transactions table: {stripped!r}",
            )
        index += 1
    return txs


def _is_separator(cells: list[str]) -> bool:
    return len(cells) == len(TABLE_COLUMNS) and all(
        _SEP_RE.fullmatch(cell) is not None for cell in cells
    )


def parse_account(file: str, text: str) -> tuple[AccountMeta, list[Transaction]]:
    """Parse account file content strictly; raise ParseError with file:line."""
    yaml_text, body, closing_line = frontmatter.split_frontmatter(text, file)
    data = frontmatter.load_yaml(yaml_text, file, closing_line)
    meta = _meta_from_yaml(data, file, closing_line)
    txs = _parse_body(file, body, closing_line)
    return meta, txs


def read_account(path: str | Path) -> tuple[AccountMeta, list[Transaction]]:
    """Read and parse an account file (universal newlines, UTF-8)."""
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8-sig")
    return parse_account(str(file_path), text)


def _assign_refs(txs: list[Transaction]) -> None:
    taken = {tx.ref for tx in txs if tx.ref is not None}
    for tx in txs:
        if tx.ref is None:
            tx.ref = new_ref(taken)
            taken.add(tx.ref)


def write_account(path: str | Path, meta: AccountMeta, txs: list[Transaction]) -> None:
    """Write an account file deterministically, assigning refs to new rows.

    Rows without a ref get a fresh 8-hex ref assigned (in place). Files are
    written with ``\\n`` line endings and rows sorted by date, then ref.
    """
    file_path = Path(path)
    _assign_refs(txs)
    content = serialize_account(meta, txs)
    with open(file_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
