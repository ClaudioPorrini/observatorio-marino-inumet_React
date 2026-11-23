import { useMemo, useRef, useState, type PointerEvent } from 'react'
import { cardinal, formatoDia, formatoDiaMes, formatoInstante, formatoMes, formatoNumero } from '../format'
import { acumularDiario, marcasX, marcasY, masCercano, recortar, tramos, type Punto } from '../serie'
import type { SerieVariable } from '../types'
import { useAncho } from '../useAncho'

const ALTO = 170
const M = { izq: 46, der: 12, arr: 10, abj: 24 } // márgenes para los ejes
const HUECO_MAX = 3 * 3600 // más de 3 h sin dato corta la línea (no se inventa el tramo)
const DIA = 86_400

type Forma = 'linea' | 'barras' | 'puntos'
const FORMA: Record<string, Forma> = { precipitation: 'barras', wind_direction: 'puntos' }

interface Props {
  variable: string
  serie: SerieVariable
  desde: number // segundos UTC
  hasta: number
}

export default function GraficoSerie({ variable, serie, desde, hasta }: Props) {
  const caja = useRef<HTMLElement>(null)
  const ancho = useAncho(caja)
  const [hover, setHover] = useState<Punto | null>(null)

  const forma: Forma = FORMA[variable] ?? 'linea'
  // Precipitación en ventanas largas: barras horarias de 0,2 px no se ven. Se pasa a acumulado diario.
  const diario = forma === 'barras' && hasta - desde > 10 * DIA
  const unidad = serie.unit ?? ''

  const puntos = useMemo(() => {
    const p = recortar(serie, desde, hasta)
    return diario ? acumularDiario(p) : p
  }, [serie, desde, hasta, diario])

  const w = ancho - M.izq - M.der
  const h = ALTO - M.arr - M.abj

  // Rango vertical
  let [lo, hi] = [0, 1]
  if (forma === 'puntos') [lo, hi] = [0, 360]
  else if (puntos.length) {
    const vs = puntos.map((p) => p.v)
    lo = Math.min(...vs)
    hi = Math.max(...vs)
    if (forma === 'barras') [lo, hi] = [0, Math.max(hi, 1)]
    else if (hi - lo < 1e-9) [lo, hi] = [lo - 1, hi + 1]
    else {
      const pad = (hi - lo) * 0.08
      ;[lo, hi] = [lo - pad, hi + pad]
    }
  }
  const x = (t: number) => M.izq + ((t - desde) / (hasta - desde)) * w
  const y = (v: number) => M.arr + (1 - (v - lo) / (hi - lo)) * h
  const ticksY = forma === 'puntos' ? [0, 90, 180, 270, 360] : marcasY(lo, hi)
  const ticksX = marcasX(desde, hasta)

  const titulo = `${serie.label}${unidad ? ` (${unidad})` : ''}${forma === 'barras' ? (diario ? ' · acumulado diario' : ' · acumulado horario') : ''}`
  const ultimoT = serie.t[serie.t.length - 1]

  const texto = (p: Punto) => {
    const cuando = diario ? formatoDia(new Date(p.t * 1000).toISOString().slice(0, 10)) : formatoInstante(p.t)
    const extra = variable === 'wind_direction' ? ` ${cardinal(p.v)}` : ''
    const u = unidad === '°' || unidad === '' ? unidad : ` ${unidad}` // 70° y no 70 °
    return `${cuando} · ${formatoNumero(p.v)}${u}${extra}`
  }

  const mover = (e: PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const t = desde + ((e.clientX - r.left - M.izq) / w) * (hasta - desde)
    // Tolerancia: unos 8 px o el paso del dato, lo que sea mayor. En un hueco no se muestra nada.
    const tol = Math.max(diario ? DIA : 3600, ((hasta - desde) / w) * 8)
    setHover(masCercano(puntos, t, tol))
  }

  const ultimo = puntos[puntos.length - 1]
  const resumen = puntos.length
    ? `${serie.label}: ${puntos.length} valores; mínimo ${formatoNumero(Math.min(...puntos.map((p) => p.v)))}, máximo ${formatoNumero(Math.max(...puntos.map((p) => p.v)))} ${unidad}`
    : `${serie.label}: sin datos en la ventana`

  return (
    <figure className="grafico" ref={caja}>
      <figcaption className="grafico-cabecera">
        <span className="grafico-titulo">{titulo}</span>
        <span className="grafico-lectura" aria-live="polite">
          {hover ? texto(hover) : ultimo ? `Último: ${texto(ultimo)}` : ''}
        </span>
      </figcaption>

      {puntos.length === 0 ? (
        <p className="grafico-vacio">
          Sin datos en esta ventana.
          {ultimoT !== undefined && ` Último dato: ${formatoInstante(ultimoT)}.`}
        </p>
      ) : (
        <svg
          width={ancho}
          height={ALTO}
          role="img"
          aria-label={resumen}
          onPointerMove={mover}
          onPointerLeave={() => setHover(null)}
        >
          {ticksY.map((v) => (
            <g key={`y${v}`}>
              <line className="eje-grilla" x1={M.izq} x2={M.izq + w} y1={y(v)} y2={y(v)} />
              <text className="eje-texto" x={M.izq - 6} y={y(v)} dy="0.32em" textAnchor="end">
                {forma === 'puntos' ? cardinal(v) : formatoNumero(v)}
              </text>
            </g>
          ))}
          {ticksX.map(({ t, mensual }) => (
            <g key={`x${t}`}>
              <line className="eje-marca" x1={x(t)} x2={x(t)} y1={M.arr + h} y2={M.arr + h + 4} />
              <text className="eje-texto" x={x(t)} y={ALTO - 6} textAnchor="middle">
                {mensual ? formatoMes(t) : formatoDiaMes(t)}
              </text>
            </g>
          ))}

          {forma === 'linea' &&
            tramos(puntos, HUECO_MAX).map((tr) => (
              <path
                key={tr[0]?.t}
                className="serie-linea"
                d={tr.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join('')}
              />
            ))}
          {forma === 'barras' &&
            puntos.map((p) => {
              const ancho_b = Math.max(1, x(p.t + (diario ? DIA : 3600)) - x(p.t) - (diario ? 1 : 0))
              return p.v > 0 ? (
                <rect key={p.t} className="serie-barra" x={x(p.t)} y={y(p.v)} width={ancho_b} height={M.arr + h - y(p.v)} />
              ) : null
            })}
          {forma === 'puntos' &&
            puntos.map((p) => <circle key={p.t} className="serie-punto" cx={x(p.t)} cy={y(p.v)} r={1.6} />)}

          {hover && (
            <g className="cursor">
              <line x1={x(hover.t)} x2={x(hover.t)} y1={M.arr} y2={M.arr + h} />
              {forma !== 'barras' && <circle cx={x(hover.t)} cy={y(hover.v)} r={3.5} />}
            </g>
          )}
        </svg>
      )}
    </figure>
  )
}
