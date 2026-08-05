/**
 * La caja.
 *
 * Todo lo que decide esta pantalla es qué llamar y cuándo. Los totales, el
 * vuelto, el asiento y el descuento de stock los resuelve ORDO: si el carro
 * calculara su propio total, habría dos verdades y la del navegador sería la
 * equivocada. Por eso el total del carro se rotula como provisional hasta que
 * `action_validate` devuelve el de verdad.
 */

import { clear, h, render } from "desk/core/dom.js";
import { api, newKey } from "desk/core/http.js";
import { format, multiply, sum } from "desk/core/money.js";
import { humanize } from "desk/core/errors.js";
import { failure, loading } from "desk/ui/shell.js";

export const title = "Caja";

const TAX_CODE = "IVA19I"; // precios con IVA incluido, como exige el retail chileno

let state = null;

export function unmount() {
  state = null;
}

export async function mount(root, ctx) {
  loading(root, "Abriendo la caja…");
  try {
    const [config, methods, catalog] = await Promise.all([
      firstRow("pos.config", ["id", "name", "location_id"]),
      api.search("pos.payment.method", {
        fields: ["id", "name", "code", "method_type"],
        limit: 20,
      }),
      api.search("product.product", {
        domain: [["product_type", "=", "consu"]],
        fields: ["id", "name", "default_code", "list_price"],
        limit: 200,
      }),
    ]);
    const session = await openShift(config.id);
    state = {
      ctx,
      config,
      session,
      methods: methods.rows,
      catalog: catalog.rows,
      cart: [],
      // La clave se acuña al abrir la venta y vive hasta que el carro se vacía.
      // Renovarla entre reintentos es exactamente cómo se cobra dos veces.
      key: newKey(),
      busy: false,
      preview: null,
      receipt: null,
      search: "",
    };
    draw(root);
  } catch (error) {
    failure(root, error, () => mount(root, ctx));
  }
}

async function firstRow(model, fields) {
  const result = await api.search(model, { fields, limit: 1 });
  if (!result.rows.length) throw new Error(`No hay ${model} configurado`);
  return result.rows[0];
}

/** El turno abierto de esta caja, o uno nuevo. */
async function openShift(configId) {
  const open = await api.search("pos.session", {
    domain: [
      ["config_id", "=", configId],
      ["state", "=", "opened"],
    ],
    fields: ["id", "name", "state", "opening_cash"],
    limit: 1,
  });
  if (open.rows.length) return open.rows[0];

  const created = await api.create(
    "pos.session",
    { config_id: configId, state: "draft", company_id: 1 },
    newKey(),
  );
  const id = created.ids[0];
  const opened = await api.run(
    "pos.session",
    id,
    "action_open",
    { opening_cash: "50000" },
    newKey(),
  );
  return { id, name: opened.result.name, state: "opened", opening_cash: "50000" };
}

// ------------------------------------------------------------------ carro

function addLine(product) {
  const existing = state.cart.find((line) => line.product_id === product.id);
  if (existing) existing.quantity = String(Number(existing.quantity) + 1);
  else
    state.cart.push({
      product_id: product.id,
      name: product.name,
      price_unit: product.list_price,
      quantity: "1",
    });
  state.preview = null;
}

function removeLine(index) {
  state.cart.splice(index, 1);
  state.preview = null;
}

/** Provisional: el total de verdad lo fija el servidor al validar. */
function provisionalTotal() {
  return sum(state.cart.map((line) => multiply(line.price_unit, line.quantity)));
}

// ---------------------------------------------------------------- acciones

async function charge(root, { dryRun }) {
  if (!state.cart.length || state.busy) return;
  state.busy = true;
  draw(root);
  try {
    const orderId = await createOrder();
    if (dryRun) {
      // Simular no cobra ni quema numeración: el savepoint de la acción se
      // revierte. Es lo que deja ver "esto es lo que va a pasar" sin riesgo.
      const simulated = await api.run("pos.order", orderId, "action_validate", {}, null, {
        dryRun: true,
      });
      state.preview = simulated.result.would_return || simulated.result;
      state.pendingOrder = orderId;
    } else {
      await payFor(orderId);
      const done = await api.run(
        "pos.order",
        orderId,
        "action_validate",
        {},
        `${state.key}:validate`,
      );
      state.receipt = done.result;
      state.cart = [];
      state.preview = null;
      state.pendingOrder = null;
      state.key = newKey();
    }
  } catch (error) {
    state.error = error;
  } finally {
    state.busy = false;
    draw(root);
  }
}

async function createOrder() {
  if (state.pendingOrder) return state.pendingOrder;
  const created = await api.create(
    "pos.order",
    {
      session_id: state.session.id,
      state: "draft",
      date_order: new Date().toISOString().slice(0, 10),
      currency_id: 1,
      company_id: 1,
    },
    `${state.key}:order`,
  );
  const orderId = created.ids[0];
  await api.create(
    "pos.order.line",
    state.cart.map((line) => ({
      order_id: orderId,
      name: line.name,
      product_id: line.product_id,
      quantity: line.quantity,
      price_unit: line.price_unit,
      discount_percent: "0",
      tax_codes: TAX_CODE,
      income_account_id: null,
      company_id: 1,
    })),
    `${state.key}:lines`,
  );
  state.pendingOrder = orderId;
  return orderId;
}

async function payFor(orderId) {
  const cash = state.methods.find((method) => method.method_type === "cash");
  const total = state.preview ? state.preview.amount_total : provisionalTotal();
  await api.create(
    "pos.payment",
    { order_id: orderId, method_id: cash.id, amount: total, company_id: 1 },
    `${state.key}:payment`,
  );
}

// ----------------------------------------------------------------- pintado

function draw(root) {
  render(root, h("div", { class: "pos" }, catalogPane(root), cartPane(root)));
}

function matches(product, term) {
  if (!term) return true;
  return (
    product.name.toLowerCase().includes(term) ||
    (product.default_code || "").toLowerCase().includes(term)
  );
}

function tiles(root) {
  const term = state.search.toLowerCase();
  const shown = state.catalog.filter((product) => matches(product, term)).slice(0, 40);
  if (!shown.length) {
    return h("p", { class: "state" }, "Nada con ese nombre ni ese SKU.");
  }
  return h(
    "div",
    { class: "tiles" },
    ...shown.map((product) =>
      h(
        "button",
        {
          class: "tile",
          onClick: () => {
            addLine(product);
            draw(root);
          },
        },
        h("strong", {}, product.name),
        h("span", {}, format(product.list_price)),
      ),
    ),
  );
}

function catalogPane(root) {
  const results = h("div", { class: "results" }, tiles(root));
  const input = h("input", {
    class: "search",
    type: "search",
    placeholder: "Buscar por nombre o SKU…",
    value: state.search,
    // Solo se repintan los resultados. Redibujar el panel entero en cada tecla
    // destruiría el input y el cursor se perdería en la primera letra.
    onInput: (event) => {
      state.search = event.target.value;
      clear(results).append(tiles(root));
    },
  });
  return h("section", { class: "catalog" }, input, results);
}

function cartPane(root) {
  const pane = h("aside", { class: "cart" });
  pane.append(
    h(
      "header",
      {},
      h("h1", {}, "Venta"),
      h("span", { class: "shift" }, `turno ${state.session.name}`),
    ),
  );

  if (state.receipt) {
    pane.append(receipt(root));
    return pane;
  }

  if (!state.cart.length) {
    pane.append(h("p", { class: "state" }, "Toca un producto para agregarlo."));
    return pane;
  }

  pane.append(
    h(
      "ul",
      { class: "lines" },
      ...state.cart.map((line, index) =>
        h(
          "li",
          {},
          h("span", { class: "qty" }, `${line.quantity}×`),
          h("span", { class: "name" }, line.name),
          h("span", { class: "amount" }, format(multiply(line.price_unit, line.quantity))),
          h(
            "button",
            {
              class: "ghost tiny",
              onClick: () => {
                removeLine(index);
                draw(root);
              },
            },
            "quitar",
          ),
        ),
      ),
    ),
    h(
      "p",
      { class: "total" },
      state.preview
        ? h("span", {}, "Total ", h("strong", {}, format(state.preview.amount_total)))
        : h(
            "span",
            {},
            "Total provisional ",
            h("strong", {}, format(provisionalTotal())),
            h("small", {}, " · el definitivo lo fija el servidor"),
          ),
    ),
  );

  if (state.preview) {
    pane.append(
      h(
        "div",
        { class: "preview" },
        h("strong", {}, "Esto es lo que va a pasar"),
        h(
          "ul",
          {},
          h("li", {}, `Ticket ${state.preview.name} (número simulado, no se gastó)`),
          h("li", {}, `Total ${format(state.preview.amount_total)}`),
          h("li", {}, "Asiento contabilizado y stock descontado de la sala de ventas"),
        ),
      ),
    );
  }

  if (state.error) {
    const plain = humanize(state.error);
    pane.append(
      h(
        "div",
        { class: "state error" },
        h("p", {}, plain.message),
        plain.hint ? h("p", { class: "hint" }, plain.hint) : null,
        h("code", { class: "code" }, plain.code),
      ),
    );
  }

  pane.append(
    h(
      "div",
      { class: "actions" },
      h(
        "button",
        {
          class: "ghost",
          disabled: state.busy,
          onClick: () => charge(root, { dryRun: true }),
        },
        "Simular",
      ),
      h(
        "button",
        {
          class: "primary",
          // Deshabilitado mientras vuela: pulsar dos veces no puede cobrar dos
          // veces, y la clave de idempotencia es la red que hay debajo.
          disabled: state.busy,
          onClick: () => charge(root, { dryRun: false }),
        },
        state.busy ? "Cobrando…" : "Cobrar en efectivo",
      ),
    ),
  );
  return pane;
}

function receipt(root) {
  // `root` viaja explícito en vez de buscarse en el documento: un selector
  // aquí ataría la pantalla a la forma del armazón.
  return h(
    "div",
    { class: "receipt" },
    h("h2", {}, `Ticket ${state.receipt.name}`),
    h("p", { class: "big" }, format(state.receipt.amount_total)),
    h(
      "ul",
      {},
      h("li", {}, `Asiento ${state.receipt.move_id} contabilizado`),
      state.receipt.picking_id
        ? h("li", {}, `Salida de bodega ${state.receipt.picking_id} validada`)
        : null,
      h("li", {}, `Vuelto ${format(state.receipt.change)}`),
    ),
    h(
      "button",
      {
        class: "primary",
        onClick: () => {
          state.receipt = null;
          state.error = null;
          draw(root);
        },
      },
      "Siguiente venta",
    ),
  );
}
