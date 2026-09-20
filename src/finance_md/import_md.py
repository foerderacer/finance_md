"""Import a v0.1 markdown-only workspace into a database-backed workspace."""

from __future__ import annotations

from pathlib import Path

from . import store
from .errors import FinanceMDError, WorkspaceError
from .models import AccountMeta, Transaction, slugify
from .views import ACCOUNTS_DIR
from .workspace import Workspace


def _prevalidate(
    md_files: list[Path],
) -> list[tuple[AccountMeta, list[Transaction]]]:
    """Strictly parse all account files; abort on any problem."""
    parsed: list[tuple[AccountMeta, list[Transaction]]] = []
    issues: list[str] = []
    ids: dict[str, str] = {}
    names: dict[str, str] = {}
    slugs: dict[str, str] = {}
    for path in md_files:
        try:
            meta, txs = store.read_account(path)
        except FinanceMDError as exc:
            issues.append(str(exc))
            continue
        if meta.id in ids:
            issues.append(f"{path.name}: duplicate account id {meta.id} (also in {ids[meta.id]})")
        ids[meta.id] = meta.name
        key = meta.name.lower()
        if key in names:
            issues.append(f"{path.name}: duplicate account name {meta.name!r}")
        names[key] = meta.name
        file_slug = slugify(meta.name)
        if file_slug in slugs:
            issues.append(
                f"{path.name}: account {meta.name!r} would use the same view file as "
                f"{slugs[file_slug]!r} ({ACCOUNTS_DIR}/{file_slug}.md)"
            )
        slugs[file_slug] = meta.name
        parsed.append((meta, txs))
    if issues:
        raise WorkspaceError(
            "cannot import; fix these problems in the markdown workspace first:\n"
            + "\n".join(issues)
        )
    return parsed


def import_md_workspace(src: str | Path, dest: str | Path) -> Workspace:
    """Convert a v0.1 markdown workspace at *src* into a new workspace at *dest*.

    All ``accounts/*.md`` files are parsed with the strict v0.1 parser.
    Any parsing problem (bad amount, bad date, duplicate account id, name or
    slug) aborts the import before anything is created. The destination is
    populated from the database first and the views are rendered last, so a
    failure can never destroy the source; if creation fails, the partial
    destination is removed again.
    """
    src_path = Path(src)
    dest_path = Path(dest)
    if src_path.resolve() == dest_path.resolve():
        raise WorkspaceError(
            "refusing to import: source and destination are the same directory; "
            "pass a destination outside the source"
        )
    accounts_dir = src_path / ACCOUNTS_DIR
    if not src_path.is_dir() or not accounts_dir.is_dir():
        raise WorkspaceError(
            f"no markdown workspace at {src_path} "
            f"(expected an '{ACCOUNTS_DIR}/' directory with account .md files)"
        )
    md_files = sorted(accounts_dir.glob("*.md"))
    if not md_files:
        raise WorkspaceError(f"no account .md files found in {accounts_dir}")

    parsed = _prevalidate(md_files)

    dest_db = dest_path / "finance.db"
    if dest_db.exists():
        raise WorkspaceError(f"refusing to import: {dest_db} already exists")
    dest_existed = dest_path.is_dir()
    from .db import Database

    db = Database.create(dest_db)
    workspace = Workspace.__new__(Workspace)
    workspace.root = dest_path
    workspace._db = db
    try:
        db.import_entries(parsed)
    except BaseException:
        # Roll the destination back so a re-run starts clean. Only the
        # database file is removed (views were not rendered yet).
        db.path.unlink(missing_ok=True)
        if not dest_existed and dest_path.is_dir() and not any(dest_path.iterdir()):
            dest_path.rmdir()
        raise
    workspace.refresh_views()
    return workspace
