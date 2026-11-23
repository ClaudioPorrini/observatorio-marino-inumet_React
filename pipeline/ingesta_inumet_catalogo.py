"""
ingest_inumet_catalogo.py — v3
==============================
Fixes aplicados sobre v2:
  - CSVs de INUMET usan separador ';' → se detecta y parsea correctamente
  - Viento tiene columnas dir_viento + int_viento → se generan dos variables
  - pkg_id de presión corregido
  - normalize() no crea una fila por observación en stations_df

v3.1 (migración a observatorio/pipeline):
  - usa DB_PATH de db_utils (ruta anclada al proyecto, no al directorio actual)
  - import duro de db_utils: ya no degrada en silencio a "solo CSV"
  - código de salida != 0 si falla algún recurso (para cron / monitoreo)
  - raw/ junto a la base y creada en main(), no al importar el módulo

Formato de columnas reales detectadas:
  temperatura:  fecha;estacion_id;temp_aire
  humedad:      _id,fecha,estacion_id,hum_relativa   ← separador coma (API)
  precipit.:    fecha;estacion_id;precip_horario
  viento:       fecha;estacion_id;dir_viento;int_viento
"""

from __future__ import annotations
import io
import sys
import unicodedata
from pathlib import Path

import pandas as pd
import requests

# Import duro: si falta db_utils el script debe FALLAR. Antes seguía en silencio
# guardando solo un CSV y la base quedaba desactualizada sin que nadie se enterara.
from db_utils import DB_PATH, init_db, upsert_stations, insert_observations

CKAN_BASE = "https://catalogodatos.gub.uy"

# ──────────────────────────────────────────────────────────
# RECURSOS VERIFICADOS
# (res_id): (pkg_id, filename, [(variable, unit, val_col)], descripcion)
# val_col = None → auto-detectar; lista para CSVs con múltiples variables
# ──────────────────────────────────────────────────────────
RESOURCES: dict[str, tuple[str, str, list[tuple[str, str, str | None]], str]] = {
    # Temperatura — separador ';', col: temp_aire
    "f800fc53-556b-4d1c-8bd6-28b41f9cf146": (
        "accd0e24-76be-4101-904b-81bb7d41ee88",
        "inumet_temperatura_del_aire.csv",
        [("air_temperature", "°C", "temp_aire")],
        "Temperatura del aire",
    ),
    # Humedad — funciona vía datastore (separador ',')
    "8cfae7fa-01f6-46e1-ad75-49bab124c036": (
        "5f4f50ac-2d11-4863-8ef2-b500d5f3aa90",
        "inumet_humedad_relativa.csv",
        [("relative_humidity", "%", "hum_relativa")],
        "Humedad relativa",
    ),
    # Precipitación — separador ';', col: precip_horario
    "d4e222b4-cd88-430d-bedd-8b1042f416d5": (
        "inumet-observaciones-meteorologicas-precipitacion-puntual-en-el-uruguay",
        "inumet_precipitacion_puntual_horaria.csv",
        [("precipitation", "mm", "precip_horario")],
        "Precipitación puntual",
    ),
    # Presión — pkg_id corregido (slug en lugar de UUID que falló)
    "dd15e646-ecce-4505-b29c-ddb4bc1c8a11": (
        "inumet-observaciones-meteorologicas-presion-atmosferica-en-el-uruguay",
        "inumet_presion_atmosferica_a_nivel_medio_del_mar.csv",
        [("pressure", "hPa", None)],
        "Presión atmosférica",
    ),
    # Viento — separador ';', cols: dir_viento + int_viento (2 variables en 1 CSV)
    "943ff07c-17d1-4397-932a-7b5b21b49375": (
        "57247625-faec-4227-8025-cfc113e18c5c",
        "inumet_direccion_e_intensidad_del_viento.csv",
        [
            ("wind_speed",     "km/h", "int_viento"),
            ("wind_direction", "°",    "dir_viento"),
        ],
        "Viento (dirección e intensidad)",
    ),
}

STATION_COORDS: dict[str, tuple[float, float]] = {
    "artigas":             (-30.4000, -56.5000),
    "colonia":             (-34.4700, -57.8400),
    "melilla":             (-34.8200, -56.2700),
    "mercedes":            (-33.2600, -58.0200),
    "paso de los toros":   (-32.8100, -56.5100),
    "rocha":               (-34.4800, -54.3300),
    "salto":               (-31.3900, -57.9600),
    "punta del este":      (-34.9700, -54.9500),
    "punta_del_este":      (-34.9700, -54.9500),
    "la paloma":           (-34.6600, -54.1500),
    "chuy":                (-33.6800, -53.4600),
}

RAW_DIR = Path(DB_PATH).parent / "raw"      # <proyecto>/data/raw (se crea en main)

_HDR = {
    "User-Agent": "Mozilla/5.0 ObservatorioMarino-INUMET/3.0",
    "Accept": "text/csv,application/csv,text/plain,*/*",
    "Referer": "https://catalogodatos.gub.uy/",
}


def _read_csv_auto(text: str) -> pd.DataFrame:
    """Lee CSV detectando separador ';' o ','."""
    # Detectar separador por la primera línea
    first = text.split("\n")[0]
    sep = ";" if first.count(";") > first.count(",") else ","
    return pd.read_csv(io.StringIO(text), sep=sep)


def download_csv(resource_id: str, pkg_id: str, filename: str, timeout: int = 90) -> pd.DataFrame | None:
    """Descarga intentando tres métodos en orden."""

    # Método 1: descarga directa
    url = f"{CKAN_BASE}/dataset/{pkg_id}/resource/{resource_id}/download/{filename}"
    try:
        r = requests.get(url, headers=_HDR, timeout=timeout)
        r.raise_for_status()
        df = _read_csv_auto(r.text)
        if not df.empty:
            return df
    except Exception as e:
        print(f"  Método 1 falló: {e}")

    # Método 2: datastore_search (funciona para humedad)
    try:
        r = requests.get(
            f"{CKAN_BASE}/api/3/action/datastore_search",
            params={"resource_id": resource_id, "limit": 10000},
            headers=_HDR, timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("success") and data["result"]["records"]:
            return pd.DataFrame(data["result"]["records"])
    except Exception as e:
        print(f"  Método 2 falló: {e}")

    # Método 3: datastore dump
    try:
        r = requests.get(
            f"{CKAN_BASE}/datastore/dump/{resource_id}",
            params={"format": "csv"},
            headers=_HDR, timeout=timeout,
        )
        r.raise_for_status()
        return _read_csv_auto(r.text)
    except Exception as e:
        print(f"  Método 3 falló: {e}")

    return None


def _slugify(text: str) -> str:
    text = str(text).strip().lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "_" for c in text).strip("_")


def _get_coords(estacion_id: str) -> tuple[float | None, float | None]:
    key = estacion_id.lower().replace("_", " ").strip()
    # Exacta
    if key in STATION_COORDS:
        return STATION_COORDS[key]
    # Parcial — tomar la primera palabra significativa (ej: "rocha_g3" → "rocha")
    for k, v in STATION_COORDS.items():
        if k in key:
            return v
    return (None, None)


def normalize(
    df: pd.DataFrame,
    variables: list[tuple[str, str, str | None]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Normaliza un DataFrame crudo al schema del observatorio.
    variables = [(variable_std, unit, val_col_name), ...]
    val_col_name puede ser None → auto-detectar la única columna no-meta.
    """
    cols = df.columns.tolist()
    col_lower = {c: c.lower() for c in cols}

    # Columna de tiempo
    time_col = next(
        (c for c, cl in col_lower.items() if "fecha" in cl or "date" in cl or "time" in cl),
        None,
    )
    # Columna de estación
    sta_col = next(
        (c for c, cl in col_lower.items() if "estacion" in cl or "station" in cl),
        None,
    )

    if not time_col or not sta_col:
        print(f"  ⚠️  No se encontraron columnas de fecha/estación. Cols: {cols}")
        return pd.DataFrame(), pd.DataFrame()

    # Estaciones únicas — SOLO una fila por station_id
    unique_stations = df[sta_col].dropna().unique()
    station_rows = []
    for sid in unique_stations:
        sid_str = str(sid).strip()
        lat, lon = _get_coords(sid_str)
        station_rows.append({
            "station_id":    f"inumet_{_slugify(sid_str)}",
            "station_name":  f"INUMET {sid_str.replace('_', ' ').title()}",
            "institution":   "InUMet",
            "source":        "INUMET Catálogo Abierto",
            "site_type":     "EMA",
            "lat":           lat,
            "lon":           lon,
            "metadata_json": None,
        })
    stations_df = pd.DataFrame(station_rows).drop_duplicates(subset=["station_id"])

    # Observaciones — una por variable
    all_obs: list[pd.DataFrame] = []
    meta_cols = {time_col, sta_col, "_id", "_full_count"}

    for variable, unit, val_col in variables:
        # Auto-detectar columna si no se especificó
        if val_col is None:
            candidates = [c for c in cols if c not in meta_cols]
            val_col = candidates[0] if candidates else None

        if not val_col or val_col not in df.columns:
            print(f"  ⚠️  Columna '{val_col}' no encontrada para {variable}")
            continue

        obs = df[[sta_col, time_col, val_col]].copy()
        obs.columns = ["sta_raw", "time_raw", "val_raw"]
        obs["station_id"] = "inumet_" + obs["sta_raw"].astype(str).str.strip().apply(_slugify)
        obs["sample_time"] = pd.to_datetime(
            obs["time_raw"], errors="coerce", utc=True,
            format="mixed",
        )
        obs["value"] = pd.to_numeric(
            obs["val_raw"].astype(str).str.replace(",", ".", regex=False),
            errors="coerce",
        )
        obs = obs.dropna(subset=["station_id", "sample_time", "value"])
        obs["variable"]    = variable
        obs["unit"]        = unit
        obs["recv_time"]   = None
        obs["qc_flag"]     = "RAW"
        obs["source"]      = "INUMET Catálogo Abierto"
        obs["raw_json"]    = None
        obs["sample_time"] = obs["sample_time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        all_obs.append(
            obs[["station_id", "variable", "value", "unit",
                 "sample_time", "recv_time", "qc_flag", "source", "raw_json"]]
        )
        print(f"  {variable}: {len(obs):,} observaciones | estaciones: {sorted(obs['station_id'].unique())}")

    obs_df = pd.concat(all_obs, ignore_index=True) if all_obs else pd.DataFrame()
    return stations_df, obs_df


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    init_db(DB_PATH)
    print(f"Base: {DB_PATH}")

    all_stations: list[pd.DataFrame] = []
    all_obs:      list[pd.DataFrame] = []
    fallidos:     list[str] = []

    for res_id, (pkg_id, filename, variables, desc) in RESOURCES.items():
        print(f"\n→ {desc}  [{res_id[:8]}...]")

        df_raw = download_csv(res_id, pkg_id, filename)

        if df_raw is None or df_raw.empty:
            print("  Sin datos.")
            fallidos.append(desc)
            continue

        print(f"  Filas: {len(df_raw):,} | Columnas: {df_raw.columns.tolist()}")
        df_raw.to_csv(RAW_DIR / f"inumet_{variables[0][0]}_raw.csv", index=False)

        sta_df, obs_df = normalize(df_raw, variables)

        if not sta_df.empty:
            all_stations.append(sta_df)
        if not obs_df.empty:
            all_obs.append(obs_df)

    if not all_obs:
        print("\n⚠️  Sin datos para insertar.")
        return 1

    if all_stations:
        sta_all = pd.concat(all_stations).drop_duplicates(subset=["station_id"])
        upsert_stations(sta_all, DB_PATH)
        print(f"\n✅ Estaciones INUMET actualizadas: {len(sta_all)}")
        for _, r in sta_all.iterrows():
            coords = f"({r['lat']:.3f}, {r['lon']:.3f})" if pd.notna(r["lat"]) else "sin coords"
            print(f"   {r['station_id']} — {coords}")

    obs_all = pd.concat(all_obs, ignore_index=True)
    inserted = insert_observations(obs_all, DB_PATH)
    print(f"✅ Observaciones nuevas: {inserted:,}")
    print(f"   Variables: {sorted(obs_all['variable'].unique())}")
    print(f"   Total preparadas: {len(obs_all):,}")

    if fallidos:
        print(f"\n⚠️  Recursos que fallaron (la base quedó parcialmente actualizada): {fallidos}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())