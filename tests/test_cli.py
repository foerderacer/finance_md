from __future__ import annotations

from decimal import Decimal

import pytest

from finance_md import cli, store


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def add_account(root, name, type_, currency="EUR"):
    cli.main(
        ["--workspace", str(root), "account", "add", name, "--type", type_, "--currency", currency]
    )


def add_tx(root, account, date, description, amount, category=None):
    argv = ["--workspace", str(root), "add", account, date, description, amount]
    if category is not None:
        argv += ["--category", category]
    return cli.main(argv)


def test_init_and_account_flow(capsys, tmp_path):
    root = tmp_path / "finances"
    code, out, _err = run(capsys, "init", str(root))
    assert code == 0
    assert "Initialized" in out
    add_account(root, "Checking", "bank")
    code, out, _err = run(capsys, "--workspace", str(root), "account", "list")
    assert code == 0
    assert "Checking" in out and "EUR" in out and "active" in out


def test_workspace_flag_after_subcommand(capsys, tmp_path):
    root = tmp_path / "finances"
    cli.main(["init", str(root)])
    code, out, _err = run(capsys, "account", "list", "--workspace", str(root))
    assert code == 0
    assert "No accounts" in out


def test_env_and_cwd_resolution(capsys, monkeypatch, tmp_path):
    root = tmp_path / "finances"
    cli.main(["init", str(root)])
    monkeypatch.setenv("FINANCE_MD_WORKSPACE", str(root))
    code, _out, _err = run(capsys, "account", "list")
    assert code == 0
    monkeypatch.delenv("FINANCE_MD_WORKSPACE", raising=False)
    monkeypatch.chdir(root)
    code, _out, _err = run(capsys, "account", "list")
    assert code == 0


def test_no_workspace_error(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FINANCE_MD_WORKSPACE", raising=False)
    code, _out, err = run(capsys, "account", "list")
    assert code == 1
    assert "error" in err and "init" in err


def test_full_flow(capsys, tmp_path):
    root = tmp_path / "finances"
    cli.main(["init", str(root)])
    add_account(root, "Checking", "bank")
    add_account(root, "Savings", "savings")
    assert add_tx(root, "Checking", "2026-09-01", "Salary", "2500.00", "income") == 0
    assert add_tx(root, "Checking", "2026-09-03", "Grocery", "-23.10", "food") == 0
    assert add_tx(root, "Checking", "2026-09-04", "Snacks", "-5", "food") == 0
    capsys.readouterr()
    code, out, _err = run(
        capsys,
        "--workspace", str(root),
        "list", "Checking", "--month", "2026-09", "--category", "food",
    )
    assert code == 0
    assert "Grocery" in out and "Snacks" in out and "Salary" not in out
    assert "Balance: 2471.90 EUR" in out
    code, _out, _err = run(
        capsys,
        "--workspace", str(root),
        "transfer", "Checking", "Savings", "100", "--date", "2026-09-05",
    )
    assert code == 0
    checking_meta, checking_txs = store.read_account(root / "accounts" / "checking.md")
    savings_meta, savings_txs = store.read_account(root / "accounts" / "savings.md")
    assert checking_meta.currency == savings_meta.currency == "EUR"
    transfer_refs_checking = {t.ref for t in checking_txs if t.category == "transfer"}
    transfer_refs_savings = {t.ref for t in savings_txs if t.category == "transfer"}
    assert transfer_refs_checking == transfer_refs_savings
    assert len(transfer_refs_checking) == 1
    code, out, _err = run(capsys, "--workspace", str(root), "summary")
    assert code == 0
    assert "Checking" in out and "Savings" in out and "Categories" in out
    assert "2371.90" in out and "100.00" in out
    code, out, _err = run(capsys, "--workspace", str(root), "summary", "--month", "2026-09")
    assert code == 0
    assert "Month net" in out
    code, out, _err = run(capsys, "--workspace", str(root), "validate")
    assert code == 0
    assert "OK" in out


def test_account_archive_cli(capsys, tmp_path):
    root = tmp_path / "finances"
    cli.main(["init", str(root)])
    add_account(root, "Old", "bank")
    code, out, _err = run(capsys, "--workspace", str(root), "account", "archive", "Old")
    assert code == 0
    code, out, _err = run(capsys, "--workspace", str(root), "account", "list")
    assert code == 0
    assert "archived" in out
    code, out, err = run(capsys, "--workspace", str(root), "add", "Old", "2026-09-01", "X", "1.00")
    assert code == 1
    assert "archived" in err


def test_edit_delete_cli(capsys, tmp_path):
    root = tmp_path / "finances"
    cli.main(["init", str(root)])
    add_account(root, "A", "cash", "USD")
    add_tx(root, "A", "2026-09-01", "Coffee", "3.50", "food")
    path = root / "accounts" / "a.md"
    _meta, txs = store.read_account(path)
    ref = txs[0].ref
    code, _out, _err = run(
        capsys,
        "--workspace", str(root),
        "edit", "A", ref, "--description", "Espresso", "--amount", "4.00",
    )
    assert code == 0
    _meta, txs2 = store.read_account(path)
    assert txs2[0].description == "Espresso"
    assert txs2[0].amount == Decimal("4.00")
    code, _out, _err = run(capsys, "--workspace", str(root), "delete", "A", ref)
    assert code == 0
    _meta, txs3 = store.read_account(path)
    assert txs3 == []
    code, _out, err = run(capsys, "--workspace", str(root), "delete", "A", "00000000")
    assert code == 1
    assert "known refs" in err


def test_edit_with_no_fields(capsys, tmp_path):
    root = tmp_path / "finances"
    cli.main(["init", str(root)])
    add_account(root, "A", "cash", "USD")
    add_tx(root, "A", "2026-09-01", "Coffee", "3.50")
    path = root / "accounts" / "a.md"
    _meta, txs = store.read_account(path)
    code, _out, err = run(capsys, "--workspace", str(root), "edit", "A", txs[0].ref)
    assert code == 2
    assert "nothing to edit" in err


@pytest.mark.parametrize(
    "argv",
    [
        ["--workspace", "{root}", "account", "add", "X", "--type", "bank"],
        ["--workspace", "{root}", "add", "A", "bad-date", "d", "1.00"],
        ["--workspace", "{root}", "add", "A", "2026-09-01", "d", "1,00"],
        ["--workspace", "{root}", "list", "A", "--month", "2026-13"],
        ["bogus"],
    ],
)
def test_usage_errors_exit_2(capsys, tmp_path, argv):
    root = tmp_path / "finances"
    cli.main(["init", str(root)])
    resolved = [part.format(root=root) for part in argv]
    with pytest.raises(SystemExit) as excinfo:
        cli.main(resolved)
    assert excinfo.value.code == 2


def test_runtime_error_exit_1(capsys, tmp_path):
    root = tmp_path / "finances"
    cli.main(["init", str(root)])
    code, _out, err = run(
        capsys, "--workspace", str(root), "add", "Ghost", "2026-09-01", "X", "1.00"
    )
    assert code == 1
    assert "error" in err and "Ghost" in err


def test_init_existing_errors(capsys, tmp_path):
    root = tmp_path / "finances"
    cli.main(["init", str(root)])
    code, _out, err = run(capsys, "init", str(root))
    assert code == 1
    assert "already exists" in err


def test_validate_cli_detects_corruption(capsys, tmp_path):
    root = tmp_path / "finances"
    cli.main(["init", str(root)])
    add_account(root, "A", "bank")
    path = root / "accounts" / "a.md"
    text = path.read_text().replace(
        "|---|---|---|---|---:|",
        "|---|---|---|---|---:|\n| a1b2c3d4 | 2026-13-01 | X | y | 1.00 |",
    )
    path.write_text(text)
    code, out, _err = run(capsys, "--workspace", str(root), "validate")
    assert code == 1
    assert "a.md:" in out and "invalid date" in out


def test_help(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    commands = (
        "init", "account", "add", "list", "edit", "delete", "transfer", "summary", "validate",
    )
    for command in commands:
        assert command in out


def test_python_m_invocation(capsys, tmp_path, monkeypatch):
    import subprocess
    import sys

    root = tmp_path / "finances"
    cli.main(["init", str(root)])
    monkeypatch.setenv("FINANCE_MD_WORKSPACE", str(root))
    result = subprocess.run(
        [sys.executable, "-m", "finance_md", "account", "list"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "No accounts. Add one with 'finance-md account add'."
