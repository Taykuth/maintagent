"""Özellik üretiminin en kritik özelliği: geleceği görmemesi. Bu testler onu kontrol eder."""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maintagent.db import load_all  # noqa: E402
from maintagent.features import FEATURES, build_features, features_at  # noqa: E402
from maintagent.synthetic import write_synthetic_csvs  # noqa: E402

START, END = datetime(2015, 2, 1), datetime(2015, 4, 1)

# Örnekleme saatine (3'ün katı) denk gelen ve aralığın 2 gün içinde olan ilk arıza
FIRST_SAMPLED_FAILURE = (
    "SELECT ts, machine_id, comp FROM failures "
    "WHERE ts BETWEEN $s + INTERVAL 2 DAY AND $e - INTERVAL 2 DAY AND hour(ts) % 3 = 0 ORDER BY ts LIMIT 1"
)


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    d = tmp_path_factory.mktemp("data")
    write_synthetic_csvs(d / "raw", n_machines=6, end="2015-05-01 06:00:00")
    return load_all(d / "raw", d / "t.duckdb")


def test_one_row_per_machine_every_3_hours(con):
    df = build_features(con, START, END)
    assert set(df.machine_id) == {1, 2, 3, 4, 5, 6}
    assert (df.ts.dt.hour % 3 == 0).all()
    assert list(df.columns[: 2]) == ["ts", "machine_id"]
    assert all(f in df.columns for f in FEATURES)


def test_features_do_not_see_the_future(con):
    """Bir andan sonraki telemetriyi bozmak, o ana kadarki özellikleri değiştirmemeli."""
    cutoff = datetime(2015, 3, 1)
    before = build_features(con, START, cutoff, with_label=False)

    con.execute("CREATE TEMP TABLE backup AS SELECT * FROM telemetry")
    try:
        con.execute("UPDATE telemetry SET vibration = 9999, volt = -1 WHERE ts > $c", {"c": cutoff})
        after = build_features(con, START, cutoff, with_label=False)
    finally:
        con.execute("DELETE FROM telemetry; INSERT INTO telemetry SELECT * FROM backup; DROP TABLE backup")

    pd.testing.assert_frame_equal(before, after)


def test_label_looks_exactly_24_hours_ahead(con):
    f_ts, mid, comp = con.execute(
        FIRST_SAMPLED_FAILURE,
        {"s": START, "e": END}).fetchone()
    df = build_features(con, START, END).set_index(["machine_id", "ts"])

    def label(hours_before):
        return df.loc[(mid, f_ts - pd.Timedelta(hours=hours_before)), "label"]

    assert label(3) == comp          # arızadan 3 saat önce: pozitif
    assert label(24) == comp         # tam 24 saat önce: hâlâ pozitif
    assert label(27) == "none"       # 27 saat önce: pencerenin dışında
    assert label(0) != comp          # arıza anının kendisi "gelecek" sayılmaz


def test_days_since_replacement_resets_after_failure(con):
    f_ts, mid, comp = con.execute(
        FIRST_SAMPLED_FAILURE,
        {"s": START, "e": END}).fetchone()
    df = build_features(con, START, END, with_label=False).set_index(["machine_id", "ts"])
    assert df.loc[(mid, f_ts), f"{comp}_days"] == 0
    assert df.loc[(mid, f_ts + pd.Timedelta(hours=24)), f"{comp}_days"] == 1


def test_features_at_returns_latest_row_per_machine(con):
    df = features_at(con, datetime(2015, 3, 10, 14))
    assert len(df) == 6
    assert (df.ts == datetime(2015, 3, 10, 14)).all()
    assert "label" not in df.columns
