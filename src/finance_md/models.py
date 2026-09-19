"""Core data models for finance_md."""

from __future__ import annotations

import dataclasses
import datetime
import re
import secrets
from decimal import Decimal

ACCOUNT_TYPES: tuple[str, ...] = ("bank", "cash", "credit", "savings", "other")

_REF_RE = re.compile(r"^[0-9a-f]{8}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_ref(value: str) -> bool:
    """Return True if *value* is a well-formed 8-hex-char ref."""
    return _REF_RE.fullmatch(value) is not None


def valid_currency(value: str) -> bool:
    """Return True if *value* is a 3-letter uppercase currency code."""
    return _CURRENCY_RE.fullmatch(value) is not None


def valid_account_type(value: str) -> bool:
    """Return True if *value* is one of the supported account types."""
    return value in ACCOUNT_TYPES


def parse_iso_date(value: str) -> datetime.date | None:
    """Parse a strict ``YYYY-MM-DD`` date; return None if invalid."""
    if _DATE_RE.fullmatch(value) is None:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


def new_ref(taken: set[str] | None = None) -> str:
    """Generate a fresh random 8-hex-char ref that is not in *taken*."""
    used = taken if taken else set()
    while True:
        ref = secrets.token_hex(4)
        if ref not in used:
            return ref


@dataclasses.dataclass
class Transaction:
    """A single ledger row.

    ``ref`` is None only for freshly parsed hand-added rows that do not have
    one yet; the tool assigns refs whenever it writes a file. Transfers share
    the same ref in both account files, which is the transfer linkage.
    """

    ref: str | None
    date: datetime.date
    description: str
    category: str
    amount: Decimal


@dataclasses.dataclass
class AccountMeta:
    """Frontmatter metadata of an account file."""

    id: str
    name: str
    type: str
    currency: str
    created: datetime.date
    archived: bool = False
