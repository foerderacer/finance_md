from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from finance_md import store
from finance_md.errors import ParseError
from finance_md.models import AccountMeta, Transaction


def make_meta(**overrides):
    values = dict(
        id="3f9c2a1b",
        name="Checking",
        type="bank",
        currency="EUR",
        created=datetime.date(2026, 9, 19),
    )
    values.update(overrides)
    return AccountMeta(**values)


def make_txs():
    return [
        Transaction("a1b2c3d4", datetime.date(2026, 9, 3), "Grocery", "food", Decimal("-23.10")),
        Transaction("3f9c2a1b", datetime.date(2026, 9, 1), "Salary", "income", Decimal("2500.00")),
    ]


def hand_text(rows):
    return (
        "---\n"
        "id: 3f9c2a1b\n"
        "name: Checking\n"
        "type: bank\n"
        "currency: EUR\n"
        "created: 2026-09-19\n"
        "archived: false\n"
        "---\n"
        "\n"
        "# Checking\n"
        "\n"
        "## Transactions\n"
        "\n"
        "| Ref | Date | Description | Category | Amount |\n"
        "|---|---|---|---|---:|\n" + rows
    )


def line_of(text, fragment):
    for number, line in enumerate(text.split("\n"), start=1):
        if fragment in line:
            return number
    raise AssertionError(f"fragment not found: {fragment!r}")


def test_serialize_canonical_shape():
    text = store.serialize_account(make_meta(), make_txs())
    lines = text.split("\n")
    assert lines[0] == "---"
    assert lines[1] == "id: 3f9c2a1b"
    assert lines[2] == "name: Checking"
    assert lines[3] == "type: bank            # bank | cash | credit | savings | other"
    assert lines[4] == "currency: EUR"
    assert lines[5] == "created: 2026-09-19"
    assert lines[6] == "archived: false"
    assert lines[7] == "---"
    assert lines[8] == ""
    assert lines[9] == "# Checking"
    assert lines[10] == ""
    assert lines[11] == "## Transactions"
    assert lines[12] == ""
    assert lines[13] == "| Ref | Date | Description | Category | Amount |"
    assert lines[14] == "|---|---|---|---|---:|"
    assert lines[15] == "| 3f9c2a1b | 2026-09-01 | Salary | income | 2500.00 |"
    assert lines[16] == "| a1b2c3d4 | 2026-09-03 | Grocery | food | -23.10 |"
    assert lines[17] == ""
    assert text.endswith("\n")


def test_serialize_parses_datetime_date_type():
    text = store.serialize_account(make_meta(), [])
    meta, _txs = store.parse_account("a.md", text)
    assert meta.created == datetime.date(2026, 9, 19)


def test_roundtrip_idempotent():
    meta = make_meta()
    txs = make_txs()
    first = store.serialize_account(meta, txs)
    meta2, txs2 = store.parse_account("accounts/checking.md", first)
    assert meta2 == meta
    assert txs2 == sorted(txs, key=lambda tx: (tx.date, tx.ref or ""))
    assert store.serialize_account(meta2, txs2) == first


def test_roundtrip_special_characters():
    txs = [
        Transaction(
            "a1b2c3d4",
            datetime.date(2026, 1, 1),
            "Pub | drinks \\ stuff",
            "food|fun",
            Decimal("-5.00"),
        )
    ]
    text = store.serialize_account(make_meta(), txs)
    meta2, txs2 = store.parse_account("x.md", text)
    assert txs2[0].description == "Pub | drinks \\ stuff"
    assert txs2[0].category == "food|fun"
    assert store.serialize_account(meta2, txs2) == text


def test_rows_sorted_by_date_then_ref():
    txs = [
        Transaction("aaaaaaaa", datetime.date(2026, 9, 10), "B", "x", Decimal("1.00")),
        Transaction("bbbbbbbb", datetime.date(2026, 9, 1), "A", "x", Decimal("2.00")),
        Transaction("cccccccc", datetime.date(2026, 9, 1), "C", "x", Decimal("3.00")),
    ]
    text = store.serialize_account(make_meta(), txs)
    assert text.index("bbbbbbbb") < text.index("cccccccc") < text.index("aaaaaaaa")


def test_serialize_requires_refs():
    txs = [Transaction(None, datetime.date(2026, 1, 1), "x", "y", Decimal("1.00"))]
    with pytest.raises(ValueError):
        store.serialize_account(make_meta(), txs)


def test_write_assigns_refs_and_is_idempotent(tmp_path):
    path = tmp_path / "acc.md"
    txs = [Transaction(None, datetime.date(2026, 1, 1), "hand", "x", Decimal("1.00"))]
    store.write_account(path, make_meta(), txs)
    assert txs[0].ref is not None
    meta, txs2 = store.read_account(path)
    assert txs2[0].ref == txs[0].ref
    content = path.read_text()
    assert "\r" not in path.read_bytes().decode()
    store.write_account(path, meta, txs2)
    assert path.read_text() == content


def test_read_write_bytes_idempotent(tmp_path):
    path = tmp_path / "acc.md"
    store.write_account(path, make_meta(), make_txs())
    first = path.read_bytes()
    meta, txs = store.read_account(path)
    store.write_account(path, meta, txs)
    assert path.read_bytes() == first


def test_crlf_file_is_read_and_normalized(tmp_path):
    path = tmp_path / "acc.md"
    store.write_account(path, make_meta(), make_txs())
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    meta, txs = store.read_account(path)
    assert meta.name == "Checking"
    assert len(txs) == 2
    store.write_account(path, meta, txs)
    assert b"\r" not in path.read_bytes()


def test_numeric_id_is_quoted_and_stable():
    meta = make_meta(id="12345678")
    text = store.serialize_account(meta, [])
    assert "id: '12345678'" in text
    meta2, _txs = store.parse_account("a.md", text)
    assert meta2.id == "12345678"


def test_hand_added_row_without_ref_kept_then_assigned(tmp_path):
    text = hand_text("| | 2026-09-03 | Grocery | food | -23.10 |\n")
    meta, txs = store.parse_account("a.md", text)
    assert txs[0].ref is None
    path = tmp_path / "a.md"
    store.write_account(path, meta, txs)
    _meta2, txs2 = store.read_account(path)
    assert txs2[0].ref is not None


def test_bad_amount_reports_line():
    text = hand_text("| a1b2c3d4 | 2026-09-03 | Grocery | food | -23.1 |\n")
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("accounts/checking.md", text)
    assert excinfo.value.file == "accounts/checking.md"
    assert excinfo.value.line == line_of(text, "-23.1")
    assert "invalid amount" in excinfo.value.message


def test_bad_date_value():
    text = hand_text("| a1b2c3d4 | 2026-13-03 | Grocery | food | -23.10 |\n")
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", text)
    assert excinfo.value.line == line_of(text, "2026-13-03")
    assert "invalid date" in excinfo.value.message


def test_bad_date_format():
    text = hand_text("| a1b2c3d4 | 03.09.2026 | Grocery | food | -23.10 |\n")
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", text)
    assert excinfo.value.line == line_of(text, "03.09.2026")


def test_impossible_date():
    text = hand_text("| a1b2c3d4 | 2026-02-30 | Grocery | food | -23.10 |\n")
    with pytest.raises(ParseError):
        store.parse_account("a.md", text)


def test_duplicate_ref_within_account():
    rows = "| a1b2c3d4 | 2026-09-01 | A | x | 1.00 |\n| a1b2c3d4 | 2026-09-02 | B | y | 2.00 |\n"
    text = hand_text(rows)
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", text)
    assert excinfo.value.line == line_of(text, "2026-09-02")
    assert "duplicate ref" in excinfo.value.message


def test_missing_description():
    text = hand_text("| a1b2c3d4 | 2026-09-03 | | food | -23.10 |\n")
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", text)
    assert excinfo.value.line == line_of(text, "2026-09-03")
    assert "missing description" in excinfo.value.message


def test_missing_category():
    text = hand_text("| a1b2c3d4 | 2026-09-03 | Grocery | | -23.10 |\n")
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", text)
    assert "missing category" in excinfo.value.message


def test_missing_date():
    text = hand_text("| a1b2c3d4 | | Grocery | food | -23.10 |\n")
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", text)
    assert "missing date" in excinfo.value.message


def test_wrong_column_count():
    text = hand_text("| a1b2c3d4 | 2026-09-03 | Grocery | food |\n")
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", text)
    assert excinfo.value.line == line_of(text, "Grocery")
    assert "expected 5 table cells" in excinfo.value.message


def test_invalid_ref():
    text = hand_text("| zz | 2026-09-03 | Grocery | food | -23.10 |\n")
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", text)
    assert "invalid ref" in excinfo.value.message


def test_missing_frontmatter_field():
    text = hand_text("").replace("currency: EUR\n", "")
    closing = [n for n, line in enumerate(text.split("\n"), start=1) if line == "---"][1]
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", text)
    assert "frontmatter missing field(s): currency" in excinfo.value.message
    assert excinfo.value.line == closing


def test_unknown_frontmatter_field():
    text = hand_text("").replace("archived: false", "archived: false\nextra: 1")
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", text)
    assert "unknown frontmatter field(s): extra" in excinfo.value.message


@pytest.mark.parametrize(
    ("field", "value", "message_part"),
    [
        ("type", "vault", "'type'"),
        ("currency", "eur", "'currency'"),
        ("currency", "EURO", "'currency'"),
        ("archived", "maybe", "'archived'"),
        ("created", "not-a-date", "'created'"),
        ("id", "xyz", "'id'"),
        ("name", "''", "'name'"),
    ],
)
def test_bad_frontmatter_values(field, value, message_part):
    text = hand_text("")
    lines = []
    for line in text.split("\n"):
        if line.startswith(f"{field}:") and field != "name":
            line = f"{field}: {value}"
        elif field == "name" and line.startswith("name:"):
            line = f"name: {value}"
        lines.append(line)
    broken = "\n".join(lines)
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", broken)
    assert message_part in excinfo.value.message


def test_missing_frontmatter_entirely():
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", "# Just a title\n")
    assert excinfo.value.line == 1


def test_missing_table():
    text = (
        "---\n"
        "id: 3f9c2a1b\n"
        "name: C\n"
        "type: bank\n"
        "currency: EUR\n"
        "created: 2026-09-19\n"
        "archived: false\n"
        "---\n"
        "\n"
        "# C\n"
    )
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", text)
    assert "transactions table not found" in excinfo.value.message


def test_header_mismatch():
    text = hand_text("").replace(
        "| Ref | Date | Description | Category | Amount |",
        "| Ref | Date | Description | Amount |",
    )
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", text)
    assert "header mismatch" in excinfo.value.message


def test_unexpected_content_before_table():
    text = hand_text("").replace(
        "## Transactions\n", "## Transactions\n\nSome stray notes.\n\n"
    )
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", text)
    assert excinfo.value.line == line_of(text, "Some stray notes.")
    assert "unexpected content before transactions table" in excinfo.value.message


def test_unexpected_content_after_table():
    text = hand_text(
        "| a1b2c3d4 | 2026-09-03 | Grocery | food | -23.10 |\n\nNotes below the table.\n"
    )
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", text)
    assert excinfo.value.line == line_of(text, "Notes below the table.")
    assert "unexpected content after transactions table" in excinfo.value.message


def test_duplicate_row_block_after_table_rejected():
    text = hand_text(
        "| a1b2c3d4 | 2026-09-03 | Grocery | food | -23.10 |\n"
        "\n"
        "| a1b2c3d4 | 2026-09-04 | More | food | -1.00 |\n"
    )
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", text)
    assert "unexpected content after transactions table" in excinfo.value.message


def test_invalid_yaml_frontmatter():
    text = hand_text("").replace("archived: false", "archived: [false")
    with pytest.raises(ParseError):
        store.parse_account("a.md", text)


def test_missing_separator_row():
    text = hand_text("").replace("|---|---|---|---|---:|\n", "")
    with pytest.raises(ParseError) as excinfo:
        store.parse_account("a.md", text)
    assert "expected table separator row" in excinfo.value.message
