from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from finance_md import service
from finance_md.db import Database
from finance_md.errors import NotFoundError, WorkspaceError
from finance_md.models import Transaction
from finance_md.workspace import Workspace, slugify


def test_init_creates_structure(tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    assert ws.db_path.is_file()
    assert (ws.root / "accounts").is_dir()
    assert (ws.root / "index.md").is_file()
    assert (ws.root / "index.md").read_text() == (
        "# Finance Workspace\n"
        "\n"
        "| Account | Type | Currency | Balance | File |\n"
        "|---|---|---|---:|---|\n"
    )
    # The database is a real SQLite database.
    db = Database.open(ws.db_path)
    assert db.counts() == (0, 0)


def test_init_refuses_existing(tmp_path):
    Workspace.init(tmp_path / "finances")
    with pytest.raises(WorkspaceError):
        Workspace.init(tmp_path / "finances")


def test_init_refuses_old_markdown_workspace(tmp_path):
    root = tmp_path / "old"
    root.mkdir()
    (root / "index.md").write_text("# Finance Workspace\n")
    with pytest.raises(WorkspaceError) as excinfo:
        Workspace.init(root)
    assert "import-md" in str(excinfo.value)


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


def test_open_old_markdown_workspace_suggests_import(tmp_path):
    root = tmp_path / "old"
    root.mkdir()
    (root / "index.md").write_text("# Finance Workspace\n")
    with pytest.raises(WorkspaceError) as excinfo:
        Workspace.open(root)
    assert "import-md" in str(excinfo.value)


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
    reloaded, _txs = ws.load_account("Checking Account")
    assert reloaded == meta


def test_create_account_duplicate_name(tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    ws.create_account("Checking", "bank", "EUR")
    with pytest.raises(WorkspaceError):
        ws.create_account("checking", "bank", "EUR")


def test_create_account_slug_collision(tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    ws.create_account("Coffee fund", "cash", "EUR")
    with pytest.raises(WorkspaceError) as excinfo:
        ws.create_account("Coffee!fund", "cash", "EUR")
    assert "same file" in str(excinfo.value)


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
    reloaded, _txs = ws.load_account("Old")
    assert reloaded.archived is True
    index = (ws.root / "index.md").read_text()
    assert "| Old | bank | EUR | 0.00 | accounts/old.md |" in index


def test_load_account_case_insensitive_and_slug(tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    ws.create_account("Checking", "bank", "EUR")
    assert ws.load_account("CHECKING")[0].name == "Checking"
    assert ws.load_account("checking")[0].name == "Checking"


def test_load_account_unknown(tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    ws.create_account("Checking", "bank", "EUR")
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


def test_hand_edit_of_view_is_overwritten_by_next_mutation(ws_with_accounts):
    """The core guarantee: hand-edited views are regenerated, never read back."""
    path = ws_with_accounts.accounts_dir / "checking.md"
    path.write_text("totally mangled content\n")
    service.add_tx(
        ws_with_accounts, "Checking", datetime.date(2026, 9, 8), "Tool", Decimal("2.00")
    )
    text = path.read_text()
    assert "totally mangled" not in text
    meta, txs = ws_with_accounts.load_account("Checking")
    assert [t.description for t in txs] == ["Tool"]
    assert meta.name == "Checking"


def test_hand_added_view_row_is_not_stored(ws_with_accounts):
    path = ws_with_accounts.accounts_dir / "checking.md"
    path.write_text(
        path.read_text().replace(
            "|---|---|---|---|---:|",
            "|---|---|---|---|---:|\n| | 2026-09-07 | Handmade | food | -1.00 |",
        )
    )
    service.add_tx(ws_with_accounts, "Checking", datetime.date(2026, 9, 8), "Tool", Decimal("2.00"))
    _meta, txs = ws_with_accounts.load_account("Checking")
    assert [t.description for t in txs] == ["Tool"]


def test_edit_rejects_duplicate_resolution(ws_with_accounts):
    with pytest.raises(WorkspaceError) as excinfo, ws_with_accounts.edit_multi(
        "Checking", "checking"
    ):
        pass
    assert "already part of this operation" in str(excinfo.value)


def test_init_refuses_stray_view_files(tmp_path):
    root = tmp_path / "finances"
    (root / "accounts").mkdir(parents=True)
    (root / "accounts" / "stray.md").write_text("precious hand data\n")
    with pytest.raises(WorkspaceError) as excinfo:
        Workspace.init(root)
    assert "already contains .md files" in str(excinfo.value)
    assert (root / "accounts" / "stray.md").read_text() == "precious hand data\n"


def test_init_allows_empty_existing_dir(tmp_path):
    root = tmp_path / "finances"
    root.mkdir()
    ws = Workspace.init(root)
    assert ws.db_path.is_file()


def test_open_cwd_v0_1_hint(monkeypatch, tmp_path):
    root = tmp_path / "old"
    root.mkdir()
    (root / "index.md").write_text("# Finance Workspace\n")
    monkeypatch.chdir(root)
    monkeypatch.delenv("FINANCE_MD_WORKSPACE", raising=False)
    with pytest.raises(WorkspaceError) as excinfo:
        Workspace.open()
    assert "import-md" in str(excinfo.value)


def test_open_env_v0_1_hint(monkeypatch, tmp_path):
    root = tmp_path / "old"
    root.mkdir()
    (root / "index.md").write_text("# Finance Workspace\n")
    monkeypatch.setenv("FINANCE_MD_WORKSPACE", str(root))
    with pytest.raises(WorkspaceError) as excinfo:
        Workspace.open()
    assert "import-md" in str(excinfo.value)


def test_load_account_ambiguous_slug(tmp_path):
    ws = Workspace.init(tmp_path / "finances")
    # Create two accounts whose names differ but slugify identically via db
    # access (create_account would refuse).
    from finance_md.models import AccountMeta

    meta1 = AccountMeta(
        id="11111111",
        name="Coffee fund",
        type="cash",
        currency="EUR",
        created=datetime.date(2026, 9, 19),
    )
    meta2 = AccountMeta(
        id="22222222",
        name="Coffee!fund",
        type="cash",
        currency="EUR",
        created=datetime.date(2026, 9, 19),
    )
    ws.db.insert_account(meta1)
    ws.db.insert_account(meta2)
    # A query that is neither name but matches both slugs is ambiguous.
    with pytest.raises(WorkspaceError) as excinfo:
        ws.load_account("Coffee / fund")
    assert "ambiguous" in str(excinfo.value)
    # An exact name match still wins over slug matches.
    assert ws.load_account("Coffee fund")[0].id == "11111111"


def test_mutation_refreshes_only_touched_views(ws_with_accounts, monkeypatch):
    """Mutations write only the affected account file + index, not a full render."""
    import finance_md.views as views

    savings_path = ws_with_accounts.accounts_dir / "savings.md"
    before = savings_path.read_text()

    def no_render(root, entries):
        raise AssertionError("full render must not run during a mutation")

    monkeypatch.setattr(views, "render", no_render)
    service.add_tx(
        ws_with_accounts, "Checking", datetime.date(2026, 9, 1), "Tool", Decimal("2.00")
    )
    checking_text = (ws_with_accounts.accounts_dir / "checking.md").read_text()
    assert "Tool" in checking_text
    assert "2.00" in checking_text
    index = ws_with_accounts.index_path.read_text()
    assert "2.00" in index
    assert savings_path.read_text() == before


def test_write_text_if_changed_skips_identical_content(tmp_path):
    import time

    from finance_md.views import write_text_if_changed

    path = tmp_path / "x.md"
    assert write_text_if_changed(path, "same\n") is True
    first_mtime = path.stat().st_mtime_ns
    time.sleep(0.01)
    assert write_text_if_changed(path, "same\n") is False
    assert path.stat().st_mtime_ns == first_mtime
    assert write_text_if_changed(path, "changed\n") is True
    assert path.read_text() == "changed\n"


def test_edit_failure_leaves_data_and_views_untouched(ws_with_accounts):
    path = ws_with_accounts.accounts_dir / "checking.md"
    before = path.read_text()
    index_before = ws_with_accounts.index_path.read_text()
    with pytest.raises(WorkspaceError), ws_with_accounts.edit("Checking") as (_meta, txs):
        txs.append(
            Transaction(
                ref="a0000000",
                date=datetime.date(2026, 9, 1),
                description="x",
                category="c",
                amount=Decimal("1.00"),
            )
        )
        raise WorkspaceError("boom")
    assert path.read_text() == before
    assert ws_with_accounts.index_path.read_text() == index_before
    assert ws_with_accounts.load_account("Checking")[1] == []
