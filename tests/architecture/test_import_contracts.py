"""Architecture guardrail (story A10).

Enforces the *innermost* hexagonal invariant — the domain layer must not import
any outer layer — by running Import Linter's ``domain-independence`` contract in
process. This is the one contract the pilot enforces (blocking); the remaining
contracts in ``.importlinter`` document known boundary debt and run report-only
via ``task arch:check`` (see agent-context/coordination/ARCH-GUARDRAIL-DECISION.md).
"""

from __future__ import annotations

import os
from pathlib import Path

from importlinter.cli import lint_imports

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / ".importlinter"

# Contracts that must always hold. Widen this tuple as boundary debt is paid down
# (see A9 for the plan to promote application/adapter contracts to blocking).
ENFORCED_CONTRACTS = ("domain-independence",)


def test_enforced_import_contracts_hold() -> None:
    """The enforced hexagonal contracts must pass on the current tree."""
    assert CONFIG.is_file(), f"missing Import Linter config at {CONFIG}"

    cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        exit_code = lint_imports(
            config_filename=str(CONFIG),
            limit_to_contracts=ENFORCED_CONTRACTS,
            no_cache=True,
        )
    finally:
        os.chdir(cwd)

    assert exit_code == 0, (
        "Enforced architecture contract(s) broken: "
        f"{', '.join(ENFORCED_CONTRACTS)}. Run `task arch:check` for the full report."
    )
