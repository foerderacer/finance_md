from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from finance_md import service
from finance_md.errors import NotFoundError, WorkspaceError
from finance_md.workspace import Workspace, slugify


def test_init_creates_structure(tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    assert (ws.root / "index.md").is_file()
    assert (ws.root / "accounts").is_dir()
    assert (ws.root / "index.md").read_text() == (
        "# Finance Workspace\n"
        "\n"
        "| Account | Type | Currency | Balance | File |\n"
        "|---|---|---|---:|---|\n"
    )


def test_init_refuses_existing(tmp_path):
    Workspace.init(tmp_path / "finances")
    with pytest.raises(WorkspaceError):
        Workspace.init(tmp_path / "finances")


def test_open_explicit(tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    assert Workspace.open(ws.root).root == ws.root


def test_open_env(monkeypatch, tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    monkeypatch.setenv("FINANCE_MD_WORKSPACE", str(ws.root))
    assert Workspace.open().root == ws.root


def test_open_cwd(monkeypatch, tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    monkeypatch.chdir(ws.root)
    assert Workspace.open().root == ws.root


def test_open_missing_dir(tmp_path):
    with pytest.raises(WorkspaceError):
        Workspace.open(tmp_path / "nope")


def test_open_cwd_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FINANCE_MD_WORKSPACE", raising=False)
    with pytest.raises(WorkspaceError) as excinfo:
        Workspace.open()
    assert "finance-md init" in str(excinfo.value)


def test_create_account(tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    meta = ws.create_account("Checking Account", "bank", "eur")
    assert meta.currency == "EUR"
    assert meta.archived is False
    assert (ws.accounts_dir / "checking-account.md").is_file()
    index = (ws.root / "index.md").read_text()
    assert "| Checking Account | bank | EUR | 0.00 | accounts/checking-account.md |" in index


def test_create_account_duplicate_name(tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    ws.create_account("Checking", "bank", "EUR")
    with pytest.raises(WorkspaceError):
        ws.create_account("checking", "bank", "EUR")


def test_create_account_slug_collision(tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    ws.create_account("Coffee fund", "cash", "EUR")
    with pytest.raises(WorkspaceError):
        ws.create_account("Coffee!fund", "cash", "EUR")


def test_create_account_bad_type_or_currency(tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    with pytest.raises(WorkspaceError):
        ws.create_account("X", "vault", "EUR")
    with pytest.raises(WorkspaceError):
        ws.create_account("X", "bank", "euro")
    with pytest.raises(WorkspaceError):
        ws.create_account("X", "bank", "EURO")
    with pytest.raises(WorkspaceError):
        ws.create_account("  ", "bank", "EUR")


def test_create_account_unique_ids(tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    metas = [ws.create_account(f"Account {i}", "bank", "EUR") for i in range(10)]
    assert len({meta.id for meta in metas}) == 10


def test_archive_account(tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    ws.create_account("Old", "bank", "EUR")
    meta = ws.archive_account("old")
    assert meta.archived is True
    _path, reloaded, _txs = ws.load_account("Old")
    assert reloaded.archived is True
    index = (ws.root / "index.md").read_text()
    assert "| Old | bank | EUR | 0.00 | accounts/old.md |" in index


def test_load_account_case_insensitive_and_slug(tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    ws.create_account("Checking", "bank", "EUR")
    assert ws.load_account("CHECKING")[1].name == "Checking"
    assert ws.load_account("checking")[1].name == "Checking"


def test_load_account_unknown(tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    with pytest.raises(NotFoundError) as excinfo:
        ws.load_account("Nope")
    assert "known accounts" in str(excinfo.value)


def test_slugify():
    assert slugify("Checking Account") == "checking-account"
    assert slugify(" Foo!!Bar ") == "foo-bar"
    assert slugify("///") == "account"
    assert slugify("Käse") == "k-se"


def test_index_regenerated_with_balance(ws_with_accounts):
    service.add_tx(
        ws_with_accounts,
        "Checking",
        datetime.date(2026, 9, 1),
        "Salary",
        Decimal("2500.00"),
        category="income",
    )
    service.add_tx(
        ws_with_accounts,
        "Checking",
        datetime.date(2026, 9, 3),
        "Grocery",
        Decimal("-23.10"),
        category="food",
    )
    index = (ws_with_accounts.root / "index.md").read_text()
    assert "| Checking | bank | EUR | 2476.90 | accounts/checking.md |" in index
    assert "| Savings | savings | EUR | 0.00 | accounts/savings.md |" in index
