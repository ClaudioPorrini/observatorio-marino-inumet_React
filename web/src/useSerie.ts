import { useEffect, useState } from 'react'
import { cargarSerie } from './data'
import type { SerieJson } from './types'

export type EstadoSerie =
  | { tipo: 'sin_datos' } // la estación no tiene mediciones en la ventana: no hay archivo
  | { tipo: 'cargando' }
  | { tipo: 'error'; mensaje: string }
  | { tipo: 'listo'; serie: SerieJson }

// Las series ya leídas quedan en memoria mientras la página está abierta:
// volver a una estación no la descarga otra vez.
const cache = new Map<string, SerieJson>()

/** Carga observaciones/series/<id>.json cuando cambia la estación elegida. */
export function useSerie(stationId: string, tieneDatos: boolean): EstadoSerie {
  const [estado, setEstado] = useState<EstadoSerie>({ tipo: 'cargando' })

  useEffect(() => {
    if (!tieneDatos) return setEstado({ tipo: 'sin_datos' })
    const enCache = cache.get(stationId)
    if (enCache) return setEstado({ tipo: 'listo', serie: enCache })

    setEstado({ tipo: 'cargando' })
    const control = new AbortController()
    cargarSerie(stationId, control.signal)
      .then((serie) => {
        cache.set(stationId, serie)
        setEstado({ tipo: 'listo', serie })
      })
      .catch((e: unknown) => {
        if (control.signal.aborted) return // cambió la estación antes de terminar: no es un error
        setEstado({ tipo: 'error', mensaje: e instanceof Error ? e.message : String(e) })
      })
    return () => control.abort()
  }, [stationId, tieneDatos])

  return estado
}
