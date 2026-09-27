"""CLI entry points for audited, resumable candidate-generation stages."""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import sqlite3
import sys
from pathlib import Path

from .candidates import CompositeIndex, ExactSqliteIndex, LexicalSqliteIndex, _keys, write_candidate_rows
from .diagnostics import VolumeHistogram, candidate_scorecard
from .folds import FoldConfig, fold_for
from .tsv import atomic_text_writer, iter_ground_truth, iter_records, sha256_file


def _write_json(path: str, payload: dict) -> None:
    with atomic_text_writer(path) as out: json.dump(payload, out, ensure_ascii=False, indent=2, sort_keys=True)


def environment_report(args: argparse.Namespace) -> None:
    import shutil
    report = {"python": sys.version, "platform": platform.platform(), "logical_cpus": os.cpu_count(), "disk": shutil.disk_usage(args.workspace)._asdict(), "packages": {}}
    try:
        import psutil
        report["memory"] = psutil.virtual_memory()._asdict(); report["physical_cpus"] = psutil.cpu_count(logical=False)
    except ImportError: report["memory"] = "psutil unavailable"
    for name in ["numpy", "pandas", "scipy", "sklearn", "duckdb", "polars", "pyarrow"]:
        try: report["packages"][name] = __import__(name).__version__
        except ImportError: report["packages"][name] = None
    with atomic_text_writer(args.output) as out:
        out.write("# Environment report\n\n## FACT\n\n```json\n" + json.dumps(report, indent=2) + "\n```\n\nThis report is generated at runtime; resource guards use current free disk rather than these values.\n")


def make_folds(args: argparse.Namespace) -> None:
    config = FoldConfig(args.folds, args.seed)
    lookup = Path(args.output).with_suffix(".country_lookup.sqlite")
    if lookup.exists(): lookup.unlink()
    con = sqlite3.connect(lookup)
    try:
        con.execute("CREATE TABLE countries(id TEXT PRIMARY KEY, country TEXT NOT NULL)")
        buffer = []
        for row in iter_records(args.source1):
            buffer.append((row.entity_id, row.country))
            if len(buffer) >= 50_000: con.executemany("INSERT INTO countries VALUES (?,?)", buffer); buffer.clear()
        if buffer: con.executemany("INSERT INTO countries VALUES (?,?)", buffer)
        con.commit()
        with atomic_text_writer(args.output) as out:
            out.write("source1_entity_id\tfold\tcountry\tcardinality\tcomposition\tfold_config_hash\n")
            for gt in iter_ground_truth(args.ground_truth):
                country_row = con.execute("SELECT country FROM countries WHERE id=?", (gt.s1_id,)).fetchone()
                if country_row is None: raise ValueError(f"GT S1 missing from source1: {gt.s1_id}")
                country, ids = country_row[0], gt.target_ids
                composition = ("S2" if any(x.startswith("S2-") for x in ids) else "") + ("S3" if any(x.startswith("S3-") for x in ids) else "") or "none"
                out.write(f"{gt.s1_id}\t{fold_for(gt.s1_id, country, ids, config)}\t{country}\t{len(ids)}\t{composition}\t{config.fingerprint()}\n")
    finally:
        con.close()
        if lookup.exists(): lookup.unlink()


def build_exact(args: argparse.Namespace) -> None:
    index = ExactSqliteIndex(args.index, args.country_partition)
    stats = index.build(args.targets, args.estimated_target_rows, disk_guard=not args.skip_disk_guard)
    _write_json(args.manifest, {"stage": "exact_index", "index": str(args.index), "target_paths": list(map(str, args.targets)), "channels": stats, "country_partition": args.country_partition, "input_sha256": {str(path): sha256_file(path) for path in args.targets}})


def generate_exact(args: argparse.Namespace) -> None:
    indexes = [ExactSqliteIndex(args.index, args.country_partition)] if args.index else []
    if args.lexical_index: indexes.append(LexicalSqliteIndex(args.lexical_index, args.country_partition))
    if not indexes: raise ValueError("provide --index and/or --lexical-index")
    stats = write_candidate_rows(args.source1, CompositeIndex(*indexes), args.output, args.provenance)
    _write_json(args.manifest, {"stage": "candidate_generation", "candidate_path": args.output, "provenance_path": args.provenance, "stats": stats, "exact_index": args.index, "lexical_index": args.lexical_index, "source1_sha256": sha256_file(args.source1)})


def generate_exact_bulk(args: argparse.Namespace) -> None:
    """Set-based exact join; avoids millions of Python/SQLite point queries."""
    work = Path(args.output).with_suffix(".bulk.sqlite")
    if work.exists(): work.unlink()
    con = sqlite3.connect(work)
    try:
        con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=FILE; CREATE TABLE q(ord INTEGER, s1 TEXT, channel TEXT, key TEXT, country TEXT);")
        buffer = []
        for ordinal, row in enumerate(iter_records(args.source1)):
            buffer.extend((ordinal, row.entity_id, channel, key, row.country) for channel, key in _keys(row).items() if key)
            if len(buffer) >= 50_000: con.executemany("INSERT INTO q VALUES (?,?,?,?,?)", buffer); buffer.clear()
        if buffer: con.executemany("INSERT INTO q VALUES (?,?,?,?,?)", buffer)
        con.commit()
        con.execute("ATTACH DATABASE ? AS targetdb", (str(Path(args.index).resolve()),))
        on = "b.channel=q.channel AND b.key=q.key AND b.country=q.country" if args.country_partition else "b.channel=q.channel AND b.key=q.key"
        query = f"SELECT q.ord,q.s1,b.target_id FROM q JOIN targetdb.blocks b ON {on} GROUP BY q.ord,q.s1,b.target_id ORDER BY q.ord,b.target_id"
        partial = Path(args.output).with_suffix(Path(args.output).suffix + ".partial")
        with open(partial, "w", encoding="utf-8", newline="") as out:
            out.write("source1_entity_id\tcandidate_entity_ids\n")
            cursor = con.execute(query); pending = cursor.fetchone(); pairs = 0; s1_count = 0
            for ordinal, row in enumerate(iter_records(args.source1)):
                ids = []
                while pending is not None and pending[0] == ordinal:
                    ids.append(pending[2]); pending = cursor.fetchone()
                out.write(f"{row.entity_id}\t{','.join(ids)}\n"); pairs += len(ids); s1_count += 1
        os.replace(partial, args.output)
        _write_json(args.manifest, {"stage": "bulk_exact_candidate_generation", "exact_index": args.index, "country_partition": args.country_partition, "candidate_path": args.output, "stats": {"s1": s1_count, "pairs": pairs}, "source1_sha256": sha256_file(args.source1)})
    finally:
        con.close()
        if work.exists(): work.unlink()


def build_lexical(args: argparse.Namespace) -> None:
    index = LexicalSqliteIndex(args.index, args.country_partition)
    stats = index.build(args.targets, args.estimated_target_rows, disk_guard=not args.skip_disk_guard)
    _write_json(args.manifest, {"stage": "lexical_index", "index": str(args.index), "channels": stats, "country_partition": args.country_partition, "input_sha256": {str(path): sha256_file(path) for path in args.targets}})


def score_candidates(args: argparse.Namespace) -> None:
    """Streaming scorecard; only one S1's GT set is materialised at a time."""
    database = Path(args.output).with_suffix(".score.sqlite")
    if database.exists(): database.unlink()
    con = sqlite3.connect(database)
    try:
        con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; CREATE TABLE country(s1 TEXT PRIMARY KEY, country TEXT); CREATE TABLE truth(s1 TEXT, target TEXT, source TEXT); CREATE INDEX truth_s1 ON truth(s1);")
        buf = []
        for row in iter_records(args.source1):
            buf.append((row.entity_id, row.country))
            if len(buf) >= 50_000: con.executemany("INSERT INTO country VALUES (?,?)", buf); buf.clear()
        if buf: con.executemany("INSERT INTO country VALUES (?,?)", buf)
        buf = []
        for row in iter_ground_truth(args.ground_truth):
            buf.extend((row.s1_id, target, target[:2]) for target in row.target_ids)
            if len(buf) >= 50_000: con.executemany("INSERT INTO truth VALUES (?,?,?)", buf); buf.clear()
        if buf: con.executemany("INSERT INTO truth VALUES (?,?,?)", buf)
        con.commit()
        hist = VolumeHistogram(); totals = {"all": 0}; hits = {"all": 0}; by_source = {}; by_country = {}; by_cardinality = {}; rows = 0; empty_s1 = 0
        def add(group, key, total, hit):
            group.setdefault(key, [0, 0]); group[key][0] += total; group[key][1] += hit
        with open(args.candidates, encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if reader.fieldnames != ["source1_entity_id", "candidate_entity_ids"]: raise ValueError("candidate TSV schema is invalid")
            for record in reader:
                rows += 1; candidate_ids = set(filter(None, record["candidate_entity_ids"].split(","))); hist.add(len(candidate_ids))
                truth = con.execute("SELECT target,source FROM truth WHERE s1=?", (record["source1_entity_id"],)).fetchall()
                country_row = con.execute("SELECT country FROM country WHERE s1=?", (record["source1_entity_id"],)).fetchone()
                if country_row is None: raise ValueError(f"candidate S1 not found in training source1: {record['source1_entity_id']}")
                if not truth: empty_s1 += 1
                total, hit = len(truth), sum(target in candidate_ids for target, _ in truth)
                totals["all"] += total; hits["all"] += hit
                card = "6+" if total >= 6 else str(total); add(by_cardinality, card, total, hit); add(by_country, country_row[0], total, hit)
                for target, source in truth: add(by_source, source, 1, int(target in candidate_ids))
        rate = lambda values: {key: (hit / total if total else None) for key, (total, hit) in values.items()}
        result = {"target_recall": hits["all"] / totals["all"] if totals["all"] else None, "true_targets": totals["all"], "recovered_targets": hits["all"], "scored_s1_rows": rows, "no_match_s1_rows": empty_s1, **hist.summary(), "source_recall": rate(by_source), "country_recall": rate(by_country), "cardinality_recall": rate(by_cardinality)}
        _write_json(args.output, result)
    finally:
        con.close()
        if database.exists(): database.unlink()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="business-er"); subs = p.add_subparsers(dest="command", required=True)
    x = subs.add_parser("environment-report"); x.add_argument("--workspace", default="."); x.add_argument("--output", required=True); x.set_defaults(func=environment_report)
    x = subs.add_parser("make-folds"); x.add_argument("--source1", required=True); x.add_argument("--ground-truth", required=True); x.add_argument("--output", required=True); x.add_argument("--folds", type=int, default=5); x.add_argument("--seed", type=int, default=20260926); x.set_defaults(func=make_folds)
    x = subs.add_parser("build-exact-index"); x.add_argument("--targets", nargs="+", required=True); x.add_argument("--index", required=True); x.add_argument("--manifest", required=True); x.add_argument("--estimated-target-rows", type=int, required=True); x.add_argument("--country-partition", action="store_true"); x.add_argument("--skip-disk-guard", action="store_true"); x.set_defaults(func=build_exact)
    x = subs.add_parser("build-lexical-index"); x.add_argument("--targets", nargs="+", required=True); x.add_argument("--index", required=True); x.add_argument("--manifest", required=True); x.add_argument("--estimated-target-rows", type=int, required=True); x.add_argument("--country-partition", action="store_true"); x.add_argument("--skip-disk-guard", action="store_true"); x.set_defaults(func=build_lexical)
    x = subs.add_parser("generate-exact-bulk"); x.add_argument("--source1", required=True); x.add_argument("--index", required=True); x.add_argument("--output", required=True); x.add_argument("--manifest", required=True); x.add_argument("--country-partition", action="store_true"); x.set_defaults(func=generate_exact_bulk)
    x = subs.add_parser("generate-exact"); x.add_argument("--source1", required=True); x.add_argument("--index"); x.add_argument("--lexical-index"); x.add_argument("--output", required=True); x.add_argument("--provenance"); x.add_argument("--manifest", required=True); x.add_argument("--country-partition", action="store_true"); x.set_defaults(func=generate_exact)
    x = subs.add_parser("score-candidates"); x.add_argument("--source1", required=True); x.add_argument("--ground-truth", required=True); x.add_argument("--candidates", required=True); x.add_argument("--output", required=True); x.set_defaults(func=score_candidates)
    return p


def main() -> None:
    args = parser().parse_args(); args.func(args)


if __name__ == "__main__": main()
