# ADR-D-002 — Web sin build

- **Estado:** aceptado
- **Fecha:** 2026-08-05
- **Decisores:** @feers77

## Contexto

El core no tiene ni un `package.json`. Su convención, visible en la
documentación que publica, es cero dependencias, offline-first y sin CDN. El
escritorio necesita pantallas con estado: punto de venta, bodega, un chat.

## Opciones consideradas

1. **Framework con bundler** (Vite + React o Svelte) — cómodo para estado
   complejo, a cambio de Node, lockfile, transpilador y CI de frontend en un
   proyecto que hoy es enteramente Python.
2. **Render en servidor con fragmentos** — poco JavaScript, pero el punto de
   venta y la cocina en vivo quedan rígidos.
3. **Módulos ES nativos, sin build.**

## Decisión

Se elige la opción 3. Los navegadores modernos cargan módulos ES y un import
map resuelve las rutas absolutas sin bundler; con eso, `import { api } from
"desk/core/http.js"` funciona tal cual, sin cadenas de `../../` y sin paso de
compilación.

El criterio dominante es que **lo que se despliega es exactamente lo que se
escribió**. Sin build no hay artefacto intermedio que difiera del fuente, ni
una cadena de herramientas que haya que actualizar para que el proyecto siga
compilando dentro de dos años.

## Consecuencias

- Positivas: `git clone` y abrir; sin `node_modules`; sin CDN, así que ninguna
  pantalla deja de funcionar porque un tercero se cayó; el código que se depura
  en el navegador es el que está en el repositorio.
- Negativas / deuda asumida: sin JSX ni reactividad automática, el estado se
  maneja a mano. Es sostenible porque cada pantalla es pequeña y explícita; si
  una creciera hasta necesitar un framework, la señal es que le sobra lógica
  que pertenece al core.
- Qué invalidaría esta decisión: que aparezca una pantalla cuyo estado no se
  pueda mantener a mano sin volverse frágil. Antes de meter un bundler, hay que
  preguntarse si esa pantalla no está haciendo trabajo de servidor.
