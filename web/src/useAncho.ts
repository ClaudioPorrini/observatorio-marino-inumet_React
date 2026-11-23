import { useEffect, useState, type RefObject } from 'react'

/** Ancho real del contenedor: los SVG se dibujan en píxeles para que el texto no se deforme. */
export function useAncho(ref: RefObject<HTMLElement | null>, inicial = 600): number {
  const [ancho, setAncho] = useState(inicial)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => {
      if (e) setAncho(Math.max(220, Math.floor(e.contentRect.width)))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref])
  return ancho
}
