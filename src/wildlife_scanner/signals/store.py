"""In-memory signal store with as-of semantics.

``as_of`` queries return, for each ``valid_time``, the latest value whose ``issue_time`` is not
after the as-of time. That single rule gives forecast semantics (what did we know on Tuesday about
Friday?) and leak-free backtests (revised data never leaks into the past).

Phase 0 keeps everything in memory; a Parquet/Zarr-backed store will implement the same interface.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta

from wildlife_scanner.core.signals import SignalValue
from wildlife_scanner.core.time import ensure_utc


class SignalStore:
    def __init__(self) -> None:
        # (signal_id, location_key) -> valid_time -> list of values (any issue time)
        self._series: dict[tuple[str, str], dict[datetime, list[SignalValue]]] = defaultdict(
            lambda: defaultdict(list)
        )

    def add(self, values: Iterable[SignalValue]) -> int:
        n = 0
        for v in values:
            versions = self._series[(v.signal_id, v.location_key)][v.valid_time]
            # Replace an identical (valid, issue) version rather than duplicating it.
            versions[:] = [x for x in versions if x.issue_time != v.issue_time]
            versions.append(v)
            n += 1
        return n

    def __len__(self) -> int:
        return sum(len(vs) for series in self._series.values() for vs in series.values())

    def keys(self) -> list[tuple[str, str]]:
        return sorted(self._series)

    def as_of(
        self,
        signal_id: str,
        location_key: str,
        as_of: datetime,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[SignalValue]:
        """Latest-known value per ``valid_time`` in ``[start, end)``, as known at ``as_of``."""
        as_of = ensure_utc(as_of)
        start = ensure_utc(start) if start is not None else None
        end = ensure_utc(end) if end is not None else None
        series = self._series.get((signal_id, location_key), {})
        out: list[SignalValue] = []
        for valid_time in sorted(series):
            if start is not None and valid_time < start:
                continue
            if end is not None and valid_time >= end:
                continue
            known = [v for v in series[valid_time] if v.issue_time <= as_of]
            if known:
                out.append(max(known, key=lambda v: v.issue_time))
        return out

    def value_at(
        self,
        signal_id: str,
        location_key: str,
        valid_time: datetime,
        as_of: datetime,
        tolerance: timedelta = timedelta(0),
    ) -> SignalValue | None:
        """Value nearest to ``valid_time`` within ``tolerance``, as known at ``as_of``."""
        valid_time = ensure_utc(valid_time)
        candidates = self.as_of(
            signal_id,
            location_key,
            as_of,
            start=valid_time - tolerance,
            end=valid_time + tolerance + timedelta(microseconds=1),
        )
        if not candidates:
            return None
        times = [c.valid_time for c in candidates]
        i = bisect.bisect_left(times, valid_time)
        best = candidates[max(0, i - 1) : i + 1]
        return min(best, key=lambda c: abs(c.valid_time - valid_time))
