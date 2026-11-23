#!/usr/bin/env python3
"""
exportar_satelite.py — publica los productos satelitales como archivos estáticos.

    NC4 de MUR (SST y anomalía)  ┐
    JPG de color real MODIS/VIIRS ├─►  public/satelite/…  +  indice.json  ─►  React
    PNG de frente de turbidez    ┘

Qué genera (todo bajo --salida, por defecto <proyecto>/public/satelite):

    sst/sst_<fecha>.png        imagen a ~1 km, ya reproyectada a Web Mercator
    sst/sst_<fecha>.bin.gz     grilla para el clic (Int16, centésimas de unidad, stride 2)
    anom/anom_<fecha>.png|.bin.gz
    modis/modis_<fecha>.jpg    copia del JPG de color real (georreferenciado por indice.json)
    viirs/viirs_<fecha>.jpg
    frente/tf_<sat><fecha><calidad>.png
    puntos.json                series diarias de TSM y anomalía en puntos costeros (6 meses)
    indice.json                fechas disponibles, límites geográficos, escalas y grilla

Decisiones (ver claude/migracion-react-estado.md):
  * La imagen se reproyecta desde el CAMPO (floats) y recién después se colorea.
    Así la costa no se contamina con colores mezclados y la paleta sale de una sola tabla.
  * La escala de colores vive acá y se escribe en indice.json: la leyenda y el color del
    popup en React usan la misma, no hay dos copias que puedan divergir.
  * Los límites del PNG se corrigen medio píxel: las coordenadas del NetCDF son CENTROS
    de celda, el overlay necesita los BORDES.
  * indice.json se escribe al final y de forma atómica: nunca apunta a archivos que no existen.
  * Solo se borran archivos con el nombre que este script genera, dentro de sus subcarpetas.

Uso:
    python pipeline/exportar_satelite.py                 # últimos 12 días disponibles
    python pipeline/exportar_satelite.py --dias 7 --forzar
    python pipeline/exportar_satelite.py --formato rgba  # PNG RGBA en vez de paleta
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

# ──────────────────────────────────────────────────────────
# RUTAS (ancladas al proyecto, no al directorio desde donde se ejecuta)
# ──────────────────────────────────────────────────────────
PROYECTO = Path(__file__).resolve().parent.parent
DATOS = Path(os.environ.get("OBSERVATORIO_DATOS", PROYECTO / "data"))
SALIDA = PROYECTO / "public" / "satelite"

NC4_DIR = DATOS / "raw" / "nc4"
ANOM_DIR = DATOS / "raw" / "nc4_anom"
CACHE_DIR = DATOS / "sat_cache"          # JPG de MODIS/VIIRS que deja satellite_utils.py
FRENTE_DIR = DATOS / "frente_turbidez"

# ──────────────────────────────────────────────────────────
# PARÁMETROS
# ──────────────────────────────────────────────────────────
DIAS_DEFAULT = 12
GRILLA_STRIDE = 2            # 2 → una celda de clic cada 0,02° (~2 km). 1 = resolución nativa.
GRILLA_ESCALA = 100          # el valor se guarda como Int16 en centésimas
GRILLA_NODATA = -32768       # Int16 mínimo: tierra / sin dato

# Región de MODIS/VIIRS (misma que satellite_utils.py)
BBOX_COLOR_REAL = {"oeste": -58.68, "sur": -36.47, "este": -53.10, "norte": -33.33}

# Escalas: lista de (valor, color). Mismos colores y rango que la versión Streamlit.
# SST: Normalize(8, 26) con 9 colores equiespaciados.
# Anomalía: TwoSlope(-5, 0, 5) con 9 colores → el gris cae justo en 0.
PRODUCTOS_MUR = {
    "sst": {
        "titulo": "Temperatura superficial del mar",
        "unidad": "°C",
        "decimales": 2,
        "rango_valido": (-2.0, 40.0),
        "variables": ("analysed_sst", "sst", "sea_surface_temperature"),
        "directorio": NC4_DIR,
        "patron": re.compile(r"^MUR_(\d{8})\.nc4$"),
        "stops": [
            (8.0, "#053061"), (10.25, "#2166ac"), (12.5, "#4393c3"), (14.75, "#92c5de"),
            (17.0, "#f7f7f7"), (19.25, "#fddbc7"), (21.5, "#f4a582"), (23.75, "#d6604d"),
            (26.0, "#67001f"),
        ],
    },
    "anom": {
        "titulo": "Anomalía de TSM",
        "unidad": "°C",
        "decimales": 2,
        "rango_valido": (-15.0, 15.0),
        "variables": ("sstAnom", "sstAnomaly"),
        "directorio": ANOM_DIR,
        "patron": re.compile(r"^MUR_anom_(\d{8})\.nc$"),
        "stops": [
            (-5.0, "#08306b"), (-3.75, "#2171b5"), (-2.5, "#6baed6"), (-1.25, "#deebf7"),
            (0.0, "#f7f7f7"),
            (1.25, "#fee0d2"), (2.5, "#fc9272"), (3.75, "#de2d26"), (5.0, "#67000d"),
        ],
    },
}

# ──────────────────────────────────────────────────────────
# PUNTOS COSTEROS (series diarias de TSM y anomalía)
# ──────────────────────────────────────────────────────────
# Coordenadas a 2-3 km mar adentro de cada lugar, para no caer en celdas de tierra.
# Ajustables: al agregar o mover un punto, la próxima corrida lo recalcula para todas las fechas.
PUNTOS_COSTEROS = [
    # (id, nombre, lat, lon)
    ("colonia", "Colonia del Sacramento", -34.485, -57.870),
    ("montevideo", "Montevideo (Pocitos)", -34.925, -56.150),
    ("atlantida", "Atlántida", -34.790, -55.760),
    ("piriapolis", "Piriápolis", -34.885, -55.265),
    ("pde_mansa", "Punta del Este – Mansa", -34.925, -54.985),
    ("pde_brava", "Punta del Este – Brava", -34.975, -54.915),
    ("jose_ignacio", "José Ignacio", -34.855, -54.630),
    ("la_paloma", "La Paloma", -34.680, -54.150),
    ("punta_diablo", "Punta del Diablo", -34.055, -53.525),
    ("barra_chuy", "Barra del Chuy", -33.760, -53.355),
]
DIAS_SERIE_PUNTOS = 183          # 6 meses en puntos.json
PUNTO_VENTANA = 1                # 1 → promedio de 3x3 celdas (~3 km) alrededor del punto
PUNTO_RADIO_KM = 5.0             # si no hay mar en el 3x3: celda de mar más cercana hasta esta distancia
# Caché incremental (derivado, no es dato de origen): va en la carpeta del proyecto nuevo,
# nunca en OBSERVATORIO_DATOS (que hoy apunta a la carpeta vieja, que no se toca).
CACHE_PUNTOS = PROYECTO / "data" / "series_puntos_mur.csv"

RE_FECHA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_FRENTE = re.compile(r"^tf_(aqua|terra)(\d{8})(clear|cloudy)\.png$")


# ──────────────────────────────────────────────────────────
# UTILIDADES
# ──────────────────────────────────────────────────────────
def compacta_a_iso(c: str) -> str | None:
    """'20260511' → '2026-05-11'. None si no es una fecha real."""
    try:
        return datetime.strptime(c, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def escribir_atomico(destino: Path, escritor) -> None:
    """Escribe en un temporal del mismo directorio y lo mueve: nunca queda un archivo a medias."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=destino.parent, prefix=".tmp_", suffix=destino.suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            escritor(f)
        os.chmod(tmp, 0o644)
        os.replace(tmp, destino)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def hex_a_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


# ──────────────────────────────────────────────────────────
# LECTURA DEL NETCDF
# ──────────────────────────────────────────────────────────
@dataclass
class Campo:
    """Campo 2D orientado norte→sur (fila 0 = latitud más al norte), lon de oeste a este."""
    valores: np.ndarray        # float32 (filas, columnas), NaN = sin dato
    lat_norte: float           # latitud del CENTRO de la fila 0
    lon_oeste: float           # longitud del CENTRO de la columna 0
    dlat: float                # paso positivo
    dlon: float


@dataclass
class Geometria:
    lat_norte: float
    lon_oeste: float
    dlat: float
    dlon: float
    filas: int
    columnas: int


def _paso_regular(coord: np.ndarray, nombre: str) -> float:
    if coord.size < 2:
        raise ValueError(f"{nombre}: menos de 2 valores")
    d = np.diff(coord.astype("float64"))
    paso = float(np.median(d))
    if paso == 0 or np.max(np.abs(d - paso)) > abs(paso) * 1e-3:
        raise ValueError(f"{nombre}: grilla no regular")
    return paso


def _nombre_coord(ds, opciones: tuple[str, ...]) -> str:
    for n in opciones:
        if n in ds.coords or n in ds.variables:
            return n
    raise ValueError(f"No encuentro coordenadas {opciones}. Hay: {list(ds.coords)}")


def leer_geometria(ruta: Path) -> Geometria:
    """Solo coordenadas (barato): lo que hace falta para el índice sin tocar los datos."""
    import xarray as xr

    with xr.open_dataset(ruta) as ds:
        lat = np.asarray(ds[_nombre_coord(ds, ("lat", "latitude"))].values, dtype="float64")
        lon = np.asarray(ds[_nombre_coord(ds, ("lon", "longitude"))].values, dtype="float64")
    dlat = _paso_regular(lat, "latitud")
    dlon = _paso_regular(lon, "longitud")
    if dlon < 0:
        raise ValueError("longitud decreciente: no soportado")
    return Geometria(
        lat_norte=float(lat.max()), lon_oeste=float(lon[0]),
        dlat=abs(dlat), dlon=dlon, filas=lat.size, columnas=lon.size,
    )


def leer_campo(ruta: Path, variables: tuple[str, ...], rango: tuple[float, float]) -> tuple[Campo, int]:
    """Devuelve (campo, cantidad de valores fuera de rango descartados)."""
    import xarray as xr

    with xr.open_dataset(ruta) as ds:
        var = next((v for v in variables if v in ds.data_vars), None)
        if var is None:
            raise ValueError(f"No encuentro {variables}. Variables: {list(ds.data_vars)}")
        lat = np.asarray(ds[_nombre_coord(ds, ("lat", "latitude"))].values, dtype="float64")
        lon = np.asarray(ds[_nombre_coord(ds, ("lon", "longitude"))].values, dtype="float64")
        datos = np.asarray(ds[var].squeeze().values, dtype="float32")

    if datos.ndim != 2 or datos.shape != (lat.size, lon.size):
        raise ValueError(f"forma inesperada {datos.shape} para lat={lat.size}, lon={lon.size}")

    dlat = _paso_regular(lat, "latitud")
    dlon = _paso_regular(lon, "longitud")
    if dlon < 0:
        raise ValueError("longitud decreciente: no soportado")
    if dlat > 0:                      # latitud creciente (ERDDAP): invertir para que fila 0 = norte
        datos = datos[::-1, :]

    if np.nanmean(datos) > 100:       # viene en Kelvin
        datos = datos - np.float32(273.15)

    lo, hi = rango
    fuera = np.isfinite(datos) & ((datos < lo) | (datos > hi))
    n_fuera = int(fuera.sum())
    if n_fuera:
        datos = np.where(fuera, np.nan, datos).astype("float32")

    if not np.isfinite(datos).any():
        raise ValueError("el campo no tiene ningún dato válido")

    return Campo(datos, float(lat.max()), float(lon[0]), abs(dlat), dlon), n_fuera


# ──────────────────────────────────────────────────────────
# REPROYECCIÓN A WEB MERCATOR + LÍMITES
# ──────────────────────────────────────────────────────────
def _transformaciones(g: Geometria):
    """Transformación de origen (EPSG:4326, bordes) y de destino (EPSG:3857)."""
    from rasterio.crs import CRS
    from rasterio.transform import from_origin
    from rasterio.warp import calculate_default_transform

    oeste = g.lon_oeste - g.dlon / 2          # centro → borde
    norte = g.lat_norte + g.dlat / 2
    este = oeste + g.columnas * g.dlon
    sur = norte - g.filas * g.dlat
    src_tf = from_origin(oeste, norte, g.dlon, g.dlat)
    # Resolución fija: 1 columna de origen = 1 píxel de salida en x (en Mercator, un paso de
    # longitud mide lo mismo en todas las latitudes). Si se deja que rasterio elija, achica ~14 %.
    paso_m = np.radians(g.dlon) * 6378137.0
    dst_tf, w, h = calculate_default_transform(
        CRS.from_epsg(4326), CRS.from_epsg(3857), g.columnas, g.filas,
        left=oeste, bottom=sur, right=este, top=norte, resolution=paso_m,
    )
    return src_tf, dst_tf, w, h, (sur, oeste, norte, este)


def limites_overlay(g: Geometria) -> list[list[float]]:
    """[[sur, oeste], [norte, este]] en grados, para L.imageOverlay."""
    from rasterio.warp import transform

    _, dst_tf, w, h, (_, oeste, _, este) = _transformaciones(g)
    x0, y0 = dst_tf * (0, 0)
    x1, y1 = dst_tf * (w, h)
    _, lats = transform("EPSG:3857", "EPSG:4326", [x0, x1], [y0, y1])
    return [[round(min(lats), 5), round(oeste, 5)], [round(max(lats), 5), round(este, 5)]]


def reproyectar(campo: Campo, g: Geometria) -> np.ndarray:
    """Campo float (4326) → campo float (3857). Sin dato = NaN."""
    from rasterio.crs import CRS
    from rasterio.warp import Resampling, reproject

    src_tf, dst_tf, w, h, _ = _transformaciones(g)
    destino = np.full((h, w), np.nan, dtype="float32")
    reproject(
        source=campo.valores, destination=destino,
        src_transform=src_tf, src_crs=CRS.from_epsg(4326), src_nodata=np.nan,
        dst_transform=dst_tf, dst_crs=CRS.from_epsg(3857), dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    return destino


# ──────────────────────────────────────────────────────────
# COLOR Y PNG
# ──────────────────────────────────────────────────────────
def _canales(valores: np.ndarray, stops) -> np.ndarray:
    """Interpola linealmente los colores de `stops`. valores finitos → (…, 3) uint8."""
    xs = np.array([s[0] for s in stops], dtype="float64")
    rgb = np.array([hex_a_rgb(s[1]) for s in stops], dtype="float64")
    v = np.clip(valores.astype("float64"), xs[0], xs[-1])
    return np.stack([np.interp(v, xs, rgb[:, c]) for c in range(3)], axis=-1).round().astype("uint8")


def png_rgba(campo: np.ndarray, stops) -> Image.Image:
    ok = np.isfinite(campo)
    out = np.zeros(campo.shape + (4,), dtype="uint8")
    out[ok, :3] = _canales(campo[ok], stops)
    out[ok, 3] = 255
    return Image.fromarray(out, "RGBA")


def png_paleta(campo: np.ndarray, stops) -> Image.Image:
    """255 niveles de color + índice 0 transparente. ~3-4 veces más liviano que RGBA."""
    vmin, vmax = stops[0][0], stops[-1][0]
    niveles = np.linspace(vmin, vmax, 255)
    tabla = _canales(niveles, stops)                         # (255, 3)
    ok = np.isfinite(campo)
    idx = np.zeros(campo.shape, dtype="uint8")
    rel = (np.clip(campo[ok], vmin, vmax) - vmin) / (vmax - vmin)
    idx[ok] = 1 + np.rint(rel * 254).astype("uint8")
    img = Image.fromarray(idx, "P")
    img.putpalette([0, 0, 0] + tabla.flatten().tolist())
    img.info["transparency"] = 0
    return img


def guardar_png(img: Image.Image, destino: Path) -> None:
    def esc(f):
        kw = {"transparency": 0} if img.mode == "P" else {}
        img.save(f, format="PNG", optimize=True, **kw)
    escribir_atomico(destino, esc)


# ──────────────────────────────────────────────────────────
# GRILLA PARA EL CLIC
# ──────────────────────────────────────────────────────────
def grilla_clic(campo: Campo) -> tuple[bytes, dict]:
    """Int16 little-endian, fila 0 = norte. Devuelve (bytes gzip, metadatos para el índice)."""
    sub = campo.valores[::GRILLA_STRIDE, ::GRILLA_STRIDE]
    ok = np.isfinite(sub)
    q = np.full(sub.shape, GRILLA_NODATA, dtype="<i2")
    q[ok] = np.rint(sub[ok].astype("float64") * GRILLA_ESCALA).astype("<i2")
    meta = {
        "lat_norte": round(campo.lat_norte, 5),
        "lon_oeste": round(campo.lon_oeste, 5),
        "dlat": round(campo.dlat * GRILLA_STRIDE, 5),
        "dlon": round(campo.dlon * GRILLA_STRIDE, 5),
        "filas": int(sub.shape[0]),
        "columnas": int(sub.shape[1]),
        "escala": GRILLA_ESCALA,
        "sin_dato": GRILLA_NODATA,
    }
    return gzip.compress(q.tobytes(), compresslevel=9, mtime=0), meta


def meta_grilla_desde_geometria(g: Geometria) -> dict:
    """Mismos metadatos que grilla_clic, sin leer datos (para fechas ya exportadas)."""
    return {
        "lat_norte": round(g.lat_norte, 5),
        "lon_oeste": round(g.lon_oeste, 5),
        "dlat": round(g.dlat * GRILLA_STRIDE, 5),
        "dlon": round(g.dlon * GRILLA_STRIDE, 5),
        "filas": -(-g.filas // GRILLA_STRIDE),
        "columnas": -(-g.columnas // GRILLA_STRIDE),
        "escala": GRILLA_ESCALA,
        "sin_dato": GRILLA_NODATA,
    }


# ──────────────────────────────────────────────────────────
# PRODUCTOS MUR
# ──────────────────────────────────────────────────────────
# Solo se publica MUR a 0,01°. En las carpetas de origen conviven, con el mismo nombre MUR_*.nc,
# archivos de OSTIA "blended" (0,05°) y anomalías calculadas localmente: esos quedan afuera para
# que nada se muestre rotulado como MUR sin serlo. (Plan B futuro: si MUR deja de existir, el
# blended entra como producto PROPIO, con su nombre, no mezclado acá.)
RE_TITULO_MUR = re.compile(r"\bMUR\b")
PASO_MUR = 0.01

_motivos_rechazo: dict[Path, str | None] = {}     # caché por corrida: cada archivo se mira una vez


def motivo_rechazo(ruta: Path) -> str | None:
    """None si el archivo es MUR a 0,01°; si no, el motivo (para el resumen)."""
    if ruta in _motivos_rechazo:
        return _motivos_rechazo[ruta]
    import xarray as xr

    motivo = None
    try:
        with xr.open_dataset(ruta) as ds:
            titulo = str(ds.attrs.get("title", ""))
            lat = np.asarray(ds[_nombre_coord(ds, ("lat", "latitude"))].values[:2], dtype="float64")
        paso = abs(float(lat[1] - lat[0])) if lat.size == 2 else float("nan")
        if not RE_TITULO_MUR.search(titulo):
            # La fecha del título se reemplaza para que el informe agrupe archivos del mismo origen
            generico = re.sub(r"\d{4}-\d{2}-\d{2}", "AAAA-MM-DD", titulo)
            motivo = f"no es MUR (título: {generico[:50]!r})"
        elif not abs(paso - PASO_MUR) < 1e-4:
            motivo = f"grilla de {paso:g}° (se espera {PASO_MUR}°)"
    except Exception as e:
        motivo = f"no se pudo leer: {type(e).__name__}"
    _motivos_rechazo[ruta] = motivo
    return motivo


def archivos_mur(clave: str) -> dict[str, Path]:
    """Todas las fechas con archivo en disco (válido o no): {fecha_iso: ruta}."""
    cfg = PRODUCTOS_MUR[clave]
    if not cfg["directorio"].is_dir():
        return {}
    encontradas = {}
    for p in cfg["directorio"].iterdir():
        m = cfg["patron"].match(p.name)
        iso = compacta_a_iso(m.group(1)) if m else None
        if iso and p.is_file():
            encontradas[iso] = p
    return encontradas


def fuentes_mur(clave: str, dias: int) -> list[tuple[str, Path]]:
    """Las `dias` fechas más recientes con archivo MUR VÁLIDO, de más nueva a más vieja.
    Un archivo rechazado no ocupa lugar en la ventana: se toma el siguiente válido."""
    out = []
    for iso, ruta in sorted(archivos_mur(clave).items(), reverse=True):
        if motivo_rechazo(ruta) is None:
            out.append((iso, ruta))
            if len(out) == dias:
                break
    return out


def informe_rechazos() -> None:
    """Resumen de archivos dejados afuera, agrupados por motivo."""
    por_motivo: dict[str, list[str]] = {}
    for ruta, motivo in _motivos_rechazo.items():
        if motivo:
            m = re.search(r"\d{8}", ruta.name)
            por_motivo.setdefault(f"{ruta.parent.name}: {motivo}", []).append(m.group() if m else ruta.name)
    if por_motivo:
        print("\nArchivos NO publicados (no son MUR 0,01°):")
        for motivo, fechas in sorted(por_motivo.items()):
            fechas.sort()
            print(f"  {len(fechas):>3} · {motivo} · {fechas[0]} → {fechas[-1]}")


def exportar_mur(clave: str, salida: Path, dias: int, formato: str, forzar: bool) -> tuple[dict, list[str]]:
    cfg = PRODUCTOS_MUR[clave]
    carpeta = salida / clave
    fechas, errores = [], []

    for iso, ruta in fuentes_mur(clave, dias):
        png = carpeta / f"{clave}_{iso}.png"
        bin_ = carpeta / f"{clave}_{iso}.bin.gz"
        try:
            geo = leer_geometria(ruta)
            vigente = (
                not forzar and png.exists() and bin_.exists()
                and min(png.stat().st_mtime, bin_.stat().st_mtime) >= ruta.stat().st_mtime
            )
            if vigente:
                grilla = meta_grilla_desde_geometria(geo)
                estado = "ya estaba"
            else:
                campo, n_fuera = leer_campo(ruta, cfg["variables"], cfg["rango_valido"])
                warp = reproyectar(campo, geo)
                img = png_paleta(warp, cfg["stops"]) if formato == "paleta" else png_rgba(warp, cfg["stops"])
                datos_bin, grilla = grilla_clic(campo)
                # Primero la grilla, al final el PNG: si algo falla en el medio, "vigente" da False.
                escribir_atomico(bin_, lambda f: f.write(datos_bin))
                guardar_png(img, png)
                estado = "ok" + (f" ({n_fuera} valores fuera de rango descartados)" if n_fuera else "")
            fechas.append({
                "fecha": iso,
                "png": f"{clave}/{png.name}",
                "grilla_archivo": f"{clave}/{bin_.name}",
                "limites": limites_overlay(geo),
                "grilla": grilla,
            })
            print(f"  [{clave}] {iso} — {estado}")
        except Exception as e:                      # un archivo roto no frena a los demás
            errores.append(f"{clave} {iso}: {e}")
            print(f"  [{clave}] {iso} — ERROR: {e}")

    producto = {
        "titulo": cfg["titulo"],
        "unidad": cfg["unidad"],
        "decimales": cfg["decimales"],
        "stops": [[v, c] for v, c in cfg["stops"]],
        "fechas": sorted(fechas, key=lambda d: d["fecha"], reverse=True),
    }
    return producto, errores


# ──────────────────────────────────────────────────────────
# COLOR REAL (MODIS / VIIRS) Y FRENTE
# ──────────────────────────────────────────────────────────
def exportar_color_real(salida: Path, prefijo_cache: str, clave: str, dias: int, forzar: bool) -> tuple[dict, list[str]]:
    carpeta = salida / clave
    patron = re.compile(rf"^{prefijo_cache}_(\d{{4}}-\d{{2}}-\d{{2}})\.jpg$")
    disponibles = {}
    if CACHE_DIR.is_dir():
        for p in CACHE_DIR.iterdir():
            m = patron.match(p.name)
            if m and compacta_a_iso(m.group(1).replace("-", "")):
                disponibles[m.group(1)] = p
    fechas, errores = [], []
    for iso, src in sorted(disponibles.items(), reverse=True)[:dias]:
        dst = carpeta / f"{clave}_{iso}.jpg"
        try:
            with Image.open(src) as im:
                im.verify()                         # descarta JPG truncados
            if forzar or not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
                carpeta.mkdir(parents=True, exist_ok=True)
                escribir_atomico(dst, lambda f: f.write(src.read_bytes()))
            fechas.append({"fecha": iso, "archivo": f"{clave}/{dst.name}"})
            print(f"  [{clave}] {iso} — ok")
        except Exception as e:
            errores.append(f"{clave} {iso}: {e}")
            print(f"  [{clave}] {iso} — ERROR: {e}")
    return {"limites": [[BBOX_COLOR_REAL["sur"], BBOX_COLOR_REAL["oeste"]],
                        [BBOX_COLOR_REAL["norte"], BBOX_COLOR_REAL["este"]]],
            "fechas": fechas}, errores


def exportar_frente(salida: Path, dias: int, forzar: bool) -> tuple[dict, list[str]]:
    carpeta = salida / "frente"
    items = []
    if FRENTE_DIR.is_dir():
        for p in FRENTE_DIR.iterdir():
            m = RE_FRENTE.match(p.name)
            iso = compacta_a_iso(m.group(2)) if m else None
            if iso:
                items.append((iso, m.group(1), m.group(3), p))
    fechas_ok = sorted({i[0] for i in items}, reverse=True)[:dias]
    out, errores = [], []
    for iso, sat, calidad, src in sorted(items, reverse=True):
        if iso not in fechas_ok:
            continue
        dst = carpeta / src.name
        try:
            with Image.open(src) as im:
                im.verify()
            if forzar or not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
                carpeta.mkdir(parents=True, exist_ok=True)
                escribir_atomico(dst, lambda f: f.write(src.read_bytes()))
            out.append({"fecha": iso, "satelite": sat, "calidad": calidad, "archivo": f"frente/{dst.name}"})
        except Exception as e:
            errores.append(f"frente {src.name}: {e}")
    print(f"  [frente] {len(out)} imágenes")
    return {"fechas": out}, errores


# ──────────────────────────────────────────────────────────
# SERIES EN PUNTOS COSTEROS
# ──────────────────────────────────────────────────────────
def extraer_puntos(ruta: Path, variables: tuple[str, ...], rango: tuple[float, float]) -> tuple[dict, dict]:
    """Valor de cada punto costero en un NC4. Lee solo una ventana chica alrededor de cada punto.

    Devuelve ({id: valor o None}, {id: aviso}). Regla:
      1. promedio de las celdas de mar del 3x3 alrededor de la celda más cercana;
      2. si son todas tierra: la celda de mar más cercana a menos de PUNTO_RADIO_KM (con aviso);
      3. si no hay: None (con aviso). Nunca se interpola desde tierra.
    """
    import xarray as xr

    valores, avisos = {}, {}
    with xr.open_dataset(ruta) as ds:
        var = next((v for v in variables if v in ds.data_vars), None)
        if var is None:
            raise ValueError(f"No encuentro {variables}. Variables: {list(ds.data_vars)}")
        nlat = _nombre_coord(ds, ("lat", "latitude"))
        nlon = _nombre_coord(ds, ("lon", "longitude"))
        lat = np.asarray(ds[nlat].values, dtype="float64")
        lon = np.asarray(ds[nlon].values, dtype="float64")
        dlat, dlon = abs(_paso_regular(lat, "latitud")), abs(_paso_regular(lon, "longitud"))
        r = int(np.ceil(PUNTO_RADIO_KM / (dlat * 111.0))) + 1          # celdas a leer alrededor

        for pid, _, plat, plon in PUNTOS_COSTEROS:
            fuera = not (lat.min() - dlat <= plat <= lat.max() + dlat and lon.min() - dlon <= plon <= lon.max() + dlon)
            if fuera:
                valores[pid], avisos[pid] = None, "fuera de la región del archivo"
                continue
            i0, j0 = int(np.argmin(np.abs(lat - plat))), int(np.argmin(np.abs(lon - plon)))
            si = slice(max(i0 - r, 0), i0 + r + 1)
            sj = slice(max(j0 - r, 0), j0 + r + 1)
            sub = np.asarray(ds[var].isel({nlat: si, nlon: sj}).squeeze().values, dtype="float64")
            if sub.ndim != 2:
                raise ValueError(f"forma inesperada {sub.shape} en {pid}")
            sub_lat, sub_lon = lat[si], lon[sj]
            if np.isfinite(sub).any() and np.nanmean(sub) > 100:      # Kelvin
                sub = sub - 273.15
            lo, hi = rango
            sub = np.where(np.isfinite(sub) & (sub >= lo) & (sub <= hi), sub, np.nan)

            ci, cj = i0 - si.start, j0 - sj.start
            k = PUNTO_VENTANA
            ventana = sub[max(ci - k, 0): ci + k + 1, max(cj - k, 0): cj + k + 1]
            if np.isfinite(ventana).any():
                valores[pid] = float(np.nanmean(ventana))
                continue
            # Plan B: la celda de mar más cercana (distancia en km, aproximación plana: válida a 5 km)
            gi, gj = np.meshgrid(sub_lat, sub_lon, indexing="ij")
            dist = np.hypot((gi - plat) * 111.0, (gj - plon) * 111.0 * np.cos(np.radians(plat)))
            dist = np.where(np.isfinite(sub), dist, np.inf)
            m = np.unravel_index(int(np.argmin(dist)), dist.shape)
            if np.isfinite(dist[m]) and dist[m] <= PUNTO_RADIO_KM:
                valores[pid] = float(sub[m])
                avisos[pid] = f"sin mar en 3x3; se usó la celda de mar más cercana a {dist[m]:.1f} km"
            else:
                valores[pid] = None
                avisos[pid] = f"sin celdas de mar a menos de {PUNTO_RADIO_KM:g} km"
    return valores, avisos


def _leer_cache_puntos() -> dict:
    """{(producto, fecha): {punto: valor o None}}"""
    import csv

    cache: dict = {}
    if CACHE_PUNTOS.exists():
        with open(CACHE_PUNTOS, newline="", encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                v = fila["valor"]
                cache.setdefault((fila["producto"], fila["fecha"]), {})[fila["punto"]] = float(v) if v else None
    return cache


def _escribir_cache_puntos(cache: dict) -> None:
    import csv, io

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["producto", "fecha", "punto", "valor"])
    for (prod, fecha) in sorted(cache):
        for pid, v in sorted(cache[(prod, fecha)].items()):
            w.writerow([prod, fecha, pid, "" if v is None else f"{v:.4f}"])
    escribir_atomico(CACHE_PUNTOS, lambda f: f.write(buf.getvalue().encode("utf-8")))


def exportar_puntos(salida: Path, dias: int, forzar: bool) -> tuple[dict | None, list[str]]:
    """Actualiza la caché con las fechas nuevas y publica puntos.json (últimos `dias` días)."""
    ids = {p[0] for p in PUNTOS_COSTEROS}
    cache = {} if forzar else _leer_cache_puntos()
    errores: list[str] = []
    avisos_por_punto: dict[str, set[str]] = {}
    nuevas = purgadas = 0

    for clave in ("sst", "anom"):
        cfg = PRODUCTOS_MUR[clave]
        for iso, ruta in fuentes_mur(clave, 10_000):             # todas las fechas en disco
            previo = cache.get((clave, iso))
            if previo is not None and set(previo) == ids:
                continue                                          # ya calculada con estos mismos puntos
            try:
                valores, avisos = extraer_puntos(ruta, cfg["variables"], cfg["rango_valido"])
                cache[(clave, iso)] = valores
                nuevas += 1
                for pid, a in avisos.items():
                    avisos_por_punto.setdefault(pid, set()).add(a)
            except Exception as e:
                errores.append(f"puntos {clave} {iso}: {e}")

    # Valores calculados antes con archivos que hoy se rechazan (p. ej. OSTIA): fuera de la caché.
    # Las fechas cuyo archivo ya no está en disco se conservan (la caché guarda la historia).
    for clave in ("sst", "anom"):
        for iso, ruta in archivos_mur(clave).items():
            if motivo_rechazo(ruta) is not None and cache.pop((clave, iso), None) is not None:
                purgadas += 1

    # Puntos que se sacaron de la lista: fuera de la caché también.
    for k in cache:
        cache[k] = {pid: v for pid, v in cache[k].items() if pid in ids}
    if nuevas or purgadas or forzar:
        _escribir_cache_puntos(cache)
    if purgadas:
        print(f"  [puntos] {purgadas} fecha(s) quitadas de la caché: venían de archivos que no son MUR 0,01°")

    nombres = {p[0]: p[1] for p in PUNTOS_COSTEROS}
    for pid, avs in sorted(avisos_por_punto.items()):
        print(f"  [puntos] ⚠ {nombres[pid]}: {'; '.join(sorted(avs))}")
    print(f"  [puntos] {nuevas} archivo(s) nuevo(s) procesado(s)")

    fechas_con_dato = sorted({f for (_, f) in cache})
    if not fechas_con_dato:
        return None, errores
    from datetime import date, timedelta

    ultima = date.fromisoformat(fechas_con_dato[-1])
    eje = [(ultima - timedelta(days=d)).isoformat() for d in range(dias - 1, -1, -1)]   # diario y continuo

    def serie(clave: str, pid: str) -> list:
        out = []
        for f in eje:
            v = cache.get((clave, f), {}).get(pid)
            out.append(None if v is None else round(v, 2))
        return out

    datos = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fuente": "MUR-GHRSST (NASA/JPL), promedio de celdas de mar en ~3 km alrededor del punto",
        "fechas": eje,
        "puntos": [
            {"id": pid, "nombre": nombre, "lat": lat, "lon": lon, "sst": serie("sst", pid), "anom": serie("anom", pid)}
            for pid, nombre, lat, lon in PUNTOS_COSTEROS
        ],
    }
    escribir_json(salida / "puntos.json", datos)
    return {"archivo": "puntos.json", "desde": eje[0], "hasta": eje[-1]}, errores


# ──────────────────────────────────────────────────────────
# LIMPIEZA E ÍNDICE
# ──────────────────────────────────────────────────────────
_PATRONES_PROPIOS = {
    "sst": re.compile(r"^sst_\d{4}-\d{2}-\d{2}\.(png|bin\.gz)$"),
    "anom": re.compile(r"^anom_\d{4}-\d{2}-\d{2}\.(png|bin\.gz)$"),
    "modis": re.compile(r"^modis_\d{4}-\d{2}-\d{2}\.jpg$"),
    "viirs": re.compile(r"^viirs_\d{4}-\d{2}-\d{2}\.jpg$"),
    "frente": RE_FRENTE,
}


def archivos_referenciados(indice: dict) -> set[str]:
    refs: set[str] = set()
    for clave in ("sst", "anom"):
        for f in indice["productos"][clave]["fechas"]:
            refs.update((f["png"], f["grilla_archivo"]))
    for clave in ("modis", "viirs", "frente"):
        refs.update(f["archivo"] for f in indice["productos"][clave]["fechas"])
    return refs


def limpiar(salida: Path, refs: set[str]) -> int:
    borrados = 0
    for sub, patron in _PATRONES_PROPIOS.items():
        carpeta = salida / sub
        if not carpeta.is_dir():
            continue
        for p in carpeta.iterdir():
            if p.is_file() and patron.match(p.name) and f"{sub}/{p.name}" not in refs:
                p.unlink()
                borrados += 1
    return borrados


def escribir_json(destino: Path, obj: dict) -> None:
    texto = json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    escribir_atomico(destino, lambda f: f.write(texto.encode("utf-8")))


# ──────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Exporta los productos satelitales a archivos estáticos.")
    ap.add_argument("--salida", type=Path, default=SALIDA)
    ap.add_argument("--dias", type=int, default=DIAS_DEFAULT, help="cantidad de fechas por producto")
    ap.add_argument("--formato", choices=("paleta", "rgba"), default="paleta")
    ap.add_argument("--dias-serie", type=int, default=DIAS_SERIE_PUNTOS, help="días de las series en puntos costeros")
    ap.add_argument("--forzar", action="store_true", help="regenerar aunque ya exista (necesario si cambia --formato)")
    args = ap.parse_args(argv)
    if args.dias < 1 or args.dias_serie < 1:
        ap.error("--dias y --dias-serie deben ser >= 1")

    salida = args.salida.resolve()
    print(f"\nexportar_satelite — datos: {DATOS} → salida: {salida}")
    print(f"  {args.dias} fechas por producto · PNG {args.formato} · clic stride {GRILLA_STRIDE}\n")

    errores: list[str] = []
    productos: dict = {}
    for clave in ("sst", "anom"):
        productos[clave], e = exportar_mur(clave, salida, args.dias, args.formato, args.forzar)
        errores += e
    productos["modis"], e = exportar_color_real(salida, "modis_truecolor", "modis", args.dias, args.forzar)
    errores += e
    productos["viirs"], e = exportar_color_real(salida, "viirs", "viirs", args.dias, args.forzar)
    errores += e
    productos["frente"], e = exportar_frente(salida, args.dias, args.forzar)
    errores += e
    puntos, e = exportar_puntos(salida, args.dias_serie, args.forzar)
    errores += e

    informe_rechazos()                                   # antes de cualquier salida temprana
    faltan = [str(d) for d in (NC4_DIR, ANOM_DIR, CACHE_DIR, FRENTE_DIR) if not d.is_dir()]
    if faltan:
        print("\nAVISO: no existen estas carpetas de origen:")
        for d in faltan:
            print(f"  - {d}")
    if not any(p["fechas"] for p in productos.values()):
        print("\nERROR: no se encontró ningún dato para publicar. "
              "No se modificó el índice anterior.")
        return 1

    indice = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "productos": productos,
        "puntos": puntos,                                   # None si no hay series
    }
    borrados = limpiar(salida, archivos_referenciados(indice))
    escribir_json(salida / "indice.json", indice)          # siempre al final

    print("\nResumen")
    for clave, p in productos.items():
        print(f"  {clave:<7} {len(p['fechas'])} fechas")
    if puntos:
        print(f"  puntos  {len(PUNTOS_COSTEROS)} puntos, {puntos['desde']} → {puntos['hasta']}")
    if borrados:
        print(f"  Eliminados {borrados} archivos fuera de ventana")
    if errores:
        print(f"\n{len(errores)} error(es):")
        for e in errores:
            print(f"  - {e}")
        return 1
    print("\nListo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())