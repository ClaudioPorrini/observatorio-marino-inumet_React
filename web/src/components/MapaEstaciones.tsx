import { useEffect, useRef } from 'react'
import * as L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { TILES_ATRIBUCION, TILES_URL } from '../config'
import type { Estacion } from '../types'

interface Props {
  estaciones: Estacion[]
  seleccionada: string | null
  onSeleccionar: (stationId: string) => void
}

const conCoordenadas = (e: Estacion): e is Estacion & { lat: number; lon: number } =>
  typeof e.lat === 'number' && typeof e.lon === 'number'

/** Mapa de estaciones. Clic en un punto = elegir la estación (lo mismo que en la tabla). */
export default function MapaEstaciones({ estaciones, seleccionada, onSeleccionar }: Props) {
  const contenedor = useRef<HTMLDivElement>(null)
  const mapaRef = useRef<L.Map | null>(null)
  const capaRef = useRef<L.LayerGroup | null>(null)
  const alElegir = useRef(onSeleccionar)
  alElegir.current = onSeleccionar

  const ubicadas = estaciones.filter(conCoordenadas)

  // 1) Crear el mapa una vez y encuadrar las estaciones.
  useEffect(() => {
    const el = contenedor.current
    if (!el) return
    const mapa = L.map(el, { zoomSnap: 0.25 })
    if (TILES_URL) L.tileLayer(TILES_URL, { attribution: TILES_ATRIBUCION, maxZoom: 14 }).addTo(mapa)
    const puntos = estaciones.filter(conCoordenadas).map((e) => L.latLng(e.lat, e.lon))
    if (puntos.length > 1) mapa.fitBounds(L.latLngBounds(puntos), { padding: [30, 30] })
    else if (puntos[0]) mapa.setView(puntos[0], 9)
    capaRef.current = L.layerGroup().addTo(mapa)
    mapaRef.current = mapa
    return () => {
      mapa.remove()
      mapaRef.current = null
      capaRef.current = null
    }
    // El encuadre se hace solo al crear el mapa (no salta cada vez que cambian los datos).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 2) Dibujar los puntos (pocos: se rehacen enteros al cambiar la selección).
  useEffect(() => {
    const capa = capaRef.current
    if (!capa) return
    capa.clearLayers()
    let elegido: L.CircleMarker | null = null
    for (const e of estaciones.filter(conCoordenadas)) {
      const esta = e.station_id === seleccionada
      const m = L.circleMarker([e.lat, e.lon], {
        radius: esta ? 9 : 7,
        weight: esta ? 3 : 1.5,
        color: '#193b42',
        fillColor: e.last_time ? '#3bb0c9' : '#5b6b70', // gris: sin datos recientes
        fillOpacity: 0.9,
      })
      // Texto como nodo DOM: el nombre no se interpreta como HTML.
      const rotulo = document.createElement('span')
      rotulo.textContent = e.last_time ? e.name : `${e.name} (sin datos recientes)`
      m.bindTooltip(rotulo, { direction: 'top', offset: [0, -6] })
      m.on('click', () => alElegir.current(e.station_id))
      m.addTo(capa)
      if (esta) elegido = m
    }
    elegido?.bringToFront()
  }, [estaciones, seleccionada])

  if (ubicadas.length === 0) return null
  return <div ref={contenedor} className="mapa mapa-estaciones" role="region" aria-label="Mapa de estaciones" />
}
