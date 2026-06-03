"""Purge session artifacts and orphaned files from the app data directory."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID


@dataclass(frozen=True)
class PurgeResult:
    """Summary of files removed (or that would be removed in dry-run)."""

    paths: tuple[Path, ...] = ()
    dry_run: bool = False

    @property
    def count(self) -> int:
        return len(self.paths)


@dataclass(frozen=True)
class CleanupReport:
    """Aggregate result from a cleanup run."""

    session_purges: tuple[PurgeResult, ...] = ()
    orphan_purges: PurgeResult = field(default_factory=PurgeResult)
    imports_cache_purge: PurgeResult = field(default_factory=PurgeResult)
    logs_purge: PurgeResult = field(default_factory=PurgeResult)
    exports_purge: PurgeResult = field(default_factory=PurgeResult)
    dry_run: bool = False

    @property
    def total_paths(self) -> int:
        return (
            sum(p.count for p in self.session_purges)
            + self.orphan_purges.count
            + self.imports_cache_purge.count
            + self.logs_purge.count
            + self.exports_purge.count
        )


def session_artifact_paths(data_dir: Path, session_id: UUID) -> list[Path]:
    """Known on-disk locations for one session (dirs and export markdown)."""
    sid = str(session_id)
    paths: list[Path] = [
        (data_dir / "chunks" / sid).resolve(),
        (data_dir / "sessions" / sid).resolve(),
        (data_dir / "imports" / "slide_previews" / sid).resolve(),
        (data_dir / "exports" / "screenshots" / sid).resolve(),
    ]
    exports_dir = (data_dir / "exports").resolve()
    if exports_dir.is_dir():
        for md in exports_dir.glob(f"{sid}_*.md"):
            paths.append(md.resolve())
    return paths


def purge_session_artifacts(
    data_dir: Path,
    session_id: UUID,
    *,
    dry_run: bool = True,
) -> PurgeResult:
    """Remove all on-disk artifacts for ``session_id``."""
    removed: list[Path] = []
    for path in session_artifact_paths(data_dir, session_id):
        if not path.exists():
            continue
        removed.append(path)
        if not dry_run:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
    return PurgeResult(paths=tuple(removed), dry_run=dry_run)


def _dir_session_id(name: str) -> UUID | None:
    try:
        return UUID(name)
    except ValueError:
        return None


def find_orphan_artifact_dirs(data_dir: Path, known_session_ids: set[UUID]) -> list[Path]:
    """Find chunk/session/preview dirs whose UUID is not in the database."""
    known = {str(s) for s in known_session_ids}
    orphans: list[Path] = []
    for parent in (
        data_dir / "chunks",
        data_dir / "sessions",
        data_dir / "imports" / "slide_previews",
        data_dir / "exports" / "screenshots",
    ):
        if not parent.is_dir():
            continue
        for child in parent.iterdir():
            if not child.is_dir():
                continue
            sid = _dir_session_id(child.name)
            if sid is None:
                continue
            if child.name not in known:
                orphans.append(child.resolve())
    return sorted(orphans)


def _purge_paths(paths: list[Path], *, dry_run: bool) -> PurgeResult:
    removed: list[Path] = []
    for path in paths:
        if not path.exists():
            continue
        removed.append(path)
        if not dry_run:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
    return PurgeResult(paths=tuple(removed), dry_run=dry_run)


def purge_imports_cache(data_dir: Path, *, dry_run: bool = True) -> PurgeResult:
    cache = (data_dir / "imports" / "downloads").resolve()
    if not cache.is_dir():
        return PurgeResult(dry_run=dry_run)
    paths = [p.resolve() for p in cache.iterdir()]
    return _purge_paths(paths, dry_run=dry_run)


def purge_rotated_logs(data_dir: Path, *, dry_run: bool = True) -> PurgeResult:
    logs_dir = (data_dir / "logs").resolve()
    if not logs_dir.is_dir():
        return PurgeResult(dry_run=dry_run)
    paths = [p.resolve() for p in logs_dir.iterdir() if p.is_file()]
    return _purge_paths(paths, dry_run=dry_run)


def purge_all_exports(data_dir: Path, *, dry_run: bool = True) -> PurgeResult:
    exports = (data_dir / "exports").resolve()
    if not exports.is_dir():
        return PurgeResult(dry_run=dry_run)
    paths = [p.resolve() for p in exports.rglob("*") if p.is_file() or p.is_dir()]
    # Remove deepest paths first when deleting for real
    paths.sort(key=lambda p: len(p.parts), reverse=True)
    return _purge_paths(paths, dry_run=dry_run)


def run_cleanup(
    data_dir: Path,
    *,
    known_session_ids: set[UUID],
    session_ids: list[UUID] | None = None,
    all_sessions: bool = False,
    orphans: bool = False,
    imports_cache: bool = False,
    logs: bool = False,
    exports: bool = False,
    dry_run: bool = True,
) -> CleanupReport:
    """Run selected cleanup operations (defaults to dry-run)."""
    session_purges: list[PurgeResult] = []
    targets: list[UUID] = []
    if all_sessions:
        targets = list(known_session_ids)
    elif session_ids:
        targets = session_ids

    for sid in targets:
        session_purges.append(purge_session_artifacts(data_dir, sid, dry_run=dry_run))

    orphan_result = PurgeResult(dry_run=dry_run)
    if orphans:
        orphan_paths = find_orphan_artifact_dirs(data_dir, known_session_ids)
        orphan_result = _purge_paths(orphan_paths, dry_run=dry_run)

    imports_result = (
        purge_imports_cache(data_dir, dry_run=dry_run)
        if imports_cache
        else PurgeResult(dry_run=dry_run)
    )
    logs_result = (
        purge_rotated_logs(data_dir, dry_run=dry_run) if logs else PurgeResult(dry_run=dry_run)
    )
    exports_result = (
        purge_all_exports(data_dir, dry_run=dry_run) if exports else PurgeResult(dry_run=dry_run)
    )

    return CleanupReport(
        session_purges=tuple(session_purges),
        orphan_purges=orphan_result,
        imports_cache_purge=imports_result,
        logs_purge=logs_result,
        exports_purge=exports_result,
        dry_run=dry_run,
    )
