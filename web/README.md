# Observatorio Marino y Costero del Uruguay — web (React + TypeScript)

Front **estático**: se compila a HTML/JS/CSS y no ejecuta nada en el servidor. Lee los
archivos que exporta el pipeline de Python (`../pipeline/`). No hay base de datos ni
procesos Python expuestos.

```
pipeline (Python, servidor interno)  →  public/observaciones/*.json  →  web (React, solo lee)
```

## Requisitos

Node **20.19+ o 22.12+** (se probó con 22; `.nvmrc` indica 22).
Con conda: `conda install -c conda-forge nodejs=22`. Alternativa: nvm.

## Uso

```bash
cd web
npm ci               # instala EXACTAMENTE lo que fija package-lock.json
npm run dev          # http://localhost:5173  (lee ../public/observaciones/*.json)
npm run typecheck    # chequeo de tipos
npm run build        # genera dist/  (tsc + vite build)
npm audit            # auditoría de dependencias
```

Antes de `npm run dev`, generar los datos (desde la raíz del proyecto):
`python pipeline/exportar_observaciones.py`

## Estructura

| Archivo | Qué hace |
|---|---|
| `src/config.ts` | URL de los datos, zona horaria (UTC), umbral de "atrasado" (6 h) |
| `src/types.ts` | Forma del JSON del exportador |
| `src/data.ts` | `fetch` de `estaciones.json` + validación de forma |
| `src/useEstaciones.ts` | Hook: carga → estados `cargando / error / listo` |
| `src/format.ts` | Fechas, edad, números, rumbo cardinal |
| `src/App.tsx` | Pestañas y estado general |
| `src/data.ts` (satélite) | `indice.json` con validación; solo acepta rutas relativas simples |
| `src/useSerie.ts`, `src/serie.ts` | Carga de `series/<id>.json` (con caché) y cálculos de los gráficos (recorte, huecos, acumulado diario, marcas de ejes) |
| `src/usePuntos.ts`, `src/colores.ts` | Series diarias en puntos costeros (`satelite/puntos.json`) y paleta validada para comparar hasta 5 |
| `src/grilla.ts` | Lee la grilla de clic (Int16 gzip) y busca el valor en un punto |
| `src/escala.ts` | Color de un valor y barra de la leyenda (la escala viene de `indice.json`) |
| `src/components/` | `Header`, `Observaciones` (tabla + detalle), `MapaEstaciones`, `GraficoSerie` (SVG propio, sin librería), `Satelite` (controles, leyenda, frente), `MapaSatelital` (Leaflet, con puntos costeros), `SeriesCosteras` + `GraficoPuntos` (TSM y anomalía por punto) |
| `src/styles.css` | Paleta PANTONE 631 C (misma que `theme_inumet.py`) |

Logo: copiar el archivo a `src/assets/inumet-logo.jpg` (o `.png` / `.svg`). Si no está, el header se ve igual sin logo.

## Decisiones

- **Dependencias mínimas, versiones exactas**: solo `react`, `react-dom` y, en desarrollo, `vite`, `@vitejs/plugin-react`, `typescript` y los tipos de React. Sin librerías de UI, de rutas ni de estado.
- **Compatible con una CSP estricta**: sin scripts ni estilos en línea, sin fuentes ni recursos externos.
- **Leaflet 1.9.4** (única dependencia nueva). Mapa base configurable (`VITE_TILES_URL`): es el único recurso externo y debe estar permitido en la CSP (`img-src`). Leaflet usa internamente un GIF `data:` de 1×1 para cancelar teselas: con una CSP sin `data:` solo produce un aviso en consola.
- **Los datos no van dentro de `dist/`**: los sirve el servidor. `VITE_DATA_BASE_URL` (ver `.env.example`) indica dónde, al hacer el build.
- **`dist/` usa rutas relativas**: funciona colgado de cualquier subruta del sitio.
- **Un valor con más de 6 h se marca como atrasado** (con texto, no solo color): hay variables cuya descarga está interrumpida y no deben leerse como actuales.
- Horas en **UTC**, como el header de la versión Streamlit.

## Estado de la migración

1. ✅ Esqueleto, tema, header, pestañas, tabla de estaciones
2. ✅ Mapa de estaciones y gráficos de series (`series/<station_id>.json`)
3. ✅ Pestaña Satélite (MUR SST/anomalía con clic, MODIS/VIIRS, frente de turbidez)
4. ⏳ Entrega a TI (`dist/` + `npm audit`)
