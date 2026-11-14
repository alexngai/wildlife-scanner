"""One live stream per coverage area: pull once, load per region, check deletions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from wildlife_radar.pipeline import livelog
from wildlife_radar.pipeline.runner import JOBS, JobContext, latest, run
from wildlife_radar.regions import load_region
from wildlife_radar.storage import ObservationStore
from wildlife_radar.synthetic import SyntheticWorld

NOW = datetime.now(UTC)


class Fake:
    def __init__(self, items):
        self.items, self.queries = items, []

    def fetch(self, query):
        self.queries.append(query)
        return iter(self.items)


def _records():
    obs = SyntheticWorld(observers=4, visits_per_observer=6).generate()[:6]
    # As iNaturalist records (their dedupe keys are inat:<id>), observed recently.
    return [
        o.model_copy(
            update={
                "source_id": "inaturalist",
                "source_record_id": str(1000 + i),
                "time": o.time.model_copy(
                    update={"start": NOW - timedelta(days=1), "end": NOW - timedelta(hours=23)}
                ),
            }
        )
        for i, o in enumerate(obs)
    ]


def _ctx(tmp_path, region_id: str, lake) -> JobContext:
    return JobContext(
        region=load_region(region_id),
        region_path=None,
        db=tmp_path / f"{region_id}.duckdb",
        lake=lake,
        now=NOW,
        log=lambda _m: None,
        params={"skip_existence_check": True},
    )


def test_one_pull_serves_every_region_of_the_coverage(tmp_path):
    lake = tmp_path / "lake"
    inat = Fake(_records())
    jobs = {"live": JOBS["live"].__class__("live", (), JOBS["live"].run, JOBS["live"].max_age)}
    sd = _ctx(tmp_path, "sandiego", lake)
    socal = _ctx(tmp_path, "socal", lake)
    for c in (sd, socal):
        ObservationStore(c.db).close()
        c.params["_inaturalist"] = inat
        c.params["_gbif"] = Fake([])  # registry-live datasets: nothing new
    first = run("live", sd, jobs=jobs)[0]["outcome"]
    assert first["coverage"] == "california" and first["pull"]["inaturalist"] == 6
    assert inat.queries[0].bbox == load_region("california").bbox  # the coverage box
    second = run("live", socal, jobs=jobs)[0]["outcome"]
    assert "pull" not in second and len(inat.queries) == 1  # the second region only loads
    assert second["parts"] == 1 and second["records"] > 0
    # Nothing new: the next run is unchanged (downstream jobs keep their inputs).
    again = run("live", socal, jobs=jobs, force=("live",))[0]["outcome"]
    assert again["unchanged"] and latest(socal.lake, "socal", "live")["outputs"]["parts"] == 0


def test_existence_check_lists_and_applies_deletions(tmp_path):
    lake = tmp_path / "lake"
    cov = load_region("california")
    livelog.pull(cov, lake, NOW, inat=Fake(_records()))

    def handler(request: httpx.Request) -> httpx.Response:
        asked = request.url.params["id"].split(",")
        return httpx.Response(200, json={"results": [{"id": int(x)} for x in asked if x != "1003"]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = livelog.check_existence(lake, "california", NOW, client=client)
    assert out == {"checked": 6, "deleted": 1}
    region = load_region("socal")
    with ObservationStore(tmp_path / "s.duckdb") as store:
        res = livelog.load_region(store.conn, region, lake, "california", None)
        keys = {k for (k,) in store.conn.execute("SELECT dedupe_key FROM observations").fetchall()}
    assert res["removed"] == 1 and "inat:1003" not in keys and "inat:1000" in keys
