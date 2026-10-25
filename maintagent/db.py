"""Ham CSV dosyalarını tek bir DuckDB veritabanına yükler.

Her tablo önce metin olarak okunur, sonra türlerine çevrilir. Böylece
CSV'deki tarih biçimi farklı olsa bile (2015-01-01 06:00:00 ya da
1/1/2015 6:00:00 AM) yükleme bozulmaz. Sütun adları snake_case'e çevrilir.
"""

from pathlib import Path

import duckdb

# Tarihi iki yaygın biçimden biriyle çözer; ikisi de tutmazsa NULL döner.
_TS = (
    "COALESCE("
    "try_strptime(datetime, '%Y-%m-%d %H:%M:%S'), "
    "try_strptime(datetime, '%m/%d/%Y %I:%M:%S %p'))"
)

# tablo adı -> (CSV dosyası, SELECT ifadesi)
TABLES: dict[str, tuple[str, str]] = {
    "machines": (
        "PdM_machines.csv",
        "CAST(machineID AS INTEGER) AS machine_id, model, CAST(age AS INTEGER) AS age",
    ),
    "telemetry": (
        "PdM_telemetry.csv",
        f"{_TS} AS ts, CAST(machineID AS INTEGER) AS machine_id, "
        "CAST(volt AS DOUBLE) AS volt, CAST(rotate AS DOUBLE) AS rotate, "
        "CAST(pressure AS DOUBLE) AS pressure, CAST(vibration AS DOUBLE) AS vibration",
    ),
    "errors": (
        "PdM_errors.csv",
        f"{_TS} AS ts, CAST(machineID AS INTEGER) AS machine_id, errorID AS error_id",
    ),
    "maint": (
        "PdM_maint.csv",
        f"{_TS} AS ts, CAST(machineID AS INTEGER) AS machine_id, comp",
    ),
    "failures": (
        "PdM_failures.csv",
        f"{_TS} AS ts, CAST(machineID AS INTEGER) AS machine_id, failure AS comp",
    ),
}


def missing_files(raw_dir: Path) -> list[str]:
    """raw_dir içinde eksik olan CSV dosyalarının adlarını döndürür."""
    return [f for f, _ in TABLES.values() if not (raw_dir / f).exists()]


def load_all(raw_dir: Path, db_path: Path) -> duckdb.DuckDBPyConnection:
    """Tüm CSV'leri okuyup db_path'teki veritabanına yazar ve bağlantıyı döndürür."""
    missing = missing_files(raw_dir)
    if missing:
        raise FileNotFoundError(f"{raw_dir} klasöründe eksik dosyalar: {', '.join(missing)}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    for table, (filename, select) in TABLES.items():
        path = (raw_dir / filename).as_posix()
        con.execute(
            f"CREATE OR REPLACE TABLE {table} AS "
            f"SELECT {select} FROM read_csv('{path}', header=true, all_varchar=true)"
        )
        if "ts" in select:
            bad = con.execute(f"SELECT count(*) FROM {table} WHERE ts IS NULL").fetchone()[0]
            if bad:
                raise ValueError(f"{table} tablosunda tarihi okunamayan {bad} satır var")
    return con


def summarize(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Her tablo için satır sayısı, makine sayısı ve tarih aralığını döndürür."""
    rows = []
    for table, (_, select) in TABLES.items():
        has_ts = " AS ts" in select
        q = (
            f"SELECT count(*), count(DISTINCT machine_id)"
            + (", min(ts), max(ts)" if has_ts else ", NULL, NULL")
            + f" FROM {table}"
        )
        n, machines, first, last = con.execute(q).fetchone()
        rows.append({"table": table, "rows": n, "machines": machines, "first": first, "last": last})
    return rows
