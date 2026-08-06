/**
 * La caja.
 *
 * Modelo mental: el carro vive en el navegador mientras se escanea, y se
 * **materializa** en un ticket de ORDO —cabecera, líneas y cobro— en cuanto hay
 * que simular o cobrar. Un ticket materializado que ya no corresponde al carro
 * se cancela antes de rehacerse: cobrar líneas viejas es peor que fallar.
 *
 * Todo lo que decide esta pantalla es qué llamar y cuándo. Los totales, el
 * vuelto, el asiento y el descuento de stock los resuelve ORDO; si el carro
 * calculara su propio total habría dos verdades y la del navegador sería la
 * equivocada. Por eso hasta validar se rotula como provisional.
 */

import { clear, h, render } from "desk/core/dom.js";
import { api, newKey } from "desk/core/http.js";
import { format, multiply, sum, toDecimal, toMinor } from "desk/core/money.js";
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
      method: methods.rows.find((m) => m.method_type === "cash") || methods.rows[0],
      received: null, // lo que entrega el cliente en efectivo
      ticket: null, // el ticket ya materializado en ORDO
      stale: false, // el carro cambió después de materializar
      preview: null,
      receipt: null,
      error: null,
      busy: false,
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

function touched() {
  // El ticket materializado deja de corresponder al carro. No se cancela aquí
  // —sería una llamada de red en medio de un click— sino al rehacerlo.
  if (state.ticket) state.stale = true;
  state.preview = null;
  state.error = null;
}

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
  state.received = null;
  touched();
}

function removeLine(index) {
  state.cart.splice(index, 1);
  state.received = null;
  touched();
}

/** Provisional: el total de verdad lo fija el servidor al validar. */
function provisionalTotal() {
  return sum(state.cart.map((line) => multiply(line.price_unit, line.quantity)));
}

/** Lo que se entrega en efectivo: por defecto, el billete siguiente. */
function defaultReceived() {
  const total = toMinor(provisionalTotal());
  const step = toMinor("1000");
  if (total === 0n || total % step === 0n) return toDecimal(total);
  return toDecimal((total / step + 1n) * step);
}

function payingAmount() {
  if (state.method?.method_type !== "cash") return provisionalTotal();
  return state.received ?? defaultReceived();
}

// ---------------------------------------------------------------- acciones

/**
 * Deja en ORDO un ticket que corresponde al carro actual, con su cobro.
 *
 * Simular exige un ticket real: la simulación corre sobre un registro y se
 * revierte, pero el registro tiene que existir. Y exige el cobro, porque un
 * ticket sin cobro no es válido y la simulación diría exactamente eso —que es
 * lo que decía antes, cuando el cobro solo se creaba en la ruta real.
 */
async function materialise() {
  if (state.ticket && !state.stale) return state.ticket;
  if (state.ticket && state.stale) {
    // Cancelar y rehacer, en vez de parchear líneas: un ticket a medio
    // corregir es la forma silenciosa de cobrar lo que no era. Y un borrador
    // abandonado bloquea el cierre del turno.
    try {
      await api.run("pos.order", state.ticket.id, "action_cancel", {}, newKey());
    } catch {
      // Si ya no se deja cancelar, se abandona: el nuevo es el que vale.
    }
    state.ticket = null;
    state.stale = false;
  }

  const key = newKey();
  const created = await api.create(
    "pos.order",
    {
      session_id: state.session.id,
      state: "draft",
      date_order: new Date().toISOString().slice(0, 10),
      currency_id: 1,
      company_id: 1,
    },
    `${key}:order`,
  );
  const id = created.ids[0];
  await api.create(
    "pos.order.line",
    state.cart.map((line) => ({
      order_id: id,
      name: line.name,
      product_id: line.product_id,
      quantity: line.quantity,
      price_unit: line.price_unit,
      discount_percent: "0",
      tax_codes: TAX_CODE,
      income_account_id: null,
      company_id: 1,
    })),
    `${key}:lines`,
  );
  await api.create(
    "pos.payment",
    { order_id: id, method_id: state.method.id, amount: payingAmount(), company_id: 1 },
    `${key}:payment`,
  );
  state.ticket = { id, key };
  state.stale = false;
  return state.ticket;
}

async function simulate(root) {
  if (!state.cart.length || state.busy) return;
  state.busy = true;
  state.error = null;
  draw(root);
  try {
    const ticket = await materialise();
    const response = await api.run("pos.order", ticket.id, "action_validate", {}, null, {
      dryRun: true,
    });
    const outcome = response.result;
    // `validations` vacío significa que saldría bien; con contenido, esos son
    // los motivos por los que fallaría. Tratar un `would_return` vacío como
    // éxito es lo que hacía que la simulación mintiera.
    state.preview = {
      ok: (outcome.validations || []).length === 0,
      would: outcome.would_return || {},
      problems: outcome.validations || [],
    };
  } catch (error) {
    state.error = error;
  } finally {
    state.busy = false;
    draw(root);
  }
}

async function charge(root) {
  if (!state.cart.length || state.busy) return;
  state.busy = true;
  state.error = null;
  draw(root);
  try {
    const ticket = await materialise();
    const done = await api.run(
      "pos.order",
      ticket.id,
      "action_validate",
      {},
      `${ticket.key}:validate`,
    );
    state.receipt = done.result;
    state.cart = [];
    state.ticket = null;
    state.stale = false;
    state.preview = null;
    state.received = null;
  } catch (error) {
    state.error = error;
  } finally {
    state.busy = false;
    draw(root);
  }
}

async function discard(root) {
  if (state.busy) return;
  state.busy = true;
  draw(root);
  try {
    if (state.ticket) {
      await api.run("pos.order", state.ticket.id, "action_cancel", {}, newKey());
    }
  } catch (error) {
    state.error = error;
  } finally {
    state.cart = [];
    state.ticket = null;
    state.stale = false;
    state.preview = null;
    state.received = null;
    state.busy = false;
    draw(root);
  }
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
  if (!shown.length) return h("p", { class: "state" }, "Nada con ese nombre ni ese SKU.");
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
    // Solo se repintan los resultados: redibujar el panel entero en cada tecla
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
    if (state.error) pane.append(errorBox());
    return pane;
  }

  pane.append(lines(root), totalBox(), paymentBox(root));
  if (state.preview) pane.append(previewBox());
  if (state.error) pane.append(errorBox());
  pane.append(actions(root));
  return pane;
}

function lines(root) {
  return h(
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
  );
}

function totalBox() {
  return h(
    "p",
    { class: "total" },
    "Total provisional ",
    h("strong", {}, format(provisionalTotal())),
    h("small", {}, " · el definitivo lo fija el servidor"),
  );
}

function paymentBox(root) {
  const box = h(
    "div",
    { class: "payment" },
    h(
      "div",
      { class: "methods" },
      ...state.methods.map((method) =>
        h(
          "button",
          {
            class: method.id === state.method?.id ? "chip on" : "chip",
            onClick: () => {
              state.method = method;
              state.received = null;
              touched();
              draw(root);
            },
          },
          method.name,
        ),
      ),
    ),
  );
  if (state.method?.method_type === "cash") {
    box.append(
      h(
        "label",
        { class: "received" },
        "Recibe ",
        h("input", {
          type: "text",
          inputmode: "decimal",
          value: state.received ?? defaultReceived(),
          onChange: (event) => {
            state.received = event.target.value.trim() || null;
            touched();
            draw(root);
          },
        }),
      ),
    );
  }
  return box;
}

function previewBox() {
  if (!state.preview.ok) {
    return h(
      "div",
      { class: "preview bad" },
      h("strong", {}, "Así no se puede cobrar"),
      h(
        "ul",
        {},
        ...state.preview.problems.map((problem) =>
          h("li", {}, h("code", {}, problem.code), " ", problem.message),
        ),
      ),
    );
  }
  const would = state.preview.would;
  return h(
    "div",
    { class: "preview" },
    h("strong", {}, "Esto es lo que va a pasar"),
    h(
      "ul",
      {},
      h("li", {}, `Ticket ${would.name} — número simulado, no se gastó`),
      h("li", {}, `Total ${format(would.amount_total)} · vuelto ${format(would.change)}`),
      h("li", {}, "Asiento contabilizado y stock descontado de la sala de ventas"),
    ),
  );
}

function errorBox() {
  const plain = humanize(state.error);
  return h(
    "div",
    { class: "state error" },
    h("p", {}, plain.message),
    plain.hint ? h("p", { class: "hint" }, plain.hint) : null,
    h("code", { class: "code" }, plain.code),
  );
}

function actions(root) {
  return h(
    "div",
    { class: "actions" },
    h("button", { class: "ghost", disabled: state.busy, onClick: () => discard(root) }, "Descartar"),
    h(
      "button",
      { class: "ghost", disabled: state.busy, onClick: () => simulate(root) },
      state.busy ? "…" : "Simular",
    ),
    h(
      "button",
      {
        // Deshabilitado mientras vuela: pulsar dos veces no puede cobrar dos
        // veces, y la clave de idempotencia es la red que hay debajo.
        class: "primary",
        disabled: state.busy,
        onClick: () => charge(root),
      },
      state.busy ? "Cobrando…" : "Cobrar",
    ),
  );
}

function receipt(root) {
  return h(
    "div",
    { class: "receipt" },
    h("h2", {}, `Ticket ${state.receipt.name}`),
    h("p", { class: "big" }, format(state.receipt.amount_total)),
    h(
      "ul",
      {},
      h("li", {}, `Vuelto ${format(state.receipt.change)}`),
      h("li", {}, `Asiento ${state.receipt.move_id} contabilizado`),
      state.receipt.picking_id
        ? h("li", {}, `Salida de bodega ${state.receipt.picking_id} validada`)
        : null,
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
