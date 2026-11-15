"""Persistent stores (DuckDB). Data files live outside the repository (see .gitignore)."""

from wildlife_scanner.storage.observations import ObservationStore, observation_row

__all__ = ["ObservationStore", "observation_row"]
