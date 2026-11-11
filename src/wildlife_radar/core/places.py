"""Named places (dive sites, hotspots, trailheads, zones). Users think in places; math in cells."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from wildlife_radar.core.geometry import Footprint, footprint_cells


class PlaceKind(StrEnum):
    DIVE_SITE = "dive_site"
    HOTSPOT = "hotspot"
    TRAILHEAD = "trailhead"
    PARK = "park"
    ZONE = "zone"
    REGION = "region"


class Place(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    place_id: str
    name: str
    kind: PlaceKind
    footprint: Footprint
    region: str | None = None
    access: str | None = None
    habitat: tuple[str, ...] = ()
    notes: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)

    def cells(self, res: int) -> frozenset[str]:
        return footprint_cells(self.footprint, res)
