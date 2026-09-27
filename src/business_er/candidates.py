"""Candidate channels, provenance union, and resource-guarded retrieval primitives."""

from __future__ import annotations

import collections
import heapq
import json
import os
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .normalization import RecordViews
from .tsv import atomic_text_writer, iter_records

EXACT_CHANNELS = ("exact_name", "exact_address", "exact_name_address")


@dataclass
class CandidateEvidence:
    target_id: str
    target_source: str
    channels: set[str] = field(default_factory=set)
    ranks: dict[str, int] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)

    def add(self, channel: str, rank: int | None = None, score: float | None = None) -> None:
        self.channels.add(channel)
        if rank is not None:
            self.ranks[channel] = min(rank, self.ranks.get(channel, rank))
        if score is not None:
            self.scores[channel] = max(score, self.scores.get(channel, score))


def union_candidates(rows: Iterable[tuple[str, str, str, int | None, float | None]]) -> dict[str, CandidateEvidence]:
    merged: dict[str, CandidateEvidence] = {}
    for target_id, target_source, channel, rank, score in rows:
        item = merged.setdefault(target_id, CandidateEvidence(target_id, target_source))
        item.add(channel, rank, score)
    return merged


class DiskBudgetError(RuntimeError):
    pass


def assert_disk_budget(required_bytes: int, output_dir: str | Path, safety_multiplier: float = 1.25) -> None:
    import shutil
    free = shutil.disk_usage(output_dir).free
    needed = int(required_bytes * safety_multiplier)
    if needed > free:
        raise DiskBudgetError(f"refusing stage: estimated {needed:,} bytes required, only {free:,} free")


def _keys(record: RecordViews) -> dict[str, str]:
    name, address = record.name_punct, record.address_punct
    return {"exact_name": name, "exact_address": address, "exact_name_address": name + "\x1f" + address}


class ExactSqliteIndex:
    """SQLite exact blocks. Bounded RAM, atomic DB creation, deterministic queries."""

    def __init__(self, path: str | Path, country_partition: bool = False):
        self.path = Path(path)
        self.country_partition = country_partition
        self._connection: sqlite3.Connection | None = None

    def open(self) -> None:
        if self._connection is None:
            self._connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def build(self, source_paths: Iterable[str | Path], estimated_target_rows: int, disk_guard: bool = True) -> dict[str, int]:
        if disk_guard:
            # Three postings plus a B-tree index and temporary write amplification.
            # This intentionally includes enough headroom for final candidate output.
            assert_disk_budget(estimated_target_rows * 550, self.path.parent)
        partial = self.path.with_suffix(self.path.suffix + ".partial")
        if partial.exists():
            partial.unlink()
        con = sqlite3.connect(partial)
        try:
            con.executescript("""
                PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=FILE;
                CREATE TABLE blocks(channel TEXT NOT NULL, key TEXT NOT NULL, country TEXT NOT NULL,
                                    target_id TEXT NOT NULL, target_source TEXT NOT NULL);
            """)
            counts = collections.Counter(); buffer: list[tuple[str, str, str, str, str]] = []
            for source_path in source_paths:
                for record in iter_records(source_path):
                    for channel, key in _keys(record).items():
                        if key:
                            buffer.append((channel, key, record.country, record.entity_id, record.source)); counts[channel] += 1
                    if len(buffer) >= 50_000:
                        con.executemany("INSERT INTO blocks VALUES (?,?,?,?,?)", buffer); buffer.clear()
            if buffer: con.executemany("INSERT INTO blocks VALUES (?,?,?,?,?)", buffer)
            con.execute("CREATE INDEX blocks_lookup ON blocks(channel, key, country, target_id)"); con.commit()
        finally:
            con.close()
        os.replace(partial, self.path)
        return dict(counts)

    def query(self, record: RecordViews) -> Iterator[tuple[str, str, str, int, float | None]]:
        owned = self._connection is None
        con = self._connection or sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        try:
            for channel, key in _keys(record).items():
                if not key: continue
                if self.country_partition:
                    sql, params = ("SELECT target_id,target_source FROM blocks WHERE channel=? AND key=? AND country=? ORDER BY target_id", (channel, key, record.country))
                else:
                    sql, params = ("SELECT target_id,target_source FROM blocks WHERE channel=? AND key=? ORDER BY target_id", (channel, key))
                for rank, (target_id, source) in enumerate(con.execute(sql, params), start=1):
                    yield target_id, source, channel, rank, None
        finally:
            if owned: con.close()


class LexicalSqliteIndex:
    """Disk-backed rare-token/numeric/postal blocks with explicit DF caps.

    This is a retrieval channel, never a matching decision. Postal values are emitted
    as one soft candidate channel and are not used to filter any other channel.
    """

    def __init__(self, path: str | Path, country_partition: bool = False):
        self.path, self.country_partition = Path(path), country_partition
        self._connection: sqlite3.Connection | None = None

    def open(self) -> None:
        if self._connection is None:
            self._connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @staticmethod
    def _features(record: RecordViews) -> Iterator[tuple[str, str]]:
        yield from (("rare_name", token) for token in set(record.name_tokens) if len(token) > 1)
        yield from (("rare_address", token) for token in set(record.address_tokens) if len(token) > 1)
        yield from (("numeric_anchor", number) for number in set(record.address_numbers))
        yield from (("postal_soft", postal) for postal in set(record.postals))

    def build(self, source_paths: Iterable[str | Path], estimated_target_rows: int, disk_guard: bool = True) -> dict[str, int]:
        # The multiplier assumes 12 unique lexical features/row; it is intentionally
        # a lower bound and prevents accidental full-scale runs on small disks.
        if disk_guard: assert_disk_budget(estimated_target_rows * 900, self.path.parent)
        partial = self.path.with_suffix(self.path.suffix + ".partial")
        if partial.exists(): partial.unlink()
        con = sqlite3.connect(partial)
        try:
            con.executescript("""
                PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=FILE;
                CREATE TABLE postings(channel TEXT NOT NULL, key TEXT NOT NULL, country TEXT NOT NULL,
                    target_id TEXT NOT NULL, target_source TEXT NOT NULL,
                    UNIQUE(channel,key,country,target_id));
            """)
            counts = collections.Counter(); buffer = []
            for source_path in source_paths:
                for record in iter_records(source_path):
                    for channel, key in self._features(record):
                        buffer.append((channel, key, record.country, record.entity_id, record.source)); counts[channel] += 1
                    if len(buffer) >= 50_000:
                        con.executemany("INSERT OR IGNORE INTO postings VALUES (?,?,?,?,?)", buffer); buffer.clear()
            if buffer: con.executemany("INSERT OR IGNORE INTO postings VALUES (?,?,?,?,?)", buffer)
            con.execute("CREATE INDEX posting_lookup ON postings(channel,key,country,target_id)")
            con.commit()
        finally:
            con.close()
        os.replace(partial, self.path)
        return dict(counts)

    def query(self, record: RecordViews, rare_name_max_df: int = 50, rare_address_max_df: int = 50, numeric_max_df: int = 20, postal_max_df: int = 100, per_channel_tokens: int = 2) -> Iterator[tuple[str, str, str, int, float | None]]:
        limits = {"rare_name": rare_name_max_df, "rare_address": rare_address_max_df, "numeric_anchor": numeric_max_df, "postal_soft": postal_max_df}
        grouped: dict[str, list[str]] = collections.defaultdict(list)
        for channel, key in self._features(record): grouped[channel].append(key)
        owned = self._connection is None
        con = self._connection or sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        try:
            for channel, keys in sorted(grouped.items()):
                frequency: list[tuple[int, str]] = []
                for key in sorted(set(keys)):
                    if self.country_partition:
                        df = con.execute("SELECT COUNT(*) FROM postings WHERE channel=? AND key=? AND country=?", (channel,key,record.country)).fetchone()[0]
                    else:
                        df = con.execute("SELECT COUNT(*) FROM postings WHERE channel=? AND key=?", (channel,key)).fetchone()[0]
                    if 0 < df <= limits[channel]: frequency.append((df, key))
                for _, key in sorted(frequency)[:per_channel_tokens]:
                    if self.country_partition:
                        sql, params = ("SELECT target_id,target_source FROM postings WHERE channel=? AND key=? AND country=? ORDER BY target_id", (channel,key,record.country))
                    else:
                        sql, params = ("SELECT target_id,target_source FROM postings WHERE channel=? AND key=? ORDER BY target_id", (channel,key))
                    for rank, (target_id, source) in enumerate(con.execute(sql, params), 1): yield target_id, source, channel, rank, None
        finally:
            if owned: con.close()


class CompositeIndex:
    """Deterministic union façade for any set of independent candidate channels."""
    def __init__(self, *indexes): self.indexes = indexes
    def open(self):
        for index in self.indexes:
            if hasattr(index, "open"): index.open()
    def close(self):
        for index in self.indexes:
            if hasattr(index, "close"): index.close()
    def query(self, record: RecordViews):
        for index in self.indexes: yield from index.query(record)


def write_candidate_rows(source1_path: str | Path, index: ExactSqliteIndex, candidate_path: str | Path, provenance_path: str | Path | None = None) -> dict[str, int]:
    """Write official candidate TSV (one S1 per row) and optional rich provenance."""
    totals = collections.Counter()
    provenance_cm = atomic_text_writer(provenance_path) if provenance_path else None
    if hasattr(index, "open"): index.open()
    try:
        with atomic_text_writer(candidate_path) as out:
            out.write("source1_entity_id\tcandidate_entity_ids\n")
            if provenance_cm:
                with provenance_cm as provenance:
                    _write_rows(source1_path, index, out, totals, provenance)
            else:
                _write_rows(source1_path, index, out, totals, None)
    finally:
        if hasattr(index, "close"): index.close()
    return dict(totals)


def _write_rows(source1_path, index, out, totals, provenance):
    for s1 in iter_records(source1_path):
        union = union_candidates(index.query(s1)); ordered = [union[key] for key in sorted(union)]
        out.write(f"{s1.entity_id}\t{','.join(row.target_id for row in ordered)}\n")
        totals["s1"] += 1; totals["pairs"] += len(ordered)
        if provenance:
            for row in ordered:
                provenance.write(json.dumps({"s1_id": s1.entity_id, "target_id": row.target_id, "target_source": row.target_source, "candidate_channels": sorted(row.channels), "channel_count": len(row.channels), "retrieval_rank_by_channel": row.ranks, "retrieval_score_by_channel": row.scores, "country": s1.country}, ensure_ascii=False, sort_keys=True) + "\n")


class CharTfidfRetriever:
    """Bounded sparse character TF-IDF retrieval for a fitted partition/sample."""

    def __init__(self, field: str, ngram_range: tuple[int, int] = (2, 4), max_features: int = 300_000):
        if field not in {"name", "address", "combined"}: raise ValueError("field must be name, address, or combined")
        self.field, self.ngram_range, self.max_features = field, ngram_range, max_features

    def _text(self, row: RecordViews) -> str:
        return row.name_punct if self.field == "name" else row.address_punct if self.field == "address" else row.name_punct + " [addr] " + row.address_punct

    def fit(self, targets: list[RecordViews]) -> "CharTfidfRetriever":
        import numpy as np
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.ids, self.sources = [r.entity_id for r in targets], [r.source for r in targets]
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=self.ngram_range, max_features=self.max_features, dtype=np.float32, norm="l2")
        self.matrix = self.vectorizer.fit_transform(self._text(r) for r in targets)
        return self

    def query(self, record: RecordViews, k: int) -> Iterator[tuple[str, str, str, int, float]]:
        query = self.vectorizer.transform([self._text(record)]); scores = (query @ self.matrix.T).toarray()[0]
        top = heapq.nlargest(min(k, len(scores)), range(len(scores)), key=lambda i: (scores[i], self.ids[i]))
        for rank, i in enumerate(top, 1):
            if scores[i] > 0: yield self.ids[i], self.sources[i], f"tfidf_{self.field}", rank, float(scores[i])
