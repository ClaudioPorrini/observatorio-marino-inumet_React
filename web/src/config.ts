// Única fuente de verdad de la configuración de la web.

// ── Dónde están los datos ───────────────────────────────────────────────
// Se cambia con la variable VITE_DATA_BASE_URL (ver .env.example). Sin ella, usa
// rutas relativas a la página, es decir, los datos en el mismo servidor.
const base: string =
  (import.meta.env.VITE_DATA_BASE_URL as string | undefined) || import.meta.env.BASE_URL

export const ESTACIONES_URL = `${base.replace(/\/$/, '')}/observaciones/estaciones.json`
export const serieUrl = (stationId: string) =>
  `${base.replace(/\/$/, '')}/observaciones/series/${encodeURIComponent(stationId)}.json`

// ── Satélite ────────────────────────────────────────────────────────────
// Todo lo que exporta pipeline/exportar_satelite.py vive bajo /satelite/ (con indice.json).
export const SATELITE_BASE = `${base.replace(/\/$/, '')}/satelite`
export const SATELITE_INDICE_URL = `${SATELITE_BASE}/indice.json`

// Una imagen más vieja que esto (en días) se marca como atrasada. MUR llega con 1-2 días de demora.
export const DIAS_ATRASADO_SAT = 3

// Mapa base. Es el ÚNICO recurso externo de la web: el servidor del mapa tiene que estar
// permitido en la CSP (img-src). VITE_TILES_URL vacío = sin mapa base (solo la capa satelital).
// Si no se define, usa OpenStreetMap.
export const TILES_URL: string =
  (import.meta.env.VITE_TILES_URL as string | undefined) ?? 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
export const TILES_ATRIBUCION: string =
  (import.meta.env.VITE_TILES_ATRIBUCION as string | undefined) ?? '© OpenStreetMap'

// ── Horas ───────────────────────────────────────────────────────────────
// Convención meteorológica: UTC (igual que el header de Streamlit).
// Para hora de Uruguay: TIMEZONE = 'America/Montevideo', ETIQUETA_TZ = 'hora local'.
export const TIMEZONE = 'UTC'
export const ETIQUETA_TZ = 'UTC'

// Un valor más viejo que esto se marca como "atrasado" en la tabla.
export const HORAS_ATRASADO = 6
