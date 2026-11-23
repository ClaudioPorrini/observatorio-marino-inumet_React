import { useMemo, useRef, useState, type PointerEvent } from 'react'
import { formatoDia, formatoDiaMes, formatoMes, formatoValor } from '../format'
import { marcasX, marcasY } from '../serie'
import { useAncho } from '../useAncho'

const ALTO = 200
const M = { izq: 46, der: 12, arr: 14, abj: 24 }
const DIA = 86_400

export interface SerieDiaria {
  id: string
  nombre: string
  color: string
  valores: (number | null)[] // alineado con `fechas`
}

interface Props {
  titulo: string
  unidad: string
  decimales: number
  conSigno: boolean // anomalía: "+1,20"
  incluirCero: boolean // anomalía: el 0 siempre visible y marcado
  fechas: string[]
  series: SerieDiaria[]
  fechaMarca?: string // fecha de la imagen que se ve en el mapa
}

const segundos = (iso: string) => Date.parse(`${iso}T00:00:00Z`) / 1000

/** Muestra de color como SVG (atributo fill, no estilo en línea: compatible con CSP). */
export function Muestra({ color }: { color: string }) {
  return (
    <svg className="muestra" width="10" height="10" aria-hidden="true">
      <rect width="10" height="10" rx="2" fill={color} />
    </svg>
  )
}

export default function GraficoPuntos(props: Props) {
  const { titulo, unidad, decimales, conSigno, incluirCero, fechas, series, fechaMarca } = props
  const caja = useRef<HTMLElement>(null)
  const ancho = useAncho(caja)
  const [hover, setHover] = useState<number | null>(null) // índice de fecha

  const w = ancho - M.izq - M.der
  const h = ALTO - M.arr - M.abj
  const t0 = fechas[0] ? segundos(fechas[0]) : 0
  const tN = fechas.length > 1 ? segundos(fechas[fechas.length - 1] as string) : t0 + DIA
  const x = (i: number) => M.izq + ((segundos(fechas[i] as string) - t0) / (tN - t0)) * w

  const valores = useMemo(() => series.flatMap((s) => s.valores.filter((v): v is number => v !== null)), [series])
  if (valores.length === 0) {
    return (
      <figure className="grafico" ref={caja}>
        <figcaption className="grafico-cabecera">
          <span className="grafico-titulo">{titulo}</span>
        </figcaption>
        <p className="grafico-vacio">Sin datos para los puntos elegidos en este período.</p>
      </figure>
    )
  }

  let lo = Math.min(...valores, ...(incluirCero ? [0] : []))
  let hi = Math.max(...valores, ...(incluirCero ? [0] : []))
  if (hi - lo < 0.5) [lo, hi] = [lo - 0.25, hi + 0.25]
  const pad = (hi - lo) * 0.08
  lo -= pad
  hi += pad
  const y = (v: number) => M.arr + (1 - (v - lo) / (hi - lo)) * h

  const fmt = (v: number) => `${formatoValor(v, decimales, conSigno)} ${unidad}`
  const iMarca = fechaMarca ? fechas.indexOf(fechaMarca) : -1

  // Lectura: la fecha bajo el cursor o, si no hay cursor, la última con algún dato.
  const ultimoConDato = (() => {
    for (let i = fechas.length - 1; i >= 0; i--) if (series.some((s) => s.valores[i] != null)) return i
    return null
  })()
  const iLectura = hover ?? ultimoConDato

  const mover = (e: PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const t = t0 + ((e.clientX - r.left - M.izq) / w) * (tN - t0)
    const i = Math.round((t - t0) / DIA)
    setHover(i >= 0 && i < fechas.length ? i : null)
  }

  return (
    <figure className="grafico" ref={caja}>
      <figcaption className="grafico-cabecera">
        <span className="grafico-titulo">
          {titulo} ({unidad})
        </span>
      </figcaption>
      {iLectura !== null && (
        <div className="lectura-multiple" aria-live="polite">
          <span className="lectura-fecha">
            {hover === null ? 'Último: ' : ''}
            {formatoDia(fechas[iLectura] as string)}
          </span>
          {series.map((s) => {
            const v = s.valores[iLectura]
            return (
              <span key={s.id} className="lectura-item">
                <Muestra color={s.color} /> {s.nombre}: <b>{v == null ? 'sin dato' : fmt(v)}</b>
              </span>
            )
          })}
        </div>
      )}

      <svg
        width={ancho}
        height={ALTO}
        role="img"
        aria-label={`${titulo}: ${series.map((s) => s.nombre).join(', ')}. Hay una tabla con los valores debajo.`}
        onPointerMove={mover}
        onPointerLeave={() => setHover(null)}
      >
        {marcasY(lo, hi).map((v) => (
          <g key={`y${v}`}>
            <line
              className={incluirCero && v === 0 ? 'eje-cero' : 'eje-grilla'}
              x1={M.izq}
              x2={M.izq + w}
              y1={y(v)}
              y2={y(v)}
            />
            <text className="eje-texto" x={M.izq - 6} y={y(v)} dy="0.32em" textAnchor="end">
              {formatoValor(v, Number.isInteger(v) ? 0 : 1, conSigno)}
            </text>
          </g>
        ))}
        {marcasX(t0, tN).map(({ t, mensual }) => {
          const px = M.izq + ((t - t0) / (tN - t0)) * w
          return (
            <g key={`x${t}`}>
              <line className="eje-marca" x1={px} x2={px} y1={M.arr + h} y2={M.arr + h + 4} />
              <text className="eje-texto" x={px} y={ALTO - 6} textAnchor="middle">
                {mensual ? formatoMes(t) : formatoDiaMes(t)}
              </text>
            </g>
          )
        })}

        {iMarca >= 0 && (
          <g className="marca-imagen">
            <line x1={x(iMarca)} x2={x(iMarca)} y1={M.arr} y2={M.arr + h} />
            {/* Rótulo alineado hacia adentro cerca de los bordes, para que no se corte. */}
            <text
              x={x(iMarca)}
              y={M.arr - 3}
              textAnchor={x(iMarca) > M.izq + w - 30 ? 'end' : x(iMarca) < M.izq + 30 ? 'start' : 'middle'}
            >
              imagen
            </text>
          </g>
        )}

        {series.map((s) => {
          // Tramos continuos: un día sin dato corta la línea. Un valor aislado se dibuja como punto.
          const tramos: number[][] = []
          let actual: number[] = []
          s.valores.forEach((v, i) => {
            if (v == null) {
              if (actual.length) tramos.push(actual)
              actual = []
            } else actual.push(i)
          })
          if (actual.length) tramos.push(actual)
          return (
            <g key={s.id}>
              {tramos.map((tr) =>
                tr.length === 1 ? (
                  <circle
                    key={tr[0]}
                    cx={x(tr[0] as number)}
                    cy={y(s.valores[tr[0] as number] as number)}
                    r={2.5}
                    fill={s.color}
                  />
                ) : (
                  <path
                    key={tr[0]}
                    className="serie-multiple"
                    stroke={s.color}
                    d={tr
                      .map((i, k) => `${k ? 'L' : 'M'}${x(i).toFixed(1)},${y(s.valores[i] as number).toFixed(1)}`)
                      .join('')}
                  />
                ),
              )}
            </g>
          )
        })}

        {hover !== null && (
          <g className="cursor">
            <line x1={x(hover)} x2={x(hover)} y1={M.arr} y2={M.arr + h} />
            {series.map((s) => {
              const v = s.valores[hover]
              return v == null ? null : (
                <circle key={s.id} className="cursor-punto" cx={x(hover)} cy={y(v)} r={4} fill={s.color} />
              )
            })}
          </g>
        )}
      </svg>

      <details className="tabla-grafico">
        <summary>Ver tabla</summary>
        <div className="tabla-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Fecha</th>
                {series.map((s) => (
                  <th scope="col" key={s.id}>
                    {s.nombre}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {fechas
                .map((f, i) => ({ f, i }))
                .reverse()
                .map(({ f, i }) => (
                  <tr key={f}>
                    <th scope="row">{formatoDia(f)}</th>
                    {series.map((s) => {
                      const v = s.valores[i]
                      return <td key={s.id}>{v == null ? '—' : formatoValor(v, decimales, conSigno)}</td>
                    })}
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  )
}
