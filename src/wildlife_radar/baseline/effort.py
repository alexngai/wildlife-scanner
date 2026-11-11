"""Effort models: how each kind of data measures sampling effort.

Different data sources observe differently, so pooling them into one "group" denominator mixes
incomparable effort (the first real-data run showed this for fishes and insects). Every record
is assigned an **effort class**, and baselines are estimated per *effort group*
(taxon group × effort class):

========================  ===========================================  =====================
class                     effort unit                                  estimator
========================  ===========================================  =====================
``checklist``             outing (observer × day × place)              share of outings
``casual``                outing (observer × day × place)              share of outings
``sensor``                outing (sensor/dataset × day × place)        share of outings
``dive_survey``           each present/absent record for the species   detections / trials
``intertidal_survey``     each present/absent record for the species   detections / trials
``survey``                each present/absent record for the species   detections / trials
========================  ===========================================  =====================

Survey classes come from structured monitoring programs that record absences (GBIF
"sampling event" datasets); their effort is the species' own trials, not a shared visit count.

Classes are assigned per dataset: a region's ``datasets.yaml`` registry first, then GBIF
dataset metadata (``SAMPLING_EVENT`` → survey), then heuristics (eBird → checklist; datasets
recording absences → survey; machine observations → sensor; otherwise casual).
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import yaml
from pydantic import BaseModel, ConfigDict, Field

EBIRD_EOD_DATASET = "4fa7b334-ce0d-4e88-aaae-2e0c138d049e"

SHARED_CLASSES = ("checklist", "casual", "sensor")
SURVEY_CLASSES = ("dive_survey", "intertidal_survey", "survey")
EFFORT_CLASSES = SHARED_CLASSES + SURVEY_CLASSES

METHOD_FOR_CLASS = {
    "checklist": "birding_checklist",
    "casual": "observer_visit",
    "sensor": "observer_visit",
    "dive_survey": "scuba_dive",
    "intertidal_survey": "tidepooling",
    "survey": "standardized_survey",
}
CLASS_LABELS = {
    "checklist": "birding checklists",
    "casual": "casual sightings",
    "sensor": "automated sensors",
    "dive_survey": "dive surveys",
    "intertidal_survey": "intertidal surveys",
    "survey": "structured surveys",
}

DATASET_META_SCHEMA = """
CREATE TABLE IF NOT EXISTS dataset_meta (
    dataset_key VARCHAR PRIMARY KEY, title VARCHAR, type VARCHAR, license VARCHAR,
    fetched_at TIMESTAMP
)
"""


def egroup(taxon_group: str, effort_class: str) -> str:
    return f"{taxon_group}:{effort_class}"


def split_egroup(group_id: str) -> tuple[str, str]:
    taxon_group, _, effort_class = group_id.partition(":")
    return taxon_group, effort_class or "casual"


def method_for(group_id: str) -> str:
    return METHOD_FOR_CLASS.get(split_egroup(group_id)[1], "observer_visit")


def label_for(group_id: str) -> str:
    taxon_group, effort_class = split_egroup(group_id)
    return f"{taxon_group} · {CLASS_LABELS.get(effort_class, effort_class)}"


class DatasetEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effort_class: str | None = None
    exclude: bool = False
    name: str | None = None
    reason: str | None = None


class DatasetRegistry(BaseModel):
    """Per-region overrides: ``regions/<id>/datasets.yaml``."""

    model_config = ConfigDict(extra="forbid")

    datasets: dict[str, DatasetEntry] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> DatasetRegistry:
        if not path.exists():
            return cls()
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    def check(self) -> None:
        bad = {
            k: e.effort_class
            for k, e in self.datasets.items()
            if e.effort_class and e.effort_class not in EFFORT_CLASSES
        }
        if bad:
            raise ValueError(f"unknown effort classes in dataset registry: {bad}")


def create_dataset_classes(
    conn: duckdb.DuckDBPyConnection, registry: DatasetRegistry | None = None
) -> None:
    """Temp table ``_dsclass(ds_id, effort_class, excluded)`` for every dataset/source present.

    ``ds_id`` is the GBIF dataset key, or the source id for records without one.
    """
    registry = registry or DatasetRegistry()
    registry.check()
    conn.execute(DATASET_META_SCHEMA)
    conn.execute(
        "CREATE OR REPLACE TEMP TABLE _registry "
        "(ds_id VARCHAR, effort_class VARCHAR, excluded BOOLEAN)"
    )
    if registry.datasets:
        conn.executemany(
            "INSERT INTO _registry VALUES (?, ?, ?)",
            [(k, e.effort_class, e.exclude) for k, e in registry.datasets.items()],
        )
    survey = "'survey'"
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _dsclass AS
        WITH ds AS (
            SELECT coalesce(dataset_key, source_id) AS ds_id,
                bool_or(outcome = 'not_detected') AS has_absence,
                mode(modality) AS modality
            FROM observations GROUP BY 1
        )
        SELECT ds.ds_id,
            coalesce(r.effort_class, CASE
                WHEN ds.ds_id = '{EBIRD_EOD_DATASET}' THEN 'checklist'
                WHEN m.type = 'SAMPLING_EVENT' OR ds.has_absence THEN {survey}
                WHEN ds.modality IN ('sensor', 'camera') THEN 'sensor'
                ELSE 'casual' END) AS effort_class,
            coalesce(r.excluded, FALSE) AS excluded
        FROM ds
        LEFT JOIN _registry r ON r.ds_id = ds.ds_id
        LEFT JOIN dataset_meta m ON m.dataset_key = ds.ds_id
        """
    )
