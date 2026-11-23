import { useEffect, useState } from 'react'
import { cargarPuntos } from './data'
import type { PuntosJson } from './types'

export type EstadoPuntos =
  | { tipo: 'no_hay' } // el índice no trae series
  | { tipo: 'cargando' }
  | { tipo: 'error'; mensaje: string }
  | { tipo: 'listo'; puntos: PuntosJson }

/** Carga satelite/puntos.json si el índice lo menciona. */
export function usePuntos(archivo: string | null): EstadoPuntos {
  const [estado, setEstado] = useState<EstadoPuntos>({ tipo: archivo ? 'cargando' : 'no_hay' })

  useEffect(() => {
    if (!archivo) return setEstado({ tipo: 'no_hay' })
    setEstado({ tipo: 'cargando' })
    const control = new AbortController()
    cargarPuntos(archivo, control.signal)
      .then((puntos) => setEstado({ tipo: 'listo', puntos }))
      .catch((e: unknown) => {
        if (control.signal.aborted) return
        setEstado({ tipo: 'error', mensaje: e instanceof Error ? e.message : String(e) })
      })
    return () => control.abort()
  }, [archivo])

  return estado
}
