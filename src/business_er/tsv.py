"""Strict streaming TSV interfaces; never materialise the supplied inputs."""

from __future__ import annotations

import csv
import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .normalization import RecordViews, make_views


@dataclass(frozen=True)
class GroundTruth:
    s1_id: str
    target_ids: tuple[str, ...]


def sha256_file(path: str | Path, block_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def iter_records(path: str | Path) -> Iterator[RecordViews]:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        expected = ["entity_id", "business_name", "business_address", "country"]
        if reader.fieldnames != expected:
            raise ValueError(f"{path}: expected {expected}; found {reader.fieldnames}")
        for line_number, row in enumerate(reader, start=2):
            if any(row[key] is None for key in expected):
                raise ValueError(f"{path}:{line_number}: malformed TSV row")
            yield make_views(row["entity_id"], row["business_name"], row["business_address"], row["country"])


def iter_ground_truth(path: str | Path) -> Iterator[GroundTruth]:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        expected = ["source1_entity_id", "matched_entity_ids"]
        if reader.fieldnames != expected:
            raise ValueError(f"{path}: expected {expected}; found {reader.fieldnames}")
        for line_number, row in enumerate(reader, start=2):
            raw = row["matched_entity_ids"]
            if row["source1_entity_id"] is None or raw is None:
                raise ValueError(f"{path}:{line_number}: malformed GT row")
            ids = tuple(item for item in raw.split(",") if item)
            if len(ids) != len(set(ids)):
                raise ValueError(f"{path}:{line_number}: duplicate target IDs")
            yield GroundTruth(row["source1_entity_id"], ids)


def atomic_text_writer(path: str | Path):
    """Context manager yielding a UTF-8 file, replaced only after success."""
    from contextlib import contextmanager

    @contextmanager
    def _writer():
        final = Path(path)
        final.parent.mkdir(parents=True, exist_ok=True)
        temporary = final.with_suffix(final.suffix + ".partial")
        try:
            with open(temporary, "w", encoding="utf-8", newline="") as out:
                yield out
            os.replace(temporary, final)
        except BaseException:
            if temporary.exists():
                temporary.unlink()
            raise
    return _writer()
