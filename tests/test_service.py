from __future__ import annotations

import datetime
import re
from decimal import Decimal

import pytest

from finance_md import service, store
from finance_md.errors import FinanceMDError, NotFoundError
from finance_md.money import parse_user_amount


def amount(text):
    return parse_user_amount(text)


def test_add_assigns_ref_and_updates_index(ws_with_accounts):
    tx = service.add_tx(
        ws_with_accounts,
        "Checking",
        datetime.date(2026, 9, 1),
        "Salary",
        amount("2500"),
        category="income",
    )
    assert tx.ref is not None
    assert len(tx.ref) == 8
    tx2 = service.add_tx(
        ws_with_accounts,
        "checking",
        datetime.date(2026, 9, 3),
        "Grocery",
        amount("-23.10"),
        category="food",
    )
    assert tx2.ref != tx.ref
    _path, meta, txs = ws_with_accounts.load_account("Checking")
    assert meta.currency == "EUR"
    assert sum(t.amount for t in txs) == Decimal("2476.90")
    index = (ws_with_accounts.root / "index.md").read_text()
    assert "2476.90" in index


def test_add_rejects_empty_fields(ws_with_accounts):
    with pytest.raises(FinanceMDError):
        service.add_tx(
            ws_with_accounts, "Checking", datetime.date(2026, 9, 1), "  ", amount("5")
        )
    with pytest.raises(FinanceMDError):
        service.add_tx(
            ws_with_accounts, "Checking", datetime.date(2026, 9, 1), "X", amount("5"), category=""
        )


def test_add_rejects_too_precise_amount(ws_with_accounts):
    with pytest.raises(FinanceMDError):
        service.add_tx(
            ws_with_accounts, "Checking", datetime.date(2026, 9, 1), "X", Decimal("5.001")
        )


def test_add_to_archived_rejected(ws_with_accounts):
    ws_with_accounts.archive_account("Cash")
    with pytest.raises(FinanceMDError) as excinfo:
        service.add_tx(
            ws_with_accounts, "Cash", datetime.date(2026, 9, 1), "X", amount("5")
        )
    assert "archived" in str(excinfo.value)


def test_add_to_unknown_account(ws_with_accounts):
    with pytest.raises(NotFoundError):
        service.add_tx(
            ws_with_accounts, "Ghost", datetime.date(2026, 9, 1), "X", amount("5")
        )


def test_edit_fields(ws_with_accounts):
    tx = service.add_tx(
        ws_with_accounts,
        "Checking",
        datetime.date(2026, 9, 1),
        "Salary",
        amount("2500"),
        category="income",
    )
    edited = service.edit_tx(
        ws_with_accounts,
        "Checking",
        tx.ref,
        description="Payday",
        amount=amount("2600.00"),
        date=datetime.date(2026, 9, 2),
        category="bonus",
    )
    assert edited.description == "Payday"
    assert edited.amount == Decimal("2600.00")
    assert edited.date == datetime.date(2026, 9, 2)
    assert edited.category == "bonus"
    _path, _meta, txs = ws_with_accounts.load_account("Checking")
    assert [(t.description, t.amount) for t in txs] == [("Payday", Decimal("2600.00"))]


def test_edit_unknown_ref_lists_known(ws_with_accounts):
    service.add_tx(
        ws_with_accounts, "Checking", datetime.date(2026, 9, 1), "Salary", amount("2500")
    )
    with pytest.raises(NotFoundError) as excinfo:
        service.edit_tx(ws_with_accounts, "Checking", "00000000", description="x")
    assert "known refs" in str(excinfo.value)
    assert "unknown ref '00000000'" in str(excinfo.value)


def test_delete(ws_with_accounts):
    tx = service.add_tx(
        ws_with_accounts, "Checking", datetime.date(2026, 9, 1), "Salary", amount("2500")
    )
    removed = service.delete_tx(ws_with_accounts, "Checking", tx.ref)
    assert removed.ref == tx.ref
    _path, _meta, txs = ws_with_accounts.load_account("Checking")
    assert txs == []


def test_transfer_invariants(ws_with_accounts):
    service.add_tx(
        ws_with_accounts,
        "Checking",
        datetime.date(2026, 9, 1),
        "Salary",
        amount("1000"),
        category="income",
    )
    out_tx, in_tx = service.transfer(
        ws_with_accounts, "Checking", "Savings", amount("123.45"), date=datetime.date(2026, 9, 5)
    )
    assert out_tx.ref == in_tx.ref
    assert out_tx.amount == Decimal("-123.45")
    assert in_tx.amount == Decimal("123.45")
    assert out_tx.category == "transfer"
    assert in_tx.category == "transfer"
    _p1, _m1, t1 = ws_with_accounts.load_account("Checking")
    _p2, _m2, t2 = ws_with_accounts.load_account("Savings")
    assert [t.ref for t in t1 if t.category == "transfer"] == [out_tx.ref]
    assert [t.ref for t in t2 if t.category == "transfer"] == [in_tx.ref]
    assert sum(t.amount for t in t1) == Decimal("876.55")
    assert sum(t.amount for t in t2) == Decimal("123.45")
    index = (ws_with_accounts.root / "index.md").read_text()
    assert "876.55" in index
    assert "123.45" in index


def test_transfer_currency_mismatch(ws_with_accounts):
    with pytest.raises(FinanceMDError) as excinfo:
        service.transfer(ws_with_accounts, "Checking", "Cash", amount("10"))
    assert "currency mismatch" in str(excinfo.value)


def test_transfer_same_account_rejected(ws_with_accounts):
    with pytest.raises(FinanceMDError) as excinfo:
        service.transfer(ws_with_accounts, "Checking", "checking", amount("10"))
    assert "same account" in str(excinfo.value)


def test_transfer_amount_must_be_positive(ws_with_accounts):
    for bad in ("0", "-5"):
        with pytest.raises(FinanceMDError):
            service.transfer(ws_with_accounts, "Checking", "Savings", amount(bad))


def test_transfer_archived_rejected_both_ways(ws_with_accounts):
    ws_with_accounts.archive_account("Savings")
    with pytest.raises(FinanceMDError):
        service.transfer(ws_with_accounts, "Checking", "Savings", amount("10"))
    with pytest.raises(FinanceMDError):
        service.transfer(ws_with_accounts, "Savings", "Checking", amount("10"))


def test_transfer_default_descriptions(ws_with_accounts):
    out_tx, in_tx = service.transfer(
        ws_with_accounts, "Checking", "Savings", amount("10"), date=datetime.date(2026, 1, 1)
    )
    assert out_tx.description == "Transfer to Savings"
    assert in_tx.description == "Transfer from Checking"


def test_summary(ws_with_accounts):
    service.add_tx(
        ws_with_accounts,
        "Checking",
        datetime.date(2026, 9, 1),
        "Salary",
        amount("2500"),
        category="income",
    )
    service.add_tx(
        ws_with_accounts,
        "Checking",
        datetime.date(2026, 9, 3),
        "Grocery",
        amount("-23.10"),
        category="food",
    )
    service.add_tx(
        ws_with_accounts,
        "Checking",
        datetime.date(2026, 8, 30),
        "Old",
        amount("-10"),
        category="food",
    )
    service.add_tx(
        ws_with_accounts,
        "Cash",
        datetime.date(2026, 9, 4),
        "Coffee",
        amount("-3.50"),
        category="food",
    )
    ws_with_accounts.archive_account("Cash")
    result = service.summary(ws_with_accounts)
    assert [item.meta.name for item in result.active] == ["Checking", "Savings"]
    assert [item.meta.name for item in result.archived] == ["Cash"]
    assert result.active[0].balance == Decimal("2466.90")
    assert result.archived[0].balance == Decimal("-3.50")
    assert dict(result.categories) == {
        "income": Decimal("2500.00"),
        "food": Decimal("-36.60"),
    }
    monthly = service.summary(ws_with_accounts, month="2026-09")
    assert dict(monthly.categories) == {
        "income": Decimal("2500.00"),
        "food": Decimal("-26.60"),
    }
    assert monthly.active[0].month_net == Decimal("2476.90")
    assert monthly.archived[0].month_net == Decimal("-3.50")


@pytest.mark.parametrize("bad", ["2026-13", "09-2026", "2026-9", "20260901"])
def test_summary_invalid_month(ws_with_accounts, bad):
    with pytest.raises(FinanceMDError):
        service.summary(ws_with_accounts, month=bad)


def test_list_txs_filters(ws_with_accounts):
    service.add_tx(
        ws_with_accounts,
        "Checking",
        datetime.date(2026, 9, 1),
        "Salary",
        amount("2500"),
        category="income",
    )
    service.add_tx(
        ws_with_accounts,
        "Checking",
        datetime.date(2026, 9, 3),
        "Grocery",
        amount("-23.10"),
        category="food",
    )
    service.add_tx(
        ws_with_accounts,
        "Checking",
        datetime.date(2026, 8, 30),
        "Old",
        amount("-10"),
        category="food",
    )
    assert len(service.list_txs(ws_with_accounts, "Checking")) == 3
    september = service.list_txs(ws_with_accounts, "Checking", month="2026-09")
    assert [t.description for t in september] == ["Salary", "Grocery"]
    food_only = service.list_txs(ws_with_accounts, "Checking", category="FOOD")
    assert [t.description for t in food_only] == ["Old", "Grocery"]
    with pytest.raises(FinanceMDError):
        service.list_txs(ws_with_accounts, "Checking", month="nope")


def test_validate_ok(ws_with_accounts):
    assert service.validate(ws_with_accounts) == []


def test_validate_detects_corrupt_file(ws_with_accounts):
    path = ws_with_accounts.accounts_dir / "checking.md"
    text = path.read_text().replace(
        "|---|---|---|---|---:|",
        "|---|---|---|---|---:|\n| badref | 2026-09-01 | X | y | 1.00 |",
    )
    path.write_text(text)
    issues = service.validate(ws_with_accounts)
    assert issues
    assert "checking.md" in issues[0]


def test_validate_detects_stale_index(ws_with_accounts):
    (ws_with_accounts.root / "index.md").write_text("stale\n")
    issues = service.validate(ws_with_accounts)
    assert any("index.md" in issue for issue in issues)


def test_validate_detects_duplicate_ids(ws_with_accounts):
    checking = ws_with_accounts.accounts_dir / "checking.md"
    savings = ws_with_accounts.accounts_dir / "savings.md"
    savings_meta, _txs = store.read_account(savings)
    new_text = re.sub(
        r"^id: .*$", f"id: {savings_meta.id}", checking.read_text(), count=1, flags=re.M
    )
    checking.write_text(new_text)
    issues = service.validate(ws_with_accounts)
    assert any("duplicate account id" in issue for issue in issues)


def test_hand_edited_rows_get_refs_on_next_mutation(ws_with_accounts):
    path = ws_with_accounts.accounts_dir / "checking.md"
    path.write_text(
        path.read_text().replace(
            "|---|---|---|---|---:|",
            "|---|---|---|---|---:|\n| | 2026-09-07 | Handmade | food | -1.00 |",
        )
    )
    service.add_tx(ws_with_accounts, "Checking", datetime.date(2026, 9, 8), "Tool", amount("2.00"))
    _meta, txs = store.read_account(path)
    assert [t.description for t in txs] == ["Handmade", "Tool"]
    refs = {t.ref for t in txs}
    assert None not in refs
    assert len(refs) == 2
