/**
 * Dinero: nunca `Number`.
 *
 * Los importes llegan de ORDO como string decimal y se quedan así. La
 * aritmética va en unidades menores con BigInt, que es exacta; `0.1 + 0.2` en
 * coma flotante no lo es, y en una caja eso se convierte en un descuadre que
 * nadie sabe explicar.
 */

const CLP = new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP" });

/** "19990.00" con 2 decimales -> 1999000n (unidades menores). */
export function toMinor(value, decimals = 2) {
  const text = String(value ?? "0").trim();
  const negative = text.startsWith("-");
  const [whole, fraction = ""] = text.replace("-", "").split(".");
  const padded = (fraction + "0".repeat(decimals)).slice(0, decimals);
  const digits = `${whole || "0"}${padded}`.replace(/\D/g, "") || "0";
  const amount = BigInt(digits);
  return negative ? -amount : amount;
}

/** 1999000n -> "19990.00" */
export function toDecimal(minor, decimals = 2) {
  const negative = minor < 0n;
  const digits = (negative ? -minor : minor).toString().padStart(decimals + 1, "0");
  const whole = digits.slice(0, digits.length - decimals) || "0";
  const fraction = decimals ? `.${digits.slice(digits.length - decimals)}` : "";
  return `${negative ? "-" : ""}${whole}${fraction}`;
}

export function add(a, b, decimals = 2) {
  return toDecimal(toMinor(a, decimals) + toMinor(b, decimals), decimals);
}

export function multiply(amount, times, decimals = 2) {
  // `times` es una cantidad, también string decimal. Se multiplica en menores
  // y se vuelve a escalar; el redondeo definitivo lo hace el servidor.
  const scaled = toMinor(amount, decimals) * toMinor(times, decimals);
  return toDecimal(scaled / 10n ** BigInt(decimals), decimals);
}

export function sum(values, decimals = 2) {
  return toDecimal(
    values.reduce((total, value) => total + toMinor(value, decimals), 0n),
    decimals,
  );
}

/** Para mostrar. El peso chileno no tiene decimales. */
export function format(value) {
  return CLP.format(Number(toMinor(value, 2)) / 100);
}
