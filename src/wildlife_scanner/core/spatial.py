"""Spatial utilities on the H3 discrete global grid.

Predictions and fields live on H3 cells; named places map onto their covering cells.
Resolution guide (average hexagon edge length):

==== ========= ==========================================
res  edge      typical use
==== ========= ==========================================
3    ~69 km    landscape / coarse policy tier
5    ~9.9 km   zones, generalized policy tier
7    ~1.4 km   local fields, default public resolution
9    ~0.2 km   sites
==== ========= ==========================================
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

import h3

RES_LANDSCAPE = 3
RES_ZONE = 5
RES_LOCAL = 7
RES_SITE = 9

EARTH_RADIUS_KM = 6371.0088


def is_valid_cell(cell: str) -> bool:
    return isinstance(cell, str) and h3.is_valid_cell(cell)


def cell_for_point(lat: float, lon: float, res: int) -> str:
    return h3.latlng_to_cell(lat, lon, res)


def cell_resolution(cell: str) -> int:
    return h3.get_resolution(cell)


def cell_center(cell: str) -> tuple[float, float]:
    lat, lon = h3.cell_to_latlng(cell)
    return lat, lon


def coarsen_cell(cell: str, res: int) -> str:
    """Parent of ``cell`` at ``res``; cells already at or coarser than ``res`` are unchanged."""
    if h3.get_resolution(cell) <= res:
        return cell
    return h3.cell_to_parent(cell, res)


def coarsen_cells(cells: Iterable[str], res: int) -> frozenset[str]:
    return frozenset(coarsen_cell(c, res) for c in cells)


def edge_km(res: int) -> float:
    return h3.average_hexagon_edge_length(res, "km")


def resolution_for_min_edge_km(min_edge_km: float) -> int:
    """Finest resolution whose average edge length is at least ``min_edge_km``."""
    for res in range(15, -1, -1):
        if edge_km(res) >= min_edge_km:
            return res
    return 0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def cells_for_disk(lat: float, lon: float, radius_m: float, res: int) -> frozenset[str]:
    """A superset of the cells intersecting a disk around a point."""
    center = cell_for_point(lat, lon, res)
    if radius_m <= 0:
        return frozenset({center})
    spacing_km = math.sqrt(3) * edge_km(res)  # center-to-center distance of neighbors
    k = math.ceil((radius_m / 1000.0) / spacing_km) + 1
    return frozenset(h3.grid_disk(center, k))


def geojson_centroid(geometry: Mapping[str, Any]) -> tuple[float, float]:
    """Approximate centroid (mean of exterior-ring vertices) as ``(lat, lon)``."""
    gtype = geometry.get("type")
    if gtype == "Polygon":
        rings = [geometry["coordinates"][0]]
    elif gtype == "MultiPolygon":
        rings = [poly[0] for poly in geometry["coordinates"]]
    else:
        raise ValueError(f"unsupported geometry type {gtype!r}")
    pts = [pt for ring in rings for pt in ring]
    lon = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)
    return lat, lon


def cells_for_geojson(geometry: Mapping[str, Any], res: int) -> frozenset[str]:
    """Cells whose centers fall inside a GeoJSON (Multi)Polygon.

    Polygons smaller than a cell fall back to the cell containing the centroid.
    """
    cells = h3.geo_to_cells(dict(geometry), res)
    if cells:
        return frozenset(cells)
    lat, lon = geojson_centroid(geometry)
    return frozenset({cell_for_point(lat, lon, res)})
