"""Candidate recall and volume scorecards on labelled training data."""

from __future__ import annotations
import collections
import statistics
from collections.abc import Iterable, Mapping
from .tsv import GroundTruth


class VolumeHistogram:
    """Exact integer quantiles without retaining a candidate row per S1."""
    def __init__(self): self.counts = collections.Counter(); self.total = self.sum = 0; self.maximum = 0
    def add(self, value: int) -> None:
        self.counts[value] += 1; self.total += 1; self.sum += value; self.maximum = max(self.maximum, value)
    def quantile(self, q: float) -> int:
        if not self.total: return 0
        threshold = round((self.total - 1) * q)
        running = 0
        for value in sorted(self.counts):
            running += self.counts[value]
            if running > threshold: return value
        return self.maximum
    def summary(self) -> dict[str, float | int]:
        return {"candidate_count": self.sum, "mean_candidates_per_s1": self.sum / self.total if self.total else 0, "p50": self.quantile(.5), "p95": self.quantile(.95), "p99": self.quantile(.99), "max": self.maximum}


def _quantile(values: list[int], q: float) -> int:
    return sorted(values)[round((len(values) - 1) * q)] if values else 0


def candidate_scorecard(ground_truth: Iterable[GroundTruth], candidates: Mapping[str, set[str]], source1_country: Mapping[str, str] | None = None) -> dict:
    gt = list(ground_truth); true_total = recovered = 0; source = collections.Counter(); source_hit = collections.Counter(); cardinality = collections.Counter(); cardinality_hit = collections.Counter(); country = collections.Counter(); country_hit = collections.Counter(); volumes: list[int] = []
    for row in gt:
        cand, truth = candidates.get(row.s1_id, set()), set(row.target_ids); volumes.append(len(cand)); true_total += len(truth); recovered += len(cand & truth)
        card = "6+" if len(truth) >= 6 else str(len(truth)); cardinality[card] += len(truth); cardinality_hit[card] += len(cand & truth)
        bucket = source1_country.get(row.s1_id, "unknown") if source1_country else "all"; country[bucket] += len(truth); country_hit[bucket] += len(cand & truth)
        for target in truth: source[target[:2]] += 1; source_hit[target[:2]] += target in cand
    rate = lambda hits, totals: {key: (hits[key] / n if n else None) for key, n in totals.items()}
    return {"target_recall": recovered / true_total if true_total else None, "true_targets": true_total, "recovered_targets": recovered, "candidate_count": sum(volumes), "mean_candidates_per_s1": statistics.fmean(volumes) if volumes else 0, "p50": _quantile(volumes, .5), "p95": _quantile(volumes, .95), "p99": _quantile(volumes, .99), "max": max(volumes, default=0), "source_recall": rate(source_hit, source), "cardinality_recall": rate(cardinality_hit, cardinality), "country_recall": rate(country_hit, country)}
