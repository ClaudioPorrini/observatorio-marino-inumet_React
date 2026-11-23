import { useState } from 'react'
import { HORAS_ATRASADO } from '../config'
import { cardinal, edadHoras, formatoFecha, formatoNumero, textoEdad } from '../format'
import type { Estacion, EstacionesJson, UltimoValor } from '../types'
import { useSerie } from '../useSerie'
import GraficoSerie from './GraficoSerie'
import MapaEstaciones from './MapaEstaciones'

// Orden preferido de columnas; las variables que no estén acá van al final.
const ORDEN: readonly string[] = [
  'air_temperature',
  'relative_humidity',
  'pressure',
  'wind_speed',
  'wind_direction',
  'precipitation',
]

const posicion = (v: string) => {
  const i = ORDEN.indexOf(v)
  return i === -1 ? ORDEN.length : i
}

interface Columna {
  variable: string
  label: string
  unit: string | null
}

/** Unión de las variables que aparecen en alguna estación (no se fija una lista a mano). */
function columnasDe(estaciones: Estacion[]): Columna[] {
  const vistas = new Map<string, Columna>()
  for (const e of estaciones) {
    for (const [variable, u] of Object.entries(e.latest)) {
      if (!vistas.has(variable)) vistas.set(variable, { variable, label: u.label, unit: u.unit })
    }
  }
  return [...vistas.values()].sort(
    (a, b) => posicion(a.variable) - posicion(b.variable) || a.variable.localeCompare(b.variable),
  )
}

// Una celda de la tabla. `props` = parámetros que recibe el componente desde su padre.
function Celda({ variable, valor }: { variable: string; valor: UltimoValor | undefined }) {
  if (!valor) return <td className="vacio">—</td>

  const horas = edadHoras(valor.time)
  const atrasado = !(horas <= HORAS_ATRASADO) // una fecha inválida (NaN) también cuenta como atrasada

  return (
    <td className={atrasado ? 'atrasado' : undefined} title={`Medido: ${formatoFecha(valor.time)}`}>
      <span className="valor">{formatoNumero(valor.value)}</span>
      {variable === 'wind_direction' && <span className="rumbo"> {cardinal(valor.value)}</span>}
      {/* El atraso se indica con texto, no solo con color. */}
      {atrasado && <span className="edad">{textoEdad(horas)}</span>}
    </td>
  )
}

const VENTANAS = [
  { dias: 7, texto: '7 días' },
  { dias: 30, texto: '30 días' },
  { dias: 183, texto: '6 meses' },
] as const

/** Gráficos de la estación elegida. */
function Detalle({ estacion }: { estacion: Estacion }) {
  const [dias, setDias] = useState<number>(7)
  const estado = useSerie(estacion.station_id, estacion.last_time !== null)
  // "hasta" es AHORA, no el último dato: si una variable dejó de llegar, el hueco se ve.
  const hasta = Math.floor(Date.now() / 3_600_000) * 3600 + 3600
  const desde = hasta - dias * 86_400

  return (
    <section className="detalle" aria-labelledby="detalle-titulo">
      <div className="detalle-cabecera">
        <h2 id="detalle-titulo">
          {estacion.name} <span className="inst">{estacion.institution}</span>
        </h2>
        <div className="ventanas" role="group" aria-label="Período de los gráficos">
          {VENTANAS.map((v) => (
            <button key={v.dias} type="button" aria-pressed={dias === v.dias} onClick={() => setDias(v.dias)}>
              {v.texto}
            </button>
          ))}
        </div>
      </div>

      {estado.tipo === 'sin_datos' && (
        <p className="aviso">Esta estación no tiene mediciones en los últimos 6 meses.</p>
      )}
      {estado.tipo === 'cargando' && <p className="aviso">Cargando series…</p>}
      {estado.tipo === 'error' && (
        <p className="aviso error" role="alert">
          {estado.mensaje}
        </p>
      )}
      {estado.tipo === 'listo' && (
        <div className="graficos">
          {Object.entries(estado.serie.variables)
            .sort(([a], [b]) => posicion(a) - posicion(b) || a.localeCompare(b))
            .map(([variable, serie]) => (
              <GraficoSerie key={variable} variable={variable} serie={serie} desde={desde} hasta={hasta} />
            ))}
        </div>
      )}
      <p className="nota">
        Valores horarios, horas en UTC. Pasá el cursor (o el dedo) sobre un gráfico para leer el valor.
      </p>
    </section>
  )
}

export default function Observaciones({ datos }: { datos: EstacionesJson }) {
  const columnas = columnasDe(datos.stations)
  // Arranca con la primera estación que tiene datos, para que los gráficos se vean de entrada.
  const [elegida, setElegida] = useState<string | null>(
    () => datos.stations.find((e) => e.last_time !== null)?.station_id ?? null,
  )
  const estacion = datos.stations.find((e) => e.station_id === elegida)

  if (datos.stations.length === 0) {
    return <p className="aviso">No hay estaciones publicables: ninguna institución está autorizada.</p>
  }

  return (
    <>
      <section>
        <h2>Estaciones y último valor medido</h2>
        <p className="nota">
          {datos.stations.length} estaciones. Los valores con fondo amarillo tienen más de {HORAS_ATRASADO} h de
          antigüedad; pasá el cursor sobre un valor para ver cuándo se midió. Elegí una estación en el mapa o en la
          tabla para ver sus series.
        </p>

        <MapaEstaciones estaciones={datos.stations} seleccionada={elegida} onSeleccionar={setElegida} />

        <div className="tabla-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Estación</th>
                {columnas.map((c) => (
                  <th scope="col" key={c.variable}>
                    {c.label}
                    {c.unit && <span className="unidad"> ({c.unit})</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {datos.stations.map((e) => (
                <tr key={e.station_id} className={e.station_id === elegida ? 'seleccionada' : undefined}>
                  <th scope="row">
                    <button
                      type="button"
                      className="estacion"
                      aria-pressed={e.station_id === elegida}
                      onClick={() => setElegida(e.station_id)}
                    >
                      {e.name}
                    </button>
                    <span className="inst">
                      {e.institution}
                      {e.last_time === null && ' · sin datos recientes'}
                    </span>
                  </th>
                  {columnas.map((c) => (
                    <Celda key={c.variable} variable={c.variable} valor={e.latest[c.variable]} />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {estacion && <Detalle estacion={estacion} />}
    </>
  )
}
