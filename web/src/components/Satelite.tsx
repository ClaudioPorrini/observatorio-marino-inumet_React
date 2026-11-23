import { useEffect, useMemo, useRef, useState } from 'react'
import { MAX_SERIES, PALETA_SERIES } from '../colores'
import { DIAS_ATRASADO_SAT } from '../config'
import { dibujarBarra } from '../escala'
import { diasDesde, formatoDia } from '../format'
import type { IndiceSatelite, Limites, ProductoMur } from '../types'
import { useIndiceSatelite } from '../useIndiceSatelite'
import { usePuntos } from '../usePuntos'
import MapaSatelital, { urlSatelite, type Capa, type Marcador } from './MapaSatelital'
import SeriesCosteras from './SeriesCosteras'

// Puntos con los que arranca la comparación: estuario → bahía/océano → límite con Brasil.
const PUNTOS_INICIALES = ['colonia', 'pde_brava', 'barra_chuy']

type Producto = 'sst' | 'anom' | 'modis' | 'viirs' | 'frente'

const PRODUCTOS: { id: Producto; texto: string }[] = [
  { id: 'sst', texto: 'Temperatura superficial del mar (MUR)' },
  { id: 'anom', texto: 'Anomalía de TSM (MUR)' },
  { id: 'modis', texto: 'Color real MODIS Aqua' },
  { id: 'viirs', texto: 'Color real VIIRS' },
  { id: 'frente', texto: 'Frente de turbidez' },
]

const NOMBRE_SAT = { aqua: 'MODIS Aqua', terra: 'MODIS Terra' } as const
const NOMBRE_CALIDAD = { clear: 'despejado', cloudy: 'con nubes' } as const

/** Barra de colores con el rango de la escala (dibujada en canvas). */
function Leyenda({ producto }: { producto: ProductoMur }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    if (ref.current) dibujarBarra(ref.current, producto.stops)
  }, [producto])
  const marcas = producto.stops.filter((_, i) => i % 2 === 0)
  return (
    <div className="leyenda">
      <canvas ref={ref} width={256} height={14} aria-hidden="true" />
      <div className="leyenda-marcas">
        {marcas.map(([v]) => (
          <span key={v}>{v}</span>
        ))}
        <span className="unidad">{producto.unidad}</span>
      </div>
    </div>
  )
}

function AvisoEdad({ fecha }: { fecha: string }) {
  const dias = diasDesde(fecha)
  if (!Number.isFinite(dias) || dias <= DIAS_ATRASADO_SAT) return null
  return (
    <p className="aviso atencion" role="status">
      Atrasado: la imagen más reciente de este producto es de hace {dias} días ({formatoDia(fecha)}).
    </p>
  )
}

function Panel({ indice }: { indice: IndiceSatelite }) {
  const [producto, setProducto] = useState<Producto>('sst')
  const [elegidas, setElegidas] = useState<Partial<Record<Producto, string>>>({})
  const [opacidad, setOpacidad] = useState(0.85)
  const estadoPuntos = usePuntos(indice.puntos?.archivo ?? null)
  const datosPuntos = estadoPuntos.tipo === 'listo' ? estadoPuntos.puntos : null

  // Puntos elegidos, cada uno con su color fijo (posición en la paleta). Al sacar uno, los demás
  // no cambian de color; el nuevo toma el primer color libre.
  const [elegidos, setElegidos] = useState<{ id: string; color: string }[] | null>(null)
  const seleccion = useMemo(() => {
    if (elegidos) return elegidos
    const ids = datosPuntos?.puntos.map((p) => p.id) ?? []
    const iniciales = PUNTOS_INICIALES.filter((id) => ids.includes(id))
    return (iniciales.length ? iniciales : ids.slice(0, 3)).map((id, i) => ({ id, color: PALETA_SERIES[i] as string }))
  }, [elegidos, datosPuntos])
  const colorDe = (id: string) => seleccion.find((s) => s.id === id)?.color ?? null
  const [rechazado, setRechazado] = useState(false) // quiso sumar un punto con la lista llena
  const alternar = (id: string) => {
    setRechazado(false)
    if (colorDe(id)) return setElegidos(seleccion.filter((s) => s.id !== id))
    if (seleccion.length >= MAX_SERIES) return setRechazado(true) // aviso visible, también al hacer clic en el mapa
    const libre = PALETA_SERIES.find((c) => !seleccion.some((s) => s.color === c)) as string
    setElegidos([...seleccion, { id, color: libre }])
  }
  const marcadores: Marcador[] = useMemo(
    () =>
      (datosPuntos?.puntos ?? []).map((p) => ({
        id: p.id,
        nombre: p.nombre,
        lat: p.lat,
        lon: p.lon,
        color: seleccion.find((s) => s.id === p.id)?.color ?? null,
      })),
    [datosPuntos, seleccion],
  )

  const p = indice.productos
  // Fechas del producto activo (la primera es la más reciente).
  const fechas: string[] = useMemo(() => {
    if (producto === 'frente') return [...new Set(p.frente.fechas.map((f) => f.fecha))]
    return p[producto].fechas.map((f) => f.fecha)
  }, [producto, p])
  const fecha = elegidas[producto] && fechas.includes(elegidas[producto]) ? elegidas[producto] : fechas[0]

  // Encuadre inicial: el de la imagen más reciente de SST (todos los productos cubren la misma región).
  const vista: Limites = p.sst.fechas[0]?.limites ?? p.modis.limites

  const capa: Capa | null = useMemo(() => {
    if (!fecha) return null
    if (producto === 'sst' || producto === 'anom') {
      const prod = p[producto]
      const f = prod.fechas.find((x) => x.fecha === fecha)
      return f
        ? { url: urlSatelite(f.png), limites: f.limites, mur: { clave: producto, producto: prod, fecha: f } }
        : null
    }
    if (producto === 'modis' || producto === 'viirs') {
      const f = p[producto].fechas.find((x) => x.fecha === fecha)
      return f ? { url: urlSatelite(f.archivo), limites: p[producto].limites, mur: null } : null
    }
    return null
  }, [producto, fecha, p])

  const mur = producto === 'sst' || producto === 'anom' ? p[producto] : null

  return (
    <section>
      <div className="controles">
        <label>
          Producto
          <select value={producto} onChange={(e) => setProducto(e.target.value as Producto)}>
            {PRODUCTOS.map((x) => (
              <option key={x.id} value={x.id}>
                {x.texto}
              </option>
            ))}
          </select>
        </label>
        <label>
          Fecha (UTC)
          <select
            value={fecha ?? ''}
            disabled={fechas.length === 0}
            onChange={(e) => setElegidas({ ...elegidas, [producto]: e.target.value })}
          >
            {fechas.map((f) => (
              <option key={f} value={f}>
                {formatoDia(f)}
              </option>
            ))}
          </select>
        </label>
        {producto !== 'frente' && (
          <label>
            Opacidad
            <input
              type="range"
              min={0.2}
              max={1}
              step={0.05}
              value={opacidad}
              onChange={(e) => setOpacidad(Number(e.target.value))}
            />
          </label>
        )}
      </div>

      {fechas.length === 0 && <p className="aviso">No hay imágenes disponibles para este producto.</p>}
      {fecha && fechas[0] === fecha && <AvisoEdad fecha={fecha} />}

      {producto === 'frente' ? (
        <Frente indice={indice} fecha={fecha} />
      ) : (
        <>
          {/* El mapa se mantiene montado al cambiar de producto: conserva zoom y posición. */}
          {capa ? (
            <MapaSatelital
              capa={capa}
              opacidad={opacidad}
              vista={vista}
              marcadores={marcadores}
              onMarcador={alternar}
            />
          ) : (
            fechas.length > 0 && <p className="aviso">Sin imagen para esta fecha.</p>
          )}
          {mur && <Leyenda producto={mur} />}
          <p className="nota">
            {mur
              ? 'Hacé clic en el mapa para leer el valor en ese punto (celdas de ~2 km). Fuente: MUR-GHRSST, NASA.'
              : 'Imagen de color real. Fuente: NASA GIBS.'}
          </p>
        </>
      )}

      {estadoPuntos.tipo === 'error' && (
        <p className="aviso error" role="alert">
          No se pudieron cargar las series costeras. {estadoPuntos.mensaje}
        </p>
      )}
      {datosPuntos && (
        <SeriesCosteras
          datos={datosPuntos}
          colorDe={colorDe}
          onAlternar={alternar}
          rechazado={rechazado}
          fechaMarca={fecha}
        />
      )}
    </section>
  )
}

function Frente({ indice, fecha }: { indice: IndiceSatelite; fecha: string | undefined }) {
  const delDia = indice.productos.frente.fechas.filter((f) => f.fecha === fecha)
  const [clave, setClave] = useState<string>('')
  const item = delDia.find((f) => f.archivo === clave) ?? delDia[0]
  if (!item) return <p className="aviso">Sin imágenes para esta fecha.</p>
  const descripcion = `Frente de turbidez, ${NOMBRE_SAT[item.satelite]}, ${formatoDia(item.fecha)} (${NOMBRE_CALIDAD[item.calidad]})`
  return (
    <div className="frente">
      {delDia.length > 1 && (
        <div className="controles">
          <label>
            Imagen
            <select value={item.archivo} onChange={(e) => setClave(e.target.value)}>
              {delDia.map((f) => (
                <option key={f.archivo} value={f.archivo}>
                  {NOMBRE_SAT[f.satelite]} · {NOMBRE_CALIDAD[f.calidad]}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      <img src={urlSatelite(item.archivo)} alt={descripcion} />
      <p className="nota">{descripcion}. Imagen sin georreferenciar.</p>
    </div>
  )
}

export default function Satelite() {
  const estado = useIndiceSatelite()
  return (
    <>
      {estado.tipo === 'cargando' && <p className="aviso">Cargando productos satelitales…</p>}
      {estado.tipo === 'error' && (
        <p className="aviso error" role="alert">
          No se pudieron cargar los productos satelitales. {estado.mensaje}
        </p>
      )}
      {estado.tipo === 'listo' && <Panel indice={estado.indice} />}
    </>
  )
}
