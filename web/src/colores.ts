// Colores de las series comparadas (puntos costeros). Paleta categórica validada para
// daltonismo (protan/deután/tritán) sobre fondo blanco. Tres tienen poco contraste con el
// fondo, por eso cada línea va SIEMPRE con su nombre en texto (botones y lectura), nunca solo color.
// Orden fijo: un punto conserva su color mientras siga elegido (no se repinta al sumar o sacar otros).
export const PALETA_SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4'] as const
export const MAX_SERIES = PALETA_SERIES.length
