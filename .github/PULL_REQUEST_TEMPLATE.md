## What and why

<!-- What this changes, and the problem it solves. Link the issue if there is one. -->

## How it was checked

<!-- Tests added or run, and for pipeline changes, a run on real or synthetic data. -->

## Checklist

- [ ] `uv run pytest`, `uv run ruff check .` and `uv run ruff format --check .` pass.
- [ ] No third-party data, caches or personal details are added to the repository.
- [ ] Public output still goes through the policy layer; nothing is finer than a tier allows.
- [ ] Static formats or the API changed? The changelog in `docs/design/static-products.md` is updated.
- [ ] New data source? Its licence and terms are in `DATA_SOURCES.md`.
