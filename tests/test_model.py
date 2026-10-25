"""Model hattının uçtan uca çalıştığını sentetik veriyle kontrol eder."""

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maintagent.db import load_all  # noqa: E402
from maintagent.features import FEATURES, build_features  # noqa: E402
from maintagent.model import evaluate, load, predict, save, top_factors, train  # noqa: E402
from maintagent.synthetic import write_synthetic_csvs  # noqa: E402


@pytest.fixture(scope="module")
def split(tmp_path_factory):
    d = tmp_path_factory.mktemp("data")
    write_synthetic_csvs(d / "raw", n_machines=12, seed=1)
    con = load_all(d / "raw", d / "t.duckdb")
    return (build_features(con, datetime(2015, 1, 2), datetime(2015, 8, 1)),
            build_features(con, datetime(2015, 8, 2), datetime(2015, 12, 31)))


def test_model_beats_rule_on_synthetic_data(split):
    train_df, test_df = split
    m = evaluate(train(train_df), train_df, test_df)
    assert m["pr_auc_model"] > m["pr_auc_rule_baseline"]
    assert m["pr_auc_model"] > 0.5


def test_saved_model_gives_same_predictions(split, tmp_path):
    train_df, test_df = split
    model = train(train_df)
    save(model, {"features": FEATURES}, tmp_path)
    a = predict(model, test_df.head(50))
    b = predict(load(tmp_path), test_df.head(50))
    assert (a.risk - b.risk).abs().max() < 1e-9


def test_top_factors_are_real_features(split):
    train_df, test_df = split
    factors = top_factors(train(train_df), test_df.head(1), "comp4")
    assert len(factors) == 3
    assert all(f["feature"] in FEATURES for f in factors)
