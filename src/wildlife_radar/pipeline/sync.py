"""Copy published versions between the worker, object storage and the API's local cache.

Layout, the same locally and in the bucket (docs/design/data-platform.md §2)::

    publish/region=<id>/version=<v>/{serving.duckdb, manifest.json, static/...}
    publish/region=<id>/CURRENT

- **Push** (worker → bucket): upload every file of the current version, then the pointer. A
  reader that sees the new ``CURRENT`` therefore always finds the whole version.
- **Pull** (bucket → API): download the bundle of the remote ``CURRENT`` into a local folder,
  then swap the local pointer; the API follows it (``serve --bundle-dir``).
- **Prune**: keep the newest few versions (and always the current one), here and remotely.
  Rollback is a pointer change to a kept version. Shared static files
  (``region=<id>/static/...``, content-addressed) are kept while a kept version's
  ``static/index.json`` references them.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from wildlife_radar.pipeline.publish import BUNDLE_FILE, CURRENT, set_current
from wildlife_radar.pipeline.static import INDEX, STATIC_DIR, referenced
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
        # Shared static files first (only new ones: they are content-addressed).
        shared = region_dir / STATIC_DIR
        if shared.exists():
            have = set(store.list(f"{_region_prefix(region_id)}/{STATIC_DIR}/"))
            for path in sorted(p for p in shared.rglob("*") if p.is_file()):
                if path.name.startswith("."):
                    continue
                key = f"{_region_prefix(region_id)}/{path.relative_to(region_dir).as_posix()}"
                if key not in have:
                    store.put_file(key, path)
                    out["uploaded"] += 1
        folder = region_dir / f"version={version}"
        prefix = f"{_region_prefix(region_id)}/version={version}"
        files = sorted(p for p in folder.rglob("*") if p.is_file())
        # The bundle and manifest go last within the version, the pointer after everything.
        files.sort(key=lambda p: p.name in (BUNDLE_FILE, "manifest.json"))
        for path in files:
            store.put_file(f"{prefix}/{path.relative_to(folder).as_posix()}", path)
        store.put_text(f"{_region_prefix(region_id)}/{CURRENT}", version + "\n", NO_CACHE)
        out["uploaded"] += len(files)
    out["pruned"] = prune_remote(store, region_id, keep)
    return out


def prune_remote(store: ObjectStore, region_id: str, keep: int = KEEP_VERSIONS) -> list[str]:
    keys = store.list(f"{_region_prefix(region_id)}/version=")
    current = (store.get_text(f"{_region_prefix(region_id)}/{CURRENT}") or "").strip()
    versions = sorted(_versions_from_keys(keys, region_id))
    drop = _stale(versions, current, keep)
    if drop:
        prefixes = tuple(f"{_region_prefix(region_id)}/version={v}/" for v in drop)
        store.delete([k for k in keys if k.startswith(prefixes)])
    # Shared static files no kept version references.
    used: set[str] = set()
    for v in set(versions) - set(drop):
        text = store.get_text(f"{_region_prefix(region_id)}/version={v}/{STATIC_DIR}/{INDEX}")
        if text:
            used |= referenced(json.loads(text))
    shared = store.list(f"{_region_prefix(region_id)}/{STATIC_DIR}/")
    strip = len(_region_prefix(region_id)) + 1
    store.delete([k for k in shared if k[strip:] not in used])
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
    shared = region_dir / STATIC_DIR
    if shared.exists():
        used: set[str] = set()
        for index in region_dir.glob(f"version=*/{STATIC_DIR}/{INDEX}"):
            used |= referenced(json.loads(index.read_text(encoding="utf-8")))
        for path in [p for p in shared.rglob("*") if p.is_file()]:
            if path.relative_to(region_dir).as_posix() not in used:
                path.unlink()
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


def sync_ref(store: ObjectStore, ref_root: Path) -> dict:
    """Two-way copy of the reference store's parts (immutable, uniquely named per writer):
    download parts other workers wrote, upload this worker's new ones."""
    remote = {k for k in store.list("ref/") if k.endswith(".parquet")}
    parts = ref_root.rglob("part-*.parquet") if ref_root.exists() else []
    local = {p.relative_to(ref_root.parent).as_posix(): p for p in parts}
    pulled = sorted(remote - set(local))
    for key in pulled:
        store.get_file(key, ref_root.parent / key)
    pushed = sorted(set(local) - remote)
    for key in pushed:
        store.put_file(key, local[key], cache_control="private, max-age=31536000, immutable")
    return {"pulled": len(pulled), "pushed": len(pushed)}
