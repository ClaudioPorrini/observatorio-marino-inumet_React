import { formatoFecha } from '../format'

// Logo opcional: si existe src/assets/inumet-logo.(jpg|png|svg) se incluye en el build;
// si no existe, el header se ve igual (sin logo) y nada falla.
const logos = import.meta.glob<string>('../assets/inumet-logo.*', { eager: true, import: 'default' })
const logoSrc = Object.values(logos)[0]

interface Props {
  instituciones: string[] // las que realmente aportan datos (sale del JSON)
  ultimaMedicion: string | null
}

export default function Header({ instituciones, ultimaMedicion }: Props) {
  return (
    <header className="cabecera">
      {logoSrc && <img src={logoSrc} alt="INUMET" />}
      <div>
        <h1>Observatorio Marino y Costero del Uruguay</h1>
        {instituciones.length > 0 && <div className="sub">{instituciones.join(' · ')}</div>}
      </div>
      {ultimaMedicion && (
        <div className="ultima">
          Última medición
          <b>{formatoFecha(ultimaMedicion)}</b>
        </div>
      )}
    </header>
  )
}
