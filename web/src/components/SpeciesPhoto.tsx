import { useState } from "react";
import { creditText, type ShownPhoto } from "../lib/photos";
import { GroupIcon } from "./Icons";

type Size = "sm" | "md" | "lg";

/** The placeholder: a group icon, shown when there's no photo or it fails to load. */
function Placeholder({ group, size }: { group?: string | null; size: Size }) {
  return (
    <span className={`thumb thumb-${size} thumb-empty`} aria-hidden="true">
      <GroupIcon group={group} />
    </span>
  );
}

function Img({ photo, group, size }: { photo: ShownPhoto; group?: string | null; size: Size }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <Placeholder group={group} size={size} />;
  return (
    <img
      className={`thumb thumb-${size}`}
      src={size === "lg" ? photo.large : photo.thumb}
      alt=""
      title={`Photo: ${creditText(photo)}`}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}

/**
 * A species thumbnail. Decorative (alt=""): the name is always next to it, and the credit is in
 * the title here and in the visible credits. A photo that has moved or gone falls back to the
 * placeholder.
 */
export function SpeciesThumb({
  photo,
  group,
  size = "sm",
}: {
  photo: ShownPhoto | null | undefined;
  group?: string | null;
  size?: Size;
}) {
  if (!photo) return <Placeholder group={group} size={size} />;
  // Keyed by URL so a new photo gets a fresh load attempt.
  return <Img key={photo.thumb} photo={photo} group={group} size={size} />;
}

/**
 * The species page's photo and its visible credit, as two grid items (the page header places the
 * photo beside the title and the credit beneath). The credit goes if the image fails to load.
 */
export function SpeciesFigure({
  photo,
  group,
  name,
}: {
  photo: ShownPhoto | null;
  group?: string | null;
  name: string;
}) {
  const [failed, setFailed] = useState(false);
  if (!photo || failed) return <Placeholder group={group} size="lg" />;
  return (
    <>
      <img
        className="thumb thumb-lg"
        src={photo.large}
        alt={name}
        decoding="async"
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
      />
      <p className="photo-caption muted">
        <PhotoCredit photo={photo} />
      </p>
    </>
  );
}

export function PhotoCredit({ photo }: { photo: ShownPhoto }) {
  const lic = photo.licenseUrl ? (
    <a href={photo.licenseUrl} rel="license noreferrer" target="_blank">
      {photo.license}
    </a>
  ) : (
    photo.license
  );
  // The source's credit often names its licence ("… (CC BY-NC), uploaded by …"); it's shown, linked, once.
  const who = photo.attribution.replace(/\s*\((?:CC|cc)[^)]*\)/, "").trim();
  return (
    <>
      Photo {who} ({lic})
      {photo.sourceUrl && (
        <>
          {" · "}
          <a href={photo.sourceUrl} rel="noreferrer" target="_blank">
            {photo.source ?? "source"}
          </a>
        </>
      )}
    </>
  );
}

/** Credits for the photos shown in a list, folded away. */
export function PhotoCredits({ items }: { items: { name: string; photo: ShownPhoto }[] }) {
  if (items.length === 0) return null;
  return (
    <details className="photo-credits">
      <summary>Photo credits</summary>
      <ul>
        {items.map(({ name, photo }) => (
          <li key={name}>
            {name}: <PhotoCredit photo={photo} />
          </li>
        ))}
      </ul>
    </details>
  );
}
