import type { GrillaMeta } from './types'

export interface Grilla {
  meta: GrillaMeta
  datos: Int16Array // filas x columnas, fila 0 = norte
}

async function descomprimir(buf: ArrayBuffer): Promise<ArrayBuffer> {
  const b = new Uint8Array(buf)
  // Algunos servidores ya entregan el .gz descomprimido (Content-Encoding): en ese caso no hay magia gzip.
  if (b[0] !== 0x1f || b[1] !== 0x8b) return buf
  const flujo = new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'))
  return new Response(flujo).arrayBuffer()
}

/** Descarga y decodifica una grilla de clic (Int16 little-endian, gzip). */
export async function cargarGrilla(url: string, meta: GrillaMeta, signal?: AbortSignal): Promise<Grilla> {
  const resp = await fetch(url, { signal })
  if (!resp.ok) throw new Error(`No se pudo leer ${url} (HTTP ${resp.status})`)
  const crudo = await descomprimir(await resp.arrayBuffer())
  const n = meta.filas * meta.columnas
  if (crudo.byteLength !== n * 2) throw new Error(`${url}: tamaño inesperado (${crudo.byteLength} bytes, se esperaban ${n * 2})`)
  const vista = new DataView(crudo)
  const datos = new Int16Array(n)
  for (let i = 0; i < n; i++) datos[i] = vista.getInt16(i * 2, true) // little-endian explícito
  return { meta, datos }
}

/** Valor en (lat, lon) por celda más cercana. null = sin dato (tierra) o fuera de la grilla. */
export function valorEn(g: Grilla, lat: number, lon: number): number | null {
  const m = g.meta
  const i = Math.round((m.lat_norte - lat) / m.dlat)
  const j = Math.round((lon - m.lon_oeste) / m.dlon)
  if (i < 0 || i >= m.filas || j < 0 || j >= m.columnas) return null
  const v = g.datos[i * m.columnas + j]
  return v === undefined || v === m.sin_dato ? null : v / m.escala
}
