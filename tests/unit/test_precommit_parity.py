"""Guard: pre-commit hooks stay in parity with the `task check` gates (C2).

`task check` runs ruff format --check, ruff check, mypy (whole tree) and the unit
pytest lane with the coverage floor. Pre-commit must run the same tools — via
``uv run`` so the versions come from the project venv (the dev extra), not from
independently pinned mirror repos that drift. pytest is too slow for every commit,
so it is the documented subset decision: it runs at the ``pre-push`` stage instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CONFIG = Path(__file__).resolve().parents[2] / ".pre-commit-config.yaml"


def _hooks() -> list[dict[str, Any]]:
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    hooks: list[dict[str, Any]] = []
    for repo in data.get("repos", []):
        hooks.extend(repo.get("hooks", []))
    return hooks


def _entry(hook: dict[str, Any]) -> str:
    return str(hook.get("entry", ""))


def _commit_stage(hook: dict[str, Any]) -> bool:
    stages = hook.get("stages")
    return stages is None or "pre-commit" in stages


def test_precommit_config_exists() -> None:
    assert CONFIG.is_file(), "missing .pre-commit-config.yaml"


def test_ruff_format_and_check_run_from_project_venv() -> None:
    entries = [_entry(h) for h in _hooks()]
    assert any("uv run ruff format" in e for e in entries), (
        "pre-commit must run ruff format via `uv run` (version parity with the dev extra)"
    )
    assert any("uv run ruff check" in e for e in entries), (
        "pre-commit must run ruff check via `uv run` (version parity with the dev extra)"
    )


def test_mypy_runs_whole_tree_like_task_check() -> None:
    mypy_hooks = [h for h in _hooks() if "uv run mypy" in _entry(h)]
    assert mypy_hooks, "pre-commit must run mypy (task check parity)"
    hook = mypy_hooks[0]
    assert _entry(hook).rstrip().endswith("mypy ."), (
        "mypy must check the whole tree (`uv run mypy .`), matching `task check`"
    )
    assert hook.get("pass_filenames") is False, (
        "mypy must not receive per-file arguments; whole-tree strictness is the gate"
    )
    assert _commit_stage(hook), "mypy runs on every commit, not only pre-push"


def test_import_linter_contracts_gate_commits() -> None:
    arch = [h for h in _hooks() if "lint-imports" in _entry(h)]
    assert arch, "pre-commit must run the import-linter architecture contracts (A9)"
    assert _commit_stage(arch[0]), "architecture contracts run on every commit"


def test_unit_pytest_gate_runs_at_pre_push() -> None:
    pytest_hooks = [h for h in _hooks() if "uv run pytest" in _entry(h)]
    assert pytest_hooks, "pre-commit config must include the unit pytest gate"
    hook = pytest_hooks[0]
    entry = _entry(hook)
    assert "not integration" in entry, "pytest hook must run the unit lane (task check parity)"
    assert "--cov=live_meeting_transcriber" in entry, (
        "pytest hook must enforce the same coverage floor as task check"
    )
    assert hook.get("stages") == ["pre-push"], (
        "pytest is the documented subset decision: too slow per-commit, runs at pre-push"
    )
    # And nothing that slow may sneak into the per-commit stage.
    for h in _hooks():
        if "pytest" in _entry(h):
            assert not _commit_stage(h), "pytest must not run on every commit (keep hooks fast)"
