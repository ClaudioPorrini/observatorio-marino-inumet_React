#!/usr/bin/env python3
"""
exportar_observaciones.py — SQLite -> JSON estáticos para la web (React).

Publica SOLO:
  - estaciones de instituciones con authorized = 1 (tabla `institutions`)
  - variables registradas en la tabla `variables`
  - valores dentro de [min_valid, max_valid] de esa variable

Escribe (todo bajo --salida, por defecto <proyecto>/public/observaciones):
  estaciones.json            sitios + último valor de cada variable
  series/<station_id>.json   serie HORARIA por variable, últimos --dias días

Uso (desde la carpeta observatorio/):
  python pipeline/exportar_observaciones.py
  python pipeline/exportar_observaciones.py --dias 183 \
      --db data/observatorio_marino.db --salida public/observaciones

La base se abre en modo SOLO LECTURA: este script no puede modificarla.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:                                   # python pipeline/exportar_observaciones.py
    from db_utils import DB_PATH
except ImportError:                    # python -m pipeline.exportar_observaciones
    from pipeline.db_utils import DB_PATH

PROYECTO = Path(__file__).resolve().parent.parent
SALIDA_DEFECTO = PROYECTO / "public" / "observaciones"

FMT_TIEMPO = "%Y-%m-%dT%H:%M:%SZ"
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
ID_VALIDO = re.compile(r"^[A-Za-z0-9_\-]+$")   # el ID se usa como nombre de archivo

# Cómo se pasa de muestras finas a una por hora.
SUMA = {"precipitation"}               # acumulados: se suman
CIRCULAR = {"wind_direction"}          # ángulos: media circular (359° y 1° -> 0°, no 180°)
DECIMALES = {"precipitation": 2, "wind_direction": 0}   # resto: 1 decimal


# ───────────────────────────── SQL ─────────────────────────────
# La "ventana publicable" se define UNA vez (CTE = subconsulta con nombre)
# y la reutilizan las dos consultas. Cambiar un criterio acá lo cambia en ambas.
# JOIN (interno) con institutions/variables = lista blanca: lo que no esté
# autorizado o registrado NO sale. Los diagnósticos avisan qué se está dejando afuera.
CTE_VENTANA = """
WITH ventana AS (
    SELECT o.obs_id, o.station_id, o.variable, o.sample_time, o.value
    FROM observations o
    JOIN stations     s ON s.station_id  = o.station_id
    JOIN institutions i ON i.institution = s.institution AND i.authorized = 1
    JOIN variables    v ON v.variable    = o.variable
    WHERE o.sample_time >= :corte
      AND o.value IS NOT NULL
      AND (v.min_valid IS NULL OR o.value >= v.min_valid)
      AND (v.max_valid IS NULL OR o.value <= v.max_valid)
)
"""

SQL_SERIES = CTE_VENTANA + "SELECT station_id, variable, sample_time, value FROM ventana"

# Última medición por estación y variable (función de ventana).
# obs_id DESC desempata si dos fuentes reportan el mismo instante.
SQL_ULTIMOS = CTE_VENTANA + """
SELECT station_id, variable, sample_time, value
FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY station_id, variable
                                 ORDER BY sample_time DESC, obs_id DESC) AS rn
    FROM ventana
)
WHERE rn = 1
"""

SQL_ESTACIONES = """
SELECT s.station_id, s.station_name, s.institution, s.site_type, s.lat, s.lon
FROM stations s
JOIN institutions i ON i.institution = s.institution AND i.authorized = 1
ORDER BY s.station_id
"""

SQL_VARIABLES = "SELECT variable, label, unit FROM variables"

_BASE_DIAG = """
FROM observations o
JOIN stations     s ON s.station_id  = o.station_id
JOIN institutions i ON i.institution = s.institution AND i.authorized = 1
"""


# ─────────────────────────── utilidades ───────────────────────────
def limpio(x):
    """NaN/NaT -> None (JSON estricto no admite NaN)."""
    return None if x is None or (isinstance(x, float) and np.isnan(x)) or x is pd.NA else x


def escribir_json(ruta: Path, obj) -> None:
    """Escritura atómica: la web nunca lee un archivo a medio escribir."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        os.chmod(tmp, 0o644)           # mkstemp crea 0600; el servidor web debe poder leerlo
        os.replace(tmp, ruta)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def abrir_solo_lectura(db: Path) -> sqlite3.Connection:
    # as_uri() codifica espacios y acentos de la ruta.
    return sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=30)


def diagnosticos(conn: sqlite3.Connection, corte: str) -> None:
    """Avisa lo que el export deja afuera. Nada de esto frena la corrida."""
    q = lambda sql, p=(): conn.execute(sql, p).fetchall()

    sin_reg = q(f"SELECT o.variable, COUNT(*) {_BASE_DIAG} "
                "LEFT JOIN variables v ON v.variable = o.variable "
                "WHERE v.variable IS NULL AND o.sample_time >= ? GROUP BY o.variable", (corte,))
    for var, n in sin_reg:
        print(f"  ⚠️  variable NO registrada en `variables` (no se publica): {var} ({n:,} filas)")

    fuera = q(f"SELECT COUNT(*) {_BASE_DIAG} JOIN variables v ON v.variable = o.variable "
              "WHERE o.sample_time >= ? AND o.value IS NOT NULL AND "
              "((v.min_valid IS NOT NULL AND o.value < v.min_valid) OR "
              " (v.max_valid IS NOT NULL AND o.value > v.max_valid))", (corte,))[0][0]
    if fuera:
        print(f"  ⚠️  {fuera:,} valores fuera de rango físico descartados")

    # El filtro por fecha compara TEXTO: solo es válido si todas las fechas tienen el mismo formato.
    mal = q(f"SELECT COUNT(*) {_BASE_DIAG} WHERE o.sample_time NOT GLOB "
            "'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'")[0][0]
    if mal:
        print(f"  ⚠️  {mal:,} filas con sample_time fuera del formato AAAA-MM-DDTHH:MM:SSZ "
              "(el filtro por fecha puede ser incorrecto para ellas)")


def a_horario(df: pd.DataFrame) -> pd.DataFrame:
    """Una fila por (estación, variable, hora). Si ya es horario, no cambia los valores."""
    cols = ["station_id", "variable", "hora", "value"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    df = df.assign(hora=df["t"].dt.floor("h"))
    claves = ["station_id", "variable", "hora"]
    es_dir = df["variable"].isin(CIRCULAR)
    es_suma = df["variable"].isin(SUMA)

    partes = [
        df[~es_dir & ~es_suma].groupby(claves, as_index=False)["value"].mean(),
        df[es_suma].groupby(claves, as_index=False)["value"].sum(),
    ]

    d = df[es_dir]
    if not d.empty:
        rad = np.deg2rad(d["value"].to_numpy())
        d = d.assign(s=np.sin(rad), c=np.cos(rad))
        g = d.groupby(claves, as_index=False)[["s", "c"]].mean()
        ang = np.round(np.rad2deg(np.arctan2(g["s"], g["c"])))   # redondear ANTES del módulo
        g["value"] = np.mod(ang, 360)                            # 360° se publica como 0°
        partes.append(g[claves + ["value"]])

    return pd.concat([p[cols] for p in partes if not p.empty] or [pd.DataFrame(columns=cols)],
                     ignore_index=True)


# ───────────────────────────── main ─────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DB_PATH, help=f"base SQLite (defecto: {DB_PATH})")
    ap.add_argument("--salida", type=Path, default=SALIDA_DEFECTO, help=f"carpeta de salida (defecto: {SALIDA_DEFECTO})")
    ap.add_argument("--dias", type=int, default=183, help="ventana en días (defecto 183 = 6 meses)")
    args = ap.parse_args()

    db, salida = args.db.resolve(), args.salida.resolve()
    if not db.exists():
        print(f"ERROR: no existe la base {db}", file=sys.stderr)
        return 1
    if args.dias < 1:
        print("ERROR: --dias debe ser >= 1", file=sys.stderr)
        return 1

    ahora = datetime.now(timezone.utc)
    corte = (ahora - timedelta(days=args.dias)).strftime(FMT_TIEMPO)
    generado = ahora.strftime(FMT_TIEMPO)
    print(f"Base:    {db}\nSalida:  {salida}\nVentana: desde {corte} ({args.dias} días)")

    conn = abrir_solo_lectura(db)
    try:
        estaciones = pd.read_sql_query(SQL_ESTACIONES, conn)
        meta = pd.read_sql_query(SQL_VARIABLES, conn).set_index("variable")
        series = pd.read_sql_query(SQL_SERIES, conn, params={"corte": corte})
        ultimos = pd.read_sql_query(SQL_ULTIMOS, conn, params={"corte": corte})
        diagnosticos(conn, corte)
    finally:
        conn.close()

    if estaciones.empty:
        print("  ⚠️  Ninguna estación pertenece a una institución autorizada: se publican archivos vacíos.")

    # Fechas -> datetime UTC. Formato estricto; lo que no encaje se descarta (y se avisa).
    series["t"] = pd.to_datetime(series["sample_time"], format=FMT_TIEMPO, utc=True, errors="coerce")
    n_mal = int(series["t"].isna().sum())
    if n_mal:
        print(f"  ⚠️  {n_mal:,} filas con fecha ilegible descartadas")
        series = series.dropna(subset=["t"])

    if not series.empty:
        dif = (series.sort_values(["station_id", "variable", "t"])
                     .groupby(["station_id", "variable"])["t"].diff().dt.total_seconds() / 60)
        intervalo = dif.groupby(series.loc[dif.index, "variable"]).median()
        print("  Intervalo mediano de muestreo (min): " +
              ", ".join(f"{v}={m:.0f}" for v, m in intervalo.items() if pd.notna(m)))

    horario = a_horario(series)
    n_prom = len(series) - len(horario)
    print(f"  Filas: {len(series):,} crudas -> {len(horario):,} horarias ({n_prom:,} absorbidas al promediar)")

    # ── estaciones.json ──
    ult_por_est: dict[str, dict] = {}
    for r in ultimos.itertuples(index=False):
        m = meta.loc[r.variable]
        dec = DECIMALES.get(r.variable, 1)
        val = round(float(r.value), dec)
        if r.variable in CIRCULAR:
            val = val % 360        # misma convención que las series: norte = 0°, no 360°
        ult_por_est.setdefault(r.station_id, {})[r.variable] = {
            "label": m["label"], "unit": limpio(m["unit"]),
            "value": int(val) if dec == 0 else val + 0.0, "time": r.sample_time,
        }

    lista = []
    for r in estaciones.itertuples(index=False):
        latest = ult_por_est.get(r.station_id, {})
        lat, lon = limpio(r.lat), limpio(r.lon)
        if lat is None or lon is None:
            print(f"  ⚠️  {r.station_id}: sin coordenadas (no se podrá ubicar en el mapa)")
        lista.append({
            "station_id": r.station_id, "name": r.station_name,
            "institution": r.institution, "site_type": limpio(r.site_type),
            "lat": lat, "lon": lon,
            "last_time": max((v["time"] for v in latest.values()), default=None),
            "latest": latest,
        })
    escribir_json(salida / "estaciones.json",
                  {"generated_at": generado, "window_days": args.dias, "stations": lista})

    # ── series/<station_id>.json ──
    dir_series = salida / "series"
    escritos: set[str] = set()
    for sid, g in horario.groupby("station_id"):
        if not ID_VALIDO.match(sid):
            print(f"  ⚠️  station_id no apto para nombre de archivo, se omite: {sid!r}")
            continue
        variables = {}
        for var, gv in g.groupby("variable"):
            gv = gv.sort_values("hora")
            dec = DECIMALES.get(var, 1)
            vals = np.round(gv["value"].to_numpy(dtype=float), dec) + 0.0   # +0.0 evita "-0.0"
            variables[var] = {
                "label": meta.loc[var, "label"], "unit": limpio(meta.loc[var, "unit"]),
                "t": ((gv["hora"] - EPOCH) // pd.Timedelta(seconds=1)).astype("int64").tolist(),
                "v": vals.astype(int).tolist() if dec == 0 else vals.tolist(),
            }
        escribir_json(dir_series / f"{sid}.json",
                      {"station_id": sid, "generated_at": generado, "variables": variables})
        escritos.add(sid)

    # Si una estación dejó de ser publicable (institución desautorizada, sin datos en
    # la ventana...), su archivo viejo NO puede quedar publicado.
    if dir_series.exists():
        for f in dir_series.glob("*.json"):
            if f.stem not in escritos:
                f.unlink()
                print(f"  🗑  retirado archivo que ya no corresponde publicar: {f.name}")

    con_datos = sum(1 for e in lista if e["latest"])
    print(f"Listo: {len(lista)} estaciones ({con_datos} con datos), {len(escritos)} series escritas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())