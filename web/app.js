/**
 * Router por hash y montaje de pantallas.
 *
 * Sin framework y sin build: cada pantalla exporta `mount(root, ctx)` y, si
 * necesita soltar algo, `unmount()`. El router desmonta la anterior antes de
 * montar la siguiente, que es todo el ciclo de vida que hace falta.
 */

import { h, render } from "desk/core/dom.js";
import { session as sessionApi } from "desk/core/http.js";
import { shell, failure, loading } from "desk/ui/shell.js";

const ROUTES = {
  "#/ropa/inventario": () => import("desk/verticals/ropa/inventario.js"),
  "#/como-funciona": () => import("desk/panels/como-funciona.js"),
};
const DEFAULT_ROUTE = "#/ropa/inventario";

let current = null;

async function boot() {
  const app = document.getElementById("app");
  loading(app, "Abriendo el escritorio…");
  let session;
  try {
    session = await sessionApi.read();
  } catch (error) {
    if (error.code === "DESK_NO_SESSION") {
      render(app, picker(app));
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

function picker(app) {
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
  const hash = ROUTES[window.location.hash] ? window.location.hash : DEFAULT_ROUTE;
  if (current?.unmount) {
    try {
      current.unmount();
    } catch (error) {
      console.error("[router] unmount", error);
    }
  }
  loading(main);
  const screen = await ROUTES[hash]();
  current = screen;
  await screen.mount(main, ctx);
}

boot();
