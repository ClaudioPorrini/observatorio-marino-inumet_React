#!/usr/bin/env python3
"""
diagnostico_nc4.py — agrupa los NC4 de MUR por formato (forma, resolución, origen) para detectar mezclas.

Solo lee; no modifica nada. Uso (desde la raíz del proyecto):
    python pipeline/diagnostico_nc4.py "../Estación marítima/data"
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import xarray as xr

datos = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
for sub in ("raw/nc4", "raw/nc4_anom"):
    carpeta = datos / sub
    grupos = defaultdict(list)
    for f in sorted(carpeta.glob("MUR_*.nc*")):
        m = re.search(r"\d{8}", f.name)
        try:
            with xr.open_dataset(f) as ds:
                nlat = "lat" if "lat" in ds.coords else "latitude"
                nlon = "lon" if "lon" in ds.coords else "longitude"
                var = next(iter(ds.data_vars))
                lat, lon = ds[nlat].values, ds[nlon].values
                clave = (
                    var,
                    ds[var].shape,
                    round(float(abs(np.diff(lat[:2])[0])), 4),
                    f"lat {lat.min():.2f}..{lat.max():.2f} lon {lon.min():.2f}..{lon.max():.2f}",
                    str(ds.attrs.get("title", ds.attrs.get("id", "sin título")))[:70],
                    str(ds[var].attrs.get("units", "?")),
                )
        except Exception as e:
            clave = ("ERROR", type(e).__name__, str(e)[:60])
        grupos[clave].append(m.group() if m else f.name)

    print(f"\n══ {carpeta}  ({sum(len(v) for v in grupos.values())} archivos)")
    for clave, fechas in sorted(grupos.items(), key=lambda kv: -len(kv[1])):
        print(f"\n  {len(fechas)} archivos · {fechas[0]} → {fechas[-1]}")
        for etiqueta, valor in zip(("variable", "forma", "paso °", "región", "título", "unidad"), clave):
            print(f"     {etiqueta:<9} {valor}")
        if len(fechas) <= 40:
            print(f"     fechas    {' '.join(fechas)}")