import { ETIQUETA_TZ, TIMEZONE } from './config'

const fechaCorta = new Intl.DateTimeFormat('es-UY', {
  timeZone: TIMEZONE,
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

/** "2026-11-20T16:00:00Z" -> "20/11/2026, 16:00 UTC". Fecha inválida -> "—". */
export function formatoFecha(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : `${fechaCorta.format(d)} ${ETIQUETA_TZ}`
}

/** Horas transcurridas desde `iso`. NaN si la fecha es inválida. */
export function edadHoras(iso: string, ahora: number = Date.now()): number {
  return (ahora - new Date(iso).getTime()) / 3_600_000
}

export function textoEdad(horas: number): string {
  if (!Number.isFinite(horas)) return 'fecha inválida'
  if (horas < 1) return 'hace menos de 1 h'
  if (horas < 48) return `hace ${Math.round(horas)} h`
  return `hace ${Math.round(horas / 24)} d`
}

// Sin separador de miles: en es-UY "1.012" se lee como decimal y no como 1012 hPa.
export function formatoNumero(n: number): string {
  return n.toLocaleString('es-UY', { maximumFractionDigits: 2, useGrouping: false })
}

// Mismos rumbos que theme_inumet.py (O = oeste).
const RUMBOS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSO', 'SO', 'OSO', 'O', 'ONO', 'NO', 'NNO']

/** 0° y 360° -> "N"; 90° -> "E"; 225° -> "SO". */
export function cardinal(grados: number): string {
  const g = ((grados % 360) + 360) % 360
  return RUMBOS[Math.round(g / 22.5) % 16] ?? ''
}

/** Número con decimales fijos. `conSigno`: "+1,25" / "-0,40" / "0,00" (para anomalías). */
export function formatoValor(n: number, decimales: number, conSigno = false): string {
  return n.toLocaleString('es-UY', {
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
    useGrouping: false,
    signDisplay: conSigno ? 'exceptZero' : 'auto',
  })
}

/** "2026-11-20" -> "20/11/2026" (sin pasar por Date: no hay corrimiento por zona horaria). */
export function formatoDia(iso: string): string {
  const [a, m, d] = iso.split('-')
  return a && m && d ? `${d}/${m}/${a}` : iso
}

/** Días enteros desde una fecha "YYYY-MM-DD" (UTC) hasta hoy. NaN si es inválida. */
export function diasDesde(iso: string, ahora: number = Date.now()): number {
  const t = Date.parse(`${iso}T00:00:00Z`)
  return Math.floor((ahora - t) / 86_400_000)
}

const diaMes = new Intl.DateTimeFormat('es-UY', { timeZone: TIMEZONE, day: '2-digit', month: '2-digit' })
const mes = new Intl.DateTimeFormat('es-UY', { timeZone: TIMEZONE, month: 'short' })

/** Segundos desde 1970 -> "20/11" (eje de los gráficos). */
export const formatoDiaMes = (s: number) => diaMes.format(s * 1000)
/** Segundos desde 1970 -> "nov" (eje de 6 meses). */
export const formatoMes = (s: number) => mes.format(s * 1000).replace('.', '')
/** Segundos desde 1970 -> "20/11/2026, 16:00 UTC". */
export const formatoInstante = (s: number) => formatoFecha(new Date(s * 1000).toISOString())
