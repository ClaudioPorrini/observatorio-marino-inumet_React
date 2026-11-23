// Forma de los datos que escribe pipeline/exportar_observaciones.py.
// Si cambia el exportador, se cambia acá (y el compilador marca todo lo afectado).
//
// OJO: TypeScript solo existe al compilar. Lo que llega por red es JSON sin
// verificar; por eso data.ts tiene además una comprobación en tiempo de ejecución.

export interface UltimoValor {
  label: string // "Temperatura del aire"
  unit: string | null // "°C"
  value: number
  time: string // "2026-11-20T16:00:00Z" (UTC)
}

export interface Estacion {
  station_id: string
  name: string
  institution: string
  site_type: string | null
  lat: number | null
  lon: number | null
  last_time: string | null // null si no tiene datos en la ventana
  latest: Record<string, UltimoValor> // clave = variable ("air_temperature", ...)
}

/** Serie HORARIA de una variable: t = segundos desde 1970 (UTC), v = valor. Solo horas con dato. */
export interface SerieVariable {
  label: string
  unit: string | null
  t: number[]
  v: number[]
}

export interface SerieJson {
  station_id: string
  generated_at: string
  variables: Record<string, SerieVariable>
}

export interface EstacionesJson {
  generated_at: string
  window_days: number
  stations: Estacion[]
}

// ── Satélite: forma de public/satelite/indice.json (pipeline/exportar_satelite.py) ──

/** [[sur, oeste], [norte, este]] en grados: lo que pide L.imageOverlay. */
export type Limites = [[number, number], [number, number]]

/** [valor, "#rrggbb"]: la escala de colores, definida una sola vez en el exportador. */
export type Parada = [number, string]

export interface GrillaMeta {
  lat_norte: number // latitud del centro de la fila 0
  lon_oeste: number // longitud del centro de la columna 0
  dlat: number
  dlon: number
  filas: number
  columnas: number
  escala: number // el Int16 guardado = valor * escala
  sin_dato: number // Int16 que marca tierra / sin dato
}

export interface FechaMur {
  fecha: string // "2026-11-20"
  png: string // ruta relativa a /satelite/
  grilla_archivo: string
  limites: Limites
  grilla: GrillaMeta
}

export interface ProductoMur {
  titulo: string
  unidad: string
  decimales: number
  stops: Parada[]
  fechas: FechaMur[] // de la más nueva a la más vieja
}

export interface ProductoColorReal {
  limites: Limites
  fechas: { fecha: string; archivo: string }[]
}

export interface FechaFrente {
  fecha: string
  satelite: 'aqua' | 'terra'
  calidad: 'clear' | 'cloudy'
  archivo: string
}

/** Serie diaria en un punto costero. Mismo largo que PuntosJson.fechas; null = sin dato ese día. */
export interface PuntoCostero {
  id: string
  nombre: string
  lat: number
  lon: number
  sst: (number | null)[]
  anom: (number | null)[]
}

export interface PuntosJson {
  generated_at: string
  fuente: string
  fechas: string[] // diarias y continuas, de la más vieja a la más nueva
  puntos: PuntoCostero[]
}

export interface IndiceSatelite {
  generated_at: string
  puntos?: { archivo: string; desde: string; hasta: string } | null
  productos: {
    sst: ProductoMur
    anom: ProductoMur
    modis: ProductoColorReal
    viirs: ProductoColorReal
    frente: { fechas: FechaFrente[] }
  }
}
