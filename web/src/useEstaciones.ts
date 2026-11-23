import { useEffect, useState } from 'react'
import { cargarEstaciones } from './data'
import type { EstacionesJson } from './types'

// Los tres estados posibles de una carga. Al ser una unión etiquetada, el compilador
// obliga a tratar cada caso: no se puede leer `datos` mientras está cargando.
export type Estado =
  | { tipo: 'cargando' }
  | { tipo: 'error'; mensaje: string }
  | { tipo: 'listo'; datos: EstacionesJson }

/** Hook: carga estaciones.json una vez, al montar el componente. */
export function useEstaciones(): Estado {
  const [estado, setEstado] = useState<Estado>({ tipo: 'cargando' })

  useEffect(() => {
    const control = new AbortController()
    cargarEstaciones(control.signal)
      .then((datos) => setEstado({ tipo: 'listo', datos }))
      .catch((e: unknown) => {
        if (control.signal.aborted) return // el componente se desmontó: no es un error
        setEstado({ tipo: 'error', mensaje: e instanceof Error ? e.message : String(e) })
      })
    return () => control.abort() // limpieza al desmontar
  }, [])

  return estado
}
