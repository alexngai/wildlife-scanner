from __future__ import annotations

from datetime import UTC, datetime

import pytest


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 11, 11, tzinfo=UTC)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)
