# AGENTS.md — reglas de `ordo-desk`

Este archivo va en la raíz del repositorio. El agente de desarrollo lo lee en
cada sesión. **Es vinculante.**

## 1. Qué es este proyecto

Las interfaces humanas —web y Telegram, complementarias— sobre ORDO, que es un
ERP/CRM API-first cuyo operador previsto es un agente.

El core dice *"no se escribe frontend, nunca"*. **Aquí sí se escribe frontend, y
nunca lógica de negocio.** Esa es la única razón por la que este repositorio
existe separado.

## 2. Prohibiciones absolutas

0. **Licencia AGPLv3**, igual que el core. Se contribuye con DCO (`git commit -s`).
1. **El BFF no tiene modelo de datos.** Ni tablas, ni ORM, ni migraciones. Si
   algo hay que guardar entre requests y no cabe en la sesión, es señal de que
   pertenece al core.
2. **El BFF no transforma respuestas de ORDO.** Toda ruta bajo `/desk/api/*` es
   un pasamanos 1:1: mismo path, mismo cuerpo, misma respuesta, mismo envelope
   de error. Agregar, renombrar o "mejorar" un campo aquí crea un segundo
   contrato que nadie mantiene.
3. **Ninguna regla de negocio en el navegador.** Si una pantalla necesita algo
   que la API no da, se arregla la API en el core. Calcular un total, decidir un
   estado o validar un invariante en JavaScript produce dos verdades.
4. **El navegador nunca ve un token de agente ni un `agent_secret`.** Su única
   credencial es una cookie de sesión firmada.
5. **`/iam/v1/*` no se proxea.** El BFF lo consume desde el servidor y jamás lo
   expone. En particular, **aprobar no se hace por una ruta directa**: si el BFF
   proxeara `/approve` con un bearer de dueño, cualquier XSS se convertiría en
   aprobador universal.
6. **Nunca `float` para dinero.** Los importes viajan y se muestran como string
   decimal; la aritmética va en unidades menores con `BigInt`.
7. **Sin build.** Módulos ES nativos, sin bundler, sin transpilador, sin
   `node_modules`. Si algo necesita compilarse, no entra.
8. **Sin CDN.** Todo se sirve desde el mismo origen. Una dependencia remota es
   una pantalla que deja de funcionar cuando el vecino se cae.
9. **No commitear secretos.** `.env` fuera de git.

## 3. Flujo de trabajo

Diseño corto en el PR → tests → implementación → `make check` → PR.

**Definition of Done**

- [ ] Tests del BFF (`pytest`) y, si toca módulos puros del navegador, del
      corredor de `tests/web/`
- [ ] Ninguna llamada nueva a `fetch` fuera de `web/core/http.js`
- [ ] Errores mostrados desde el envelope de ORDO, sin inventar mensajes
- [ ] Estados de carga y error explícitos en cada vista
- [ ] Entrada en `CHANGELOG.md`
- [ ] Commit con DCO

## 4. Reglas de código

**Python (BFF)**: 3.12, type hints completos, `mypy --strict`, `ruff` con
line-length 100. Async por defecto; nada de `requests` ni `time.sleep`.

**JavaScript (web)**: módulos ES, `import` absoluto vía el import map
(`desk/...`), sin framework. Cada pantalla exporta `mount(root, ctx)` y
`unmount()`. Estado explícito por pantalla; sin store global salvo `session` y
`bus`.

**CSS**: variables en `:root`, modo claro y oscuro, sin preprocesador.

## 5. Errores

Los códigos de error son los del core. El BFF **no inventa códigos propios**
salvo para lo que ocurre antes de llegar a ORDO (sesión ausente, pool agotado),
y esos llevan prefijo `DESK_`.

## 6. Cuándo detenerse y preguntar

- El diseño empuja a poner una regla de negocio en el BFF o en el navegador.
- Hace falta un endpoint nuevo en el core.
- Aparece la tentación de guardar estado de negocio fuera de ORDO.
- Se encuentra un defecto de seguridad: **repórtalo antes de arreglarlo**.

## 7. Comandos

```bash
make dev      # BFF con recarga, sirve web/ en el mismo origen
make web      # solo los estáticos, sin BFF (tools/serve_dev.py)
make check    # lint + types + tests
make provision TENANT=ropa   # identidades IAM de la demo, una sola vez
```
