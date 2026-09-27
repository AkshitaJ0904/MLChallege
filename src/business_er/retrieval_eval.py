"""Set-based evaluation of existing retrieval indexes.

This module deliberately never calls an index ``build`` method.  It materialises
only Source-1 query features in a disposable work database, attaches read-only
completed indexes, and calculates candidate metrics from generated pairs.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import sqlite3
import statistics
import time
from pathlib import Path

from .candidates import EXACT_CHANNELS, LexicalSqliteIndex, _keys
from .normalization import country_bucket
from .tsv import atomic_text_writer, iter_ground_truth, iter_records


LEXICAL = ("rare_name", "rare_address", "numeric_anchor", "postal_soft")
BITS = {name: 1 << i for i, name in enumerate(EXACT_CHANNELS + LEXICAL)}


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=FILE; PRAGMA cache_size=-262144;")
    return con


def populate_queries(con: sqlite3.Connection, source1: str, truth_path: str | None) -> None:
    con.executescript("""
      CREATE TABLE s1(ord INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, country TEXT NOT NULL);
      CREATE TABLE feat(ord INTEGER NOT NULL, channel TEXT NOT NULL, key TEXT NOT NULL,
                        UNIQUE(ord,channel,key));
      CREATE INDEX feat_lookup ON feat(channel,key,ord);
    """)
    s_rows: list[tuple[int, str, str]] = []
    f_rows: list[tuple[int, str, str]] = []
    for ordinal, row in enumerate(iter_records(source1)):
        s_rows.append((ordinal, row.entity_id, row.country))
        f_rows.extend((ordinal, channel, key) for channel, key in _keys(row).items() if key)
        f_rows.extend((ordinal, channel, key) for channel, key in LexicalSqliteIndex._features(row))
        if len(s_rows) >= 20_000:
            con.executemany("INSERT INTO s1 VALUES (?,?,?)", s_rows); s_rows.clear()
            con.executemany("INSERT OR IGNORE INTO feat VALUES (?,?,?)", f_rows); f_rows.clear()
    if s_rows: con.executemany("INSERT INTO s1 VALUES (?,?,?)", s_rows)
    if f_rows: con.executemany("INSERT OR IGNORE INTO feat VALUES (?,?,?)", f_rows)
    if truth_path:
        con.executescript("CREATE TABLE truth(ord INTEGER NOT NULL, target TEXT NOT NULL, source TEXT NOT NULL, PRIMARY KEY(ord,target)); CREATE INDEX truth_target ON truth(ord,target);")
        rows: list[tuple[int, str, str]] = []
        ids = {row[0]: row[1] for row in con.execute("SELECT id,ord FROM s1")}
        for gt in iter_ground_truth(truth_path):
            ordinal = ids.get(gt.s1_id)
            if ordinal is None: raise ValueError(f"truth S1 not present: {gt.s1_id}")
            rows.extend((ordinal, target, target[:2]) for target in gt.target_ids)
            if len(rows) >= 50_000:
                con.executemany("INSERT INTO truth VALUES (?,?,?)", rows); rows.clear()
        if rows: con.executemany("INSERT INTO truth VALUES (?,?,?)", rows)
    con.commit()


def build_event_tables(con: sqlite3.Connection, exact_index: str, lexical_index: str, country_partition: bool, configs: dict[str, dict]) -> None:
    con.execute("ATTACH DATABASE ? AS exactdb", (str(Path(exact_index).resolve()),))
    con.execute("ATTACH DATABASE ? AS lexdb", (str(Path(lexical_index).resolve()),))
    country = " AND b.country=s.country" if country_partition else ""
    con.executescript("CREATE TABLE exact_event(ord INTEGER NOT NULL, target TEXT NOT NULL, channel TEXT NOT NULL); CREATE INDEX exact_event_idx ON exact_event(channel,ord,target);")
    for channel in EXACT_CHANNELS:
        con.execute(f"""INSERT INTO exact_event
          SELECT f.ord,b.target_id,? FROM feat f JOIN s1 s ON s.ord=f.ord
          JOIN exactdb.blocks b ON b.channel=f.channel AND b.key=f.key{country}
          WHERE f.channel=?""", (channel, channel))
    con.commit()
    # Candidate feature DF is measured against the existing lexical index.  A
    # distinct feature table prevents a common feature repeated in Source-1 from
    # causing repeated index counts.
    con.executescript("CREATE TABLE lexical_df(channel TEXT NOT NULL,key TEXT NOT NULL,df INTEGER NOT NULL,PRIMARY KEY(channel,key));")
    con.execute("""INSERT INTO lexical_df
      SELECT q.channel,q.key,COUNT(p.target_id)
      FROM (SELECT DISTINCT channel,key FROM feat WHERE channel IN ('rare_name','rare_address','numeric_anchor','postal_soft')) q
      JOIN lexdb.postings p ON p.channel=q.channel AND p.key=q.key
      GROUP BY q.channel,q.key""")
    con.commit()
    for label, cfg in configs.items():
        limits = cfg["limits"]; per = cfg["per_channel_tokens"]
        con.executescript(f"CREATE TABLE lex_selected_{label}(ord INTEGER NOT NULL,channel TEXT NOT NULL,key TEXT NOT NULL,PRIMARY KEY(ord,channel,key)); CREATE TABLE lex_event_{label}(ord INTEGER NOT NULL,target TEXT NOT NULL,channel TEXT NOT NULL); CREATE INDEX lex_event_{label}_idx ON lex_event_{label}(channel,ord,target);")
        allowed = " OR ".join("(f.channel='%s' AND d.df<=%d)" % (ch, limits[ch]) for ch in LEXICAL)
        con.execute(f"""INSERT INTO lex_selected_{label}
          SELECT ord,channel,key FROM (
            SELECT f.ord,f.channel,f.key,d.df,
                   ROW_NUMBER() OVER (PARTITION BY f.ord,f.channel ORDER BY d.df,f.key) AS rn
            FROM feat f JOIN lexical_df d ON d.channel=f.channel AND d.key=f.key
            WHERE {allowed}
          ) WHERE rn<=?""", (per,))
        country2 = " AND p.country=s.country" if country_partition else ""
        con.execute(f"""INSERT INTO lex_event_{label}
          SELECT q.ord,p.target_id,q.channel FROM lex_selected_{label} q
          JOIN s1 s ON s.ord=q.ord
          JOIN lexdb.postings p ON p.channel=q.channel AND p.key=q.key{country2}""")
        con.commit()


def _make_candidate(con: sqlite3.Connection, config: dict) -> None:
    con.execute("DROP TABLE IF EXISTS current")
    selects = []
    exact = config.get("exact", ())
    lexical = config.get("lexical", ())
    if exact:
        quoted = ",".join("?" for _ in exact)
        con.execute(f"CREATE TABLE current AS SELECT DISTINCT ord,target FROM exact_event WHERE channel IN ({quoted})", exact)
    else:
        con.execute("CREATE TABLE current(ord INTEGER NOT NULL,target TEXT NOT NULL)")
    if lexical:
        label, channels = lexical
        quoted = ",".join("?" for _ in channels)
        con.execute(f"INSERT OR IGNORE INTO current SELECT DISTINCT ord,target FROM lex_event_{label} WHERE channel IN ({quoted})", channels)
        # CREATE TABLE AS has no uniqueness guarantee; remove inter-channel and
        # exact/lexical duplicates deterministically.
        con.execute("CREATE TABLE dedup AS SELECT DISTINCT ord,target FROM current")
        con.execute("DROP TABLE current"); con.execute("ALTER TABLE dedup RENAME TO current")
    con.execute("CREATE INDEX current_idx ON current(ord,target)")


def _rate(n: int, d: int) -> float | None:
    return n / d if d else None


def score_current(con: sqlite3.Connection) -> dict:
    total = con.execute("SELECT COUNT(*) FROM truth").fetchone()[0]
    hits = con.execute("SELECT COUNT(*) FROM truth t JOIN current c ON c.ord=t.ord AND c.target=t.target").fetchone()[0]
    by_source = {src: [int(n), int(h)] for src, n, h in con.execute("SELECT source,COUNT(*),SUM(EXISTS(SELECT 1 FROM current c WHERE c.ord=t.ord AND c.target=t.target)) FROM truth t GROUP BY source")}
    by_country = {country_bucket(c): [int(n), int(h)] for c, n, h in con.execute("SELECT s.country,COUNT(*),SUM(EXISTS(SELECT 1 FROM current c WHERE c.ord=t.ord AND c.target=t.target)) FROM truth t JOIN s1 s ON s.ord=t.ord GROUP BY s.country")}
    by_card = {str(card): [int(n), int(h)] for card, n, h in con.execute("""
      WITH card AS (SELECT ord,COUNT(*) n FROM truth GROUP BY ord)
      SELECT CASE WHEN card.n>=6 THEN '6+' ELSE CAST(card.n AS TEXT) END,
             COUNT(t.target),SUM(EXISTS(SELECT 1 FROM current c WHERE c.ord=t.ord AND c.target=t.target))
      FROM truth t JOIN card ON card.ord=t.ord GROUP BY 1""")}
    hist = collections.Counter(); s1_count = 0; zeros = 0; singleton_candidate_rows = 0
    no_truth = no_truth_with_candidates = truth_singletons = truth_singleton_hits = 0
    for count, truth_count, truth_hits in con.execute("""
      SELECT COUNT(c.target),COALESCE(t.n,0),COALESCE(t.h,0)
      FROM s1 s LEFT JOIN current c ON c.ord=s.ord
      LEFT JOIN (SELECT t.ord,COUNT(*) n,SUM(EXISTS(SELECT 1 FROM current c2 WHERE c2.ord=t.ord AND c2.target=t.target)) h FROM truth t GROUP BY t.ord) t ON t.ord=s.ord
      GROUP BY s.ord"""):
        count = int(count); truth_count = int(truth_count); truth_hits = int(truth_hits)
        hist[count] += 1; s1_count += 1; zeros += count == 0; singleton_candidate_rows += count == 1
        if truth_count == 0:
            no_truth += 1; no_truth_with_candidates += count > 0
        if truth_count == 1:
            truth_singletons += 1; truth_singleton_hits += truth_hits
    def q(frac: float) -> int:
        threshold = round((s1_count - 1) * frac); seen = 0
        for value in sorted(hist):
            seen += hist[value]
            if seen > threshold: return value
        return max(hist, default=0)
    count_total = sum(v * n for v, n in hist.items())
    return {
      "true_targets": total, "recovered_targets": hits, "missed_targets": total-hits, "target_recall": _rate(hits,total),
      "candidate_count": count_total, "mean_candidates_per_s1": count_total/s1_count, "p50": q(.5), "p95": q(.95), "p99": q(.99), "max": max(hist, default=0),
      "source_recall": {k:_rate(v[1],v[0]) for k,v in by_source.items()}, "country_recall": {k:_rate(v[1],v[0]) for k,v in by_country.items()}, "cardinality_recall": {k:_rate(v[1],v[0]) for k,v in by_card.items()},
      "candidate_zero_s1_rows": zeros, "candidate_singleton_s1_rows": singleton_candidate_rows,
      "ground_truth_zero_s1_rows": no_truth, "ground_truth_zero_s1_with_candidates": no_truth_with_candidates,
      "ground_truth_singleton_s1_rows": truth_singletons, "ground_truth_singleton_target_recall": _rate(truth_singleton_hits,truth_singletons),
    }


def write_current(con: sqlite3.Connection, path: str) -> None:
    with atomic_text_writer(path) as out:
        out.write("source1_entity_id\tcandidate_entity_ids\n")
        cursor = con.execute("SELECT s.id,c.target FROM s1 s LEFT JOIN current c ON c.ord=s.ord ORDER BY s.ord,c.target")
        previous = None; values: list[str] = []
        for s1_id, target in cursor:
            if previous is not None and s1_id != previous:
                out.write(previous + "\t" + ",".join(values) + "\n"); values = []
            previous = s1_id
            if target is not None: values.append(target)
        if previous is not None: out.write(previous + "\t" + ",".join(values) + "\n")


def run_train(args: argparse.Namespace) -> None:
    start = time.monotonic(); work = Path(args.work)
    if work.exists(): raise RuntimeError(f"refusing to overwrite existing work database: {work}")
    con = _connect(work)
    configs = {
      "default": {"limits":{"rare_name":50,"rare_address":50,"numeric_anchor":20,"postal_soft":100}, "per_channel_tokens":2},
      "constrained": {"limits":{"rare_name":20,"rare_address":20,"numeric_anchor":10,"postal_soft":50}, "per_channel_tokens":1},
    }
    try:
      populate_queries(con,args.source1,args.ground_truth)
      build_event_tables(con,args.exact_index,args.lexical_index,args.country_partition,configs)
      experiment = {
       "exact_name":{"exact":["exact_name"]}, "exact_address":{"exact":["exact_address"]}, "exact_name_address":{"exact":["exact_name_address"]}, "exact_union":{"exact":list(EXACT_CHANNELS)},
       "rare_name":{"lexical":["default",["rare_name"]]}, "rare_address":{"lexical":["default",["rare_address"]]}, "numeric_address_anchor":{"lexical":["default",["numeric_anchor"]]}, "postal":{"lexical":["default",["postal_soft"]]},
       "lexical_default":{"lexical":["default",list(LEXICAL)]}, "exact_plus_lexical_default":{"exact":list(EXACT_CHANNELS),"lexical":["default",list(LEXICAL)]},
       "lexical_constrained":{"lexical":["constrained",list(LEXICAL)]}, "exact_plus_lexical_constrained":{"exact":list(EXACT_CHANNELS),"lexical":["constrained",list(LEXICAL)]},
      }
      results = {}
      exact_recovered = None
      for name, cfg in experiment.items():
        phase = time.monotonic(); _make_candidate(con,cfg); result=score_current(con); result["runtime_seconds"] = time.monotonic()-phase
        if name == "exact_union": exact_recovered=result["recovered_targets"]
        if exact_recovered is not None: result["incremental_targets_over_exact_union"] = result["recovered_targets"]-exact_recovered; result["incremental_recall_over_exact_union"] = (result["recovered_targets"]-exact_recovered)/result["true_targets"]
        results[name]=result
      # Selection is explicit and data-driven: the full caps are retained only
      # when their candidate volume is no more than 3x the constrained union.
      full, constrained = results["exact_plus_lexical_default"], results["exact_plus_lexical_constrained"]
      final = "exact_plus_lexical_default" if full["candidate_count"] <= 3*constrained["candidate_count"] else "exact_plus_lexical_constrained"
      _make_candidate(con,experiment[final]); write_current(con,args.final_train_candidates)
      results[final]["final_train_candidate_path"] = args.final_train_candidates
      report={"stage":"train_retrieval_evaluation","indexes_read_only":{"exact":args.exact_index,"lexical":args.lexical_index},"lexical_configurations":configs,"results":results,"final_configuration":final,"selection_rule":"retain default lexical caps only if its exact+lexical candidate count is <=3x the constrained exact+lexical count; otherwise use constrained", "character_tfidf":"not evaluated: no fitted full-corpus character index is represented by train_lexical.sqlite; building one would be a new index build and was not performed", "runtime_seconds":time.monotonic()-start}
      with atomic_text_writer(args.report) as out: json.dump(report,out,indent=2,ensure_ascii=False,sort_keys=True)
    finally: con.close()


def main() -> None:
    p=argparse.ArgumentParser(); s=p.add_subparsers(dest="cmd",required=True)
    x=s.add_parser("train"); x.add_argument("--source1",required=True); x.add_argument("--ground-truth",required=True); x.add_argument("--exact-index",required=True); x.add_argument("--lexical-index",required=True); x.add_argument("--work",required=True); x.add_argument("--report",required=True); x.add_argument("--final-train-candidates",required=True); x.add_argument("--country-partition",action="store_true"); x.set_defaults(func=run_train)
    args=p.parse_args(); args.func(args)


if __name__ == "__main__": main()
