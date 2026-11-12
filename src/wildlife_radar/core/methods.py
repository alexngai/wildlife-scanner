"""Encounter methods and their standard effort units.

Every prediction is "P(encountering evidence of taxon X using method M with standard effort E)".
The method generalizes to evidence modality, which is what lets the framework cover rare, cryptic
species: for a mountain lion the headline method is a sign survey, not a sighting.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from wildlife_radar.core.observations import Effort, Modality


class EncounterMethod(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method_id: str
    modality: Modality
    standard_effort: Effort
    description: str


STANDARD_METHODS: dict[str, EncounterMethod] = {
    m.method_id: m
    for m in (
        EncounterMethod(
            method_id="scuba_dive",
            modality=Modality.SEE,
            standard_effort=Effort(duration_min=60),
            description="60-minute daytime scuba dive by an experienced diver",
        ),
        EncounterMethod(
            method_id="freedive",
            modality=Modality.SEE,
            standard_effort=Effort(duration_min=60),
            description="60-minute freediving session",
        ),
        EncounterMethod(
            method_id="snorkel",
            modality=Modality.SEE,
            standard_effort=Effort(duration_min=60),
            description="60-minute snorkel",
        ),
        EncounterMethod(
            method_id="birding_checklist",
            modality=Modality.SEE,
            standard_effort=Effort(duration_min=60, distance_km=2),
            description="1-hour, ≤2 km complete birding checklist (eBird S&T-style standard)",
        ),
        EncounterMethod(
            method_id="sign_survey",
            modality=Modality.SIGN,
            standard_effort=Effort(duration_min=120),
            description="2-hour trail survey for fresh tracks, scat, scrapes or kills",
        ),
        EncounterMethod(
            method_id="camera_trap",
            modality=Modality.CAMERA,
            standard_effort=Effort(trap_nights=7),
            description="One camera-trap-week",
        ),
        EncounterMethod(
            method_id="wildlife_viewing",
            modality=Modality.SEE,
            standard_effort=Effort(duration_min=120),
            description="2-hour viewing session (e.g., from a viewpoint with optics)",
        ),
        EncounterMethod(
            method_id="shore_watch",
            modality=Modality.SEE,
            standard_effort=Effort(duration_min=60),
            description="1-hour watch from shore",
        ),
        EncounterMethod(
            method_id="boat_trip",
            modality=Modality.SEE,
            standard_effort=Effort(duration_min=180),
            description="3-hour boat-based viewing trip",
        ),
        EncounterMethod(
            method_id="tidepooling",
            modality=Modality.SEE,
            standard_effort=Effort(duration_min=60),
            description="1-hour low-tide visit to the rocky intertidal",
        ),
        EncounterMethod(
            method_id="standardized_survey",
            modality=Modality.SEE,
            standard_effort=Effort(),
            description="One unit of a structured monitoring survey (transect, quadrat, point)",
        ),
        EncounterMethod(
            method_id="observer_visit",
            modality=Modality.SEE,
            standard_effort=Effort(),
            description=(
                "A typical recorded visit (one observer, one day, one place) by someone who "
                "reports this taxon group. Level-0 proxy: not effort-standardized."
            ),
        ),
    )
}
