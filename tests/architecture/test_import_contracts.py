"""Architecture guardrail (stories A10 + A9).

Enforces the hexagonal import contracts by running Import Linter in process:

- ``domain-independence`` — the domain layer imports no outer layer (A10).
- ``application-independent-of-adapters`` — application depends on domain +
  ports only; the composition root (``application/container.py``) is the one
  exempt wiring point (A9).
- ``adapters-do-not-import-upward`` — adapters never import application, CLI
  or UI (A9).

All three are blocking (``task check`` + CI). See docs/architecture-guardrails.md.
"""

from __future__ import annotations

import os
from pathlib import Path

from importlinter.cli import lint_imports

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / ".importlinter"

# Contracts that must always hold (A9: all pilot contracts are now enforced).
ENFORCED_CONTRACTS = (
    "domain-independence",
    "application-independent-of-adapters",
    "adapters-do-not-import-upward",
)


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
