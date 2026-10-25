"""db.py için testler. Gerçek veri yerine birkaç satırlık sahte CSV'ler kullanır."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maintagent.db import load_all, missing_files, summarize  # noqa: E402

CSV = {
    "PdM_machines.csv": "machineID,model,age\n1,model3,18\n2,model4,7\n",
    # telemetry ISO biçiminde, errors ABD biçiminde: iki biçim de okunmalı
    "PdM_telemetry.csv": (
        "datetime,machineID,volt,rotate,pressure,vibration\n"
        "2015-01-01 06:00:00,1,176.2,418.5,113.1,45.1\n"
        "2015-01-01 07:00:00,1,162.9,402.7,95.5,43.4\n"
        "2015-01-01 06:00:00,2,170.0,450.0,100.0,40.0\n"
    ),
    "PdM_errors.csv": "datetime,machineID,errorID\n1/3/2015 7:00:00 PM,1,error1\n",
    "PdM_maint.csv": "datetime,machineID,comp\n2014-06-01 06:00:00,1,comp2\n",
    "PdM_failures.csv": "datetime,machineID,failure\n2015-01-05 06:00:00,1,comp4\n",
}


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    for name, text in CSV.items():
        (tmp_path / name).write_text(text)
    return tmp_path


def test_loads_all_tables(raw_dir, tmp_path):
    con = load_all(raw_dir, tmp_path / "test.duckdb")
    counts = {r["table"]: r["rows"] for r in summarize(con)}
    assert counts == {"machines": 2, "telemetry": 3, "errors": 1, "maint": 1, "failures": 1}


def test_parses_both_date_formats(raw_dir, tmp_path):
    con = load_all(raw_dir, tmp_path / "test.duckdb")
    err_ts = con.execute("SELECT ts FROM errors").fetchone()[0]
    assert str(err_ts) == "2015-01-03 19:00:00"
    first, last = con.execute("SELECT min(ts), max(ts) FROM telemetry WHERE machine_id = 1").fetchone()
    assert str(first) == "2015-01-01 06:00:00" and str(last) == "2015-01-01 07:00:00"


def test_renames_columns(raw_dir, tmp_path):
    con = load_all(raw_dir, tmp_path / "test.duckdb")
    cols = [c[0] for c in con.execute("DESCRIBE failures").fetchall()]
    assert cols == ["ts", "machine_id", "comp"]


def test_reports_missing_files(tmp_path):
    assert len(missing_files(tmp_path)) == 5
    with pytest.raises(FileNotFoundError):
        load_all(tmp_path, tmp_path / "test.duckdb")


def test_rejects_unreadable_dates(raw_dir, tmp_path):
    (raw_dir / "PdM_failures.csv").write_text("datetime,machineID,failure\n05.01.2015,1,comp4\n")
    with pytest.raises(ValueError):
        load_all(raw_dir, tmp_path / "test.duckdb")
