from __future__ import annotations

import datetime
import sqlite3
from decimal import Decimal

import pytest

from finance_md.db import SCHEMA_VERSION, Database
from finance_md.errors import FinanceMDError, WorkspaceError
from finance_md.models import AccountMeta, Transaction, new_ref, parse_iso_date


def make_meta(name="Checking", account_id="3f9c2a1b"):
    return AccountMeta(
        id=account_id,
        name=name,
        type="bank",
        currency="EUR",
        created=datetime.date(2026, 9, 19),
        archived=False,
    )


def tx(ref, date="2026-09-01", amount="10.00", description="X", category="food"):
    return Transaction(
        ref=ref,
        date=parse_iso_date(date),
        description=description,
        category=category,
        amount=Decimal(amount),
    )


def test_create_and_open(tmp_path):
    path = tmp_path / "finance.db"
    Database.create(path)
    assert path.is_file()
    db = Database.open(path)
    assert db.counts() == (0, 0)


def test_create_refuses_existing(tmp_path):
    path = tmp_path / "finance.db"
    Database.create(path)
    with pytest.raises(WorkspaceError):
        Database.create(path)


def test_open_missing(tmp_path):
    with pytest.raises(WorkspaceError):
        Database.open(tmp_path / "nope.db")


def test_open_rejects_unknown_schema_version(tmp_path):
    path = tmp_path / "finance.db"
    db = Database.create(path)
    db.execute_script("PRAGMA user_version = 99")
    with pytest.raises(WorkspaceError) as excinfo:
        Database.open(path)
    assert "schema version" in str(excinfo.value)


def test_open_rejects_version_zero(tmp_path):
    path = tmp_path / "finance.db"
    Database.create(path)
    # Simulate a foreign/empty sqlite file: version 0.
    import sqlite3

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA user_version = 0")
    conn.close()
    with pytest.raises(WorkspaceError) as excinfo:
        Database.open(path)
    assert "not a finance_md database" in str(excinfo.value)


def test_open_rejects_non_sqlite_file(tmp_path):
    path = tmp_path / "finance.db"
    path.write_text("this is not a database")
    with pytest.raises(WorkspaceError) as excinfo:
        Database.open(path)
    assert "not a valid finance_md database" in str(excinfo.value)


def test_schema_version_is_set(tmp_path):
    db = Database.create(tmp_path / "finance.db")
    conn = sqlite3.connect(str(db.path))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        conn.close()


def test_account_roundtrip(tmp_path):
    db = Database.create(tmp_path / "finance.db")
    meta = make_meta()
    db.insert_account(meta)
    assert db.get_account(meta.id) == meta
    assert db.list_accounts() == [meta]


def test_get_account_unknown_returns_none(tmp_path):
    db = Database.create(tmp_path / "finance.db")
    assert db.get_account("ffffffff") is None


def test_duplicate_name_case_insensitive(tmp_path):
    db = Database.create(tmp_path / "finance.db")
    db.insert_account(make_meta(name="Checking"))
    with pytest.raises(WorkspaceError):
        db.insert_account(make_meta(name="checking", account_id="aaaaaaaa"))


def test_duplicate_account_id(tmp_path):
    db = Database.create(tmp_path / "finance.db")
    db.insert_account(make_meta())
    with pytest.raises(WorkspaceError):
        db.insert_account(make_meta(name="Other"))


def test_transactions_roundtrip_and_order(tmp_path):
    db = Database.create(tmp_path / "finance.db")
    meta = make_meta()
    db.insert_account(meta)
    txs = [
        tx("b0000000", "2026-09-03", "-5.00"),
        tx("a0000000", "2026-09-01", "100.00"),
        tx("c0000000", "2026-09-03", "-7.00"),
    ]
    db.replace_txs(meta.id, txs)
    loaded = db.list_txs(meta.id)
    assert [t.ref for t in loaded] == ["a0000000", "b0000000", "c0000000"]
    assert loaded[1].amount == Decimal("-5.00")
    assert db.all_txs() == {meta.id: loaded}
    assert db.counts() == (1, 3)


def test_duplicate_ref_within_account_rejected(tmp_path):
    db = Database.create(tmp_path / "finance.db")
    meta = make_meta()
    db.insert_account(meta)
    with pytest.raises(WorkspaceError):
        db.replace_txs(meta.id, [tx("a0000000"), tx("a0000000", "2026-09-02")])


def test_replace_txs_removes_old_rows(tmp_path):
    db = Database.create(tmp_path / "finance.db")
    meta = make_meta()
    db.insert_account(meta)
    db.replace_txs(meta.id, [tx("a0000000")])
    db.replace_txs(meta.id, [tx("b0000000", "2026-09-02")])
    assert [t.ref for t in db.list_txs(meta.id)] == ["b0000000"]


def test_set_archived(tmp_path):
    db = Database.create(tmp_path / "finance.db")
    meta = make_meta()
    db.insert_account(meta)
    db.set_archived(meta.id, True)
    assert db.get_account(meta.id).archived is True
    db.set_archived(meta.id, False)
    assert db.get_account(meta.id).archived is False
    with pytest.raises(WorkspaceError):
        db.set_archived("ffffffff", True)


def test_import_entries_atomic(tmp_path):
    db = Database.create(tmp_path / "finance.db")
    good = (make_meta(), [tx("a0000000")])
    db.import_entries([good])
    assert db.counts() == (1, 1)
    bad = (make_meta(name="Checking", account_id="bbbbbbbb"), [tx("b0000000")])
    with pytest.raises(WorkspaceError):
        db.import_entries([good, bad])
    assert db.counts() == (1, 1)


def test_list_accounts_sorted_by_name(tmp_path):
    db = Database.create(tmp_path / "finance.db")
    db.insert_account(make_meta(name="Zebra"))
    db.insert_account(make_meta(name="apple", account_id="aaaaaaaa"))
    assert [meta.name for meta in db.list_accounts()] == ["apple", "Zebra"]


def test_read_rejects_nan_amount(tmp_path):
    db = Database.create(tmp_path / "finance.db")
    meta = make_meta()
    db.insert_account(meta)
    db.replace_txs(meta.id, [tx("a0000000")])
    conn = sqlite3.connect(str(db.path))
    conn.execute(
        "UPDATE transactions SET amount = 'NaN' WHERE ref = 'a0000000'"
    )
    conn.commit()
    conn.close()
    with pytest.raises(WorkspaceError) as excinfo:
        db.list_txs(meta.id)
    assert "corrupt database" in str(excinfo.value)


def test_read_rejects_bad_precision_amount(tmp_path):
    db = Database.create(tmp_path / "finance.db")
    meta = make_meta()
    db.insert_account(meta)
    db.replace_txs(meta.id, [tx("a0000000", amount="1.00")])
    conn = sqlite3.connect(str(db.path))
    conn.execute(
        "UPDATE transactions SET amount = '1.234' WHERE ref = 'a0000000'"
    )
    conn.commit()
    conn.close()
    with pytest.raises(WorkspaceError) as excinfo:
        db.list_txs(meta.id)
    assert "corrupt database" in str(excinfo.value)


def test_write_rejects_non_finite_amount(tmp_path):
    db = Database.create(tmp_path / "finance.db")
    meta = make_meta()
    db.insert_account(meta)
    bad = tx("a0000000")
    bad.amount = Decimal("NaN")
    with pytest.raises(FinanceMDError):
        db.replace_txs(meta.id, [bad])


def test_edit_locked_roundtrip(tmp_path):
    db = Database.create(tmp_path / "finance.db")
    meta = make_meta()
    db.insert_account(meta)
    db.replace_txs(meta.id, [tx("a0000000")])
    with db.edit_locked([meta.id]) as snapshot:
        snapshot[meta.id].append(tx("b0000000", "2026-09-02"))
    assert [t.ref for t in db.list_txs(meta.id)] == ["a0000000", "b0000000"]


def test_edit_locked_rolls_back_on_error(tmp_path):
    db = Database.create(tmp_path / "finance.db")
    meta = make_meta()
    db.insert_account(meta)
    db.replace_txs(meta.id, [tx("a0000000")])
    with pytest.raises(RuntimeError), db.edit_locked([meta.id]) as snapshot:
        snapshot[meta.id].clear()
        raise RuntimeError("boom")
    assert [t.ref for t in db.list_txs(meta.id)] == ["a0000000"]


def test_new_ref_avoids_taken():
    taken = {"00000000"}
    assert new_ref(taken) != "00000000"
