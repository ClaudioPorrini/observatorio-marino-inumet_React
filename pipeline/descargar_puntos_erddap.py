#!/usr/bin/env python3
"""
descargar_puntos_erddap.py — series diarias de MUR (TSM y anomalía) en puntos costeros, desde ERDDAP.

Pensado para históricos largos (MUR empieza el 2002-06-01) y para reusar en otros análisis:
no depende del sitio web ni de los NC4 locales.

    ERDDAP (griddap, CSV)  →  data/erddap_puntos/raw/<producto>/<punto>/<año>.csv   (crudo, todas las celdas)
                           →  data/erddap_puntos/mur_puntos_diario.csv              (largo: fecha, punto, producto, valor)
                           →  data/erddap_puntos/mur_<producto>_diario_ancho.csv    (ancho: fecha × punto)
                           →  data/erddap_puntos/celdas.json                        (qué celdas se usaron por punto)

Mismo criterio que exportar_satelite.py (los puntos se toman de ahí, una sola lista):
  * promedio de las celdas de agua del 3x3 (~3 km) alrededor de la celda más cercana;
  * si el 3x3 es todo tierra, la celda de agua más cercana a menos de 5 km;
  * si no hay, el punto se omite (con aviso).
La elección de celdas se hace UNA vez por punto y producto (la máscara de tierra de MUR es fija),
mirando la última fecha disponible, y queda registrada en celdas.json.

Se pide por AÑO y por punto (9 celdas × 365 días ≈ 150 KB por pedido). Un año completo ya bajado
no se vuelve a pedir: si se corta, se retoma. El año en curso se rebaja en cada corrida.

Uso (desde la raíz del proyecto):
    # prueba corta para medir cuánto tarda el servidor
    python pipeline/descargar_puntos_erddap.py --puntos colonia --productos sst --desde 2025-01-01
    # histórico completo (puede llevar horas; se puede cortar y retomar)
    nohup python pipeline/descargar_puntos_erddap.py > data/erddap_puntos.log 2>&1 &
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from exportar_satelite import PUNTO_RADIO_KM, PUNTOS_COSTEROS  # noqa: E402  (una sola lista de puntos)

PROYECTO = Path(__file__).resolve().parent.parent
SALIDA = PROYECTO / "data" / "erddap_puntos"

SERVIDOR = "https://coastwatch.pfeg.noaa.gov/erddap"
PRODUCTOS = {
    # producto: (dataset ERDDAP, variable). Ambos: diarios 09:00 UTC, grilla 0,01°, °C.
    "sst": ("jplMURSST41", "analysed_sst"),
    "anom": ("jplMURSST41anom1day", "sstAnom"),  # anomalía vs climatología MUR 2003-2014
}
INICIO_MUR = date(2002, 6, 1)
CAJA_SONDEO = 0.06          # ± grados alrededor del punto para elegir celdas (≈ 13×13 celdas)
PAUSA_S = 1.0               # entre pedidos: el servidor es público y compartido
TIMEOUT_S = 600
ESPERAS_REINTENTO = (10, 30, 90)


# ──────────────────────────────────────────────────────────
# ERDDAP
# ──────────────────────────────────────────────────────────
class SinDatos(Exception):
    """ERDDAP respondió que la consulta no tiene resultados (no es un error de red)."""


def pedir_csv(url: str) -> pd.DataFrame:
    """GET a un .csv de ERDDAP con reintentos. Devuelve el DataFrame (sin la fila de unidades)."""
    ultimo = None
    for intento, espera in enumerate((0, *ESPERAS_REINTENTO)):
        if espera:
            print(f"      reintento {intento} en {espera} s ({ultimo})")
            time.sleep(espera)
        try:
            r = requests.get(url, timeout=TIMEOUT_S)
        except requests.RequestException as e:
            ultimo = type(e).__name__
            continue
        if r.status_code == 200:
            df = pd.read_csv(io.StringIO(r.text), skiprows=[1])   # fila 2 = unidades
            return df
        cuerpo = r.text[:400]
        if r.status_code == 404 and "no matching results" in cuerpo.lower():
            raise SinDatos(cuerpo)
        if r.status_code in (400, 404):                            # error de la consulta: no reintentar
            raise ValueError(f"HTTP {r.status_code}: {cuerpo}")
        ultimo = f"HTTP {r.status_code}"
    raise ConnectionError(f"sin respuesta válida tras {len(ESPERAS_REINTENTO)} reintentos: {ultimo}")


def rango_tiempo(servidor: str, dataset: str) -> tuple[date, date]:
    """Primera y última fecha que tiene el dataset en el servidor."""
    df0 = pedir_csv(f"{servidor}/griddap/{dataset}.csv?time[0]")
    df1 = pedir_csv(f"{servidor}/griddap/{dataset}.csv?time[last]")
    a = pd.to_datetime(df0["time"].iloc[0], utc=True).date()
    b = pd.to_datetime(df1["time"].iloc[-1], utc=True).date()
    return a, b


def url_datos(servidor, dataset, var, t0: str, t1: str, lat0, lat1, lon0, lon1) -> str:
    return (f"{servidor}/griddap/{dataset}.csv?{var}"
            f"[({t0}):1:({t1})][({lat0:.2f}):1:({lat1:.2f})][({lon0:.2f}):1:({lon1:.2f})]")


# ──────────────────────────────────────────────────────────
# ELECCIÓN DE CELDAS (una vez por punto y producto)
# ──────────────────────────────────────────────────────────
@dataclass
class Celdas:
    metodo: str             # "3x3" | "mas_cercana"
    lat0: float
    lat1: float
    lon0: float
    lon1: float
    n_agua: int
    distancia_km: float     # del punto a la celda central / elegida


def elegir_celdas(sondeo: pd.DataFrame, var: str, plat: float, plon: float) -> Celdas | None:
    """Con una fecha de la caja ±CAJA_SONDEO, decide qué celdas representan al punto."""
    lat = sondeo["latitude"].to_numpy(float)
    lon = sondeo["longitude"].to_numpy(float)
    val = sondeo[var].to_numpy(float)
    km = np.hypot((lat - plat) * 111.0, (lon - plon) * 111.0 * math.cos(math.radians(plat)))
    if km.size == 0:
        return None
    c = int(np.argmin(km))                                  # celda más cercana (agua o tierra)
    clat, clon = lat[c], lon[c]
    en_3x3 = (np.abs(lat - clat) < 0.015) & (np.abs(lon - clon) < 0.015)
    agua = np.isfinite(val)
    if (en_3x3 & agua).any():
        return Celdas("3x3", clat - 0.01, clat + 0.01, clon - 0.01, clon + 0.01,
                      int((en_3x3 & agua).sum()), round(float(km[c]), 2))
    km_agua = np.where(agua, km, np.inf)
    a = int(np.argmin(km_agua))
    if np.isfinite(km_agua[a]) and km_agua[a] <= PUNTO_RADIO_KM:
        return Celdas("mas_cercana", lat[a], lat[a], lon[a], lon[a], 1, round(float(km_agua[a]), 2))
    return None


# ──────────────────────────────────────────────────────────
# ESCRITURA
# ──────────────────────────────────────────────────────────
def escribir_atomico(destino: Path, texto: str) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=destino.parent, prefix=".tmp_", suffix=destino.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(texto)
        os.replace(tmp, destino)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ──────────────────────────────────────────────────────────
# DESCARGA
# ──────────────────────────────────────────────────────────
def descargar(args) -> tuple[int, list[str]]:
    salida: Path = args.salida.resolve()
    meta_path = salida / "celdas.json"
    celdas_meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    puntos = [p for p in PUNTOS_COSTEROS if not args.puntos or p[0] in args.puntos]
    errores: list[str] = []
    pedidos = 0

    for prod in args.productos:
        dataset, var = PRODUCTOS[prod]
        try:
            primero, ultimo = rango_tiempo(args.servidor, dataset)
        except Exception as e:
            errores.append(f"{prod}: no se pudo leer el rango de fechas de {dataset}: {e}")
            continue
        desde, hasta = max(args.desde, primero), min(args.hasta or ultimo, ultimo)
        print(f"\n── {prod} ({dataset}) · servidor: {primero} → {ultimo} · pedido: {desde} → {hasta}")
        if desde > hasta:
            continue

        for pid, nombre, plat, plon in puntos:
            clave = f"{prod}/{pid}"
            m = celdas_meta.get(clave)
            if not m or m.get("lat") != plat or m.get("lon") != plon:          # nuevo o se movió el punto
                try:
                    sondeo = pedir_csv(url_datos(args.servidor, dataset, var, "last", "last",
                                                 plat - CAJA_SONDEO, plat + CAJA_SONDEO,
                                                 plon - CAJA_SONDEO, plon + CAJA_SONDEO))
                    pedidos += 1
                    time.sleep(PAUSA_S)
                except Exception as e:
                    errores.append(f"{clave}: sondeo de celdas: {e}")
                    continue
                c = elegir_celdas(sondeo, var, plat, plon)
                if c is None:
                    print(f"  ⚠ {nombre}: sin celdas de agua a menos de {PUNTO_RADIO_KM:g} km — se omite")
                    celdas_meta[clave] = {"lat": plat, "lon": plon, "metodo": "sin_agua"}
                    escribir_atomico(meta_path, json.dumps(celdas_meta, ensure_ascii=False, indent=1))
                    continue
                m = {"lat": plat, "lon": plon, **c.__dict__}
                celdas_meta[clave] = m
                escribir_atomico(meta_path, json.dumps(celdas_meta, ensure_ascii=False, indent=1))
                # Si cambió la elección de celdas, los crudos viejos de ese punto ya no valen.
                for viejo in (salida / "raw" / prod / pid).glob("*.csv"):
                    viejo.unlink()
                if c.metodo != "3x3":
                    print(f"  ⚠ {nombre}: 3x3 todo tierra; celda de agua más cercana a {c.distancia_km} km")
            if m.get("metodo") == "sin_agua":
                continue

            for anio in range(desde.year, hasta.year + 1):
                a0 = max(desde, date(anio, 1, 1))
                a1 = min(hasta, date(anio, 12, 31))
                # Completo = cubre todo lo que el servidor tiene de ese año y el año ya cerró
                # (2002 empieza en junio y también cuenta como completo).
                completo = a0 == max(date(anio, 1, 1), primero) and a1 == date(anio, 12, 31)
                # Año completo: <año>.csv (no se vuelve a pedir). Parcial: <año>_parcial.csv (se rehace).
                destino = salida / "raw" / prod / pid / (f"{anio}.csv" if completo else f"{anio}_parcial.csv")
                if completo and destino.exists():
                    continue
                # Extremos a las 09:00 (hora de los datos): ERDDAP toma el valor MÁS CERCANO a cada
                # extremo, y un 23:59 del 31/12 se iría al 1/1 del año siguiente.
                url = url_datos(args.servidor, dataset, var, f"{a0}T09:00:00Z", f"{a1}T09:00:00Z",
                                m["lat0"], m["lat1"], m["lon0"], m["lon1"])
                t = time.time()
                try:
                    df = pedir_csv(url)
                except SinDatos:
                    df = pd.DataFrame(columns=["time", "latitude", "longitude", var])
                except Exception as e:
                    errores.append(f"{clave} {anio}: {e}")
                    print(f"  ✗ {nombre} {anio}: {e}")
                    continue
                pedidos += 1
                escribir_atomico(destino, df.to_csv(index=False))
                if completo:                                   # el parcial de ese año ya no hace falta
                    (destino.parent / f"{anio}_parcial.csv").unlink(missing_ok=True)
                print(f"  {nombre:<24} {anio}: {len(df):>5} filas · {time.time() - t:5.1f} s")
                time.sleep(PAUSA_S)
    return pedidos, errores


# ──────────────────────────────────────────────────────────
# CONSOLIDACIÓN
# ──────────────────────────────────────────────────────────
def consolidar(salida: Path) -> pd.DataFrame:
    """Une los crudos: un valor por (punto, producto, fecha) = promedio de las celdas con agua."""
    salida = salida.resolve()
    nombres = {p[0]: (p[1], p[2], p[3]) for p in PUNTOS_COSTEROS}
    partes = []
    for prod, (_, var) in PRODUCTOS.items():
        for carpeta in sorted((salida / "raw" / prod).glob("*")):
            pid = carpeta.name
            if pid not in nombres:
                continue                          # punto que se sacó de la lista
            archivos = sorted(carpeta.glob("*.csv"))
            if not archivos:
                continue
            df = pd.concat([pd.read_csv(f) for f in archivos], ignore_index=True)
            if df.empty:
                continue
            df["fecha"] = pd.to_datetime(df["time"], utc=True).dt.date.astype(str)
            # Una fila por celda y día (si dos crudos se solapan, no se cuenta dos veces)
            df = df.drop_duplicates(subset=["fecha", "latitude", "longitude"], keep="last")
            g = df.groupby("fecha")[var].agg(valor="mean", n_celdas="count").reset_index()
            g = g[g["n_celdas"] > 0]
            nombre, lat, lon = nombres[pid]
            g.insert(1, "punto", pid)
            g.insert(2, "nombre", nombre)
            g.insert(3, "lat", lat)
            g.insert(4, "lon", lon)
            g.insert(5, "producto", prod)
            partes.append(g)
    if not partes:
        return pd.DataFrame()
    largo = pd.concat(partes, ignore_index=True).sort_values(["producto", "punto", "fecha"])
    largo["valor"] = largo["valor"].round(3)
    escribir_atomico(salida / "mur_puntos_diario.csv", largo.to_csv(index=False))
    for prod in largo["producto"].unique():
        ancho = largo[largo["producto"] == prod].pivot(index="fecha", columns="punto", values="valor")
        orden = [p[0] for p in PUNTOS_COSTEROS if p[0] in ancho.columns]
        escribir_atomico(salida / f"mur_{prod}_diario_ancho.csv", ancho[orden].to_csv())
    return largo


# ──────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ids = [p[0] for p in PUNTOS_COSTEROS]
    ap = argparse.ArgumentParser(description="Series diarias de MUR (TSM y anomalía) en puntos costeros, desde ERDDAP.")
    ap.add_argument("--desde", type=date.fromisoformat, default=INICIO_MUR, help=f"AAAA-MM-DD (defecto {INICIO_MUR})")
    ap.add_argument("--hasta", type=date.fromisoformat, default=None, help="AAAA-MM-DD (defecto: último dato del servidor)")
    ap.add_argument("--productos", nargs="+", choices=list(PRODUCTOS), default=list(PRODUCTOS))
    ap.add_argument("--puntos", nargs="+", choices=ids, default=None, help="defecto: todos")
    ap.add_argument("--salida", type=Path, default=SALIDA, help=f"defecto: {SALIDA}")
    ap.add_argument("--servidor", default=SERVIDOR, help=f"ERDDAP a usar (defecto: {SERVIDOR})")
    ap.add_argument("--solo-consolidar", action="store_true", help="no descarga; rehace los CSV finales")
    args = ap.parse_args(argv)
    if args.hasta and args.hasta < args.desde:
        ap.error("--hasta es anterior a --desde")
    args.servidor = args.servidor.rstrip("/")

    inicio = time.time()
    print(f"descargar_puntos_erddap — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC → {args.salida.resolve()}")
    pedidos, errores = (0, []) if args.solo_consolidar else descargar(args)
    largo = consolidar(args.salida)

    print(f"\nResumen ({pedidos} pedidos, {(time.time() - inicio) / 60:.1f} min)")
    if not largo.empty:
        res = largo.groupby(["producto", "punto"])["fecha"].agg(["min", "max", "count"])
        print(res.to_string())
        print(f"\n  → {args.salida.resolve() / 'mur_puntos_diario.csv'}")
    if errores:
        print(f"\n{len(errores)} error(es) (al volver a correr se reintentan solo esos):")
        for e in errores:
            print(f"  - {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())