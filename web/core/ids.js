/**
 * Identificadores únicos, sin depender de un contexto seguro.
 *
 * `crypto.randomUUID` solo existe bajo HTTPS o en localhost. Servido en una IP
 * de la red local sobre HTTP plano no está definido, y el escritorio se cae al
 * primer intento de cobrar — que es justo donde la clave de idempotencia hace
 * falta.
 *
 * `crypto.getRandomValues` sí está disponible en contextos no seguros, así que
 * la aleatoriedad es la misma; lo único que cambia es que el formato UUID se
 * compone a mano.
 *
 * Sin imports a propósito: así se puede probar bajo node sin el import map.
 */

const HEX = Array.from({ length: 256 }, (_, index) => index.toString(16).padStart(2, "0"));

export function uuid4() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // versión 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variante RFC 4122
  const hex = Array.from(bytes, (byte) => HEX[byte]);
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10, 16).join(""),
  ].join("-");
}

/** Clave de idempotencia: la acuña quien sabe qué es una intención. */
export function newKey() {
  return `desk-${uuid4()}`;
}
