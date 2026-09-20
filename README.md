# finance_md

SQLite-backed finance management for multiple accounts.
**The database is the source of truth** — every workspace stores its data in
a robust SQLite file (`finance.db`), and plain, readable, renderable
Markdown files (`index.md` plus one file per account) are generated from it
after every change as a visualization you can read, diff and render.

```
finances/
  finance.db        <- the real database (SQLite)
  index.md          <- generated overview (refreshed after every change)
  accounts/
    checking.md     <- generated ledger view per account
    savings.md
```

## Why

- **Dumbest-user-proof storage**: ledger data lives in SQLite, not in files
  people like to edit. A mangled, half-deleted or typo-ridden `.md` file
  can never corrupt your books — the next command regenerates it from the
  database.
- The `.md` views stay ordinary Markdown: readable, renderable in any
  preview, and git-diffable after every change (deterministic writes, rows
  sorted by date, then Ref).
- Real transactional safety: transfers write both accounts in one atomic
  SQLite transaction; balances are computed on read, never stored.
- Hand-editing is no longer a supported workflow. To change data, use the
  CLI (`add`, `edit`, `delete`, `transfer`) — it validates every field.

## Install

```
pip install finance_md
```

Requires Python 3.9+. The only runtime dependency is PyYAML (used to render
and to import v0.1 workspaces); SQLite is part of the Python standard
library.

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

## Architecture

- `finance.db` is a SQLite database with an `accounts` table (id, name,
  type, currency, created, archived) and a `transactions` table (account,
  ref, date, description, category, amount), plus a schema version marker.
  Delete it and you have lost your data — back it up like any database.
- Every mutating command writes the database and then **regenerates the
  `.md` views**. Views are treated as caches: hand edits are never read
  back and are silently overwritten.
- `finance-md validate` checks that the views match the database and
  reports missing, out-of-sync or orphaned view files.
- `finance-md render` regenerates the views without changing any data —
  useful after you (or an editor plugin) mangled them.

## View format

The generated files are plain Markdown. A generated banner marks them as
machine-owned:

```markdown
<!-- GENERATED FILE - do not edit. The database (finance.db) is the source of truth; any change here is overwritten by the next finance-md command. -->
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

Format rules (as produced by the tool):

- **Ref**: 8-hex-character stable id; transfers share the same Ref across
  the two account views, which is the transfer linkage.
- **Amount**: decimal with exactly 2 places; income `+`, expense `-`.
- **Balance**: computed on read (sum of Amount), never stored.
- Files are written with `\n` and rows sorted by date, then Ref, so git
  diffs stay minimal.

## Migrating from v0.1 (markdown-only workspaces)

v0.1 stored the data directly in the `.md` files. Convert an old workspace:

```
finance-md import-md OLD_DIR [DEST]     # DEST defaults to ./finances
```

The old workspace is parsed with the strict v0.1 parser; any problem (bad
amount, bad date, duplicate account id, name or filename slug) aborts the
import before anything is created, and a failed import rolls the
destination back. The source directory is never written to, and importing
a directory into itself is refused — delete the old directory after you
are satisfied with the converted workspace.

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
| `finance-md validate` | check views against the database (non-zero exit on issues) |
| `finance-md render` | regenerate the `.md` views from the database |
| `finance-md import-md SRC [DEST]` | import a v0.1 markdown-only workspace |

Every command accepts `--workspace PATH` (before or after the command).
Exit codes: `0` ok, `1` error, `2` usage.

Workspace resolution order: `--workspace` flag, then `FINANCE_MD_WORKSPACE`
environment variable, then the current directory if it contains
`finance.db`; otherwise an error tells you to run `finance-md init`.

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

for meta, txs in ws.load_all():
    print(meta.name, meta.currency, sum(t.amount for t in txs))

issues = service.validate(ws)              # [] means the views match the database
```

Lower layers: `finance_md.db.Database` is the SQLite repository, `views`
renders the `.md` files, and `finance_md.store` keeps the v0.1 strict
parser/serializer (used by `import-md`). `finance_md.errors` defines
`FinanceMDError`, `WorkspaceError`, `ParseError(file, line)` and
`NotFoundError`.

## Concurrency

SQLite gives you real multi-process safety on one machine: reads are
concurrent, writes take a short exclusive lock, and each multi-account
operation is atomic. Working from several machines at once (e.g. a synced
folder) is still out of scope — pick one writer at a time. Keep the
workspace in git or a backup routine: `finance.db` holds the data, and the
generated views diff nicely.

## Development

```
pip install -e ".[dev]"
pytest
ruff check .
mypy src
python -m build && twine check dist/*
```

## Roadmap (out of scope in v0.2)

CSV import/export, budgets, multi-currency/FX, recurring transactions,
custom table columns, interest calculations, workspace-level encryption.

## License

MIT — see [LICENSE](LICENSE).
