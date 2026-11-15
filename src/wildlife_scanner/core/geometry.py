"""Footprints: where an observation, signal or place applies, with its uncertainty.

Every record keeps its native spatial support (a point with uncertainty, an obscured cell, a
fishing block polygon, a station...). Models link records to the latent state by integrating over
the footprint; the policy layer coarsens footprints before anything is published.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from wildlife_scanner.core import spatial


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PointFootprint(_FrozenModel):
    kind: Literal["point"] = "point"
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    uncertainty_m: float | None = Field(default=None, ge=0)


class PolygonFootprint(_FrozenModel):
    kind: Literal["polygon"] = "polygon"
    geometry: dict[str, Any]

    @field_validator("geometry")
    @classmethod
    def _polygonal(cls, v: dict[str, Any]) -> dict[str, Any]:
        if v.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError("geometry must be a GeoJSON Polygon or MultiPolygon")
        return v


class CellsFootprint(_FrozenModel):
    kind: Literal["cells"] = "cells"
    cells: frozenset[str]

    @field_validator("cells")
    @classmethod
    def _valid_cells(cls, v: frozenset[str]) -> frozenset[str]:
        if not v:
            raise ValueError("cells footprint must not be empty")
        bad = [c for c in v if not spatial.is_valid_cell(c)]
        if bad:
            raise ValueError(f"invalid H3 cells: {sorted(bad)[:3]}")
        return v


class StationFootprint(_FrozenModel):
    """A fixed sensor/station (tide gauge, buoy, radar, acoustic recorder)."""

    kind: Literal["station"] = "station"
    network: str
    station_id: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


Footprint = Annotated[
    PointFootprint | PolygonFootprint | CellsFootprint | StationFootprint,
    Field(discriminator="kind"),
]


def footprint_centroid(fp: Footprint) -> tuple[float, float]:
    """Representative ``(lat, lon)`` of a footprint."""
    if isinstance(fp, PointFootprint | StationFootprint):
        return fp.lat, fp.lon
    if isinstance(fp, PolygonFootprint):
        return spatial.geojson_centroid(fp.geometry)
    lats, lons = zip(*(spatial.cell_center(c) for c in fp.cells), strict=True)
    return sum(lats) / len(lats), sum(lons) / len(lons)


def footprint_cells(fp: Footprint, res: int, *, use_uncertainty: bool = True) -> frozenset[str]:
    """H3 cells at ``res`` covering a footprint.

    Points expand to a disk when ``use_uncertainty`` is set and an uncertainty is known. Cells
    finer than ``res`` are coarsened; cells coarser than ``res`` are kept as-is (never refined,
    which would invent precision).
    """
    if isinstance(fp, PointFootprint):
        if use_uncertainty and fp.uncertainty_m:
            return spatial.cells_for_disk(fp.lat, fp.lon, fp.uncertainty_m, res)
        return frozenset({spatial.cell_for_point(fp.lat, fp.lon, res)})
    if isinstance(fp, StationFootprint):
        return frozenset({spatial.cell_for_point(fp.lat, fp.lon, res)})
    if isinstance(fp, PolygonFootprint):
        return spatial.cells_for_geojson(fp.geometry, res)
    return spatial.coarsen_cells(fp.cells, res)


def location_key(fp: Footprint) -> str:
    """Stable key used to index signal series by location."""
    if isinstance(fp, StationFootprint):
        return f"station:{fp.network}:{fp.station_id}"
    if isinstance(fp, CellsFootprint) and len(fp.cells) == 1:
        return f"h3:{next(iter(fp.cells))}"
    if isinstance(fp, PointFootprint):
        return f"point:{fp.lat:.5f},{fp.lon:.5f}"
    raise ValueError("location keys require a station, a single cell, or a point")
