"""Object storage for published products: a local folder or an S3-compatible bucket (R2).

``open_store(url)`` takes ``s3://bucket/prefix`` or a local path (``file://`` optional).

S3 settings come from the standard AWS environment, which boto3 reads itself, so nothing
secret is passed on the command line:

- ``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY`` (an R2 API token's key pair);
- ``AWS_ENDPOINT_URL_S3``, e.g. ``https://<account id>.r2.cloudflarestorage.com``;
- ``AWS_REGION=auto`` for R2.

boto3 is the optional ``deploy`` extra (``uv sync --extra deploy``).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Protocol

IMMUTABLE = "public, max-age=31536000, immutable"
"""Cache-Control for versioned files: a published version never changes."""
NO_CACHE = "no-cache"
"""Cache-Control for pointers (``CURRENT``), which change on every publish."""

_TYPES = {
    ".json": "application/json",
    ".gz": "application/gzip",
    ".duckdb": "application/octet-stream",
    ".sqlite": "application/vnd.sqlite3",
    ".pmtiles": "application/vnd.pmtiles",
}


def content_type(key: str) -> str:
    return _TYPES.get(Path(key).suffix, "application/octet-stream")


class ObjectStore(Protocol):
    url: str

    def put_file(self, key: str, path: Path, cache_control: str = IMMUTABLE) -> None: ...
    def get_file(self, key: str, path: Path) -> None: ...
    def put_text(self, key: str, text: str, cache_control: str = NO_CACHE) -> None: ...
    def get_text(self, key: str) -> str | None: ...
    def list(self, prefix: str) -> list[str]: ...
    def delete(self, keys: list[str]) -> None: ...


class LocalStore:
    """A folder standing in for a bucket (tests, single-machine setups)."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.url = str(self.root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"key escapes the store: {key!r}")
        return path

    def put_file(self, key: str, path: Path, cache_control: str = IMMUTABLE) -> None:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".{dest.name}.tmp")
        shutil.copyfile(path, tmp)
        os.replace(tmp, dest)

    def get_file(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._path(key), path)

    def put_text(self, key: str, text: str, cache_control: str = NO_CACHE) -> None:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".{dest.name}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, dest)

    def get_text(self, key: str) -> str | None:
        path = self._path(key)
        return path.read_text(encoding="utf-8") if path.exists() else None

    def list(self, prefix: str) -> list[str]:
        base = self._path(prefix) if prefix else self.root
        folder = base if base.is_dir() else base.parent
        if not folder.exists():
            return []
        keys = (p.relative_to(self.root).as_posix() for p in folder.rglob("*") if p.is_file())
        return sorted(k for k in keys if k.startswith(prefix) and not Path(k).name.startswith("."))

    def delete(self, keys: list[str]) -> None:
        for key in keys:
            self._path(key).unlink(missing_ok=True)


class S3Store:
    """An S3-compatible bucket (Cloudflare R2 in production)."""

    def __init__(self, bucket: str, prefix: str = "", client=None) -> None:
        if client is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover - depends on the install
                raise RuntimeError(
                    "S3 storage needs the deploy extra: uv sync --extra deploy"
                ) from exc
            client = boto3.client("s3")
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.url = f"s3://{bucket}/{self.prefix}".rstrip("/")

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def put_file(self, key: str, path: Path, cache_control: str = IMMUTABLE) -> None:
        self.client.upload_file(
            str(path),
            self.bucket,
            self._key(key),
            ExtraArgs={"ContentType": content_type(key), "CacheControl": cache_control},
        )

    def get_file(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.part")
        self.client.download_file(self.bucket, self._key(key), str(tmp))
        os.replace(tmp, path)

    def put_text(self, key: str, text: str, cache_control: str = NO_CACHE) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._key(key),
            Body=text.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
            CacheControl=cache_control,
        )

    def get_text(self, key: str) -> str | None:
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
        except self.client.exceptions.NoSuchKey:
            return None
        return obj["Body"].read().decode("utf-8")

    def list(self, prefix: str) -> list[str]:
        strip = len(self.prefix) + 1 if self.prefix else 0
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self._key(prefix)):
            keys += [o["Key"][strip:] for o in page.get("Contents", [])]
        return sorted(keys)

    def delete(self, keys: list[str]) -> None:
        for i in range(0, len(keys), 1000):
            batch = [{"Key": self._key(k)} for k in keys[i : i + 1000]]
            self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": batch})


def open_store(url: str | Path) -> ObjectStore:
    text = str(url)
    if text.startswith("s3://"):
        bucket, _, prefix = text[5:].partition("/")
        return S3Store(bucket, prefix)
    return LocalStore(text.removeprefix("file://"))
