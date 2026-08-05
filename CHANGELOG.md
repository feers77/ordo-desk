# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/es/) + Conventional Commits.

## [Unreleased]

### Added

- `DESK_COOKIE_SECURE`, unidad systemd y notas de despliegue en LAN. La cookie se emite con
  `Secure` por defecto; sobre HTTP plano el navegador no la guarda y el escritorio parece
  roto sin decir por qué, así que apagarlo es una decisión explícita de despliegue —y solo
  un `0` literal la apaga, no un valor vacío ni un typo—. El costo, dicho sin rodeos: la
  cookie viaja en claro por la red local.

- **D0/D1** Andamio del escritorio e identidad. BFF en FastAPI que sirve `web/` desde el
  mismo origen —lo que hace innecesario pedirle CORS al core— y presta identidad: un
  `TokenBroker` que custodia el secreto del agente, obtiene el token OIDC del dueño que
  exige el intercambio RFC 8693, y renueva a los 12 de los 15 minutos en vez de esperar al
  401. Un candado por clave evita la estampida cuando diez requests llegan con el token
  vencido. El proxy es un pasamanos 1:1 con lista blanca de prefijos, `webhook.subscription`
  fuera del alcance del navegador —sus registros llevan el secreto de firma—, borrado de
  toda cabecera de identidad que llegue del cliente y `limit` acotado a 200. `/iam/v1/*` no
  se proxea. La sesión es una cookie firmada con HMAC que **no lleva token**; una cookie
  manipulada es un visitante sin sesión, no un 500.
- Web sin build: import map de cinco líneas, router por hash, `core/http.js` como único
  sitio que toca `fetch` (lee el envelope de ORDO en vez de inventar mensajes y reintenta
  solo lo reintentable **con la misma clave de idempotencia**), `core/money.js` con
  aritmética en `BigInt` porque en una caja la coma flotante se convierte en un descuadre
  que nadie sabe explicar, y un cajón lateral que muestra cada llamada a la API.
- Primera pantalla: existencias de la tienda. Deliberadamente simple: lo que prueba no es la
  interfaz sino la cadena completa —cookie, token puesto por el BFF, permiso resuelto por el
  PDP, datos reales— sin que el navegador vea nunca una credencial.
