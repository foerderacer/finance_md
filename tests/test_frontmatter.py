from __future__ import annotations

import pytest

from finance_md import frontmatter
from finance_md.errors import ParseError


def test_split_frontmatter_ok():
    text = "---\nid: abc\n---\n\n# Title\n"
    yaml_text, body, line = frontmatter.split_frontmatter(text, "a.md")
    assert yaml_text == "id: abc"
    assert body == "\n# Title\n"
    assert line == 3


def test_split_frontmatter_missing_open():
    with pytest.raises(ParseError) as excinfo:
        frontmatter.split_frontmatter("no frontmatter", "a.md")
    assert excinfo.value.line == 1


def test_split_frontmatter_unterminated():
    with pytest.raises(ParseError):
        frontmatter.split_frontmatter("---\nid: abc\n", "a.md")


def test_load_yaml_invalid():
    with pytest.raises(ParseError):
        frontmatter.load_yaml("id: [unclosed", "a.md", 5)


def test_load_yaml_non_mapping():
    with pytest.raises(ParseError):
        frontmatter.load_yaml("- a\n- b", "a.md", 5)


def test_load_yaml_empty():
    assert frontmatter.load_yaml("", "a.md", 5) == {}


def test_load_yaml_scalar_value_rejected():
    with pytest.raises(ParseError):
        frontmatter.load_yaml("42", "a.md", 5)


def test_dump_yaml_stable():
    assert frontmatter.dump_yaml("Checking").startswith("Checking")
    assert frontmatter.dump_yaml("123").startswith("'123'")
    assert frontmatter.dump_yaml({"a": 1}) == "a: 1\n"
