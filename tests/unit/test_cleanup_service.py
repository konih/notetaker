"""Unit tests for application cleanup_service (no CLI, no transcript text)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from live_meeting_transcriber.application.cleanup_service import (
    find_orphan_artifact_dirs,
    purge_all_exports,
    purge_imports_cache,
    purge_rotated_logs,
    purge_session_artifacts,
    run_cleanup,
    session_artifact_paths,
)


def _seed_session_artifacts(data_dir: Path, session_id: UUID) -> dict[str, Path]:
    """Create a minimal on-disk tree for one session (binary placeholders only)."""
    sid = str(session_id)
    paths: dict[str, Path] = {
        "chunks": data_dir / "chunks" / sid,
        "sessions": data_dir / "sessions" / sid,
        "slide_previews": data_dir / "imports" / "slide_previews" / sid,
        "screenshots": data_dir / "exports" / "screenshots" / sid,
    }
    for directory in paths.values():
        directory.mkdir(parents=True)
        (directory / "artifact.bin").write_bytes(b"\x00")
    export_md = data_dir / "exports" / f"{sid}_export.md"
    export_md.parent.mkdir(parents=True, exist_ok=True)
    export_md.write_bytes(b"#\n")
    paths["export_md"] = export_md
    return paths


def test_session_artifact_paths_lists_known_locations(tmp_path: Path) -> None:
    sid = uuid4()
    seeded = _seed_session_artifacts(tmp_path, sid)

    paths = session_artifact_paths(tmp_path, sid)
    resolved = {p.resolve() for p in paths}

    for key in ("chunks", "sessions", "slide_previews", "screenshots", "export_md"):
        assert seeded[key].resolve() in resolved


def test_purge_session_artifacts_dry_run_lists_without_deleting(tmp_path: Path) -> None:
    sid = uuid4()
    seeded = _seed_session_artifacts(tmp_path, sid)

    result = purge_session_artifacts(tmp_path, sid, dry_run=True)

    assert result.dry_run is True
    assert result.count == len(seeded)
    removed = {p.resolve() for p in result.paths}
    for path in seeded.values():
        assert path.resolve() in removed
        assert path.exists()


def test_purge_session_artifacts_removes_all_related_dirs(tmp_path: Path) -> None:
    sid = uuid4()
    seeded = _seed_session_artifacts(tmp_path, sid)

    result = purge_session_artifacts(tmp_path, sid, dry_run=False)

    assert result.dry_run is False
    assert result.count == len(seeded)
    for path in seeded.values():
        assert not path.exists()


def test_find_orphan_artifact_dirs_under_chunks_sessions_imports(tmp_path: Path) -> None:
    known_id = uuid4()
    orphan_id = uuid4()
    _seed_session_artifacts(tmp_path, known_id)

    orphan_locations = {
        "chunks": tmp_path / "chunks" / str(orphan_id),
        "sessions": tmp_path / "sessions" / str(orphan_id),
        "imports": tmp_path / "imports" / "slide_previews" / str(orphan_id),
    }
    for directory in orphan_locations.values():
        directory.mkdir(parents=True)
        (directory / "artifact.bin").write_bytes(b"\x00")

    orphans = find_orphan_artifact_dirs(tmp_path, {known_id})
    orphan_resolved = {p.resolve() for p in orphans}

    for directory in orphan_locations.values():
        assert directory.resolve() in orphan_resolved
    assert (tmp_path / "chunks" / str(known_id)).resolve() not in orphan_resolved


def test_find_orphan_artifact_dirs_ignores_non_uuid_dir_names(tmp_path: Path) -> None:
    junk_dir = tmp_path / "chunks" / "not-a-uuid"
    junk_dir.mkdir(parents=True)

    orphans = find_orphan_artifact_dirs(tmp_path, set())

    assert junk_dir.resolve() not in {p.resolve() for p in orphans}


def test_run_cleanup_orphans_dry_run_lists_without_deleting(tmp_path: Path) -> None:
    orphan_id = uuid4()
    orphan_dir = tmp_path / "sessions" / str(orphan_id)
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "artifact.bin").write_bytes(b"\x00")

    report = run_cleanup(tmp_path, known_session_ids=set(), orphans=True, dry_run=True)

    assert report.dry_run is True
    assert report.orphan_purges.count == 1
    assert orphan_dir.resolve() in {p.resolve() for p in report.orphan_purges.paths}
    assert orphan_dir.is_dir()


def test_run_cleanup_orphans_deletes(tmp_path: Path) -> None:
    orphan_id = uuid4()
    orphan_dir = tmp_path / "chunks" / str(orphan_id)
    orphan_dir.mkdir(parents=True)

    report = run_cleanup(tmp_path, known_session_ids=set(), orphans=True, dry_run=False)

    assert report.orphan_purges.count == 1
    assert not orphan_dir.exists()


def test_run_cleanup_session_ids_dry_run_vs_delete(tmp_path: Path) -> None:
    sid = uuid4()
    seeded = _seed_session_artifacts(tmp_path, sid)

    dry_report = run_cleanup(
        tmp_path,
        known_session_ids={sid},
        session_ids=[sid],
        dry_run=True,
    )
    assert dry_report.session_purges[0].count == len(seeded)
    assert all(p.exists() for p in seeded.values())

    live_report = run_cleanup(
        tmp_path,
        known_session_ids={sid},
        session_ids=[sid],
        dry_run=False,
    )
    assert live_report.session_purges[0].count == len(seeded)
    assert all(not p.exists() for p in seeded.values())


def test_purge_imports_cache_dry_run_lists_downloads(tmp_path: Path) -> None:
    cache = tmp_path / "imports" / "downloads"
    cache.mkdir(parents=True)
    file_a = cache / "a.bin"
    file_b = cache / "b.bin"
    file_a.write_bytes(b"\x01")
    file_b.write_bytes(b"\x02")

    result = purge_imports_cache(tmp_path, dry_run=True)

    assert result.count == 2
    assert file_a.exists() and file_b.exists()


def test_purge_imports_cache_deletes(tmp_path: Path) -> None:
    cache = tmp_path / "imports" / "downloads"
    cache.mkdir(parents=True)
    cached = cache / "cached.bin"
    cached.write_bytes(b"\x01")

    result = purge_imports_cache(tmp_path, dry_run=False)

    assert result.count == 1
    assert not cached.exists()


def test_purge_rotated_logs_dry_run_and_delete(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True)
    log_file = logs_dir / "app.log.1"
    log_file.write_bytes(b"LOG\n")

    dry = purge_rotated_logs(tmp_path, dry_run=True)
    assert dry.count == 1
    assert log_file.exists()

    live = purge_rotated_logs(tmp_path, dry_run=False)
    assert live.count == 1
    assert not log_file.exists()


def test_purge_all_exports_dry_run_lists_files(tmp_path: Path) -> None:
    sid = uuid4()
    seeded = _seed_session_artifacts(tmp_path, sid)

    result = purge_all_exports(tmp_path, dry_run=True)

    assert result.count >= 1
    assert seeded["export_md"].exists()
    assert seeded["screenshots"].exists()


def test_run_cleanup_total_paths_aggregates(tmp_path: Path) -> None:
    orphan_id = uuid4()
    orphan_dir = tmp_path / "sessions" / str(orphan_id)
    orphan_dir.mkdir(parents=True)

    cache = tmp_path / "imports" / "downloads"
    cache.mkdir(parents=True)
    (cache / "dl.bin").write_bytes(b"\x00")

    report = run_cleanup(
        tmp_path,
        known_session_ids=set(),
        orphans=True,
        imports_cache=True,
        dry_run=True,
    )

    assert report.total_paths == report.orphan_purges.count + report.imports_cache_purge.count
    assert report.total_paths == 2
