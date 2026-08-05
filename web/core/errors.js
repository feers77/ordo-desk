/**
 * Traducción de códigos a lenguaje de mostrador.
 *
 * Solo los códigos cuyo mensaje del core está escrito para un agente y no para
 * una persona detrás de una caja. Para el resto se muestra el mensaje del
 * envelope tal cual: ya está bien redactado y traducirlo lo desincronizaría.
 */

const PLAIN = {
  DESK_NO_SESSION: "Se cerró la sesión. Vuelve a entrar eligiendo con quién operas.",
  DESK_NO_CREDENTIALS: "El escritorio no tiene identidad configurada para esta persona.",
  DESK_UPSTREAM_UNREACHABLE: "No se pudo hablar con el sistema. Reintenta en unos segundos.",
  AUTH_DENIED: "Tu rol no puede hacer esto.",
  AUTH_REQUIRED: "Hay que volver a entrar.",
  IDEMPOTENCY_KEY_REUSED: "Esa operación ya se envió con otros datos.",
  CONCURRENT_MODIFICATION: "Alguien más cambió este registro mientras lo editabas.",
};

export function humanize(error) {
  return {
    code: error.code,
    message: PLAIN[error.code] || error.message,
    hint: error.hint,
    retryable: error.retryable,
    requiresApproval: error.requiresApproval,
    traceId: error.traceId,
  };
}
