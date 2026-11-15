# Contributing to Wildlife Scanner

Thanks for helping. This project predicts where and when people can see wildlife, so two
things matter as much as working code: **protecting sensitive species** and **respecting the
data's licences and the people who recorded it**. The rules below follow from those.

## Ways to help

- **Report a problem:** a bug, a prediction that looks wrong, a species with the wrong name or
  status, a place that's missing. Use the [issue templates](../../issues/new/choose).
- **Report a sensitive species shown too precisely**, or a security problem: privately, as
  described in [`SECURITY.md`](SECURITY.md). Please don't open a public issue for these.
- **Improve the code:** pick an open issue, or propose a change in an issue first if it's large.
- **Add a region** (a region pack), **species knowledge** (profiles), or **a data source**
  (see the checklists below).
- **Improve the docs:** clear explanations of what the numbers mean are as valuable as code.

## Setting up

You need Python 3.11 or later and [uv](https://docs.astral.sh/uv/). For the web app, Node 20 or
later.

```bash
uv sync
uv run pytest                                          # the test suite (no network needed)
uv run ruff check . && uv run ruff format --check .    # lint and formatting
uv run wildlife-scanner demo                           # a synthetic database, offline
```

The web app has its own instructions in [`web/README.md`](web/README.md).

## Making a change

1. Fork the repository and create a branch.
2. Make the change with tests. Bug fixes should come with a test that fails without the fix.
3. Run the tests and the linters (above). CI runs the same checks on Python 3.11 and 3.13.
4. Open a pull request using the template, and say what you changed and how you checked it.

Style:

- Formatting and linting are `ruff`'s (line length 100). Type hints throughout.
- Keep functions small and documented where the reason isn't obvious from the code.
- Tests must not use the network: use the fakes and `httpx.MockTransport` patterns in `tests/`.
- Documentation is plain, concrete English: short sentences, numbers with units, no marketing.

## Rules that protect species and people

These are enforced in code and reviews will check them:

1. **Never publish finer detail than a species' tier allows.** All public output (API, static
   files) goes through the policy layer (`src/wildlife_scanner/policy/`). Don't add a path
   around it.
2. **Tier assignment fails closed.** If a status lookup fails or is missing, the species stays
   protected. Code that defaults to "open" on error will not be merged.
3. **Statuses come from authoritative sources.** Language models and heuristics may suggest,
   but never set or lower, a status or a tier.
4. **Publishing stays gated on the tier audit.** Don't weaken the gate to get a build through.
   Fix the finding, or document a reviewed override.
5. **No third-party data in the repository.** Data, caches and generated files go in the
   git-ignored `data/` folder. Small synthetic fixtures for tests are fine.
6. **No personal details in requests to outside services.** The default User-Agent names the
   project and version only. Operators add their own contact through configuration.
7. **Respect each source's terms.** Many sources are non-commercial or require attribution. A new
   source needs its licence and terms recorded in [`DATA_SOURCES.md`](DATA_SOURCES.md) before its
   data is used.

## Contracts with the web app

The static file formats ([`docs/design/static-products.md`](docs/design/static-products.md)) and
the API's `/openapi.json` are contracts with the web app:

- Additions (new fields, new endpoints) are fine.
- Breaking changes bump the format number.
- Every change gets a line in the changelog at the top of that document.

## Checklists

**A new region**
- [ ] A pack in `regions/<id>/` with bounding box, time zone, places, status scopes and (if it
      sits inside one) its coverage area. Copy an existing pack.
- [ ] Curated statuses for locally sensitive species (`statuses.yaml`), with sources.
- [ ] A full `run publish` passes its backtests and the tier audit. Note the audit findings in
      the pull request.

**A new data source**
- [ ] Licence, terms and attribution in `DATA_SOURCES.md`; check that non-commercial and
      share-alike terms fit the project.
- [ ] A connector with rate limiting, retries and a test using a mocked transport.
- [ ] How the source's own sensitive-species handling (obscured coordinates, embargoes) is kept.

**A species profile**
- [ ] Sources for every claim (see [`profiles/README.md`](profiles/README.md)).
- [ ] Condition terms are hypotheses: they're tested on held-out data before being used.

## Filing a good issue

- **Wrong prediction:** the region, species, place or map cell, the week or date, what you
  expected and why (for example, your own observations or a published source).
- **Bug:** steps to reproduce, what happened, what you expected, and the version (`wildlife-scanner
  --version`) or commit.
- **Feature:** the problem it solves for someone looking for wildlife.

## Conduct

Be kind and assume good faith. Disagree about ideas, not people. Harassment of any kind isn't
welcome. Maintainers may remove comments or contributions that break this, and may block
repeat offenders.

By contributing, you agree that your contribution is licensed under the
[GNU AGPL-3.0](LICENSE), like the rest of the project.
