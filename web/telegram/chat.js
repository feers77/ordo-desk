/**
 * El chat de Telegram, dentro del escritorio.
 *
 * El navegador **no compone ni un solo carácter**: pinta el `text` que IAM
 * armó, respetando sus saltos de línea, y un botón por cada entrada de
 * `inline_keyboard` usando su propia etiqueta. Por eso es fiel por
 * construcción y no por disciplina: si mañana cambia el formato del mensaje,
 * esta pantalla lo muestra cambiado sin que nadie la toque.
 */

import { clear, h } from "desk/core/dom.js";
import { bus } from "desk/core/bus.js";

const messages = new Map();

export function chatPanel() {
  const thread = h("div", { class: "thread" });
  const panel = h(
    "aside",
    { class: "telegram" },
    h(
      "header",
      {},
      h("strong", {}, "Telegram"),
      h("span", { class: "muted" }, "chat de la dueña"),
    ),
    thread,
  );

  const repaint = () => {
    clear(thread);
    if (!messages.size) {
      thread.append(
        h("p", { class: "state" }, "Sin mensajes. Aparecen cuando algo necesita aprobación."),
      );
      return;
    }
    for (const message of [...messages.values()].sort((a, b) => a.message_id - b.message_id)) {
      thread.append(bubble(message));
    }
  };

  bus.on("telegram.message", (message) => {
    messages.set(message.message_id, message);
    repaint();
  });
  bus.on("telegram.resolved", (resolved) => {
    const message = messages.get(resolved.message_id);
    if (message) {
      message.resolved = resolved;
      repaint();
    }
  });

  repaint();
  return panel;
}

function bubble(message) {
  const node = h("article", { class: "bubble" }, h("pre", {}, message.text));
  if (message.resolved) {
    node.append(
      h(
        "p",
        { class: "resolved" },
        `${message.resolved.label} · ${message.resolved.result?.action || "enviado"}`,
      ),
    );
    return node;
  }
  node.append(
    h(
      "div",
      { class: "inline-keyboard" },
      ...message.buttons.map((button, index) =>
        h(
          "button",
          {
            class: "inline",
            onClick: async (event) => {
              for (const sibling of event.target.parentElement.children) {
                sibling.disabled = true;
              }
              await click(message.message_id, index);
            },
          },
          button.text,
        ),
      ),
    ),
  );
  return node;
}

async function click(messageId, buttonIndex) {
  const response = await fetch("/desk/tg/click", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message_id: messageId, button_index: buttonIndex }),
    credentials: "same-origin",
  });
  const payload = await response.json();
  if (!response.ok) {
    bus.emit("telegram.resolved", {
      message_id: messageId,
      label: "error",
      result: { action: payload?.error?.code || "falló" },
    });
  }
  // El caso bueno llega por SSE, igual que si lo hubiera resuelto otra persona
  // desde su teléfono: una sola fuente de verdad para el estado del mensaje.
}

/** Historial y flujo en vivo. Se llama una vez desde el armazón. */
export async function connect() {
  try {
    const response = await fetch("/desk/tg/history", { credentials: "same-origin" });
    if (response.ok) {
      const payload = await response.json();
      for (const message of payload.messages) bus.emit("telegram.message", message);
    }
  } catch {
    // Sin historial se sigue: los mensajes nuevos llegan igual por SSE.
  }
  const stream = new EventSource("/desk/events");
  for (const topic of ["telegram.message", "telegram.resolved"]) {
    stream.addEventListener(topic, (event) => bus.emit(topic, JSON.parse(event.data)));
  }
  return stream;
}
