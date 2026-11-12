"""Synthetic observations with known truth, for tests and offline demos.

Observers concentrate at a few hotspots (as real observers do), so raw record counts mostly
measure effort. Each species has a true detection probability per place and week; a correct
baseline should recover that truth better than raw counts do.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from wildlife_radar.core.geometry import PointFootprint
from wildlife_radar.core.ids import hash_identifier
from wildlife_radar.core.licenses import CC_BY, CC_BY_NC
from wildlife_radar.core.observations import EvidenceGrade, Modality, Observation, Outcome
from wildlife_radar.core.spatial import haversine_km
from wildlife_radar.core.taxa import TaxonRef, TaxonScheme
from wildlife_radar.core.time import Precision, TimeWindow


@dataclass(frozen=True)
class SyntheticSpecies:
    name: str
    group: str = "birds"
    centers: tuple[tuple[float, float, float], ...] = ()
    """``(lat, lon, sigma_km)`` blobs of high occurrence."""
    base: float = 0.0
    floor: float = 0.0
    peak_week: int | None = None
    season_sigma_weeks: float = 4.0

    @property
    def taxon_id(self) -> str:
        return self.name.lower().replace(" ", "-")

    def seasonal(self, week: int) -> float:
        if self.peak_week is None:
            return 1.0
        d = abs(week - self.peak_week)
        d = min(d, 52 - d)
        return math.exp(-0.5 * (d / self.season_sigma_weeks) ** 2)

    def spatial(self, lat: float, lon: float) -> float:
        if not self.centers:
            return 0.0
        return max(
            math.exp(-0.5 * (haversine_km(lat, lon, clat, clon) / sigma) ** 2)
            for clat, clon, sigma in self.centers
        )

    def p_true(self, lat: float, lon: float, week: int) -> float:
        p = self.floor + self.base * self.spatial(lat, lon)
        return min(1.0, p * self.seasonal(week))


DEFAULT_SPECIES = (
    SyntheticSpecies(name="Commonus ubiquitus", floor=0.6),
    # Mostly in a rarely visited inland area, thinly present everywhere else.
    SyntheticSpecies(
        name="Raritas orientalis", centers=((33.05, -116.90, 8.0),), base=0.5, floor=0.04
    ),
    # Coastal and strongly seasonal (peaks mid-May).
    SyntheticSpecies(
        name="Vernalis litoralis",
        centers=((32.85, -117.27, 6.0),),
        base=0.6,
        peak_week=20,
        season_sigma_weeks=3.0,
    ),
)

DEFAULT_HOTSPOTS = (
    (32.85, -117.27, 0.6, 2.0),  # (lat, lon, share of visits, sigma_km)
    (32.72, -117.17, 0.25, 2.0),
)


@dataclass
class SyntheticWorld:
    bbox: tuple[float, float, float, float] = (-117.35, 32.6, -116.8, 33.2)
    species: tuple[SyntheticSpecies, ...] = DEFAULT_SPECIES
    hotspots: tuple[tuple[float, float, float, float], ...] = DEFAULT_HOTSPOTS
    observers: int = 80
    visits_per_observer: int = 60
    start: date = date(2023, 1, 1)
    end: date = date(2025, 12, 31)
    seed: int = 7
    visits: list[tuple[str, float, float, date]] = field(default_factory=list)
    survey_sites: tuple[tuple[float, float], ...] = ()
    """Fixed dive-survey sites, surveyed twice a month; every species gets a present/absent
    record per survey (a structured program recording absences)."""
    survey_species: tuple[SyntheticSpecies, ...] = ()
    survey_dataset: str = "synthetic-dive-survey"

    def _visit_location(self, rng: random.Random) -> tuple[float, float]:
        lon_min, lat_min, lon_max, lat_max = self.bbox
        u = rng.random()
        acc = 0.0
        for lat, lon, share, sigma_km in self.hotspots:
            acc += share
            if u < acc:
                dlat = rng.gauss(0, sigma_km) / 111.32
                dlon = rng.gauss(0, sigma_km) / (111.32 * math.cos(math.radians(lat)))
                return (
                    min(max(lat + dlat, lat_min), lat_max),
                    min(max(lon + dlon, lon_min), lon_max),
                )
        return rng.uniform(lat_min, lat_max), rng.uniform(lon_min, lon_max)

    def generate(self) -> list[Observation]:
        rng = random.Random(self.seed)
        days = (self.end - self.start).days
        out: list[Observation] = []
        self.visits = []
        n = 0
        for o in range(self.observers):
            observer = hash_identifier(f"synthetic-observer-{o}")
            for _ in range(self.visits_per_observer):
                lat, lon = self._visit_location(rng)
                day = self.start + timedelta(days=rng.randrange(days + 1))
                week = min(day.isocalendar().week, 52)
                self.visits.append((observer, lat, lon, day))
                when = datetime(day.year, day.month, day.day, 17, tzinfo=UTC)  # ~9am local
                for sp in self.species:
                    if rng.random() >= sp.p_true(lat, lon, week):
                        continue
                    n += 1
                    out.append(
                        Observation(
                            obs_id=f"synthetic:{n}",
                            source_id="synthetic",
                            source_record_id=str(n),
                            taxon=TaxonRef(
                                scheme=TaxonScheme.NAME, id=sp.name, name=sp.name, rank="species"
                            ),
                            footprint=PointFootprint(lat=lat, lon=lon, uncertainty_m=20),
                            time=TimeWindow.instant(when, Precision.MINUTE),
                            modality=Modality.SEE,
                            outcome=Outcome.PRESENCE_ONLY,
                            evidence_grade=EvidenceGrade.C1,
                            license=CC_BY_NC if n % 3 else CC_BY,
                            extras={"group": sp.group, "observer_hash": observer},
                        )
                    )
        out.extend(self._surveys(rng, n))
        return out

    def _surveys(self, rng: random.Random, n0: int) -> list[Observation]:
        out: list[Observation] = []
        n = n0
        day = self.start
        while day <= self.end:
            for d in (day, day + timedelta(days=14)):
                if d > self.end:
                    continue
                week = min(d.isocalendar().week, 52)
                when = datetime(d.year, d.month, d.day, 18, tzinfo=UTC)
                for s_idx, (lat, lon) in enumerate(self.survey_sites):
                    for sp in self.survey_species:
                        n += 1
                        seen = rng.random() < sp.p_true(lat, lon, week)
                        out.append(
                            Observation(
                                obs_id=f"synthetic-survey:{n}",
                                source_id="synthetic-survey",
                                source_record_id=str(n),
                                taxon=TaxonRef(
                                    scheme=TaxonScheme.NAME,
                                    id=sp.name,
                                    name=sp.name,
                                    rank="species",
                                ),
                                footprint=PointFootprint(lat=lat, lon=lon, uncertainty_m=20),
                                time=TimeWindow.instant(when, Precision.MINUTE),
                                modality=Modality.SEE,
                                outcome=Outcome.DETECTED if seen else Outcome.NOT_DETECTED,
                                evidence_grade=EvidenceGrade.C1,
                                license=CC_BY,
                                extras={
                                    "group": sp.group,
                                    "dataset_key": self.survey_dataset,
                                    "observer_hash": f"site-{s_idx}",
                                },
                            )
                        )
            day = (day.replace(day=1) + timedelta(days=32)).replace(day=1)
        return out
