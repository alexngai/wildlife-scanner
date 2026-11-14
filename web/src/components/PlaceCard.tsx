import type { ReactNode } from "react";
import { Link } from "react-router";
import { ChevronRightIcon, PlaceKindIcon } from "./Icons";

const KIND: Record<string, string> = {
  dive_site: "Dive site",
  park: "Park",
  zone: "Area",
  trail: "Trail",
  beach: "Beach",
  hotspot: "Birding hotspot",
};

export function kindLabel(kind: string): string {
  return KIND[kind] ?? kind.charAt(0).toUpperCase() + kind.slice(1).replace(/_/g, " ");
}

/** One place, linked: the same card on the region, nearby and hotspot views. */
export function PlaceCard({ to, name, kind, detail }: { to: string; name: string; kind: string; detail?: ReactNode }) {
  return (
    <Link className="card card-link" to={to}>
      <span className="place-icon">
        <PlaceKindIcon kind={kind} />
      </span>
      <span className="card-body">
        <span className="card-title">{name}</span>
        <span className="muted small">{detail ?? kindLabel(kind)}</span>
      </span>
      <span className="chevron">
        <ChevronRightIcon />
      </span>
    </Link>
  );
}
