import math

import h3
import pytest

from wildlife_radar.core import spatial
from wildlife_radar.core.geometry import (
    CellsFootprint,
    PointFootprint,
    PolygonFootprint,
    StationFootprint,
    footprint_cells,
    location_key,
)


def test_coarsen_cell():
    c9 = spatial.cell_for_point(32.85, -117.27, 9)
    c5 = spatial.coarsen_cell(c9, 5)
    assert h3.get_resolution(c5) == 5
    assert spatial.coarsen_cell(c5, 7) == c5  # never refines


def test_resolution_for_min_edge_km():
    assert spatial.resolution_for_min_edge_km(1.0) == 7
    assert spatial.resolution_for_min_edge_km(29) == 3
    assert spatial.edge_km(spatial.resolution_for_min_edge_km(5)) >= 5


def test_cells_for_disk_covers_the_disk():
    lat, lon, radius_m = 32.85, -117.27, 5000
    cells = spatial.cells_for_disk(lat, lon, radius_m, 7)
    for bearing in range(0, 360, 15):
        d_km = 4.9
        dlat = d_km * math.cos(math.radians(bearing)) / 111.32
        dlon = d_km * math.sin(math.radians(bearing)) / (111.32 * math.cos(math.radians(lat)))
        assert spatial.cell_for_point(lat + dlat, lon + dlon, 7) in cells


def test_small_polygon_falls_back_to_centroid_cell():
    tiny = {
        "type": "Polygon",
        "coordinates": [
            [(-117.27, 32.85), (-117.2699, 32.85), (-117.2699, 32.8501), (-117.27, 32.85)]
        ],
    }
    cells = spatial.cells_for_geojson(tiny, 5)
    assert len(cells) == 1


def test_footprint_cells_and_keys():
    point = PointFootprint(lat=32.85, lon=-117.27)
    assert len(footprint_cells(point, 9)) == 1
    assert location_key(point) == "point:32.85000,-117.27000"
    station = StationFootprint(network="noaa-coops", station_id="9410230", lat=32.867, lon=-117.257)
    assert location_key(station) == "station:noaa-coops:9410230"
    cell = spatial.cell_for_point(32.85, -117.27, 7)
    assert location_key(CellsFootprint(cells=frozenset({cell}))) == f"h3:{cell}"
    poly = PolygonFootprint(
        geometry={
            "type": "Polygon",
            "coordinates": [[(-117.3, 32.8), (-117.2, 32.8), (-117.2, 32.9), (-117.3, 32.8)]],
        }
    )
    with pytest.raises(ValueError):
        location_key(poly)


def test_cells_footprint_validates_cells():
    with pytest.raises(ValueError):
        CellsFootprint(cells=frozenset({"not-a-cell"}))
    with pytest.raises(ValueError):
        CellsFootprint(cells=frozenset())
