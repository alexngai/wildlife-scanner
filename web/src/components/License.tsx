import type { License } from "../products/types";

const LICENSE_URLS: Record<string, string> = {
  "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
  "CC-BY-NC-4.0": "https://creativecommons.org/licenses/by-nc/4.0/",
  "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
  "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
};

/** License and attribution for a piece of data; shown wherever that data is shown. */
export function LicenseNote({ license }: { license: License | null | undefined }) {
  if (!license) return null;
  return (
    <p className="license-note">
      <span>Data licence: </span>
      {license.license_ids.map((id, i) => (
        <span key={id}>
          {i > 0 && ", "}
          {LICENSE_URLS[id] ? (
            <a href={LICENSE_URLS[id]} rel="license noreferrer" target="_blank">
              {id}
            </a>
          ) : (
            id
          )}
        </span>
      ))}
      {license.noncommercial && <span className="nc"> · Non-commercial use only</span>}
      {license.attribution.length > 0 && <span> · {license.attribution.join("; ")}</span>}
    </p>
  );
}
