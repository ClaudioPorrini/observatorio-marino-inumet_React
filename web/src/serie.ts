// Cálculos puros de los gráficos de series (sin React ni DOM): fáciles de probar.
import type { SerieVariable } from './types'

export interface Punto {
  t: number // segundos desde 1970, UTC
  v: number
}

const DIA = 86_400

/** Primer índice con t >= x (búsqueda binaria; t está ordenado). */
function primerIndice(t: number[], x: number): number {
  let lo = 0
  let hi = t.length
  while (lo < hi) {
    const m = (lo + hi) >> 1
    if ((t[m] as number) < x) lo = m + 1
    else hi = m
  }
  return lo
}

/** Puntos con desde <= t <= hasta. */
export function recortar(s: SerieVariable, desde: number, hasta: number): Punto[] {
  const out: Punto[] = []
  for (let i = primerIndice(s.t, desde); i < s.t.length; i++) {
    const t = s.t[i] as number
    if (t > hasta) break
    out.push({ t, v: s.v[i] as number })
  }
  return out
}

/** Suma por día UTC (t = 00:00 del día). Para precipitación en ventanas largas. */
export function acumularDiario(p: Punto[]): Punto[] {
  const out: Punto[] = []
  for (const { t, v } of p) {
    const dia = Math.floor(t / DIA) * DIA
    const ultimo = out[out.length - 1]
    if (ultimo && ultimo.t === dia) ultimo.v += v
    else out.push({ t: dia, v })
  }
  for (const x of out) x.v = Math.round(x.v * 100) / 100 // evita 0.30000000000000004
  return out
}

/** Corta la línea donde faltan datos: un hueco mayor a `maxHueco` segundos empieza un tramo nuevo. */
export function tramos(p: Punto[], maxHueco: number): Punto[][] {
  const out: Punto[][] = []
  let actual: Punto[] = []
  for (const x of p) {
    const prev = actual[actual.length - 1]
    if (prev && x.t - prev.t > maxHueco) {
      out.push(actual)
      actual = []
    }
    actual.push(x)
  }
  if (actual.length) out.push(actual)
  return out
}

/** Punto más cercano a t, si está a menos de `tolerancia` segundos. */
export function masCercano(p: Punto[], t: number, tolerancia: number): Punto | null {
  if (p.length === 0) return null
  let lo = 0
  let hi = p.length - 1
  while (lo < hi) {
    const m = (lo + hi) >> 1
    if ((p[m] as Punto).t < t) lo = m + 1
    else hi = m
  }
  const a = p[lo] as Punto
  const b = p[lo - 1]
  const mejor = b && Math.abs(b.t - t) < Math.abs(a.t - t) ? b : a
  return Math.abs(mejor.t - t) <= tolerancia ? mejor : null
}

/** Marcas "redondas" para el eje Y dentro de [min, max] (≈ n marcas). */
export function marcasY(min: number, max: number, n = 4): number[] {
  const rango = max - min
  if (!(rango > 0)) return [min]
  const crudo = rango / n
  const mag = 10 ** Math.floor(Math.log10(crudo))
  const r = crudo / mag
  const paso = (r < 1.5 ? 1 : r < 3 ? 2 : r < 7 ? 5 : 10) * mag
  const out: number[] = []
  for (let k = Math.ceil(min / paso); k * paso <= max + paso * 1e-9; k++) {
    out.push(Number((k * paso).toPrecision(12)))
  }
  return out
}

/** Marcas del eje X: días (≤ 10 d), cada 5 días (≤ 40 d) o primero de cada mes. */
export function marcasX(desde: number, hasta: number): { t: number; mensual: boolean }[] {
  const dias = (hasta - desde) / DIA
  const out: { t: number; mensual: boolean }[] = []
  if (dias <= 40) {
    const paso = dias <= 10 ? 1 : 5
    for (let d = Math.ceil(desde / DIA); d * DIA <= hasta; d++) {
      if (d % paso === 0) out.push({ t: d * DIA, mensual: false })
    }
    return out
  }
  const f = new Date(desde * 1000)
  let a = f.getUTCFullYear()
  let m = f.getUTCMonth() + 1 // primer día del mes siguiente
  for (;;) {
    if (m > 11) {
      a += 1
      m = 0
    }
    const t = Date.UTC(a, m, 1) / 1000
    if (t > hasta) break
    out.push({ t, mensual: true })
    m += 1
  }
  return out
}
