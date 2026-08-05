/**
 * Qué pantallas existen y a qué personas sirven.
 *
 * Vive aparte del router para que el armazón pueda pintar el menú sin importar
 * `app.js`, que a su vez importa el armazón: un ciclo que hoy funcionaría por
 * el orden de evaluación y mañana no.
 *
 * La lista de personas no es cosmética. El capability token del cajero no
 * incluye reportes, así que mandarlo a la bodega produce un 403 correcto y una
 * pantalla rota; quien no puede entrar no la ve en el menú ni aterriza en ella.
 */

export const ROUTES = {
  "#/ropa/pos": {
    label: "Caja",
    personas: ["cajero"],
    load: () => import("desk/verticals/ropa/pos.js"),
  },
  "#/ropa/inventario": {
    label: "Inventario",
    personas: ["bodeguero", "duena"],
    load: () => import("desk/verticals/ropa/inventario.js"),
  },
  "#/como-funciona": {
    label: "Cómo funciona",
    personas: ["cajero", "bodeguero", "duena"],
    load: () => import("desk/panels/como-funciona.js"),
  },
};

export function routesFor(persona) {
  return Object.entries(ROUTES).filter(([, screen]) => screen.personas.includes(persona));
}

export function landingFor(persona) {
  const [hash] = routesFor(persona)[0] || ["#/como-funciona"];
  return hash;
}
