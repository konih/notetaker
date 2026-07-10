"""Drift guard: the test suite must keep the shape the pyramid policy promises (T5).

The 2026-07-08 test-pyramid audit found the pyramid shape acceptable but *unenforced* —
nothing stopped it from inverting (slow e2e creeping up, the base thinning, the integration
lane being deleted). This test locks in the regression-proof invariants so the shape can't
silently rot, the same way ``test_configuration_docs.py`` locks the config docs to the model.

It enforces only what current reality already satisfies (a ratchet), **not** the aspirational
target band (unit 75-85 / integration 10-15 / e2e 5-10). Growing the integration lane toward
that band is T5 Phase 2 / C3; until then asserting ``integration >= 10 %`` would false-red.
The thresholds live here as the single source of truth; the policy doc must echo them.

Policy of record: ``docs/development.md`` -> "Test pyramid policy".
"""

from __future__ import annotations

from pathlib import Path

# Enforced invariants (see docs/development.md#test-pyramid-policy). These lock the current
# shape and may only ratchet toward the aspirational band, never loosen.
UNIT_MIN_RATIO = 0.75  # unit files dominate — guards against pyramid inversion
E2E_MAX_RATIO = 0.15  # keep the slow layer lean and high-value
INTEGRATION_MIN_FILES = 1  # the seam lane must survive (its buildout is Phase 2)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TESTS = _REPO_ROOT / "tests"
_POLICY_DOC = _REPO_ROOT / "docs" / "development.md"


def _layer_counts() -> tuple[int, int, int, int]:
    """(unit, integration, e2e, total) counted by ``test_*.py`` file, by directory.

    ``test_*.py`` naturally excludes ``__init__.py``/``conftest.py``/helper modules. e2e and
    integration are the two dedicated directories; everything else (``tests/unit``,
    ``tests/architecture``, any at the root) counts as unit.
    """
    all_files = list(_TESTS.rglob("test_*.py"))
    e2e = sum(1 for p in all_files if (_TESTS / "e2e") in p.parents)
    integration = sum(1 for p in all_files if (_TESTS / "integration") in p.parents)
    unit = len(all_files) - e2e - integration
    return unit, integration, e2e, len(all_files)


def test_unit_layer_dominates() -> None:
    unit, _integration, _e2e, total = _layer_counts()
    ratio = unit / total
    assert ratio >= UNIT_MIN_RATIO, (
        f"Unit layer is {ratio:.0%} of {total} test files (floor {UNIT_MIN_RATIO:.0%}). "
        "The pyramid is inverting — add fast unit coverage or justify a policy change in "
        "docs/development.md#test-pyramid-policy."
    )


def test_e2e_layer_stays_small() -> None:
    _unit, _integration, e2e, total = _layer_counts()
    ratio = e2e / total
    assert ratio <= E2E_MAX_RATIO, (
        f"E2E layer is {ratio:.0%} of {total} test files (ceiling {E2E_MAX_RATIO:.0%}). "
        "Keep e2e small and high-value — push new coverage down into unit/integration, or "
        "revise the policy in docs/development.md#test-pyramid-policy."
    )


def test_integration_lane_survives() -> None:
    _unit, integration, _e2e, _total = _layer_counts()
    assert integration >= INTEGRATION_MIN_FILES, (
        f"Integration lane has {integration} test file(s) (floor {INTEGRATION_MIN_FILES}). "
        "Growing this lane is T5 Phase 2 / C3 — do not shrink it to zero."
    )


def test_policy_doc_states_the_enforced_thresholds() -> None:
    """The doc and this test are one policy — the doc must echo the enforced numbers.

    Mirrors the D3 pattern: the machine-checkable source (this module) is authoritative and
    the prose must not drift from it, so a reader can trust docs/development.md.
    """
    assert _POLICY_DOC.is_file(), f"missing policy doc: {_POLICY_DOC}"
    doc = _POLICY_DOC.read_text(encoding="utf-8")
    assert "Test pyramid policy" in doc
    for token in (
        f"{int(UNIT_MIN_RATIO * 100)}",  # 75
        f"{int(E2E_MAX_RATIO * 100)}",  # 15
    ):
        assert token in doc, (
            f"policy doc does not mention the enforced threshold {token} % — "
            "docs/development.md has drifted from tests/unit/test_test_pyramid_policy.py"
        )
