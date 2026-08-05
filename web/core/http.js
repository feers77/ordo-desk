/**
 * El único sitio del escritorio que toca `fetch`.
 *
 * Concentra tres cosas que en cualquier otro lado se hacen mal: leer el
 * envelope de error de ORDO en vez de inventar un mensaje, reintentar solo lo
 * que el servidor declaró reintentable **con la misma clave de idempotencia**,
 * y registrar cada llamada para el panel "cómo funciona".
 */

import { bus } from "desk/core/bus.js";
import { newKey } from "desk/core/ids.js";

// Dos prefijos, uno por familia de rutas de ORDO. Leen igual que las suyas.
const API = "/desk/api";
const META = "/desk/meta";
const MAX_RETRIES = 2;

// Se reexporta para que las pantallas no tengan que conocer de dónde sale la
// clave; lo único que les importa es acuñarla una vez por intención.
export { newKey };

/** Error con el contrato de ORDO, no una cadena suelta. */
export class OrdoError extends Error {
  constructor(payload, status) {
    const error = (payload && payload.error) || {};
    super(error.message || `Error ${status}`);
    this.name = "OrdoError";
    this.code = error.code || "UNKNOWN";
    this.hint = error.hint || "";
    this.status = status;
    this.retryable = Boolean(error.retryable);
    this.requiresApproval = Boolean(error.requires_approval);
    this.traceId = error.trace_id || "";
    this.field = error.field || "";
    this.currentState = error.current_state || null;
  }
}

function query(params) {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    search.set(key, typeof value === "string" ? value : JSON.stringify(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function once(path, { method = "GET", body, key, params, base = API } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (key) headers["Idempotency-Key"] = key;

  const started = performance.now();
  const response = await fetch(`${base}${path}${query(params)}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });

  let payload = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }
  bus.emit("http", {
    method,
    path: `${path}${query(params)}`,
    status: response.status,
    ms: Math.round(performance.now() - started),
    body,
    key: key || null,
  });
  if (!response.ok) throw new OrdoError(payload, response.status);
  return payload;
}

/**
 * Una llamada, con reintento solo si el servidor lo declaró reintentable.
 *
 * La clave de idempotencia **no** se renueva entre intentos: renovarla es
 * exactamente cómo se cobra dos veces.
 */
export async function request(path, options = {}) {
  let attempt = 0;
  for (;;) {
    try {
      return await once(path, options);
    } catch (error) {
      const isOrdo = error instanceof OrdoError;
      const retryable = isOrdo ? error.retryable : true; // fallo de red
      if (!retryable || attempt >= MAX_RETRIES) throw error;
      attempt += 1;
      await new Promise((resolve) => setTimeout(resolve, 250 * attempt));
    }
  }
}

export const api = {
  search: (model, { domain, fields, limit, cursor, order } = {}) =>
    request(`/v1/${model}`, {
      params: {
        domain: domain ? JSON.stringify(domain) : undefined,
        fields: fields ? fields.join(",") : undefined,
        limit,
        cursor,
        order,
      },
    }),
  read: (model, id, fields) =>
    request(`/v1/${model}/${id}`, { params: { fields: fields ? fields.join(",") : undefined } }),
  aggregate: (model, body) => request(`/v1/${model}/aggregate`, { method: "POST", body }),
  create: (model, values, key) =>
    request(`/v1/${model}`, { method: "POST", body: { values }, key }),
  write: (model, id, values, key, expectedVersion) =>
    request(`/v1/${model}/${id}`, {
      method: "PATCH",
      body: { values, expected_version: expectedVersion ?? null },
      key,
    }),
  tx: (operations, key) =>
    request(`/v1/tx`, { method: "POST", body: { atomic: true, operations }, key }),
  actions: (model) => request(`/v1/${model}/actions`),
  run: (model, id, action, params, key, { dryRun = false } = {}) =>
    request(`/v1/${model}/${id}/actions/${action}`, {
      method: "POST",
      body: { params: params || {} },
      key,
      params: dryRun ? { dry_run: "true" } : undefined,
    }),
  explain: (model, id) => request(`/v1/${model}/${id}/explain`),
  report: (name, params) => request(`/v1/reports/${name}`, { params }),
  reports: () => request(`/v1/reports`),
  schema: (models) =>
    request(`/v1/schema`, { base: META, params: { models: models.join(",") } }),
  translate: (question, models) =>
    request(`/v1/translate-query`, {
      base: META,
      method: "POST",
      body: { question, models: models || null },
    }),
};

/** La sesión no pasa por el proxy: es del propio escritorio. */
export const session = {
  read: async () => {
    const response = await fetch("/desk/session", { credentials: "same-origin" });
    const payload = await response.json();
    if (!response.ok) throw new OrdoError(payload, response.status);
    return payload;
  },
  start: async (persona) => {
    const response = await fetch("/desk/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ persona }),
      credentials: "same-origin",
    });
    const payload = await response.json();
    if (!response.ok) throw new OrdoError(payload, response.status);
    return payload;
  },
};
