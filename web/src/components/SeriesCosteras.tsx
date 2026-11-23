import { useState } from 'react'
import { MAX_SERIES } from '../colores'
import type { PuntosJson } from '../types'
import GraficoPuntos, { Muestra, type SerieDiaria } from './GraficoPuntos'

const VENTANAS = [
  { dias: 30, texto: '30 días' },
  { dias: 90, texto: '90 días' },
  { dias: 183, texto: '6 meses' },
] as const

interface Props {
  datos: PuntosJson
  colorDe: (id: string) => string | null // null = punto no elegido
  onAlternar: (id: string) => void
  rechazado: boolean // se intentó sumar un punto con MAX_SERIES ya elegidos
  fechaMarca?: string
}

/** TSM y anomalía diarias en puntos costeros, debajo del mapa satelital. */
export default function SeriesCosteras({ datos, colorDe, onAlternar, rechazado, fechaMarca }: Props) {
  const [dias, setDias] = useState<number>(90)

  const desde = Math.max(0, datos.fechas.length - dias)
  const fechas = datos.fechas.slice(desde)
  const elegidos = datos.puntos.filter((p) => colorDe(p.id) !== null)
  const series = (clave: 'sst' | 'anom'): SerieDiaria[] =>
    elegidos.map((p) => ({ id: p.id, nombre: p.nombre, color: colorDe(p.id) as string, valores: p[clave].slice(desde) }))

  return (
    <section className="series-costeras" aria-labelledby="costeras-titulo">
      <div className="detalle-cabecera">
        <h2 id="costeras-titulo">TSM y anomalía en la costa</h2>
        <div className="ventanas" role="group" aria-label="Período de las series costeras">
          {VENTANAS.map((v) => (
            <button key={v.dias} type="button" aria-pressed={dias === v.dias} onClick={() => setDias(v.dias)}>
              {v.texto}
            </button>
          ))}
        </div>
      </div>

      <div className="chips" role="group" aria-label="Puntos costeros a comparar">
        {datos.puntos.map((p) => {
          const color = colorDe(p.id)
          return (
            <button
              key={p.id}
              type="button"
              className="chip-punto"
              aria-pressed={color !== null}
              onClick={() => onAlternar(p.id)}
            >
              {color && <Muestra color={color} />} {p.nombre}
            </button>
          )
        })}
      </div>
      <p className="nota" aria-live="polite">
        {rechazado
          ? `Se pueden comparar hasta ${MAX_SERIES} puntos a la vez: sacá uno para sumar otro.`
          : `Elegí hasta ${MAX_SERIES} puntos (acá o en el mapa). Valores diarios de MUR-GHRSST, promedio de ~3 km de mar frente a cada lugar.`}
      </p>

      {elegidos.length === 0 ? (
        <p className="aviso">Elegí al menos un punto para ver las series.</p>
      ) : (
        <div className="graficos graficos-costeros">
          <GraficoPuntos
            titulo="Temperatura superficial del mar"
            unidad="°C"
            decimales={2}
            conSigno={false}
            incluirCero={false}
            fechas={fechas}
            series={series('sst')}
            fechaMarca={fechaMarca}
          />
          <GraficoPuntos
            titulo="Anomalía de TSM"
            unidad="°C"
            decimales={2}
            conSigno={true}
            incluirCero={true}
            fechas={fechas}
            series={series('anom')}
            fechaMarca={fechaMarca}
          />
        </div>
      )}
    </section>
  )
}
