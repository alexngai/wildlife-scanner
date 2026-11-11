"""Registry of signal definitions (the nodes of the signal DAG)."""

from __future__ import annotations

from collections.abc import Iterable

from wildlife_radar.core.signals import SignalDefinition, SignalKind


class SignalRegistry:
    def __init__(self, definitions: Iterable[SignalDefinition] = ()) -> None:
        self._defs: dict[str, SignalDefinition] = {}
        for d in definitions:
            self.register(d)

    def register(self, definition: SignalDefinition) -> None:
        existing = self._defs.get(definition.signal_id)
        if existing is not None and existing != definition:
            raise ValueError(f"conflicting definition for signal {definition.signal_id!r}")
        self._defs[definition.signal_id] = definition

    def get(self, signal_id: str) -> SignalDefinition:
        try:
            return self._defs[signal_id]
        except KeyError:
            raise KeyError(f"unknown signal {signal_id!r}") from None

    def __contains__(self, signal_id: object) -> bool:
        return signal_id in self._defs

    def __iter__(self):
        return iter(sorted(self._defs.values(), key=lambda d: d.signal_id))

    def check_dependencies(self) -> None:
        """Raise if a derived signal depends on an unregistered signal or on itself (cycle)."""
        for d in self._defs.values():
            for dep in d.depends_on:
                if dep not in self._defs:
                    raise ValueError(f"{d.signal_id!r} depends on unknown signal {dep!r}")
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(sid: str) -> None:
            if sid in done:
                return
            if sid in visiting:
                raise ValueError(f"signal dependency cycle at {sid!r}")
            visiting.add(sid)
            for dep in self._defs[sid].depends_on:
                visit(dep)
            visiting.discard(sid)
            done.add(sid)

        for sid in self._defs:
            visit(sid)


def builtin_registry() -> SignalRegistry:
    """Signals provided by the Phase-0 connectors."""
    from wildlife_radar.connectors.astronomy import SIGNALS as ASTRO_SIGNALS
    from wildlife_radar.connectors.noaa_coops import SIGNALS as TIDE_SIGNALS

    registry = SignalRegistry([*ASTRO_SIGNALS, *TIDE_SIGNALS])
    registry.register(
        SignalDefinition(
            signal_id="tide.stage",
            units="category",
            description="Rising or falling tide, from NOAA high/low predictions",
            kind=SignalKind.DERIVED,
            depends_on=("tide.extreme_m",),
        )
    )
    registry.check_dependencies()
    return registry
