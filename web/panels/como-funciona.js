/**
 * El panel que explica el sistema.
 *
 * Por ahora, lo esencial: que todo lo que se ve en pantalla es una llamada
 * HTTP que cualquiera puede repetir con curl. El registro de peticiones del
 * cajón lateral lo demuestra en vivo.
 */

import { h, render } from "desk/core/dom.js";

export const title = "Cómo funciona";

export async function mount(root, ctx) {
  render(
    root,
    h(
      "section",
      {},
      h("h1", {}, "Cómo funciona"),
      h(
        "p",
        { class: "lead" },
        "Debajo de este escritorio no hay nada más que la API de ORDO. ",
        "Abre el cajón de peticiones y verás cada llamada que hace la pantalla.",
      ),
      h(
        "ol",
        { class: "steps" },
        h(
          "li",
          {},
          h("strong", {}, "El navegador no tiene credenciales. "),
          "Su única cookie es una sesión firmada que dice con quién entraste. ",
          "El token de agente vive en el escritorio, se renueva solo a los 12 de sus 15 ",
          "minutos y jamás baja al cliente.",
        ),
        h(
          "li",
          {},
          h("strong", {}, "Cada persona es un agente distinto. "),
          `Ahora operas como ${ctx.session.persona}: el PDP resuelve sus permisos en cada `,
          "llamada, y lo que no puede hacer devuelve 403 con su motivo.",
        ),
        h(
          "li",
          {},
          h("strong", {}, "Las escrituras llevan clave de idempotencia. "),
          "La acuña la pantalla, no el servidor: solo quien sabe qué es una intención ",
          "puede mantener la misma clave entre reintentos.",
        ),
      ),
    ),
  );
}
