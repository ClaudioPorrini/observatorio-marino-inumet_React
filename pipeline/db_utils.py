from __future__ import annotations
import os
import sqlite3
from pathlib import Path
import pandas as pd

# Ruta anclada a la ubicación de este archivo (no al directorio desde el que
# se ejecuta): evita crear una base vacía por correr desde otra carpeta.
# Se puede forzar otra con la variable de entorno OBSERVATORIO_DB.
_PROYECTO = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("OBSERVATORIO_DB", _PROYECTO / "data" / "observatorio_marino.db"))

# Instituciones: "authorized" = 1 solo si hay convenio para publicar sus datos.
# Default seguro: 0 (no se exporta). Se cambia a mano al firmarse el convenio.
SEED_INSTITUTIONS = [
    # (institution, authorized)
    ("InUMet", 1),
    ("Intendencia de Montevideo", 0),
    ("ANP", 0),
    ("ICO / Udelar", 0),
    ("SOHMA / Armada", 0),
]

# Variables: (variable, label, unit, min_valid, max_valid). Los rangos son
# físicos y holgados; sirven para marcar errores groseros, no para QC fino.
SEED_VARIABLES = [
    ("water_temperature", "Temperatura del agua", "°C", -2, 40),
    ("salinity", "Salinidad", "PSU", 0, 45),
    ("sea_level", "Nivel del mar", "m", -5, 10),
    ("turbidity", "Turbidez", "NTU", 0, 4000),
    ("ph", "pH", "pH", 0, 14),
    ("wind_speed", "Viento", "km/h", 0, 400),
    ("wind_direction", "Dirección del viento", "°", 0, 360),
    ("air_temperature", "Temperatura del aire", "°C", -50, 60),
    ("relative_humidity", "Humedad relativa", "%", 0, 100),
    ("precipitation", "Precipitación", "mm", 0, 1000),
    ("pressure", "Presión atmosférica", "hPa", 850, 1100),
    ("fecal_coliforms", "Coliformes fecales", "CF/100mL", 0, None),
    ("enterococci", "Enterococos", "CF/100mL", 0, None),
]


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path | str = DB_PATH) -> None:
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS stations (
        station_id TEXT PRIMARY KEY,
        station_name TEXT NOT NULL,
        institution TEXT,
        source TEXT,
        site_type TEXT,
        lat REAL,
        lon REAL,
        metadata_json TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS observations (
        obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
        station_id TEXT NOT NULL,
        variable TEXT NOT NULL,
        value REAL,
        unit TEXT,
        sample_time TEXT NOT NULL,
        recv_time TEXT,
        qc_flag TEXT,
        source TEXT,
        raw_json TEXT,
        UNIQUE(station_id, variable, sample_time, source),
        FOREIGN KEY(station_id) REFERENCES stations(station_id)
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_obs_station_var_time
    ON observations(station_id, variable, sample_time);
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS institutions (
        institution TEXT PRIMARY KEY,
        authorized  INTEGER NOT NULL DEFAULT 0 CHECK (authorized IN (0, 1))
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS variables (
        variable  TEXT PRIMARY KEY,
        label     TEXT NOT NULL,
        unit      TEXT,
        min_valid REAL,
        max_valid REAL
    );
    """)

    # INSERT OR IGNORE: no pisa cambios hechos a mano (p. ej. authorized=1).
    cur.executemany(
        "INSERT OR IGNORE INTO institutions (institution, authorized) VALUES (?, ?)",
        SEED_INSTITUTIONS,
    )
    cur.executemany(
        "INSERT OR IGNORE INTO variables (variable, label, unit, min_valid, max_valid) "
        "VALUES (?, ?, ?, ?, ?)",
        SEED_VARIABLES,
    )

    conn.commit()
    conn.close()


def upsert_stations(stations_df: pd.DataFrame, db_path: Path | str = DB_PATH) -> None:
    if stations_df.empty:
        return

    conn = get_connection(db_path)
    cur = conn.cursor()

    rows = stations_df.fillna("").to_dict(orient="records")

    for row in rows:
        cur.execute("""
        INSERT INTO stations (
            station_id, station_name, institution, source, site_type, lat, lon, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(station_id) DO UPDATE SET
            station_name=excluded.station_name,
            institution=excluded.institution,
            source=excluded.source,
            site_type=excluded.site_type,
            lat=excluded.lat,
            lon=excluded.lon,
            metadata_json=excluded.metadata_json
        """, (
            row.get("station_id"),
            row.get("station_name"),
            row.get("institution"),
            row.get("source"),
            row.get("site_type"),
            row.get("lat") if row.get("lat") != "" else None,
            row.get("lon") if row.get("lon") != "" else None,
            row.get("metadata_json"),
        ))

    conn.commit()
    conn.close()


def insert_observations(obs_df: pd.DataFrame, db_path: Path | str = DB_PATH) -> int:
    if obs_df.empty:
        return 0

    conn = get_connection(db_path)
    cur = conn.cursor()

    rows = obs_df.fillna("").to_dict(orient="records")
    inserted = 0

    for row in rows:
        cur.execute("""
        INSERT OR IGNORE INTO observations (
            station_id, variable, value, unit, sample_time, recv_time, qc_flag, source, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row.get("station_id"),
            row.get("variable"),
            row.get("value") if row.get("value") != "" else None,
            row.get("unit"),
            row.get("sample_time"),
            row.get("recv_time"),
            row.get("qc_flag"),
            row.get("source"),
            row.get("raw_json"),
        ))
        inserted += cur.rowcount

    conn.commit()
    conn.close()
    return inserted


def read_stations(db_path: Path | str = DB_PATH) -> pd.DataFrame:
    conn = get_connection(db_path)
    df = pd.read_sql_query("SELECT * FROM stations", conn)
    conn.close()
    return df


def read_observations(db_path: Path | str = DB_PATH) -> pd.DataFrame:
    conn = get_connection(db_path)
    df = pd.read_sql_query("SELECT * FROM observations", conn)
    conn.close()
    return df