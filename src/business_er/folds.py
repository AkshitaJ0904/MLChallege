"""Deterministic S1-grouped folds with explicit, stable config fingerprints."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FoldConfig:
    n_folds: int = 5
    seed: int = 20260926
    version: str = "s1-stratified-v1"

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]


def cardinality_bucket(n: int) -> str:
    return "6+" if n >= 6 else str(n)


def fold_for(s1_id: str, country: str, targets: Iterable[str], config: FoldConfig) -> int:
    """Stable hash stratification on country, cardinality, and S2/S3 composition."""
    ids = tuple(targets)
    composition = ("S2" if any(x.startswith("S2-") for x in ids) else "") + ("S3" if any(x.startswith("S3-") for x in ids) else "")
    stratum = f"{country}|{cardinality_bucket(len(ids))}|{composition or 'none'}"
    raw = f"{config.seed}|{stratum}|{s1_id}".encode("utf-8")
    return int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big") % config.n_folds
