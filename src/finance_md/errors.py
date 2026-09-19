"""Exception hierarchy for finance_md."""

from __future__ import annotations


class FinanceMDError(Exception):
    """Base class for all finance_md errors."""


class WorkspaceError(FinanceMDError):
    """Raised for workspace-level problems (missing index.md, bad setup)."""


class ParseError(FinanceMDError):
    """Raised when an account file cannot be parsed strictly.

    ``file`` is the path as reported to the user; ``line`` is the 1-based
    line number, or None for file-level problems.
    """

    def __init__(self, file: str, line: int | None, message: str) -> None:
        self.file = file
        self.line = line
        self.message = message
        location = f"{file}:{line}" if line is not None else file
        super().__init__(f"{location}: {message}")


class NotFoundError(FinanceMDError):
    """Raised when an account or transaction ref does not exist."""
