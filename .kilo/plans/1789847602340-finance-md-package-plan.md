# Plan: `finance_md` — markdown-backed finance management package

## Goal

Create a publishable PyPI package `finance_md`: a finance management system for multiple accounts where **all storage is plain `.md` files** (the defining constraint — files must stay valid, readable, renderable Markdown that users can hand-edit).

## Resolved decisions

| Decision | Choice |
|---|---|
| Package name | `finance_md` (CLI command: `finance-md`) |
| Interface | Python library (core) + argparse CLI on top |
| Data model | Account = transaction ledger (date, description, category, amount); transfers = linked entry pairs |
| Layout | One `.md` file per account + top-level `index.md` overview |
| Entry format | Markdown table row per transaction |
| Currency | Per-account currency in frontmatter; transfers only between same-currency accounts; no FX |
| v1 features | CRUD + transfers + summary/reports + validate. CSV import/export explicitly out of scope |
| Dependencies | `PyYAML` only; CLI with stdlib `argparse`; Python >= 3.9 |

## Storage format (source of truth)

Workspace = directory containing `index.md`:

```
finances/
  index.md
  accounts/
    checking.md
    savings.md
```

`index.md` — generated overview (regenerated after every mutation; account files are authoritative, index is derived and may be deleted/rebuilt):

```markdown
# Finance Workspace

| Account | Type | Currency | Balance | File |
|---|---|---|---:|---|
| Checking | bank | EUR | 1234.56 | accounts/checking.md |
```

Account file `accounts/checking.md`:

```markdown
---
id: 3f9c2a1b
name: Checking
type: bank            # bank | cash | credit | savings | other
currency: EUR
created: 2026-09-19
archived: false
---

# Checking

## Transactions

| Ref | Date | Description | Category | Amount |
|---|---|---|---|---:|
| 3f9c2a1b | 2026-09-01 | Salary | income | 2500.00 |
| a1b2c3d4 | 2026-09-03 | Grocery | food | -23.10 |
```

Format rules:
- `Ref`: 8-hex-char stable id, auto-assigned by the tool on `add`/transfer. Hand-added rows without a `Ref` get one assigned on the next tool write (idempotent afterwards).
- Transfers: the withdrawal and deposit entries **share the same Ref**, which is the linkage (no extra state, no metadata duplication).
- Amount: `Decimal`, 2 decimal places, sign convention income `+` / expense `-`. No thousands separators.
- Balance is **computed on read** (sum of Amount) — never stored, so no drift.
- Table schema is fixed to the 5 columns above; any deviation is a validation error with `file:line`. Notes go in `Description` (free text).
- Files are written with `\n`, parsed with universal newlines; write is deterministic (rows sorted by date, then Ref) so git diffs stay minimal.
- Parsing is strict for finance safety: bad date/amount/duplicate Ref/missing field → error with `file:line`, never silently skipped.

## Package structure (src layout, PEP 621)

```
pyproject.toml          # hatchling backend, PyYAML dep, [project.scripts] finance-md
README.md               # format docs + quickstart (PyPI landing page)
LICENSE                 # MIT
CHANGELOG.md
.gitignore
src/finance_md/
  __init__.py           # __version__ via importlib.metadata (fallback "0.0.0.dev0")
  __main__.py           # python -m finance_md
  cli.py                # argparse parsers, command dispatch, exit codes (0 ok / 1 error / 2 usage)
  errors.py             # FinanceMDError, WorkspaceError, ParseError(file, line), NotFoundError
  models.py             # @dataclass Transaction(ref, date, description, category, amount: Decimal);
                        # @dataclass AccountMeta(id, name, type, currency, created, archived)
  money.py              # Decimal parse/format helpers (reject NaN/inf, quantize 2dp)
  frontmatter.py        # minimal YAML frontmatter split + PyYAML load/dump
  store.py              # read_account / write_account: parse & serialize account .md files (roundtrip-safe)
  workspace.py          # Workspace: discovery (cwd or --workspace, must contain index.md),
                        # init, account create/list/archive, index regeneration
  service.py            # high-level ops used by CLI and library users:
                        # add, list, edit, delete, transfer, summary, validate
tests/
  conftest.py           # tmp_path workspace fixtures
  test_money.py  test_frontmatter.py  test_store.py
  test_workspace.py  test_service.py  test_cli.py
```

Library sketch: `Workspace.open(path)` → `ws.accounts`, `ws.add_tx(account, ...)`, `ws.transfer(from, to, amount, date)`, `ws.summary(month=None)`; `store` functions are pure (str/bytes in/out) for testability.

## CLI commands (v1)

- `finance-md init [DIR]` (default `./finances`)
- `finance-md account add NAME --type bank --currency EUR` / `account list` / `account archive NAME`
- `finance-md add ACCOUNT DATE DESCRIPTION AMOUNT [--category C]`
- `finance-md list ACCOUNT [--month YYYY-MM] [--category C]`
- `finance-md edit ACCOUNT REF [--date --description --category --amount]`
- `finance-md delete ACCOUNT REF`
- `finance-md transfer FROM TO AMOUNT [--date --description]` (same-currency enforced)
- `finance-md summary [--month YYYY-MM]` (per-account balances; category totals; archived accounts shown separately)
- `finance-md validate` (lint whole workspace; exit non-zero on any issue)

Workspace resolution: `--workspace` flag → `FINANCE_MD_WORKSPACE` env var → cwd if it contains `index.md` → error telling user to run `init`. No config file.

## Edge cases to handle

- Hand-edited rows: parse strictly, report `file:line`; missing `Ref` columns filled on next write.
- Duplicate `Ref`s within or across accounts → `validate` and all mutations fail with location info.
- Account name → filename slug: slugify name; reject collision with existing file/id.
- Transfer to/from archived account rejected; `summary` separates archived.
- Delete/edit by unknown Ref → clear error listing nearby refs.
- Concurrent writers: out of scope (no locking); document "use git" in README.

## Packaging / PyPI

- `pyproject.toml`: PEP 621, `requires-python = ">=3.9"`, deps `["PyYAML>=6.0"]`, hatchling backend, classifiers, `license`, `readme`, `urls`.
- Dev extras: `pytest`, `ruff`, `mypy`, `build`, `twine`.
- Publish path: `python -m build` → `twine check dist/*` → `twine upload` (manual), plus optional GitHub Actions workflow: test matrix (3.9–3.13) on push, and `pypi-publish` with trusted publishing on `v*` tags.
- Version: static in `pyproject.toml`; start at `0.1.0`.

## Validation plan

1. `pytest` with: roundtrip/idempotency tests (parse→write→parse yields identical bytes for tool-written files), corrupt-fixture tests (bad amount, bad date, dup Ref, missing field → correct `file:line`), transfer invariant tests (same ref both sides, balance math, currency mismatch rejected), CLI integration tests via `capsys`.
2. `ruff check` + `mypy src` clean.
3. `python -m build && twine check dist/*` before any upload.
4. Manual smoke: `init` → `account add` ×2 → `add` ×3 → `transfer` → `summary` → hand-edit a `.md` in an editor → `validate` and confirm tool accepts/rejects appropriately.

## Out of scope (v1)

CSV import/export, budgets, multi-currency/FX, recurring transactions, file locking/concurrent-edit merge, custom table columns, interest calculations. Listed as future work in README.

## Task order

1. Scaffold repo: `pyproject.toml`, src layout, LICENSE, README skeleton, `.gitignore`.
2. `errors.py`, `money.py`, `models.py`, `frontmatter.py` (+ unit tests).
3. `store.py` parse/serialize with roundtrip tests and corrupt fixtures.
4. `workspace.py`: init, discovery, account CRUD, index regeneration (+ tests).
5. `service.py`: add/list/edit/delete/transfer/summary/validate (+ tests).
6. `cli.py` + `__main__.py` wiring, exit codes, help texts (+ CLI tests).
7. Full README (format spec, quickstart, library usage), CHANGELOG, version 0.1.0.
8. Quality gate: pytest, ruff, mypy, build + twine check; optional GitHub Actions workflow.
