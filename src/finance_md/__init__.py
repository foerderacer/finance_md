"""finance_md: SQLite-backed finance management; .md files are generated views."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .db import Database
from .errors import FinanceMDError, NotFoundError, ParseError, WorkspaceError
from .models import ACCOUNT_TYPES, AccountMeta, Transaction
from .workspace import Workspace

try:
    __version__ = version("finance_md")
except PackageNotFoundError:  # pragma: no cover - only when not installed
    __version__ = "0.0.0.dev0"

__all__ = [
    "ACCOUNT_TYPES",
    "AccountMeta",
    "Database",
    "FinanceMDError",
    "NotFoundError",
    "ParseError",
    "Transaction",
    "Workspace",
    "WorkspaceError",
    "__version__",
]
