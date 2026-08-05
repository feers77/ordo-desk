# ordo-desk

Las interfaces humanas —web y Telegram— sobre [ORDO](https://github.com/feers77/ordo),
un ERP/CRM API-first cuyo operador previsto es un agente.

El core dice *"no se escribe frontend, nunca"*. **Aquí sí se escribe frontend, y
nunca lógica de negocio.** Esa es la única razón por la que este repositorio
existe separado.

## Cómo está armado

```
navegador ──cookie firmada──> BFF ──token de agente──> ordo-api
                               │
                               └──────────────────────> ordo-iam (nunca proxeado)
```

**El navegador no tiene credenciales.** Su única cookie dice con quién entraste;
el token de agente vive en el escritorio, se renueva solo a los 12 de sus 15
minutos y jamás baja al cliente. No es una precaución opcional: el intercambio
RFC 8693 exige el secreto del agente **y** un access token OIDC de su dueño, así
que el navegador no podría hacerlo aunque quisiéramos.

**El BFF no tiene modelo de datos.** Toda ruta bajo `/desk/api/*` y
`/desk/meta/*` es un pasamanos 1:1 hacia ORDO: mismo path, mismo cuerpo, misma
respuesta, mismo envelope de error.

**`/iam/v1/*` no se proxea nunca.** En particular, aprobar no se hace por una
ruta directa: si el BFF expusiera `/approve` con un bearer de dueño, cualquier
XSS se convertiría en aprobador universal. Las aprobaciones van por el canal de
Telegram, como con el bot real.

**Sin build.** Módulos ES nativos, sin bundler y sin CDN. Todo se sirve desde el
mismo origen, que es lo que hace innecesario el CORS.

## Levantarlo

```bash
uv sync
export DESK_SESSION_SECRET=$(python -c "import secrets;print(secrets.token_hex(32))")
export ORDO_API_URL=http://127.0.0.1:8000
export ORDO_IAM_URL=http://127.0.0.1:8002
make provision TENANT=ropa   # crea agentes y capacidades en IAM, una sola vez
make dev                     # http://127.0.0.1:8100
```

El tenant se siembra desde el core con `make seed TENANT=ropa`, y su primera
usuaria con `tools/seed_iam_user.py`.

## Servirlo en una red local

`infra/ordo-desk.service` es la unidad systemd que usa el despliegue de
referencia: lee `/etc/ordo-desk/env` (modo 0600) y escucha en el puerto 8100.

**Sobre HTTP plano hay que apagar `DESK_COOKIE_SECURE`**, o el navegador ni
siquiera guarda la cookie de sesión y nada funciona. El costo es que la cookie
viaja en claro por la red local: es aceptable en una LAN de confianza y no lo
es en Internet. Delante de un proxy con TLS, déjalo en `1`.

El puerto debe abrirse **solo a la red local**:

```bash
ufw allow proto tcp from 192.168.1.0/24 to any port 8100
```

## Licencia

AGPLv3, igual que el core. Se contribuye con DCO (`git commit -s`).
