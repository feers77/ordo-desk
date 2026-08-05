/**
 * Router por hash y montaje de pantallas.
 *
 * El catálogo de pantallas vive en `core/routes.js`, no aquí: el armazón lo
 * necesita para pintar el menú y este módulo lo importa a él, así que tenerlo
 * en cualquiera de los dos crearía un ciclo.
 */

import { h, render } from "desk/core/dom.js";
import { session as sessionApi } from "desk/core/http.js";
import { shell, failure, loading } from "desk/ui/shell.js";
import { ROUTES, landingFor, routesFor } from "desk/core/routes.js";

let current = null;

async function boot() {
  const app = document.getElementById("app");
  loading(app, "Abriendo el escritorio…");
  let session;
  try {
    session = await sessionApi.read();
  } catch (error) {
    if (error.code === "DESK_NO_SESSION") {
      render(app, picker());
      return;
    }
    failure(app, error, boot);
    return;
  }
  const ctx = { session, companyId: 1 };
  const main = shell(app, ctx);
  window.addEventListener("hashchange", () => route(main, ctx));
  await route(main, ctx);
}

function picker() {
  const personas = [
    ["cajero", "Vende y cobra en la caja"],
    ["bodeguero", "Recibe, traslada y repone"],
    ["duena", "Ve los números y aprueba"],
  ];
  return h(
    "section",
    { class: "picker" },
    h("h1", {}, "¿Con quién entras?"),
    h(
      "p",
      { class: "lead" },
      "Cada persona opera con su propio agente y sus propios permisos. ",
      "El navegador nunca ve el token: lo custodia el escritorio.",
    ),
    h(
      "div",
      { class: "cards" },
      ...personas.map(([persona, description]) =>
        h(
          "button",
          {
            class: "card",
            onClick: async () => {
              await sessionApi.start(persona);
              window.location.hash = landingFor(persona);
              await boot();
            },
          },
          h("strong", {}, persona),
          h("span", {}, description),
        ),
      ),
    ),
  );
}

async function route(main, ctx) {
  const allowed = routesFor(ctx.session.persona).map(([hash]) => hash);
  const hash = allowed.includes(window.location.hash)
    ? window.location.hash
    : landingFor(ctx.session.persona);
  if (current?.unmount) {
    try {
      current.unmount();
    } catch (error) {
      console.error("[router] unmount", error);
    }
  }
  loading(main);
  const screen = await ROUTES[hash].load();
  current = screen;
  await screen.mount(main, ctx);
}

boot();
