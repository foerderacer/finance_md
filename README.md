# finance_md

Markdown-backed finance management for multiple accounts.
**Your `.md` files are the database** — everything stays plain, readable,
renderable Markdown that you can hand-edit, diff in git, and view in any
editor or Markdown preview.

```
finances/
  index.md          <- generated overview (regenerated after every change)
  accounts/
    checking.md     <- one ledger per account
    savings.md
```

## Why

- No database, no lock-in: account ledgers are ordinary Markdown files with a
  YAML frontmatter header and a transaction table.
- Hand-editing is a first-class workflow. The tool parses strictly and reports
  problems as `file:line`, so typos are caught instead of silently ignored.
- Deterministic writes: rows are sorted by date, then Ref, files use `\n`
  line endings — git diffs stay minimal.
- Balances are computed on read (sum of amounts), never stored — no drift.

## Install

```
pip install finance_md
```

Requires Python 3.9+. The only runtime dependency is PyYAML.

## Quickstart

```
finance-md init                                                 # creates ./finances
cd finances
finance-md account add Checking --type bank --currency EUR
finance-md account add Savings --type savings --currency EUR
finance-md add Checking 2026-09-01 "Salary" 2500.00 --category income
finance-md add Checking 2026-09-03 "Grocery" -23.10 --category food
finance-md transfer Checking Savings 100 --date 2026-09-05
finance-md summary
finance-md validate
```

Amounts use the sign convention **income `+` / expense `-`**, two decimal
places, no thousands separators.

## File format

`index.md` is generated and may be deleted and rebuilt at any time; the
account files are authoritative.

```markdown
# Finance Workspace

| Account | Type | Currency | Balance | File |
|---|---|---|---:|---|
| Checking | bank | EUR | 2376.90 | accounts/checking.md |
```

`accounts/checking.md`:

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

- **Ref**: 8-hex-character stable id, auto-assigned by the tool on `add` and
  `transfer`. Hand-added rows without a `Ref` get one assigned on the next
  tool write (idempotent afterwards).
- **Transfers**: the withdrawal and deposit entries **share the same Ref**
  across the two account files — that shared Ref is the linkage. Ref
  uniqueness is enforced per account.
- **Amount**: decimal with exactly 2 places, no thousands separators.
- **Balance**: computed on read (sum of Amount), never stored.
- The table schema is fixed to the 5 columns above; any deviation is a
  validation error with `file:line`. Notes go in `Description` (free text;
  `|` and `\` are escaped automatically).
- Files are written with `\n`, parsed with universal newlines.
- Parsing is strict for finance safety: bad date, bad amount, duplicate Ref,
  or a missing field is an error with `file:line` — never silently skipped.
  Only the title, the `## Transactions` heading and the table may appear in
  the body, so tool writes can never drop hand-written content.

## CLI reference

| Command | Description |
|---|---|
| `finance-md init [DIR]` | create a workspace (default `./finances`) |
| `finance-md account add NAME --type TYPE --currency CODE` | create an account |
| `finance-md account list` | list accounts with balances |
| `finance-md account archive NAME` | archive an account |
| `finance-md add ACCOUNT DATE DESCRIPTION AMOUNT [--category C]` | add a transaction |
| `finance-md list ACCOUNT [--month YYYY-MM] [--category C]` | list transactions |
| `finance-md edit ACCOUNT REF [--date --description --category --amount]` | edit by ref |
| `finance-md delete ACCOUNT REF` | delete by ref |
| `finance-md transfer FROM TO AMOUNT [--date --description]` | move money (same currency) |
| `finance-md summary [--month YYYY-MM]` | balances, archived accounts, category totals |
| `finance-md validate` | lint the whole workspace (non-zero exit on issues) |

Every command accepts `--workspace PATH` (before or after the command).
Exit codes: `0` ok, `1` error, `2` usage.

Workspace resolution order: `--workspace` flag, then `FINANCE_MD_WORKSPACE`
environment variable, then the current directory if it contains `index.md`;
otherwise an error tells you to run `finance-md init`.

Archived accounts reject new transactions and transfers; `edit`/`delete`
still work for corrections, and `summary` lists archived accounts separately.

## Library usage

```python
from decimal import Decimal

from finance_md import Workspace, service

ws = Workspace.open("~/finances")          # or Workspace.init(path)
ws.create_account("Checking", "bank", "EUR")

service.add_tx(ws, "Checking", date(2026, 9, 1), "Salary", Decimal("2500.00"), category="income")
out_tx, in_tx = service.transfer(ws, "Checking", "Savings", Decimal("100.00"))

for path, meta, txs in ws.load_all():
    print(meta.name, meta.currency, sum(t.amount for t in txs))

issues = service.validate(ws)              # [] means the workspace is valid
```

The `finance_md.store` module is pure (text in, objects out) if you want to
work with the file format directly, and `finance_md.errors` defines
`FinanceMDError`, `WorkspaceError`, `ParseError(file, line)` and
`NotFoundError`.

## Concurrency

There is no file locking and concurrent edits are out of scope. Keep your
workspace in git: it gives you history, diffing, and conflict resolution for
free — which is the point of Markdown storage.

## Development

```
pip install -e ".[dev]"
pytest
ruff check .
mypy src
python -m build && twine check dist/*
```

## Roadmap (out of scope in v1)

CSV import/export, budgets, multi-currency/FX, recurring transactions,
file locking and concurrent-edit merge, custom table columns, interest
calculations.

## License

MIT — see [LICENSE](LICENSE).
