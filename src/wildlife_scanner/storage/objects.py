"""Object storage for published products and the lake: a local folder, an S3-compatible
bucket, or an R2 bucket through Cloudflare's REST API.

``open_store(url)`` takes ``r2://<account id>/<bucket>/<prefix>``, ``s3://bucket/prefix`` or
a local path (``file://`` optional).

**R2 over the REST API** (``r2://``) sends the token as a bearer header, so a proxy can inject
it and no secret reaches the process: set ``CLOUDFLARE_API_TOKEN`` only where no proxy does.
The token needs *Account → Workers R2 Storage → Edit*; a token scoped to one bucket's objects
is refused by the REST API (tested 2026-11-14). One upload is at most 300 MiB.

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


R2_API = "https://api.cloudflare.com/client/v4/accounts/{account}/r2/buckets/{bucket}"
R2_MAX_PUT = 300 * 1024 * 1024
"""Largest single upload the REST API accepts (301 MiB is refused with 413)."""
R2_TOKEN_ENV = "CLOUDFLARE_API_TOKEN"
_MISSING = 10007  # "The specified key does not exist."


class R2RestStore:
    """An R2 bucket through Cloudflare's REST object API (no S3 signing)."""

    def __init__(
        self, account: str, bucket: str, prefix: str = "", client=None, retries: int = 4
    ) -> None:
        import httpx

        from wildlife_scanner.connectors.base import make_client

        self.base = R2_API.format(account=account, bucket=bucket)
        self.prefix = prefix.strip("/")
        self.url = f"r2://{account}/{bucket}/{self.prefix}".rstrip("/")
        self.retries = retries
        if client is None:
            client = make_client(timeout=600)
            token = os.environ.get(R2_TOKEN_ENV)
            if token:
                client.headers["Authorization"] = f"Bearer {token}"
        self.client: httpx.Client = client

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def _object(self, key: str) -> str:
        from urllib.parse import quote

        return f"{self.base}/objects/{quote(self._key(key), safe='/')}"

    def _send(self, method: str, url: str, **kw):
        import time

        import httpx

        for attempt in range(self.retries + 1):
            try:
                body = kw.get("content")
                if hasattr(body, "seek"):
                    body.seek(0)
                resp = self.client.request(method, url, **kw)
            except httpx.TransportError:
                if attempt == self.retries:
                    raise
            else:
                if resp.status_code != 429 and resp.status_code < 500:
                    return resp
                if attempt == self.retries:
                    resp.raise_for_status()
            time.sleep(min(60, 2**attempt))
        raise AssertionError("unreachable")

    @staticmethod
    def _check(resp, what: str) -> None:
        if resp.status_code >= 400:
            raise RuntimeError(f"R2 {what}: HTTP {resp.status_code} {resp.text[:300]}")
        ctype = resp.headers.get("content-type", "")
        if ctype.startswith("application/json") and resp.content[:1] == b"{":
            data = resp.json()
            if data.get("success") is False:
                raise RuntimeError(f"R2 {what}: {data.get('errors')}")

    def _put(self, key: str, body, ctype: str, cache_control: str) -> None:
        resp = self._send(
            "PUT",
            self._object(key),
            content=body,
            headers={"Content-Type": ctype, "Cache-Control": cache_control},
        )
        if resp.status_code >= 400 or not resp.json().get("success"):
            raise RuntimeError(f"R2 put {key}: HTTP {resp.status_code} {resp.text[:300]}")

    def put_file(self, key: str, path: Path, cache_control: str = IMMUTABLE) -> None:
        size = path.stat().st_size
        if size > R2_MAX_PUT:
            raise ValueError(f"{path} is {size >> 20} MiB; R2's REST API takes at most 300 MiB")
        with open(path, "rb") as fh:
            self._put(key, fh, content_type(key), cache_control)

    def get_file(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.part")
        for attempt in range(self.retries + 1):
            try:
                with self.client.stream("GET", self._object(key)) as resp:
                    if resp.status_code >= 400:
                        resp.read()
                        raise RuntimeError(f"R2 get {key}: HTTP {resp.status_code}")
                    with open(tmp, "wb") as fh:
                        for chunk in resp.iter_bytes(1 << 20):
                            fh.write(chunk)
                break
            except Exception:
                if attempt == self.retries:
                    tmp.unlink(missing_ok=True)
                    raise
        os.replace(tmp, path)

    def put_text(self, key: str, text: str, cache_control: str = NO_CACHE) -> None:
        self._put(key, text.encode("utf-8"), "text/plain; charset=utf-8", cache_control)

    def get_text(self, key: str) -> str | None:
        resp = self._send("GET", self._object(key))
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise RuntimeError(f"R2 get {key}: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.content.decode("utf-8")

    def list(self, prefix: str) -> list[str]:
        return sorted(self.stat(prefix))

    def stat(self, prefix: str) -> dict[str, int]:
        """Key → size, for every object under ``prefix``."""
        strip = len(self.prefix) + 1 if self.prefix else 0
        out: dict[str, int] = {}
        cursor = None
        while True:
            params = {"prefix": self._key(prefix), "per_page": 1000}
            if cursor:
                params["cursor"] = cursor
            resp = self._send("GET", f"{self.base}/objects", params=params)
            self._check(resp, f"list {prefix}")
            data = resp.json()
            for o in data.get("result") or []:
                out[o["key"][strip:]] = int(o.get("size") or 0)
            info = data.get("result_info") or {}
            cursor = info.get("cursor")
            if not info.get("is_truncated") or not cursor:
                return out

    def delete(self, keys: list[str]) -> None:
        from concurrent.futures import ThreadPoolExecutor

        def one(key: str) -> None:
            resp = self._send("DELETE", self._object(key))
            if resp.status_code == 404:
                return
            data = resp.json() if resp.content else {}
            if data.get("success") is False and not any(
                e.get("code") == _MISSING for e in data.get("errors") or []
            ):
                raise RuntimeError(f"R2 delete {key}: {data.get('errors')}")

        with ThreadPoolExecutor(8) as pool:
            list(pool.map(one, keys))


def open_store(url: str | Path) -> ObjectStore:
    text = str(url)
    if text.startswith("r2://"):
        account, _, rest = text[5:].partition("/")
        bucket, _, prefix = rest.partition("/")
        if not account or not bucket:
            raise ValueError("r2 URLs look like r2://<account id>/<bucket>/<prefix>")
        return R2RestStore(account, bucket, prefix)
    if text.startswith("s3://"):
        bucket, _, prefix = text[5:].partition("/")
        return S3Store(bucket, prefix)
    return LocalStore(text.removeprefix("file://"))
