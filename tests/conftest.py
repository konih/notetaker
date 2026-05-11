from __future__ import annotations

import os

import pytest


def pytest_runtest_setup(item: pytest.Item) -> None:
    if "integration" in item.keywords and os.getenv("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("integration tests skipped (set RUN_INTEGRATION_TESTS=1)")

