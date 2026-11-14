/**
 * Small inline line icons (24×24, stroke = currentColor). Decorative: each is aria-hidden, so
 * whatever uses one must carry its own text or label.
 */
import type { ReactNode } from "react";

function Svg({ children, filled = false }: { children: ReactNode; filled?: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke={filled ? "none" : "currentColor"}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

export const LogoIcon = () => (
  <Svg>
    <circle cx="12" cy="12" r="8.5" />
    <circle cx="12" cy="12" r="4" />
    <path d="M12 12 18 6" />
    <circle cx="12" cy="12" r="0.6" fill="currentColor" />
  </Svg>
);

export const ExploreIcon = () => (
  <Svg>
    <circle cx="12" cy="12" r="9" />
    <path d="m15.5 8.5-2 5-5 2 2-5z" />
  </Svg>
);

export const NearbyIcon = () => (
  <Svg>
    <path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z" />
    <circle cx="12" cy="10" r="2.4" />
  </Svg>
);

export const InfoIcon = () => (
  <Svg>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5" />
    <path d="M12 7.6v.1" />
  </Svg>
);

export const SunIcon = () => (
  <Svg>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4" />
  </Svg>
);

export const MoonIcon = () => (
  <Svg>
    <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
  </Svg>
);

export const SystemIcon = () => (
  <Svg>
    <rect x="3" y="4.5" width="18" height="12" rx="2" />
    <path d="M8.5 20h7M12 16.5V20" />
  </Svg>
);

export const SearchIcon = () => (
  <Svg>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m20 20-4.2-4.2" />
  </Svg>
);

export const LayersIcon = () => (
  <Svg>
    <path d="m12 3 9 5-9 5-9-5z" />
    <path d="m3 13 9 5 9-5" />
  </Svg>
);

export const ChevronRightIcon = () => (
  <Svg>
    <path d="m9 6 6 6-6 6" />
  </Svg>
);

export const ChevronLeftIcon = () => (
  <Svg>
    <path d="m15 6-6 6 6 6" />
  </Svg>
);

export const CheckIcon = () => (
  <Svg>
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </Svg>
);

export const PlusIcon = () => (
  <Svg>
    <path d="M12 5v14M5 12h14" />
  </Svg>
);

export const PlayIcon = () => (
  <Svg filled>
    <path d="M8 5.5v13a1 1 0 0 0 1.5.9l10.4-6.5a1 1 0 0 0 0-1.8L9.5 4.6A1 1 0 0 0 8 5.5z" />
  </Svg>
);

export const PauseIcon = () => (
  <Svg filled>
    <rect x="6.5" y="5" width="4" height="14" rx="1" />
    <rect x="13.5" y="5" width="4" height="14" rx="1" />
  </Svg>
);

export const LocateIcon = () => (
  <Svg>
    <circle cx="12" cy="12" r="7" />
    <circle cx="12" cy="12" r="2.5" />
    <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
  </Svg>
);

export const WeatherIcon = () => (
  <Svg>
    <path d="M7 18a4 4 0 1 1 .9-7.9A5.5 5.5 0 0 1 18.5 12 3 3 0 0 1 18 18z" />
  </Svg>
);

export const ArrowLeftIcon = () => (
  <Svg>
    <path d="M19 12H5M11 6l-6 6 6 6" />
  </Svg>
);

const WavesIcon = () => (
  <Svg>
    <path d="M3 9c2 0 2-1.5 4.5-1.5S9.5 9 12 9s2.5-1.5 4.5-1.5S19 9 21 9" />
    <path d="M3 14c2 0 2-1.5 4.5-1.5S9.5 14 12 14s2.5-1.5 4.5-1.5S19 14 21 14" />
    <path d="M3 19c2 0 2-1.5 4.5-1.5S9.5 19 12 19s2.5-1.5 4.5-1.5S19 19 21 19" />
  </Svg>
);

const TreeIcon = () => (
  <Svg>
    <path d="M12 3 6 11h3l-4 6h14l-4-6h3z" />
    <path d="M12 17v4" />
  </Svg>
);

const BirdIcon = () => (
  <Svg>
    <path d="M16 7.5a2.5 2.5 0 1 0-4.6 1.4L4 16.5c3.5 1 7.5.5 10-2.5 1.5-1.8 2-4 2-6.5z" />
    <path d="M16 7.5 20 8l-3.5 1.5" />
  </Svg>
);

const BeachIcon = () => (
  <Svg>
    <path d="M4 12a8 8 0 0 1 16 0z" />
    <path d="M12 12v8M3 20h18" />
  </Svg>
);

/** An icon for a place kind (dive site, park, hotspot, …); a pin for anything else. */
export function PlaceKindIcon({ kind }: { kind: string }) {
  if (/dive|reef|bay|marine|harbo/i.test(kind)) return <WavesIcon />;
  if (/park|forest|reserve|trail|preserve/i.test(kind)) return <TreeIcon />;
  if (/hotspot|bird|slough|marsh|wetland/i.test(kind)) return <BirdIcon />;
  if (/beach|coast/i.test(kind)) return <BeachIcon />;
  return <NearbyIcon />;
}
