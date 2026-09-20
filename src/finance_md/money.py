"""Decimal parsing and formatting helpers for money amounts."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .errors import FinanceMDError, ParseError

TWO_PLACES = Decimal("0.01")

_FILE_AMOUNT_RE = re.compile(r"^-?\d+\.\d{2}$")
_USER_AMOUNT_RE = re.compile(r"^-?\d+(\.\d{1,2})?$")


def parse_file_amount(text: str, file: str, line: int) -> Decimal:
    """Parse an amount cell from an account file (strictly two decimals)."""
    value = text.strip()
    if _FILE_AMOUNT_RE.fullmatch(value) is None:
        raise ParseError(
            file, line, f"invalid amount {text!r}: expected -12.34 style with exactly 2 decimals"
        )
    return Decimal(value)


def parse_user_amount(text: str) -> Decimal:
    """Parse a user-supplied amount (0 to 2 decimals), quantized to 2 places."""
    value = text.strip()
    if _USER_AMOUNT_RE.fullmatch(value) is None:
        raise FinanceMDError(
            f"invalid amount {text!r}: use a plain number like 2500, -23.1 or -23.10 "
            "(no thousands separators, at most 2 decimals)"
        )
    quantized = Decimal(value).quantize(TWO_PLACES)
    return Decimal("0.00") if quantized == 0 else quantized


def normalize_amount(value: Decimal) -> Decimal:
    """Validate a library-provided amount: finite and at most 2 decimal places."""
    if not value.is_finite():
        raise FinanceMDError(f"amount must be finite, got {value}")
    try:
        quantized = value.quantize(TWO_PLACES)
    except InvalidOperation:
        raise FinanceMDError(f"amount {value} is out of range") from None
    if quantized != value:
        raise FinanceMDError(f"amount {value} has more than 2 decimal places")
    return Decimal("0.00") if quantized == 0 else quantized


def format_amount(value: Decimal) -> str:
    """Format a Decimal with exactly two decimal places (no thousands separators)."""
    if not value.is_finite():
        raise FinanceMDError(f"amount must be finite, got {value}")
    quantized = value.quantize(TWO_PLACES)
    if quantized == 0:
        quantized = Decimal("0.00")
    return str(quantized)
