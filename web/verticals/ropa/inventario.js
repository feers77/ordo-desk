/**
 * Primera pantalla: existencias de la tienda.
 *
 * Deliberadamente sencilla. Lo que prueba no es la interfaz sino la cadena
 * completa: cookie de sesión, token de agente puesto por el BFF, permiso
 * resuelto por el PDP y datos reales de ORDO, sin que el navegador vea nunca
 * una credencial.
 */

import { h, render } from "desk/core/dom.js";
import { api } from "desk/core/http.js";
import { format } from "desk/core/money.js";
import { empty, failure, loading } from "desk/ui/shell.js";

export const title = "Inventario";

export async function mount(root, ctx) {
  await load(root, ctx);
}

async function load(root, ctx) {
  loading(root, "Contando existencias…");
  try {
    const report = await api.report("stock.on_hand", { company_id: ctx.companyId });
    if (!report.rows.length) {
      empty(root, "La bodega está vacía. Recibe mercadería para verla aquí.");
      return;
    }
    render(root, table(report));
  } catch (error) {
    failure(root, error, () => load(root, ctx));
  }
}

function table(report) {
  return h(
    "section",
    {},
    h("h1", {}, "Existencias"),
    h(
      "p",
      { class: "lead" },
      "Valor total del inventario: ",
      h("strong", {}, format(report.total_value)),
    ),
    h(
      "table",
      { class: "grid" },
      h(
        "thead",
        {},
        h(
          "tr",
          {},
          h("th", {}, "Producto"),
          h("th", {}, "SKU"),
          h("th", { class: "num" }, "Cantidad"),
          h("th", { class: "num" }, "Costo promedio"),
          h("th", { class: "num" }, "Valor"),
        ),
      ),
      h(
        "tbody",
        {},
        ...report.rows.map((row) =>
          h(
            "tr",
            {},
            h("td", {}, row.name),
            h("td", {}, h("code", {}, row.default_code || "—")),
            h("td", { class: "num" }, row.quantity),
            h("td", { class: "num" }, format(row.average_cost)),
            h("td", { class: "num" }, format(row.value)),
          ),
        ),
      ),
    ),
  );
}
