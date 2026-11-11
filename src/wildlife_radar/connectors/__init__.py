"""Connectors: one module per data source. Each exposes a ``SOURCE`` describing its terms."""

from wildlife_radar.connectors import astronomy, gbif, inaturalist, noaa_coops
from wildlife_radar.connectors.base import ConnectorError, ObservationQuery, RateLimiter

ALL_SOURCES = {m.SOURCE.source_id: m.SOURCE for m in (astronomy, gbif, inaturalist, noaa_coops)}

__all__ = ["ALL_SOURCES", "ConnectorError", "ObservationQuery", "RateLimiter"]
