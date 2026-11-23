import { ESTACIONES_URL, SATELITE_BASE, SATELITE_INDICE_URL, serieUrl } from './config'
import type { EstacionesJson, IndiceSatelite, PuntosJson, SerieJson } from './types'

const esObjeto = (x: unknown): x is Record<string, unknown> =>
  typeof x === 'object' && x !== null && !Array.isArray(x)

// Comprobación mínima de forma. Si el exportador cambia el formato, la web muestra
// un error claro en lugar de romperse a mitad de la tabla.
function esEstacionesJson(x: unknown): x is EstacionesJson {
  if (!esObjeto(x) || typeof x.generated_at !== 'string' || !Array.isArray(x.stations)) return false
  return x.stations.every(
    (e) =>
      esObjeto(e) &&
      typeof e.station_id === 'string' &&
      typeof e.name === 'string' &&
      typeof e.institution === 'string' &&
      esObjeto(e.latest),
  )
}

export async function cargarEstaciones(signal?: AbortSignal): Promise<EstacionesJson> {
  // no-cache: el navegador revalida con el servidor y no muestra datos viejos.
  const resp = await fetch(ESTACIONES_URL, { signal, cache: 'no-cache' })
  if (!resp.ok) throw new Error(`No se pudo leer ${ESTACIONES_URL} (HTTP ${resp.status})`)

  let datos: unknown
  try {
    datos = await resp.json()
  } catch {
    // El servidor de desarrollo responde index.html cuando falta el archivo.
    throw new Error(`${ESTACIONES_URL} no devolvió JSON. ¿Se corrió exportar_observaciones.py?`)
  }
  if (!esEstacionesJson(datos)) throw new Error('estaciones.json no tiene el formato esperado')
  return datos
}

// ── Series de una estación ──────────────────────────────────────────────

function esSerieJson(x: unknown, stationId: string): x is SerieJson {
  if (!esObjeto(x) || x.station_id !== stationId || !esObjeto(x.variables)) return false
  return Object.values(x.variables).every((s) => {
    if (!esObjeto(s) || typeof s.label !== 'string' || !Array.isArray(s.t) || !Array.isArray(s.v)) return false
    if (s.t.length !== s.v.length) return false
    for (let i = 0; i < s.t.length; i++) {
      const t = s.t[i]
      const v = s.v[i]
      if (typeof t !== 'number' || typeof v !== 'number' || !Number.isFinite(t) || !Number.isFinite(v)) return false
      if (i > 0 && t <= (s.t[i - 1] as number)) return false // los gráficos asumen tiempo creciente
    }
    return true
  })
}

export async function cargarSerie(stationId: string, signal?: AbortSignal): Promise<SerieJson> {
  const url = serieUrl(stationId)
  const resp = await fetch(url, { signal, cache: 'no-cache' })
  if (!resp.ok) throw new Error(`No se pudo leer la serie de ${stationId} (HTTP ${resp.status})`)
  let datos: unknown
  try {
    datos = await resp.json()
  } catch {
    throw new Error(`La serie de ${stationId} no devolvió JSON`)
  }
  if (!esSerieJson(datos, stationId)) throw new Error(`La serie de ${stationId} no tiene el formato esperado`)
  return datos
}

// ── Satélite ────────────────────────────────────────────────────────────

const esNumero = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x)

// Las rutas del índice se piden al servidor tal cual: solo se aceptan rutas relativas simples.
// Un índice alterado no puede hacer que la web pida otro dominio ni suba de carpeta.
const RUTA_SEGURA = /^[A-Za-z0-9_\-]+(\/[A-Za-z0-9_\-.]+)+$/
const esRuta = (x: unknown): x is string => typeof x === 'string' && RUTA_SEGURA.test(x) && !x.includes('..')
const esArchivoRaiz = (x: unknown): x is string => typeof x === 'string' && /^[A-Za-z0-9_\-]+\.json$/.test(x)
const esFecha = (x: unknown): x is string => typeof x === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(x)

function esLimites(x: unknown): boolean {
  return (
    Array.isArray(x) &&
    x.length === 2 &&
    x.every((p) => Array.isArray(p) && p.length === 2 && p.every(esNumero))
  )
}

function esGrillaMeta(x: unknown): boolean {
  if (!esObjeto(x)) return false
  return ['lat_norte', 'lon_oeste', 'dlat', 'dlon', 'filas', 'columnas', 'escala', 'sin_dato'].every((k) =>
    esNumero(x[k]),
  ) && (x.filas as number) > 0 && (x.columnas as number) > 0 && (x.escala as number) > 0
}

function esProductoMur(x: unknown): boolean {
  if (!esObjeto(x) || typeof x.titulo !== 'string' || typeof x.unidad !== 'string') return false
  if (!esNumero(x.decimales) || !Array.isArray(x.stops) || x.stops.length < 2 || !Array.isArray(x.fechas)) return false
  const stopsOk = x.stops.every(
    (s) => Array.isArray(s) && s.length === 2 && esNumero(s[0]) && typeof s[1] === 'string' && /^#[0-9a-fA-F]{6}$/.test(s[1]),
  )
  return (
    stopsOk &&
    x.fechas.every(
      (f) =>
        esObjeto(f) && esFecha(f.fecha) && esRuta(f.png) && esRuta(f.grilla_archivo) && esLimites(f.limites) && esGrillaMeta(f.grilla),
    )
  )
}

function esColorReal(x: unknown): boolean {
  return (
    esObjeto(x) &&
    esLimites(x.limites) &&
    Array.isArray(x.fechas) &&
    x.fechas.every((f) => esObjeto(f) && esFecha(f.fecha) && esRuta(f.archivo))
  )
}

function esIndiceSatelite(x: unknown): x is IndiceSatelite {
  if (!esObjeto(x) || typeof x.generated_at !== 'string' || !esObjeto(x.productos)) return false
  // `puntos` es opcional (índices viejos no lo tienen) o null (sin series todavía).
  if (x.puntos !== undefined && x.puntos !== null && !(esObjeto(x.puntos) && esArchivoRaiz(x.puntos.archivo))) return false
  const p = x.productos
  return (
    esProductoMur(p.sst) &&
    esProductoMur(p.anom) &&
    esColorReal(p.modis) &&
    esColorReal(p.viirs) &&
    esObjeto(p.frente) &&
    Array.isArray(p.frente.fechas) &&
    p.frente.fechas.every(
      (f) =>
        esObjeto(f) &&
        esFecha(f.fecha) &&
        (f.satelite === 'aqua' || f.satelite === 'terra') &&
        (f.calidad === 'clear' || f.calidad === 'cloudy') &&
        esRuta(f.archivo),
    )
  )
}

export async function cargarIndiceSatelite(signal?: AbortSignal): Promise<IndiceSatelite> {
  const resp = await fetch(SATELITE_INDICE_URL, { signal, cache: 'no-cache' })
  if (!resp.ok) throw new Error(`No se pudo leer ${SATELITE_INDICE_URL} (HTTP ${resp.status})`)
  let datos: unknown
  try {
    datos = await resp.json()
  } catch {
    throw new Error(`${SATELITE_INDICE_URL} no devolvió JSON. ¿Se corrió exportar_satelite.py?`)
  }
  if (!esIndiceSatelite(datos)) throw new Error('indice.json no tiene el formato esperado')
  return datos
}

// ── Series en puntos costeros ───────────────────────────────────────────

const esSerieDiaria = (x: unknown, n: number) =>
  Array.isArray(x) && x.length === n && x.every((v) => v === null || esNumero(v))

function esPuntosJson(x: unknown): x is PuntosJson {
  if (!esObjeto(x) || !Array.isArray(x.fechas) || !x.fechas.every(esFecha) || !Array.isArray(x.puntos)) return false
  const n = x.fechas.length
  return x.puntos.every(
    (p) =>
      esObjeto(p) &&
      typeof p.id === 'string' &&
      typeof p.nombre === 'string' &&
      esNumero(p.lat) &&
      esNumero(p.lon) &&
      esSerieDiaria(p.sst, n) &&
      esSerieDiaria(p.anom, n),
  )
}

export async function cargarPuntos(archivo: string, signal?: AbortSignal): Promise<PuntosJson> {
  const url = `${SATELITE_BASE}/${archivo}`
  const resp = await fetch(url, { signal, cache: 'no-cache' })
  if (!resp.ok) throw new Error(`No se pudo leer ${url} (HTTP ${resp.status})`)
  let datos: unknown
  try {
    datos = await resp.json()
  } catch {
    throw new Error(`${url} no devolvió JSON`)
  }
  if (!esPuntosJson(datos)) throw new Error('puntos.json no tiene el formato esperado')
  return datos
}
