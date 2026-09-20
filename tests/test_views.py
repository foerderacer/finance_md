from __future__ import annotations

import datetime

from finance_md import store, views
from finance_md.models import AccountMeta, Transaction, parse_iso_date
from finance_md.money import parse_user_amount


def meta(name="Checking", account_id="3f9c2a1b"):
    return AccountMeta(
        id=account_id,
        name=name,
        type="bank",
        currency="EUR",
        created=datetime.date(2026, 9, 19),
    )


def tx(ref, date, description, category, amount):
    return Transaction(
        ref=ref,
        date=parse_iso_date(date),
        description=description,
        category=category,
        amount=parse_user_amount(amount),
    )


def test_slugify():
    assert views.slugify("Checking Account") == "checking-account"
    assert views.slugify(" Foo!!Bar ") == "foo-bar"
    assert views.slugify("///") == "account"
    assert views.slugify("Käse") == "k-se"


def test_account_view_has_warning_and_canonical_body():
    rows = [tx("a0000000", "2026-09-01", "Salary", "income", "100")]
    text = views.account_view_text(meta(), rows)
    assert text.startswith("<!-- GENERATED FILE - do not edit.")
    body = text.split("\n", 1)[1]
    assert body == store.serialize_account(meta(), rows)
    assert "| a0000000 | 2026-09-01 | Salary | income | 100.00 |" in body


def test_index_content_empty():
    assert views.index_content_from([]) == (
        "# Finance Workspace\n"
        "\n"
        "| Account | Type | Currency | Balance | File |\n"
        "|---|---|---|---:|---|\n"
    )


def test_index_content_balances():
    entries = [
        (meta(), [tx("a0000000", "2026-09-01", "Salary", "income", "100.00")]),
        (meta(name="Alone", account_id="bbbbbbbb"), []),
    ]
    content = views.index_content_from(entries)
    assert "| Checking | bank | EUR | 100.00 | accounts/checking.md |" in content
    assert "| Alone | bank | EUR | 0.00 | accounts/alone.md |" in content


def test_render_writes_and_cleans_orphans(tmp_path):
    entries = [(meta(), [tx("a0000000", "2026-09-01", "Salary", "income", "100")])]
    written = views.render(tmp_path, entries)
    assert written == ["index.md", "accounts/checking.md"]
    assert (tmp_path / "index.md").is_file()
    assert (tmp_path / "accounts" / "checking.md").is_file()
    orphan = tmp_path / "accounts" / "ghost.md"
    orphan.write_text("orphan")
    second = tmp_path / "accounts" / "other.txt"
    second.write_text("keep me")
    views.render(tmp_path, entries)
    assert not orphan.exists()
    assert second.exists()


def test_render_is_deterministic(tmp_path):
    entries = [(meta(), [tx("a0000000", "2026-09-01", "S", "c", "1")])]
    views.render(tmp_path, entries)
    first = (tmp_path / "accounts" / "checking.md").read_text()
    views.render(tmp_path, entries)
    assert (tmp_path / "accounts" / "checking.md").read_text() == first
