# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versions follow [Semantic Versioning](https://semver.org/).

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
