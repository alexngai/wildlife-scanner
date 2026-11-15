"""Core entities (the canonical data model) and utilities.

Connectors produce these; models, the policy layer and products consume them.
"""

from wildlife_scanner.core.geometry import (
    CellsFootprint,
    Footprint,
    PointFootprint,
    PolygonFootprint,
    StationFootprint,
    footprint_cells,
    footprint_centroid,
    location_key,
)
from wildlife_scanner.core.licenses import License, UsageConstraints, combine, parse_license
from wildlife_scanner.core.methods import STANDARD_METHODS, EncounterMethod
from wildlife_scanner.core.observations import (
    SENSITIVE_CONTEXTS,
    Effort,
    EvidenceGrade,
    Modality,
    Observation,
    Outcome,
    SensitivityFlags,
)
from wildlife_scanner.core.places import Place, PlaceKind
from wildlife_scanner.core.predictions import Confidence, Prediction
from wildlife_scanner.core.signals import SignalDefinition, SignalKind, SignalValue
from wildlife_scanner.core.sources import ObservationProcess, ObservationType, Source, SourceKind
from wildlife_scanner.core.taxa import Taxon, TaxonChange, TaxonChangeKind, TaxonRef, TaxonScheme
from wildlife_scanner.core.time import Granularity, Precision, TimeWindow

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
