"""Species profiles: schema, inheritance and loading."""

from wildlife_scanner.profiles.loader import (
    DEFAULT_PROFILES_DIR,
    ProfileError,
    ProfileLibrary,
    deep_merge,
)
from wildlife_scanner.profiles.schema import (
    LatentStateSpec,
    MethodsSpec,
    NowcastSpec,
    PolicySpec,
    PriorSpec,
    Provenance,
    RegionalPolicySpec,
    SignalSpec,
    SourceSpec,
    SpeciesProfile,
    WindowSpec,
)

__all__ = [
    "DEFAULT_PROFILES_DIR",
    "LatentStateSpec",
    "MethodsSpec",
    "NowcastSpec",
    "PolicySpec",
    "PriorSpec",
    "ProfileError",
    "ProfileLibrary",
    "Provenance",
    "RegionalPolicySpec",
    "SignalSpec",
    "SourceSpec",
    "SpeciesProfile",
    "WindowSpec",
    "deep_merge",
]
