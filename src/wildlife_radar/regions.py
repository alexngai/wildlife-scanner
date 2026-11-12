"""Region packs: regional sources, places, status scopes and policy context.

A new region is a new pack under ``regions/<id>/region.yaml``; the core is untouched.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from wildlife_radar.core.places import Place

DEFAULT_REGIONS_DIR = Path(__file__).resolve().parents[2] / "regions"


class TideStation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    station_id: str
    name: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    verified: bool = False
    """Whether id/coordinates were checked against the NOAA metadata API."""


class PipelineSettings(BaseModel):
    """Per-region settings for the job graph (``wildlife-radar run``)."""

    model_config = ConfigDict(extra="forbid")

    since_year: int | None = 2010
    """Ignore records before this year in baselines."""
    backtest_split: date | None = None
    """Train before / test from this date; default: January 1 of the previous year."""
    conditions_split: date | None = None
    """Split for Level 1–2 backtests; default: January 1, two years back."""


class Region(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    bbox: tuple[float, float, float, float]
    """``(lon_min, lat_min, lon_max, lat_max)``."""
    scopes: list[str] = Field(default_factory=lambda: ["global"])
    """Conservation-status scopes that apply inside the region (e.g. ``us``, ``us-ca``)."""
    inat_place_scopes: dict[str, str] = Field(default_factory=dict)
    """iNaturalist ids of places that *contain* the region → status scope (``"14": us-ca``)."""
    inat_innermost_place: str | None = None
    """The smallest mapped place; statuses for places inside it also apply (conservatively)."""
    tide_stations: list[TideStation] = Field(default_factory=list)
    places: list[Place] = Field(default_factory=list)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    notes: str | None = None

    @model_validator(mode="after")
    def _bbox(self) -> Region:
        lon_min, lat_min, lon_max, lat_max = self.bbox
        if not (-180 <= lon_min < lon_max <= 180 and -90 <= lat_min < lat_max <= 90):
            raise ValueError("bbox must be (lon_min, lat_min, lon_max, lat_max)")
        if "global" not in self.scopes:
            self.scopes.insert(0, "global")
        ids = [p.place_id for p in self.places]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate place ids")
        return self

    def contains(self, lat: float, lon: float) -> bool:
        lon_min, lat_min, lon_max, lat_max = self.bbox
        return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max

    def place(self, place_id: str) -> Place:
        for p in self.places:
            if p.place_id == place_id:
                return p
        raise KeyError(place_id)


def region_dir(region_id: str, root: Path = DEFAULT_REGIONS_DIR) -> Path:
    return root / region_id


def load_region(region: str | Path, root: Path = DEFAULT_REGIONS_DIR) -> Region:
    """Load a region by id (``"socal"``) or by path to its YAML file."""
    path = Path(region)
    if not path.suffix:
        path = root / str(region) / "region.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Region.model_validate(doc)
