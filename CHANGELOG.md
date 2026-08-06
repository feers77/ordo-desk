# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/es/) + Conventional Commits.

## [Unreleased]

### Added

- **D5** Chat de Telegram fiel y coreografía de aprobaciones. El escritorio **no compone ni
  un solo carácter** del mensaje: lo recibe ya armado por IAM y pinta su texto y sus
  botones. Pulsar uno tampoco firma nada — se reinyecta el `callback_data` que IAM firmó,
  tal cual, a su webhook real, y quien verifica la firma y exige que el aprobador sea el
  dueño del agente sigue siendo IAM. Es fiel por construcción y no por disciplina: si cambia
  el formato del mensaje, la pantalla lo muestra cambiado sin que nadie la toque.
  Ante `IAM_APPROVAL_REQUIRED` el BFF crea la solicitud con el token del agente sellando la
  operación exacta que se reintentará, y **no bloquea**: devolver el id y dejar que el
  navegador reenvíe deja al cajero atendiendo en vez de mirando una pantalla congelada.
  El emisor del emulador se declara por red (`DESK_TELEGRAM_SENDERS`) y se compara como
  dirección IP, nunca por prefijo de texto — "172.1" dejaría entrar a "172.18.0.99".
- **D4** Pantalla de reposición: alertas agrupadas por modelo y desglosadas por talla, con
  el traslado desde bodega en un botón. Los bloqueados se listan aparte, no se esconden.
- SSE en `/desk/events` para lo que **nace en el escritorio**. Los eventos de negocio son de
  ORDO y llegarán por webhook; mezclarlos aquí haría creer que el escritorio los origina.

- `tests/web/test_syntax.py`: verifica con `node --check` que cada módulo del navegador
  parsea, que ningún archivo importa y declara el mismo nombre, y que todo import resuelve a
  un archivo que existe. **No es un build** —solo parsea, no genera nada y se salta si node
  no está—, así que la regla de "lo que se despliega es exactamente lo que se escribió"
  sigue en pie.

- **D3** Pantalla de caja. El carro es memoria; los totales, el vuelto, el asiento y el
  descuento de stock los resuelve ORDO — si el navegador calculara su propio total habría
  dos verdades y la del navegador sería la equivocada, así que hasta validar se rotula como
  **provisional**. Botón "Simular" que usa `dry_run`: muestra el ticket, el total y el
  asiento que *harían*, sin gastar numeración. El botón de cobrar se deshabilita mientras
  vuela y la clave de idempotencia **no se renueva** entre reintentos.
- **D2** `sim/day_ropa.py`: un día de operación reproducible que habla **por el escritorio**,
  con la misma cookie y las mismas rutas que el navegador. No es un atajo: convierte al
  simulador en un test de contrato de la pantalla. Quedarse sin stock se cuenta y se sigue,
  porque es un desenlace legítimo de un día de tienda. El Z del turno lo pide la dueña, no
  el cajero: su capability no incluye reportes, y eso es el control funcionando.

### Fixed

- **El botón "Simular" nunca funcionó.** La simulación corre sobre un ticket real y exige su
  cobro, pero el cobro solo se creaba en la ruta de cobrar: simular respondía siempre
  `POS_PAYMENT_INSUFFICIENT`. Peor, la pantalla trataba un `would_return` vacío como éxito,
  así que mostraba un preview con campos indefinidos en vez de decir que fallaría. Y cada
  intento dejaba un borrador huérfano, que es lo que bloquea el cierre del turno.
  Ahora el carro se **materializa** —cabecera, líneas y cobro— antes de simular o cobrar; si
  el carro cambia después, el ticket se cancela y se rehace, porque cobrar líneas viejas es
  peor que fallar. `validations` vacío es éxito y con contenido son los motivos, que la
  pantalla muestra tal cual. Aparece "Descartar", que cancela el borrador de verdad.
- Se agrega el cobro con medio elegible y el importe recibido en efectivo, que es de donde
  sale el vuelto: sin eso el vuelto siempre era cero y la mitad del punto se perdía.
- `tests/e2e/test_pos_flow.py` reproduce la secuencia exacta de la pantalla contra el
  escritorio vivo, **incluida la simulación**. Los tests del BFF no podían verlo —no conocen
  el flujo— y `sim/day_ropa.py` tampoco, porque vende sin simular.

- `crypto.randomUUID` **solo existe en contextos seguros** (HTTPS o localhost). Servido en
  una IP de la red local sobre HTTP plano no está definido, y el escritorio se caía justo al
  cobrar, que es donde la clave de idempotencia hace falta. Se compone el UUID con
  `crypto.getRandomValues`, disponible también en contextos no seguros: la aleatoriedad es
  la misma. Es el segundo tropiezo del mismo tipo —después de la cookie `Secure`—, así que
  ahora hay un test que apaga `randomUUID` y comprueba que igual funciona.
- `tests/web/run_node.mjs`: corredor de los módulos puros del navegador bajo node. Cubre lo
  que un test del BFF nunca vería: el identificador único y que el dinero no pase por coma
  flotante.

- Una edición dejó `import { ROUTES }` y `export const ROUTES` en el mismo archivo. Es un
  `SyntaxError`: el navegador no ejecuta nada y **la página queda en blanco, sin mensaje**.
  Llegó a estar publicado. Los tests del BFF no podían verlo porque nunca miran el
  JavaScript; ahora hay uno que sí.

- El router mandaba a **todas** las personas a la pantalla de bodega, y el capability token
  del cajero no incluye reportes: la denegación era correcta y el destino no. Ahora cada
  pantalla declara a qué personas sirve, y quien no puede entrar no la ve en el menú ni
  aterriza en ella.
- `app.js` y `ui/shell.js` se importaban mutuamente. Funcionaba por el orden de evaluación,
  que es la clase de cosa que deja de funcionar sin avisar; las rutas se mudan a
  `core/routes.js`.
- El buscador de la caja perdía el foco en cada tecla porque se repintaba el panel entero.

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
