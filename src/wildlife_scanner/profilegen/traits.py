"""Curated trait databases → field candidates.

TetrapodTraits (Moura et al. 2024, PLOS Biology; Zenodo record 11303604, CC BY 4.0) covers
~33,000 tetrapods with body size, activity time, habitat use and IUCN habitat classes, and flags
every value as measured or phylogenetically imputed. Its IUCN assessment column is deliberately
not imported: statuses come only from status providers.

The CSV is downloaded by the operator into ``data/`` (never committed):
``https://zenodo.org/records/11303604/files/TetrapodTraits_1.0.0.csv``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import duckdb

from wildlife_scanner.profilegen.candidates import Candidate, Rank
from wildlife_scanner.profiles.schema import Provenance

TETRAPODTRAITS_SOURCE = "TetrapodTraits 1.0.0 (Moura et al. 2024, Zenodo 11303604)"
TETRAPODTRAITS_LICENSE = "CC-BY-4.0"
TETRAPODTRAITS_URL = "https://zenodo.org/records/11303604/files/TetrapodTraits_1.0.0.csv"

#: IUCN Habitats Classification Scheme level-1 classes present in TetrapodTraits.
IUCN_MAJOR_HABITATS = {
    1: "forest",
    2: "savanna",
    3: "shrubland",
    4: "grassland",
    5: "wetlands",
    6: "rocky_areas",
    7: "caves",
    8: "desert",
    9: "marine_neritic",
    10: "marine_oceanic",
    12: "marine_intertidal",
    13: "marine_coastal",
    14: "artificial_terrestrial",
    15: "artificial_aquatic",
    16: "introduced_vegetation",
    17: "other",
}
HABITAT_USE = {
    "Fos": "fossorial",
    "Ter": "terrestrial",
    "Aqu": "aquatic",
    "Arb": "arboreal",
    "Aer": "aerial",
}
ECOSYSTEMS = {"EcoTer": "terrestrial", "EcoFresh": "freshwater", "EcoMar": "marine"}


def activity_from(diu: float | None, noc: float | None) -> str | None:
    """Diurnal/nocturnal scores (0/1 when measured, probabilities when imputed) → pattern.

    TetrapodTraits has no crepuscular class, so dawn/dusk specialists read as cathemeral or
    nocturnal here; occurrence-derived diel patterns and extraction can refine it.
    """
    if diu is None or noc is None:
        return None
    day, night = diu >= 0.5, noc >= 0.5
    if day and night:
        return "cathemeral"
    if day:
        return "diurnal"
    if night:
        return "nocturnal"
    return None


class TetrapodTraits:
    def __init__(self, path: Path | str, conn: duckdb.DuckDBPyConnection | None = None) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(
                f"{self.path} not found; download it from {TETRAPODTRAITS_URL} (CC BY 4.0)"
            )
        self.conn = conn or duckdb.connect()
        self.conn.execute(
            "CREATE OR REPLACE TEMP TABLE _tetrapodtraits AS "
            "SELECT * FROM read_csv(?, header = true, all_varchar = true)",
            [str(self.path)],
        )

    def row(self, names: Iterable[str]) -> dict[str, str | None] | None:
        names = [n for n in names if n]
        if not names:
            return None
        cur = self.conn.execute(
            """
            SELECT * FROM _tetrapodtraits
            WHERE "Scientific.Name" IN (SELECT unnest(?)) OR "IUCN_Binomial" IN (SELECT unnest(?))
            ORDER BY "Scientific.Name" = ? DESC LIMIT 1
            """,
            [names, names, names[0]],
        )
        rec = cur.fetchone()
        if rec is None:
            return None
        return dict(zip([d[0] for d in cur.description], rec, strict=True))

    def candidates(self, names: Iterable[str]) -> list[Candidate]:
        row = self.row(list(names))
        if row is None:
            return []
        out: list[Candidate] = []

        def num(col: str) -> float | None:
            v = row.get(col)
            try:
                return float(v) if v not in (None, "", "NA") else None
            except ValueError:
                return None

        def add(field: str, value, imputed_col: str, evidence_col: str | None = None) -> None:
            if value is None or value == []:
                return
            measured = num(imputed_col) == 0
            out.append(
                Candidate(
                    field=field,
                    value=value,
                    rank=Rank.DB_MEASURED if measured else Rank.DB_IMPUTED,
                    provenance=Provenance(
                        source=TETRAPODTRAITS_SOURCE,
                        method="import",
                        measured=measured,
                        confidence=0.9 if measured else 0.6,
                        license=TETRAPODTRAITS_LICENSE,
                        evidence=(
                            f"{row['Scientific.Name']}: {row.get(evidence_col)}"
                            if evidence_col and row.get(evidence_col)
                            else str(row["Scientific.Name"])
                        ),
                    ),
                )
            )

        mass = num("BodyMass_g")
        add("traits.body_mass_g", round(mass, 3) if mass else None, "ImputedMass", "SourceBodyMass")
        length = num("BodyLength_mm")
        add(
            "traits.body_length_mm",
            round(length, 1) if length else None,
            "ImputedLength",
            "SourceBodyLength",
        )
        add(
            "traits.activity_pattern",
            activity_from(num("Diu"), num("Noc")),
            "ImputedActTime",
            "SourceActTime",
        )
        add(
            "traits.habitat_use",
            [v for k, v in HABITAT_USE.items() if (num(k) or 0) >= 0.5],
            "ImputedHabitat",
            "SourceHabitat",
        )
        add(
            "traits.iucn_habitats",
            [v for k, v in IUCN_MAJOR_HABITATS.items() if (num(f"MajorHabitat_{k}") or 0) >= 0.5],
            "ImputedMajorHabitat",
        )
        add(
            "traits.ecosystems",
            [v for k, v in ECOSYSTEMS.items() if (num(k) or 0) >= 0.5],
            "ImputedEcosystem",
        )
        return out
