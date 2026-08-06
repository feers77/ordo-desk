/** El armazón: cabecera con la persona activa y el cajón de peticiones. */

import { h, clear } from "desk/core/dom.js";
import { humanize } from "desk/core/errors.js";
import { bus } from "desk/core/bus.js";
import { routesFor } from "desk/core/routes.js";
import { chatPanel, connect } from "desk/telegram/chat.js";

export function shell(root, ctx) {
  const main = h("main", { class: "content" });
  const log = h("ol", { class: "reqlog", reversed: true });

  const header = h(
    "header",
    { class: "topbar" },
    h("span", { class: "brand" }, "ORDO"),
    h(
      "nav",
      {},
      ...routesFor(ctx.session.persona).map(([hash, screen]) =>
        h("a", { href: hash, class: "nav-link" }, screen.label),
      ),
    ),
    h(
      "span",
      { class: "who" },
      h("strong", {}, ctx.session.persona),
      " · ",
      h("code", {}, ctx.session.tenant),
    ),
    h(
      "button",
      { class: "ghost", onClick: () => document.body.classList.toggle("show-log") },
      "peticiones",
    ),
    h(
      "button",
      { class: "ghost", onClick: () => document.body.classList.toggle("show-chat") },
      "Telegram",
    ),
  );

  bus.on("http", (entry) => {
    const item = h(
      "li",
      { class: entry.status < 400 ? "ok" : "bad" },
      h("code", {}, `${entry.method} ${entry.path}`),
      h("span", { class: "meta" }, `${entry.status} · ${entry.ms} ms`),
    );
    log.prepend(item);
    while (log.children.length > 60) log.lastChild.remove();
  });

  clear(root).append(
    header,
    main,
    h("aside", { class: "drawer" }, h("h2", {}, "Peticiones a la API"), log),
    chatPanel(),
  );
  // El chat escucha desde que se abre el escritorio: una aprobación puede
  // llegar mientras el cajero está en otra pantalla.
  connect();
  return main;
}

export function loading(root, text = "Cargando…") {
  clear(root).append(h("p", { class: "state" }, text));
}

export function failure(root, error, retry) {
  const plain = humanize(error);
  clear(root).append(
    h(
      "div",
      { class: "state error" },
      h("p", {}, plain.message),
      plain.hint ? h("p", { class: "hint" }, plain.hint) : null,
      h("code", { class: "code" }, plain.code),
      plain.retryable && retry
        ? h("button", { class: "primary", onClick: retry }, "Reintentar")
        : null,
    ),
  );
}

export function empty(root, text) {
  clear(root).append(h("p", { class: "state" }, text));
}
