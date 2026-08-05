/**
 * Bus de eventos del escritorio.
 *
 * Una sola API para las pantallas (`bus.on("stock.picking.action_validate", fn)`)
 * con el transporte por debajo intercambiable: hoy nada, luego SSE del BFF y
 * webhooks de ORDO. Las pantallas no se enteran del cambio.
 */

const listeners = new Map();

export const bus = {
  on(topic, handler) {
    if (!listeners.has(topic)) listeners.set(topic, new Set());
    listeners.get(topic).add(handler);
    return () => listeners.get(topic)?.delete(handler);
  },
  emit(topic, payload) {
    for (const handler of listeners.get(topic) || []) {
      try {
        handler(payload);
      } catch (error) {
        // Un oyente roto no puede tumbar al que emite ni a los demás.
        console.error(`[bus] ${topic}`, error);
      }
    }
  },
};
