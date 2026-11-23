import type { Parada } from './types'

function rgb(hex: string): [number, number, number] {
  return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)]
}

/** Color de `valor` en la escala (interpolación lineal entre paradas; fuera de rango = extremo). */
export function colorEnEscala(valor: number, stops: Parada[]): string {
  const primero = stops[0]
  const ultimo = stops[stops.length - 1]
  if (!primero || !ultimo) return 'rgb(0,0,0)'
  const v = Math.min(Math.max(valor, primero[0]), ultimo[0])
  for (let i = 1; i < stops.length; i++) {
    const a = stops[i - 1]
    const b = stops[i]
    if (!a || !b) continue
    if (v <= b[0]) {
      const t = b[0] === a[0] ? 0 : (v - a[0]) / (b[0] - a[0])
      const ca = rgb(a[1])
      const cb = rgb(b[1])
      const c = ca.map((x, k) => Math.round(x + t * ((cb[k] ?? x) - x)))
      return `rgb(${c[0]},${c[1]},${c[2]})`
    }
  }
  return `rgb(${rgb(ultimo[1]).join(',')})`
}

/** Dibuja la barra de colores en un <canvas> (no usa estilos en línea). */
export function dibujarBarra(canvas: HTMLCanvasElement, stops: Parada[]): void {
  const ctx = canvas.getContext('2d')
  const primero = stops[0]
  const ultimo = stops[stops.length - 1]
  if (!ctx || !primero || !ultimo) return
  const { width, height } = canvas
  for (let x = 0; x < width; x++) {
    ctx.fillStyle = colorEnEscala(primero[0] + ((ultimo[0] - primero[0]) * x) / (width - 1), stops)
    ctx.fillRect(x, 0, 1, height)
  }
}
