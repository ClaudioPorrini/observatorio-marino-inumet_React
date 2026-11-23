import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// En DESARROLLO (npm run dev) Vite sirve la carpeta ../public en la raíz, o sea
// los JSON que genera el pipeline quedan en:
//   http://localhost:5173/observaciones/estaciones.json
// En el BUILD no se copia nada: los datos los sirve el servidor, no van dentro de dist/.
export default defineConfig(({ command }) => ({
  plugins: [react()],
  publicDir: command === 'serve' ? '../public' : false,
  base: './', // rutas relativas: dist/ funciona colgado de cualquier subruta del sitio
  // Sin imágenes embebidas como data: (los íconos del CSS de Leaflet): una CSP estricta las bloquea.
  build: { assetsInlineLimit: 0 },
}))
