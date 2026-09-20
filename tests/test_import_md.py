from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from finance_md import store
from finance_md.errors import WorkspaceError
from finance_md.import_md import import_md_workspace
from finance_md.models import AccountMeta, Transaction, parse_iso_date
from finance_md.money import parse_user_amount


def build_old_workspace(root, accounts):
    """Create a v0.1-style markdown workspace (index.md + accounts/*.md)."""
    (root / "accounts").mkdir(parents=True)
    index_lines = [
        "# Finance Workspace",
        "",
        "| Account | Type | Currency | Balance | File |",
        "|---|---|---|---:|---|",
    ]
    for meta, txs in accounts:
        path = root / "accounts" / f"{meta.name.lower()}.md"
        store.write_account(path, meta, txs)
        balance = sum((tx.amount for tx in txs), Decimal("0"))
        index_lines.append(
            f"| {meta.name} | {meta.type} | {meta.currency} | {balance} | accounts/{path.name} |"
        )
    (root / "index.md").write_text("\n".join(index_lines) + "\n")


def make_meta(name, account_id, currency="EUR"):
    return AccountMeta(
        id=account_id,
        name=name,
        type="bank",
        currency=currency,
        created=datetime.date(2026, 9, 19),
    )


def txs(*rows):
    return [
        Transaction(
            ref=ref,
            date=parse_iso_date(date),
            description=description,
            category=category,
            amount=parse_user_amount(amount),
        )
        for ref, date, description, category, amount in rows
    ]


def test_import_roundtrip(tmp_path):
    old = tmp_path / "old_md"
    transfer_ref = "abcdef01"
    build_old_workspace(
        old,
        [
            (
                make_meta("Checking", "3f9c2a1b"),
                txs(
                    ("a0000001", "2026-09-01", "Salary", "income", "2500.00"),
                    (transfer_ref, "2026-09-05", "Transfer to Savings", "transfer", "-100.00"),
                ),
            ),
            (
                make_meta("Savings", "2b8e4c1d"),
                txs((transfer_ref, "2026-09-05", "Transfer from Checking", "transfer", "100.00")),
            ),
        ],
    )
    dest = tmp_path / "finances"
    ws = import_md_workspace(old, dest)
    assert ws.db_path.is_file()
    assert ws.db.counts() == (2, 3)
    meta, loaded = ws.load_account("checking")
    assert meta.id == "3f9c2a1b"
    assert [t.ref for t in loaded] == ["a0000001", "abcdef01"]
    checking, savings = ws.load_account("Checking")[1], ws.load_account("Savings")[1]
    assert {t.ref for t in checking if t.category == "transfer"} == {
        t.ref for t in savings if t.category == "transfer"
    }
    index = (ws.root / "index.md").read_text()
    assert "| Checking | bank | EUR | 2400.00 | accounts/checking.md |" in index
    assert (ws.accounts_dir / "checking.md").is_file()
    assert (ws.accounts_dir / "savings.md").is_file()


def test_import_refuses_missing_source(tmp_path):
    with pytest.raises(WorkspaceError) as excinfo:
        import_md_workspace(tmp_path / "nope", tmp_path / "dest")
    assert "no markdown workspace" in str(excinfo.value)


def test_import_refuses_empty_accounts(tmp_path):
    old = tmp_path / "old_md"
    old.mkdir()
    (old / "accounts").mkdir()
    with pytest.raises(WorkspaceError) as excinfo:
        import_md_workspace(old, tmp_path / "dest")
    assert "no account .md files" in str(excinfo.value)


def test_import_aborts_on_corrupt_file(tmp_path):
    old = tmp_path / "old_md"
    build_old_workspace(
        old,
        [
            (make_meta("Checking", "3f9c2a1b"), txs(("a0000001", "2026-09-01", "X", "y", "1.00"))),
        ],
    )
    path = old / "accounts" / "checking.md"
    path.write_text(path.read_text().replace("1.00", "1,00"))
    dest = tmp_path / "finances"
    with pytest.raises(WorkspaceError) as excinfo:
        import_md_workspace(old, dest)
    assert "checking.md" in str(excinfo.value)
    assert "invalid amount" in str(excinfo.value)
    assert not dest.exists()


def test_import_aborts_on_duplicate_ids(tmp_path):
    old = tmp_path / "old_md"
    build_old_workspace(
        old,
        [
            (make_meta("Checking", "3f9c2a1b"), []),
            (make_meta("Other", "3f9c2a1b"), []),
        ],
    )
    with pytest.raises(WorkspaceError) as excinfo:
        import_md_workspace(old, tmp_path / "dest")
    assert "duplicate account id" in str(excinfo.value)


def test_import_refuses_existing_destination(tmp_path):
    old = tmp_path / "old_md"
    build_old_workspace(old, [(make_meta("Checking", "3f9c2a1b"), [])])
    dest = tmp_path / "finances"
    dest.mkdir()
    (dest / "finance.db").write_bytes(b"not a database")
    with pytest.raises(WorkspaceError):
        import_md_workspace(old, dest)


def test_import_refuses_same_source_and_destination(tmp_path):
    old = tmp_path / "old_md"
    build_old_workspace(old, [(make_meta("Checking", "3f9c2a1b"), [])])
    with pytest.raises(WorkspaceError) as excinfo:
        import_md_workspace(old, old)
    assert "same directory" in str(excinfo.value)
    # The source is untouched.
    assert (old / "accounts" / "checking.md").is_file()


def test_import_aborts_on_slug_collision(tmp_path):
    old = tmp_path / "old_md"
    build_old_workspace(
        old,
        [
            (make_meta("Coffee fund", "3f9c2a1b"), []),
            (make_meta("Coffee!fund", "2b8e4c1d"), []),
        ],
    )
    dest = tmp_path / "finances"
    with pytest.raises(WorkspaceError) as excinfo:
        import_md_workspace(old, dest)
    assert "same view file" in str(excinfo.value)
    assert not dest.exists()


def test_failed_import_cleans_up_destination(tmp_path, monkeypatch):
    from finance_md.db import Database

    old = tmp_path / "old_md"
    build_old_workspace(old, [(make_meta("Checking", "3f9c2a1b"), [])])
    dest = tmp_path / "finances"

    def boom(self, entries):
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(Database, "import_entries", boom)
    with pytest.raises(RuntimeError):
        import_md_workspace(old, dest)
    assert not dest.exists()

    # A pre-existing empty destination directory survives the rollback.
    dest.mkdir()
    with pytest.raises(RuntimeError):
        import_md_workspace(old, dest)
    assert dest.is_dir()
    assert not (dest / "finance.db").exists()
    monkeypatch.undo()
    ws = import_md_workspace(old, dest)  # re-run after fixing succeeds
    assert ws.db.counts() == (1, 0)
