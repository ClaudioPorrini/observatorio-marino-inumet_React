import { useEffect, useState } from 'react'
import { cargarIndiceSatelite } from './data'
import type { IndiceSatelite } from './types'

export type EstadoIndice =
  | { tipo: 'cargando' }
  | { tipo: 'error'; mensaje: string }
  | { tipo: 'listo'; indice: IndiceSatelite }

/** Hook: carga satelite/indice.json una vez, al montar la pestaña. */
export function useIndiceSatelite(): EstadoIndice {
  const [estado, setEstado] = useState<EstadoIndice>({ tipo: 'cargando' })

  useEffect(() => {
    const control = new AbortController()
    cargarIndiceSatelite(control.signal)
      .then((indice) => setEstado({ tipo: 'listo', indice }))
      .catch((e: unknown) => {
        if (control.signal.aborted) return
        setEstado({ tipo: 'error', mensaje: e instanceof Error ? e.message : String(e) })
      })
    return () => control.abort()
  }, [])

  return estado
}
