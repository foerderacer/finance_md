# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versions follow [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-09-20

### Changed

- **Breaking**: the database is now the source of truth. Every workspace
  stores its data in a SQLite file (`finance.db`); the `.md` files
  (`index.md` plus one file per account under `accounts/`) are generated
  views that are refreshed after every change. Hand edits to views are
  never read back and are overwritten by the next command, so typo-prone
  editing can no longer corrupt the books.
- `finance-md validate` now checks that the views match the database
  (missing, out-of-sync or orphaned view files) instead of linting
  hand-maintained files.

### Added

- New `finance-md render` command to regenerate the `.md` views without
  changing data.
- New `finance-md import-md SRC [DEST]` command to convert v0.1
  markdown-only workspaces (strict parser; parsing problems abort before
  anything is created and a failed import rolls the destination back).
- Atomic multi-account writes: transfers persist both sides in one SQLite
  transaction, and read-modify-write runs under the write lock, so
  concurrent CLI invocations serialize instead of overwriting each other.

### Removed

- Hand-editing of `.md` files as a supported workflow (see `import-md` for
  migrating data that was only kept in hand-edited files).

## [0.1.0] - 2026-09-19

### Added

- Markdown-ledger storage: one `.md` file per account plus a generated
  `index.md` overview; strict parsing with `file:line` error locations and
  deterministic, roundtrip-safe writes.
- Accounts with frontmatter metadata (id, name, type, currency, created,
  archived), slug-based filenames, and archive support.
- Transactions: add, list (month/category filters), edit, delete; balances
  computed on read.
- Transfers between same-currency accounts sharing one Ref across both files.
- `summary` with per-account balances, archived separation, and category
  totals (optionally month-scoped).
- `validate` workspace linting.
- `finance-md` CLI (argparse) with exit codes 0/1/2 and `--workspace` /
  `FINANCE_MD_WORKSPACE` resolution, plus `python -m finance_md`.
- Python library API (`Workspace`, `service`, pure `store`) with type hints
  (PEP 561 `py.typed`).
