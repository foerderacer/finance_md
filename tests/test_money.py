from __future__ import annotations

from decimal import Decimal

import pytest

from finance_md.errors import FinanceMDError, ParseError
from finance_md.money import format_amount, normalize_amount, parse_file_amount, parse_user_amount


def test_parse_user_amount_basic():
    assert parse_user_amount("2500") == Decimal("2500.00")
    assert parse_user_amount("-23.1") == Decimal("-23.10")
    assert parse_user_amount(" -23.10 ") == Decimal("-23.10")
    assert parse_user_amount("-0") == Decimal("0")
    assert parse_user_amount("0.00") == Decimal("0")


@pytest.mark.parametrize(
    "bad", ["1,234.56", "1.234", "abc", "", "1e5", "+5", "12.", ".", "--3", "1..2"]
)
def test_parse_user_amount_rejects(bad):
    with pytest.raises(FinanceMDError):
        parse_user_amount(bad)


def test_parse_file_amount_ok():
    assert parse_file_amount("2500.00", "a.md", 12) == Decimal("2500.00")
    assert parse_file_amount("-23.10", "a.md", 12) == Decimal("-23.10")


@pytest.mark.parametrize("bad", ["23.1", "23", "1,000.00", "abc", "1e3", "+2.00", "-0.001"])
def test_parse_file_amount_rejects_with_location(bad):
    with pytest.raises(ParseError) as excinfo:
        parse_file_amount(bad, "accounts/a.md", 17)
    assert excinfo.value.file == "accounts/a.md"
    assert excinfo.value.line == 17
    assert "accounts/a.md:17" in str(excinfo.value)


def test_format_amount():
    assert format_amount(Decimal("1234.5")) == "1234.50"
    assert format_amount(Decimal("-23.1")) == "-23.10"
    assert format_amount(Decimal("-0.001")) == "0.00"
    assert format_amount(Decimal("0")) == "0.00"
    assert format_amount(Decimal("2500.00")) == "2500.00"


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_format_amount_rejects_non_finite(bad):
    with pytest.raises(FinanceMDError):
        format_amount(Decimal(bad))


def test_normalize_amount():
    assert normalize_amount(Decimal("1.25")) == Decimal("1.25")
    assert normalize_amount(Decimal("-0.00")) == Decimal("0")
    with pytest.raises(FinanceMDError):
        normalize_amount(Decimal("1.234"))
    with pytest.raises(FinanceMDError):
        normalize_amount(Decimal("NaN"))
    with pytest.raises(FinanceMDError):
        normalize_amount(Decimal("Infinity"))
    with pytest.raises(FinanceMDError):
        normalize_amount(Decimal("-Infinity"))
