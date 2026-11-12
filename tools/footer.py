"""Reconstruct a sparse local Parquet file holding only the real footer, so DuckDB's
parquet_metadata() can read row-group statistics without downloading the data pages."""

import struct


def write_sparse(path: str, size: int, tail: bytes) -> None:
    """tail = the last len(tail) bytes of the real file (must include footer + 8-byte trailer)."""
    footer_len = struct.unpack("<I", tail[-8:-4])[0]
    assert tail[-4:] == b"PAR1", "not a parquet file"
    assert footer_len + 8 <= len(tail), f"need {footer_len + 8} tail bytes"
    with open(path, "wb") as fh:
        fh.write(b"PAR1")
        fh.truncate(size)
        fh.seek(size - len(tail))
        fh.write(tail)


def needed_tail(tail8: bytes) -> int:
    return struct.unpack("<I", tail8[-8:-4])[0] + 8
