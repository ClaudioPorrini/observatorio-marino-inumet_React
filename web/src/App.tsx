import { useState } from 'react'
import Header from './components/Header'
import Observaciones from './components/Observaciones'
import Satelite from './components/Satelite'
import { useEstaciones } from './useEstaciones'

type Pestana = 'observaciones' | 'satelite'

const PESTANAS: { id: Pestana; texto: string }[] = [
  { id: 'satelite', texto: 'Satélite' },
  { id: 'observaciones', texto: 'Observaciones' }
]
// Pestaña con la que abre la página.
const PESTANA_INICIAL: Pestana = 'satelite'

export default function App() {
  // Estado: cuál pestaña está activa. Equivale a st.session_state en Streamlit,
  // pero explícito: al cambiarlo, React vuelve a dibujar lo que depende de él.
  const [activa, setActiva] = useState<Pestana>(PESTANA_INICIAL)

  // Los datos se cargan acá (en el padre) porque los usan el header y la pestaña.
  const estado = useEstaciones()

  const datos = estado.tipo === 'listo' ? estado.datos : null
  const instituciones = datos ? [...new Set(datos.stations.map((e) => e.institution))].sort() : []
  const ultima = datos
    ? datos.stations.reduce<string | null>((max, e) => (e.last_time && (!max || e.last_time > max) ? e.last_time : max), null)
    : null

  return (
    <div className="pagina">
      <Header instituciones={instituciones} ultimaMedicion={ultima} />

      <div className="pestanas" role="tablist">
        {PESTANAS.map((p) => (
          <button
            key={p.id}
            role="tab"
            type="button"
            aria-selected={activa === p.id}
            onClick={() => setActiva(p.id)}
          >
            {p.texto}
          </button>
        ))}
      </div>

      <main role="tabpanel">
        {activa === 'satelite' && <Satelite />}
        {activa === 'observaciones' && (
          <>
            {estado.tipo === 'cargando' && <p className="aviso">Cargando datos…</p>}
            {estado.tipo === 'error' && (
              <p className="aviso error" role="alert">
                No se pudieron cargar los datos. {estado.mensaje}
              </p>
            )}
            {estado.tipo === 'listo' && <Observaciones datos={estado.datos} />}
          </>
        )}
      </main>
    </div>
  )
}
