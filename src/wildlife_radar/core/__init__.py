"""Core entities (the canonical data model) and utilities.

Connectors produce these; models, the policy layer and products consume them.
"""

from wildlife_radar.core.geometry import (
    CellsFootprint,
    Footprint,
    PointFootprint,
    PolygonFootprint,
    StationFootprint,
    footprint_cells,
    footprint_centroid,
    location_key,
)
from wildlife_radar.core.licenses import License, UsageConstraints, combine, parse_license
from wildlife_radar.core.methods import STANDARD_METHODS, EncounterMethod
from wildlife_radar.core.observations import (
    SENSITIVE_CONTEXTS,
    Effort,
    EvidenceGrade,
    Modality,
    Observation,
    Outcome,
    SensitivityFlags,
)
from wildlife_radar.core.places import Place, PlaceKind
from wildlife_radar.core.predictions import Confidence, Prediction
from wildlife_radar.core.signals import SignalDefinition, SignalKind, SignalValue
from wildlife_radar.core.sources import ObservationProcess, ObservationType, Source, SourceKind
from wildlife_radar.core.taxa import Taxon, TaxonChange, TaxonChangeKind, TaxonRef, TaxonScheme
from wildlife_radar.core.time import Granularity, Precision, TimeWindow

__all__ = [
    "SENSITIVE_CONTEXTS",
    "STANDARD_METHODS",
    "CellsFootprint",
    "Confidence",
    "Effort",
    "EncounterMethod",
    "EvidenceGrade",
    "Footprint",
    "Granularity",
    "License",
    "Modality",
    "Observation",
    "ObservationProcess",
    "ObservationType",
    "Outcome",
    "Place",
    "PlaceKind",
    "PointFootprint",
    "PolygonFootprint",
    "Precision",
    "Prediction",
    "SensitivityFlags",
    "SignalDefinition",
    "SignalKind",
    "SignalValue",
    "Source",
    "SourceKind",
    "StationFootprint",
    "Taxon",
    "TaxonChange",
    "TaxonChangeKind",
    "TaxonRef",
    "TaxonScheme",
    "TimeWindow",
    "UsageConstraints",
    "combine",
    "footprint_cells",
    "footprint_centroid",
    "location_key",
    "parse_license",
]
