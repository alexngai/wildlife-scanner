# Licensing posture

**Decision (2026-11-11):** wildlife-scanner is **exclusively non-commercial**.
- It is a free, educational service.
- No monetization of any kind: no ads, paid tiers, affiliate or referral links, or commercial sponsorship of features.
- It is not operated by or on behalf of a for-profit entity. **The operator is the project founder, as an individual.** It may move to a fiscal sponsor or nonprofit later, e.g., to accept grants.
- **The code is licensed under AGPL-3.0** ([`../../LICENSE`](../../LICENSE)). It is genuinely open source, and anyone running a modified version as a network service must publish their source.

This note records what that changes. It is based on the research in [`../research/`](../research/). Several primary terms pages could not be read during that research (marked UNVERIFIED there). **Read the actual terms before relying on any row below.** This is not legal advice.

## 1. What being non-commercial unlocks

| Source | License / terms | Status for a commercial product | Status for us now |
|---|---|---|---|
| iNaturalist observations (most CC BY-NC) | Per-record CC; iNat Terms | Blocked; commercial AI training banned | ✅ Usable with attribution. The AI-training ban covers commercial use only. API etiquette still applies (≤60 req/min; "not for scraping"). |
| FishBase / SeaLifeBase | CC BY-NC | Blocked | ✅ **Marine traits gap closed:** depth, temperature, spawning, diet |
| AquaMaps | CC BY-NC | Blocked | ✅ Marine range priors |
| Map of Life | CC BY-NC | Blocked | ✅ Range priors |
| Happywhale / OBIS-SEAMAP | Mostly CC BY-NC | Blocked | ✅ |
| Open-Meteo (free tier) | Non-commercial; data CC BY 4.0 | Paid plan needed | ✅ Within fair-use limits |
| BirdNET models | CC BY-NC-SA | Blocked | ✅ ShareAlike: fine-tuned models must be released CC BY-NC-SA |
| xeno-canto recordings (many NC) | Per-recording CC | Mostly blocked | ✅ |
| Semantic Scholar / S2ORC | Non-commercial; CC BY-NC | Blocked | ✅ For literature extraction |
| BHL in-copyright items | CC BY-NC-SA | Blocked | ✅ |
| IUCN Red List API / spatial data | Non-commercial; commercial via IBAT | Blocked | ⚠ Likely usable, but **check the limits on redistributing raw data and range polygons** and the registration requirements |
| BirdLife range maps | Non-commercial, by request | Blocked | ⚠ Request per purpose; raw maps can't be redistributed |
| CITES Species+ | Commercial use needs written permission | Permission needed | ✅ Likely |
| TetrapodTraits (Zenodo 11303604) | CC BY 4.0 | ✅ | ✅ Imported into generated profiles with attribution; values carry `CC-BY-4.0` in their provenance |
| Wikidata | CC0 | ✅ | ✅ Identity crosswalk (ids, sitelinks, referenced IUCN categories as tier hints only) |
| **eBird Observation Dataset via GBIF** | **CC BY 4.0** (verified on 2026-11-01 snapshot records, dataset `4fa7b334-…`) | ✅ | ✅ Presence-only eBird data **without** the eBird API/EBD terms. It has no effort or non-detections, updates roughly annually, and sensitive species are withheld. Our Level-0 baseline only needs presence records. |

## 2. What being non-commercial does *not* fix

| Source | Remaining constraint | Action |
|---|---|---|
| **eBird API** | Non-commercial license is fine, but the key must not be shared; "single copy on a single device" language; server-side caching and redistribution not clearly addressed | Never commit keys; each deployer uses its own key. **Ask Cornell** about a public web service. |
| **eBird Basic Dataset** | Request per purpose; no redistribution in the original format | Request access for this purpose; publish only derived products, with attribution |
| **eBird Status & Trends** | Redistribution on websites is prohibited *even non-commercially*. Exceptions: peer-reviewed work; educational materials covering ≤100 species | **Written permission from Cornell** for a public app. The educational exception might cover a limited featured set; ask. |
| BirdCast | No API or reuse license | Partnership |
| Fishing-report sites (e.g., sportfishingreport.com) | Terms prohibit automated access and redistribution, whatever the purpose | Partnership only; never scrape |
| CNDDB (CDFW) | Subscription license; no republication | Use only as a sensitivity input, if at all |
| BIEN | CC BY-NC-ND (no derivatives) | Avoid |
| Wikipedia text | CC BY-SA: displayed excerpts are share-alike | Unchanged: store facts with citations; display text in a BY-SA component. Implemented in `profilegen`: extracted values carry `CC-BY-SA-4.0` taint and cite revision + character range. Quoted evidence stays in the git-ignored `data/profiles/extractions/` audit files |
| Movebank, Wildlife Insights NC projects, partner data | Per-study / per-agreement terms | Unchanged |
| Ethical limits (e.g., CDFW's daily collared-wolf tracker) | Not a license issue | Unchanged: never redistribute |

**Why "free" alone may not meet a "non-commercial" condition:**

- **CC definition.** CC's NC clause means "not primarily intended for or directed towards commercial advantage or monetary compensation."
- **eBird's definition is broader.** It includes any use *by or to assist a commercial entity*.
- **Keeping the project unambiguously non-commercial:**
  - no ads
  - no paid tiers
  - no affiliate or referral links (dive shops, charters, gear, tours)
  - run by an individual, a nonprofit, a fiscal sponsor or a university, **not a company**
  - donations and grants are normally fine, but say so when asking Cornell

## 3. New considerations that open source introduces

1. **Code and data licenses are separate.** An OSI-approved code license (MIT, Apache-2.0, GPL…) allows commercial use *of the code* by anyone, and that is fine. It does not relicense any data. NC data stays NC for every downstream user.
2. **The repo ships no third-party data.** No data files, API keys, partner data or precomputed fine-scale predictions are committed. Connectors fetch data at runtime under each deployer's own credentials and agreements. A `DATA_SOURCES.md` lists each source's terms; anyone running the code is responsible for their own data terms.
3. **The license ledger is still needed, for a different reason.** Before, it separated commercial from non-commercial builds. Now it labels **what each published data product inherits**:
   - NC inputs → NC outputs.
   - A **fully open variant** is built from CC0/CC BY/public-domain inputs only, so others (including scientists in other settings) can reuse it freely.
   - Restricted and partner inputs may inform models but are **never re-exposed**. Check that model artifacts trained on them don't leak fine-scale locations before releasing those artifacts.
4. **Sensitive species and openness.** Open code means the policy logic is public. That is good: safety comes from the design, not from secrecy. But:
   - every **published** data product (API, tiles, bulk dumps, model outputs) is post-policy;
   - unfiltered intermediates for tier ≥1 species are never published;
   - a fork can remove the policy layer from the code, but it then has only the data its operator can obtain.
5. **Contributions:**
   - **Code:** the Developer Certificate of Origin (DCO).
   - **User data:** observations, profile edits and hypotheses under **CC BY 4.0** (or CC0), so they are maximally reusable by science and education.
   - Pasted text from NC or BY-SA sources is rejected.

## 4. Proposed project licenses (to confirm)

| Asset | Proposed license | Note |
|---|---|---|
| Code | **AGPL-3.0** (decided) | See the options below |
| Docs | CC BY 4.0 | |
| Our own data products | CC BY 4.0 where all inputs allow; otherwise the inherited license (typically CC BY-NC 4.0) | Set automatically by the ledger |
| User contributions | CC BY 4.0 (or CC0) | |

### Code license options considered (AGPL-3.0 chosen)

**AGPL-3.0 obligations for our own deployment.** The web app must offer users a link to the corresponding source (AGPL §13). The API should expose a source link too.

The project's *service and data* are non-commercial either way. A separate question is whether third parties may use the *code* commercially.

| Option | Others' commercial use of the code | "Open source" (OSI)? | Notes |
|---|---|---|---|
| **AGPL-3.0** | Allowed, but anyone running a modified version as a service must publish their source | Yes | Deters closed commercial forks. Commercial forks also lack our NC data and partner data. |
| Apache-2.0 / MIT | Allowed, no conditions beyond attribution | Yes | Maximizes reuse, including by companies |
| PolyForm Noncommercial 1.0.0 | **Prohibited** | **No** ("source-available") | Hard NC guarantee. Some contributors, institutions and packagers avoid non-OSI licenses. |

## 5. Outreach angle

"Free, open-source, educational, conservation-aligned" makes data requests much easier. Lead with it in requests to:
- **Cornell:** eBird API/EBD/S&T, BirdCast
- **iNaturalist**
- **marine science partners:** REEF, Reef Check, PIER
- **fishing data:** the Fish Reports Network / landings, and CDFW for party-boat logbook data
- **wildlife programs:** UCSB's Benioff Ocean Science Lab, and the agency carnivore programs

Partners may still restrict how their data is redistributed. The architecture supports this through private inputs and partner-only tiers.
