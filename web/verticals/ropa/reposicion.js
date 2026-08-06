/**
 * Reposición: de la alerta al traslado, sin pasos manuales.
 *
 * La pantalla no calcula cuánto reponer ni decide de dónde sale: eso lo hace la
 * regla en ORDO, que además sabe si el origen tiene existencias. Aquí solo se
 * muestra lo que el reporte ya trae y se dispara la acción que él mismo indica
 * en `suggested_action`.
 */

import { clear, h, render } from "desk/core/dom.js";
import { api, newKey } from "desk/core/http.js";
import { humanize } from "desk/core/errors.js";
import { failure, loading } from "desk/ui/shell.js";

export const title = "Reposición";

export async function mount(root, ctx) {
  await load(root, ctx);
}

async function load(root, ctx) {
  loading(root, "Revisando qué falta…");
  try {
    const plan = await api.report("stock.replenishment_plan", { company_id: ctx.companyId });
    const alerts = await api.report("stock.reorder_alerts", { company_id: ctx.companyId });
    render(root, view(root, ctx, plan, alerts));
  } catch (error) {
    failure(root, error, () => load(root, ctx));
  }
}

function view(root, ctx, plan, alerts) {
  const section = h("section", {});
  section.append(
    h("h1", {}, "Reposición"),
    h(
      "p",
      { class: "lead" },
      alerts.count === 0
        ? "Nada bajo el mínimo. La tienda está surtida."
        : `${alerts.count} variantes bajo el mínimo en ${alerts.by_template.length} modelos. ` +
          `${plan.ready.length} se pueden reponer desde bodega ahora.`,
    ),
  );

  if (!alerts.count) return section;

  for (const group of alerts.by_template) {
    section.append(card(root, ctx, group, plan));
  }

  if (plan.blocked.length) {
    section.append(
      h(
        "div",
        { class: "blocked" },
        h("strong", {}, `${plan.blocked.length} sin poder reponer`),
        h(
          "p",
          {},
          "La bodega tampoco tiene, o la regla no declara de dónde sacarlo. ",
          "Se listan aparte en vez de esconderse: es trabajo que alguien tiene que resolver.",
        ),
        h(
          "ul",
          {},
          ...plan.blocked.map((row) =>
            h(
              "li",
              {},
              `${row.name} — faltan ${row.suggested_quantity}, `,
              row.on_hand_source === null
                ? "sin origen declarado"
                : `la bodega tiene ${row.on_hand_source}`,
            ),
          ),
        ),
      ),
    );
  }
  return section;
}

function card(root, ctx, group, plan) {
  const ready = new Set(plan.ready.map((row) => row.rule_id));
  const body = h("div", { class: "variants" });
  const box = h(
    "article",
    { class: "reorder" },
    h(
      "header",
      {},
      h("h2", {}, group.name),
      h("span", { class: "shift" }, `faltan ${group.total_suggested} unidades`),
    ),
    body,
  );

  for (const variant of group.variants) {
    const line = h("div", { class: "variant" });
    const status = h("span", { class: "status" });
    line.append(
      h("strong", {}, variant.variant_label || variant.name),
      h("span", { class: "num" }, `${variant.on_hand} en sala`),
      h("span", { class: "num" }, `faltan ${variant.suggested_quantity}`),
      status,
    );
    if (ready.has(variant.rule_id)) {
      line.append(
        h(
          "button",
          {
            class: "primary tiny",
            onClick: async (event) => {
              const button = event.target;
              button.disabled = true;
              button.textContent = "Trasladando…";
              try {
                const done = await api.run(
                  "stock.reorder.rule",
                  variant.rule_id,
                  variant.suggested_action,
                  {},
                  newKey(),
                );
                clear(status).append(
                  h("span", { class: "done" }, `${done.result.name} · ${done.result.quantity}`),
                );
                button.remove();
              } catch (error) {
                const plain = humanize(error);
                clear(status).append(h("code", { class: "code" }, plain.code));
                button.disabled = false;
                button.textContent = "Reintentar";
              }
            },
          },
          "Traer de bodega",
        ),
      );
    } else {
      status.append(
        h(
          "span",
          { class: "muted" },
          variant.on_hand_source === null
            ? "sin origen"
            : `bodega: ${variant.on_hand_source}`,
        ),
      );
    }
    body.append(line);
  }

  box.append(
    h(
      "footer",
      {},
      h(
        "button",
        {
          class: "ghost tiny",
          onClick: () => load(root, ctx),
        },
        "Actualizar",
      ),
    ),
  );
  return box;
}
