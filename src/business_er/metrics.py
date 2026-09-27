"""Official S1-set metric, intentionally independent of pairwise scoring."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def f_beta_set(truth: Iterable[str], prediction: Iterable[str], beta: float = 0.5) -> float:
    gt, pred = set(truth), set(prediction)
    if not gt:
        return 1.0 if not pred else 0.0
    if not pred:
        return 0.0
    intersection = len(gt & pred)
    precision, recall = intersection / len(pred), intersection / len(gt)
    beta_sq = beta * beta
    denominator = beta_sq * precision + recall
    return 0.0 if denominator == 0 else (1 + beta_sq) * precision * recall / denominator


def macro_f_beta(truth_by_s1: Mapping[str, Iterable[str]], predictions_by_s1: Mapping[str, Iterable[str]], beta: float = 0.5) -> float:
    if not truth_by_s1:
        raise ValueError("Macro metric requires at least one S1 record")
    return sum(f_beta_set(truth, predictions_by_s1.get(s1, ()), beta) for s1, truth in truth_by_s1.items()) / len(truth_by_s1)
