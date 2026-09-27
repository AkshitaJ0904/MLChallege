from business_er.candidates import union_candidates
from business_er.candidates import CharTfidfRetriever, ExactSqliteIndex, write_candidate_rows
from business_er.folds import FoldConfig, fold_for
from business_er.metrics import f_beta_set, macro_f_beta
from business_er.normalization import country_bucket, make_views, postal_like


def test_unicode_and_punctuation_views_preserve_raw():
    row = make_views("S2-1", "Caf\u00e9 & Sons", "१२ Main-Rd, Delhi 110001", "India")
    assert row.business_name == "Caf\u00e9 & Sons"
    assert "caf\u00e9" in row.name_tokens and "sons" in row.name_tokens
    assert "110001" in row.address_numbers and row.postals == ("110001",)


def test_country_is_open_set_and_postal_is_country_aware():
    assert country_bucket("France") == "France" and country_bucket("Kenya") == "Other/unknown"
    assert postal_like("Paris 75001", "France") == ("75001",) and postal_like("Paris 75001", "Kenya") == ()


def test_official_empty_and_multilabel_metric_cases():
    assert f_beta_set([], []) == 1 and f_beta_set([], ["S2-1"]) == 0 and f_beta_set(["S2-1"], []) == 0
    assert f_beta_set(["S2-1"], ["S2-1", "S2-1"]) == 1
    assert f_beta_set(["S2-1", "S3-1"], ["S2-1"]) == 5 / 6
    assert macro_f_beta({"a": [], "b": ["S2-1"]}, {"a": [], "b": ["S2-1"]}) == 1


def test_fold_is_stable_s1_grouped():
    config = FoldConfig()
    assert fold_for("S1-1", "India", ["S2-2"], config) == fold_for("S1-1", "India", ["S2-2"], config)


def test_candidate_union_deduplicates_and_keeps_provenance():
    union = union_candidates([("S2-1", "S2", "exact_name", 1, None), ("S2-1", "S2", "tfidf_name", 2, .9)])
    assert set(union) == {"S2-1"} and union["S2-1"].channels == {"exact_name", "tfidf_name"}
    assert union["S2-1"].ranks["tfidf_name"] == 2


def test_exact_index_writes_official_candidate_schema_and_provenance(tmp_path):
    targets = tmp_path / "targets.tsv"; source1 = tmp_path / "source1.tsv"
    targets.write_text("entity_id\tbusiness_name\tbusiness_address\tcountry\nS2-1\tCafé & Sons\t12 Main Rd\tIndia\nS3-1\tOther\t12 Main Rd\tIndia\n", encoding="utf-8")
    source1.write_text("entity_id\tbusiness_name\tbusiness_address\tcountry\nS1-1\tCafé and Sons\t12 Main Rd\tIndia\nS1-2\tMissing\tNo Address\tFrance\n", encoding="utf-8")
    index = ExactSqliteIndex(tmp_path / "blocks.sqlite"); index.build([targets], 2, disk_guard=False)
    candidates, provenance = tmp_path / "candidate_pairs.tsv", tmp_path / "provenance.jsonl"
    stats = write_candidate_rows(source1, index, candidates, provenance)
    assert candidates.read_text(encoding="utf-8").splitlines() == ["source1_entity_id\tcandidate_entity_ids", "S1-1\tS2-1,S3-1", "S1-2\t"]
    assert stats == {"s1": 2, "pairs": 2} and '"candidate_channels"' in provenance.read_text(encoding="utf-8")


def test_sparse_tfidf_retrieval_is_ranked_and_non_dense_contract():
    target = make_views("S2-1", "Baker Street Café", "12 Baker Street", "France")
    distractor = make_views("S3-1", "Book Store", "99 River Road", "France")
    result = list(CharTfidfRetriever("name", (2, 3)).fit([target, distractor]).query(target, 2))
    assert result[0][0] == "S2-1" and result[0][2] == "tfidf_name"
