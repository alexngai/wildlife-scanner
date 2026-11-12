"""Copy published versions between the worker, object storage and the API's local cache.

Layout, the same locally and in the bucket (docs/design/data-platform.md §2)::

    publish/region=<id>/version=<v>/{serving.duckdb, manifest.json, static/...}
    publish/region=<id>/CURRENT

- **Push** (worker → bucket): upload every file of the current version, then the pointer. A
  reader that sees the new ``CURRENT`` therefore always finds the whole version.
- **Pull** (bucket → API): download the bundle of the remote ``CURRENT`` into a local folder,
  then swap the local pointer; the API follows it (``serve --bundle-dir``).
- **Prune**: keep the newest few versions (and always the current one), here and remotely.
  Rollback is a pointer change to a kept version.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from wildlife_radar.pipeline.publish import BUNDLE_FILE, CURRENT, set_current
from wildlife_radar.storage.objects import NO_CACHE, ObjectStore

KEEP_VERSIONS = 6


def _region_prefix(region_id: str) -> str:
    return f"region={region_id}"


def local_current(region_dir: Path) -> str | None:
    pointer = region_dir / CURRENT
    return pointer.read_text(encoding="utf-8").strip() if pointer.exists() else None


def _versions_from_keys(keys: list[str], region_id: str) -> set[str]:
    prefix = f"{_region_prefix(region_id)}/version="
    return {k[len(prefix) :].split("/", 1)[0] for k in keys if k.startswith(prefix)}


def push_publish(
    publish_root: Path, store: ObjectStore, region_id: str, keep: int = KEEP_VERSIONS
) -> dict:
    """Upload the region's current local version (if new), swap the remote pointer, prune."""
    region_dir = publish_root / _region_prefix(region_id)
    version = local_current(region_dir)
    if version is None:
        raise RuntimeError(f"nothing published locally for region {region_id!r}")
    remote_version = (store.get_text(f"{_region_prefix(region_id)}/{CURRENT}") or "").strip()
    out: dict = {"version": version, "uploaded": 0}
    if remote_version != version:
        folder = region_dir / f"version={version}"
        prefix = f"{_region_prefix(region_id)}/version={version}"
        files = sorted(p for p in folder.rglob("*") if p.is_file())
        # The bundle and manifest go last within the version, the pointer after everything.
        files.sort(key=lambda p: p.name in (BUNDLE_FILE, "manifest.json"))
        for path in files:
            store.put_file(f"{prefix}/{path.relative_to(folder).as_posix()}", path)
        store.put_text(f"{_region_prefix(region_id)}/{CURRENT}", version + "\n", NO_CACHE)
        out["uploaded"] = len(files)
    out["pruned"] = prune_remote(store, region_id, keep)
    return out


def prune_remote(store: ObjectStore, region_id: str, keep: int = KEEP_VERSIONS) -> list[str]:
    keys = store.list(f"{_region_prefix(region_id)}/version=")
    current = (store.get_text(f"{_region_prefix(region_id)}/{CURRENT}") or "").strip()
    drop = _stale(sorted(_versions_from_keys(keys, region_id)), current, keep)
    if drop:
        prefixes = tuple(f"{_region_prefix(region_id)}/version={v}/" for v in drop)
        store.delete([k for k in keys if k.startswith(prefixes)])
    return drop


def prune_local(publish_root: Path, region_id: str, keep: int = KEEP_VERSIONS) -> list[str]:
    region_dir = publish_root / _region_prefix(region_id)
    if not region_dir.exists():
        return []
    versions = sorted(
        p.name.removeprefix("version=") for p in region_dir.glob("version=*") if p.is_dir()
    )
    drop = _stale(versions, local_current(region_dir), keep)
    for v in drop:
        shutil.rmtree(region_dir / f"version={v}", ignore_errors=True)
    return drop


def _stale(versions: list[str], current: str | None, keep: int) -> list[str]:
    """Versions to delete: all but the newest ``keep`` and the current one."""
    kept = set(versions[-keep:]) if keep > 0 else set()
    if current:
        kept.add(current)
    return [v for v in versions if v not in kept]


def pull_current(
    store: ObjectStore, region_id: str, cache_root: Path, keep: int = 2, files=(BUNDLE_FILE,)
) -> str | None:
    """Mirror the remote ``CURRENT`` bundle into ``cache_root``; returns the new version, or
    ``None`` when the local copy is already current (or nothing is published yet)."""
    region_dir = cache_root / _region_prefix(region_id)
    remote = (store.get_text(f"{_region_prefix(region_id)}/{CURRENT}") or "").strip()
    if not remote or remote == local_current(region_dir):
        return None
    folder = region_dir / f"version={remote}"
    tmp = region_dir / f".tmp-{remote}"
    shutil.rmtree(tmp, ignore_errors=True)
    for name in files:
        store.get_file(f"{_region_prefix(region_id)}/version={remote}/{name}", tmp / name)
    shutil.rmtree(folder, ignore_errors=True)
    tmp.rename(folder)
    set_current(region_dir, remote)
    # Keep the previous version too: the API may still hold it open until its next request.
    prune_local(cache_root, region_id, keep)
    return remote
