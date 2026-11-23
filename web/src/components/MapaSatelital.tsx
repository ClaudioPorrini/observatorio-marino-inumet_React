import { useEffect, useRef, useState } from 'react'
import * as L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { SATELITE_BASE, TILES_ATRIBUCION, TILES_URL } from '../config'
import { colorEnEscala } from '../escala'
import { formatoDia, formatoValor } from '../format'
import { cargarGrilla, valorEn, type Grilla } from '../grilla'
import type { FechaMur, Limites, ProductoMur } from '../types'

/** Lo que el mapa dibuja: una imagen georreferenciada y, si es MUR, de dónde sale el valor al hacer clic. */
export interface Capa {
  url: string
  limites: Limites
  mur: { clave: 'sst' | 'anom'; producto: ProductoMur; fecha: FechaMur } | null
}

export interface Marcador {
  id: string
  nombre: string
  lat: number
  lon: number
  color: string | null // null = no elegido
}

interface Props {
  capa: Capa
  opacidad: number // 0..1
  vista: Limites // encuadre inicial
  marcadores?: Marcador[] // puntos costeros
  onMarcador?: (id: string) => void
}

export const urlSatelite = (ruta: string) => `${SATELITE_BASE}/${ruta}`

function popup(titulo: string, fecha: string, lat: number, lon: number, valor: HTMLElement | string): HTMLElement {
  // DOM + textContent, nunca HTML en texto: ningún dato puede inyectar markup (y es compatible con CSP).
  const raiz = document.createElement('div')
  raiz.className = 'popup-sat'
  const t = document.createElement('strong')
  t.textContent = titulo
  const v = document.createElement('div')
  v.className = 'popup-valor'
  if (typeof valor === 'string') v.textContent = valor
  else v.appendChild(valor)
  const pie = document.createElement('small')
  pie.textContent = `${formatoDia(fecha)} · ${formatoValor(lat, 3)}°, ${formatoValor(lon, 3)}°`
  raiz.append(t, v, pie)
  return raiz
}

export default function MapaSatelital({ capa, opacidad, vista, marcadores = [], onMarcador }: Props) {
  const contenedor = useRef<HTMLDivElement>(null)
  const mapaRef = useRef<L.Map | null>(null)
  const overlayRef = useRef<L.ImageOverlay | null>(null)
  const marcadorRef = useRef<L.CircleMarker | null>(null)
  const capaRef = useRef(capa)
  const opacidadRef = useRef(opacidad)
  const grillas = useRef(new Map<string, Promise<Grilla>>())
  const puntosRef = useRef<L.LayerGroup | null>(null)
  const alMarcador = useRef(onMarcador)
  alMarcador.current = onMarcador
  const [errorImagen, setErrorImagen] = useState<string | null>(null)

  capaRef.current = capa
  opacidadRef.current = opacidad

  // 1) Crear el mapa una sola vez. (En desarrollo React lo monta dos veces: la limpieza lo destruye bien.)
  useEffect(() => {
    const el = contenedor.current
    if (!el) return
    const mapa = L.map(el, { zoomSnap: 0.25, worldCopyJump: false })
    if (TILES_URL) L.tileLayer(TILES_URL, { attribution: TILES_ATRIBUCION, maxZoom: 12 }).addTo(mapa)
    mapa.fitBounds(vista)
    const globo = L.popup() // uno solo: al cambiar el contenido no se abren y cierran popups superpuestos

    mapa.on('click', (e: L.LeafletMouseEvent) => {
      const actual = capaRef.current.mur
      if (!actual) return
      const { latlng } = e
      const { clave, producto, fecha } = actual

      marcadorRef.current?.remove()
      marcadorRef.current = L.circleMarker(latlng, {
        radius: 5,
        weight: 2,
        color: '#193b42',
        fillColor: '#ffffff',
        fillOpacity: 1,
      }).addTo(mapa)
      const abrir = (valor: HTMLElement | string) => {
        globo.setLatLng(latlng).setContent(popup(producto.titulo, fecha.fecha, latlng.lat, latlng.lng, valor))
        if (!mapa.hasLayer(globo)) globo.openOn(mapa)
      }
      abrir('Cargando…')

      let promesa = grillas.current.get(fecha.grilla_archivo)
      if (!promesa) {
        promesa = cargarGrilla(urlSatelite(fecha.grilla_archivo), fecha.grilla)
        grillas.current.set(fecha.grilla_archivo, promesa)
        promesa.catch(() => grillas.current.delete(fecha.grilla_archivo)) // que un fallo no quede en caché
      }
      promesa.then(
        (g) => {
          // Si mientras tanto cambió producto o fecha, este resultado ya no corresponde.
          if (capaRef.current.mur?.fecha.grilla_archivo !== fecha.grilla_archivo) return
          const v = valorEn(g, latlng.lat, latlng.lng)
          if (v === null) return abrir('Sin dato (tierra o fuera de la región)')
          const cont = document.createElement('span')
          const chip = document.createElement('span')
          chip.className = 'chip'
          chip.style.backgroundColor = colorEnEscala(v, producto.stops) // CSSOM: permitido por CSP
          const txt = document.createElement('b')
          txt.textContent = ` ${formatoValor(v, producto.decimales, clave === 'anom')} ${producto.unidad}`
          cont.append(chip, txt)
          abrir(cont)
        },
        () => {
          if (capaRef.current.mur?.fecha.grilla_archivo === fecha.grilla_archivo) abrir('No se pudo leer el valor')
        },
      )
    })

    puntosRef.current = L.layerGroup().addTo(mapa)
    mapaRef.current = mapa
    return () => {
      mapa.remove()
      puntosRef.current = null
      mapaRef.current = null
      overlayRef.current = null
      marcadorRef.current = null
    }
    // El encuadre inicial se usa solo al crear el mapa; no debe recrearlo si cambia.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 2) Cambiar la imagen cuando cambia el producto o la fecha.
  useEffect(() => {
    const mapa = mapaRef.current
    if (!mapa) return
    setErrorImagen(null)
    marcadorRef.current?.remove()
    mapa.closePopup()
    const overlay = L.imageOverlay(capa.url, capa.limites, { opacity: opacidadRef.current, interactive: false })
    overlay.on('error', () => setErrorImagen('No se pudo cargar la imagen de esta fecha.'))
    overlay.addTo(mapa)
    overlayRef.current = overlay
    return () => {
      overlay.remove()
    }
  }, [capa.url, capa.limites])

  // 2b) Puntos costeros: elegidos con su color (anillo blanco para que se vean sobre la imagen).
  useEffect(() => {
    const capaPuntos = puntosRef.current
    if (!capaPuntos) return
    capaPuntos.clearLayers()
    for (const m of marcadores) {
      const elegido = m.color !== null
      const c = L.circleMarker([m.lat, m.lon], {
        radius: elegido ? 7 : 4.5,
        weight: 2,
        color: elegido ? '#ffffff' : '#193b42',
        fillColor: m.color ?? '#ffffff',
        fillOpacity: 1,
        bubblingMouseEvents: false, // el clic elige el punto y no abre el popup de valor
      })
      const rotulo = document.createElement('span')
      rotulo.textContent = `${m.nombre}${elegido ? '' : ' (clic para comparar)'}`
      c.bindTooltip(rotulo, { direction: 'top', offset: [0, -6] })
      c.on('click', () => alMarcador.current?.(m.id))
      c.addTo(capaPuntos)
    }
  }, [marcadores])

  // 3) La opacidad se cambia sobre la capa existente, sin recargar la imagen.
  useEffect(() => {
    overlayRef.current?.setOpacity(opacidad)
  }, [opacidad])

  return (
    <>
      <div ref={contenedor} className="mapa" role="region" aria-label="Mapa de productos satelitales" />
      {errorImagen && (
        <p className="aviso error" role="alert">
          {errorImagen}
        </p>
      )}
    </>
  )
}
