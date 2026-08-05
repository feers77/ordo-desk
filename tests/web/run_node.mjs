/**
 * Corredor mínimo de los módulos puros del navegador, bajo node.
 *
 * Solo se prueban aquí los módulos sin imports ni DOM: `ids.js` y `money.js`.
 * El resto necesita el import map y un documento, y para eso está la suite de
 * extremo a extremo.
 */

import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import path from "node:path";

const WEB = path.resolve(process.argv[2]);
const load = (relative) => import(pathToFileURL(path.join(WEB, relative)).href);

const results = [];
function check(name, fn) {
  try {
    fn();
    results.push(["ok", name]);
  } catch (error) {
    results.push(["FALLO", `${name}: ${error.message}`]);
  }
}

const { uuid4, newKey } = await load("core/ids.js");
const money = await load("core/money.js");

check("uuid4 tiene el formato de un UUID v4", () => {
  const value = uuid4();
  assert.match(value, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});

check("uuid4 no depende de randomUUID", () => {
  // randomUUID solo existe en contextos seguros. Sin él, el escritorio servido
  // por HTTP en la LAN se caía al cobrar.
  const original = globalThis.crypto.randomUUID;
  try {
    Object.defineProperty(globalThis.crypto, "randomUUID", {
      value: undefined,
      configurable: true,
    });
    assert.match(uuid4(), /^[0-9a-f]{8}-/);
  } finally {
    Object.defineProperty(globalThis.crypto, "randomUUID", {
      value: original,
      configurable: true,
    });
  }
});

check("dos claves seguidas no colisionan", () => {
  const keys = new Set(Array.from({ length: 500 }, () => newKey()));
  assert.equal(keys.size, 500);
});

check("la clave lleva su prefijo", () => {
  assert.ok(newKey().startsWith("desk-"));
});

check("el dinero no pasa por coma flotante", () => {
  // 0.1 + 0.2 en binario da 0.30000000000000004; en una caja eso es un
  // descuadre que nadie sabe explicar.
  assert.equal(money.add("0.10", "0.20"), "0.30");
  assert.equal(money.sum(["19990.00", "39990.00"]), "59980.00");
  assert.equal(money.multiply("19990.00", "3"), "59970.00");
});

check("los importes negativos sobreviven el viaje", () => {
  assert.equal(money.toDecimal(money.toMinor("-500.00")), "-500.00");
});

for (const [status, name] of results) console.log(`${status.padEnd(6)} ${name}`);
process.exit(results.some(([status]) => status === "FALLO") ? 1 : 0);
