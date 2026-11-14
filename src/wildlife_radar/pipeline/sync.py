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


LAKE_PREFIXES = ("ref", "norm")
MUTABLE = {"_cursor.json"}
"""Lake files that change in place (live-log cursors); everything else is immutable."""
MARKERS = {"_SUCCESS.json", "delta.json"}
"""Written last in a coverage snapshot folder: uploaded last, so a reader never sees a
partial snapshot as complete."""


def _incomplete_snapshot(rel: str, complete: set[str]) -> bool:
    """A coverage snapshot folder whose build hasn't finished (no ``_SUCCESS.json``)."""
    parts = rel.split("/")
    if "source=gbif" not in parts:
        return False
    i = parts.index("source=gbif")
    if len(parts) < i + 3:
        return False
    return "/".join(parts[: i + 3]) not in complete


def lake_files(lake: Path) -> dict[str, Path]:
    """Lake files to share (``ref/`` and ``norm/``), keyed by their path under the lake;
    hidden and temporary files and unfinished snapshot builds are left out."""
    out: dict[str, Path] = {}
    for prefix in LAKE_PREFIXES:
        root = lake / prefix
        if root.exists():
            for p in root.rglob("*"):
                rel = p.relative_to(lake)
                if p.is_file() and not any(x.startswith(".") for x in rel.parts):
                    out[rel.as_posix()] = p
    complete = {k.rsplit("/", 1)[0] for k in out if k.endswith("/_SUCCESS.json")}
    return {k: p for k, p in out.items() if not _incomplete_snapshot(k, complete)}


def sync_lake(
    store: ObjectStore,
    lake: Path,
    *,
    push: bool = True,
    pull: bool = False,
    pull_prefixes: tuple[str, ...] = LAKE_PREFIXES,
    workers: int = 4,
    prune: bool = False,
    log=lambda _m: None,
) -> dict:
    """Copy the lake's shared layers to and from object storage.

    ``prune`` deletes remote files inside snapshot folders that are complete here but no
    longer hold them (e.g. tiles split into smaller parts): pulled, they would duplicate rows.

    Immutable files are matched by key and size; live-log cursors are pushed when their
    content changed and pulled only when missing. ``pull`` restores a fresh machine (limited
    to ``pull_prefixes``, e.g. only the reference store and the live log)."""
    from concurrent.futures import ThreadPoolExecutor

    from wildlife_radar.storage.objects import R2_MAX_PUT

    remote: dict[str, int] = {}
    for prefix in LAKE_PREFIXES:
        if hasattr(store, "stat"):
            remote.update(store.stat(f"{prefix}/"))
        else:
            remote.update({k: -1 for k in store.list(f"{prefix}/")})
    local = lake_files(lake)
    out: dict = {"pushed": 0, "pushed_bytes": 0, "pulled": 0, "pulled_bytes": 0}

    if push:
        todo, too_big = [], []
        for key, path in local.items():
            size = path.stat().st_size
            name = key.rsplit("/", 1)[-1]
            if name in MUTABLE:
                if key in remote and store.get_text(key) == path.read_text(encoding="utf-8"):
                    continue
            elif key in remote and remote[key] in (-1, size):
                continue
            if size > R2_MAX_PUT:
                too_big.append(key)
                continue
            todo.append((key, path, size))
        data = [t for t in todo if t[0].rsplit("/", 1)[-1] not in MARKERS]
        markers = [t for t in todo if t[0].rsplit("/", 1)[-1] in MARKERS]

        def up(item) -> int:
            key, path, size = item
            name = key.rsplit("/", 1)[-1]
            cache = "no-cache" if name in MUTABLE else "private, max-age=31536000, immutable"
            store.put_file(key, path, cache_control=cache)
            return size

        for batch in (data, markers):
            with ThreadPoolExecutor(workers) as pool:
                for i, size in enumerate(pool.map(up, batch), 1):
                    out["pushed"] += 1
                    out["pushed_bytes"] += size
                    if i % 50 == 0:
                        log(f"pushed {out['pushed']}/{len(todo)} ({out['pushed_bytes'] >> 20} MiB)")
        if too_big:
            out["too_big"] = too_big

    if prune:
        local_complete = {k.rsplit("/", 1)[0] for k in local if k.endswith("/_SUCCESS.json")}
        stale = [
            k
            for k in remote
            if k not in local
            and "/source=gbif/" in k
            and any(k.startswith(f"{folder}/") for folder in local_complete)
        ]
        if stale:
            store.delete(stale)
            for k in stale:
                remote.pop(k, None)
        out["pruned"] = len(stale)

    if pull:
        complete = {k.rsplit("/", 1)[0] for k in remote if k.endswith("/_SUCCESS.json")}
        want = [
            k
            for k in remote
            if k not in local
            and k.startswith(pull_prefixes)
            and not _incomplete_snapshot(k, complete)
        ]
        # Markers last here too: a crash mid-pull leaves the snapshot incomplete, not wrong.
        want.sort(key=lambda k: k.rsplit("/", 1)[-1] in MARKERS)

        def down(key: str) -> int:
            store.get_file(key, lake / key)
            return (lake / key).stat().st_size

        data = [k for k in want if k.rsplit("/", 1)[-1] not in MARKERS]
        markers = [k for k in want if k.rsplit("/", 1)[-1] in MARKERS]
        for batch in (data, markers):
            with ThreadPoolExecutor(workers) as pool:
                for size in pool.map(down, batch):
                    out["pulled"] += 1
                    out["pulled_bytes"] += size
    return out
