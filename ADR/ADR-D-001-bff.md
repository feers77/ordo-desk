# ADR-D-001 — Un BFF entre el navegador y ORDO

- **Estado:** aceptado
- **Fecha:** 2026-08-05
- **Decisores:** @feers77

## Contexto

El escritorio necesita hablar con una API que exige `Authorization: Bearer` con
un token de agente de 15 minutos sin refresh. La pregunta es si el navegador
puede hablarle directo.

## Opciones consideradas

1. **El navegador llama a ORDO directamente** — menos piezas. Exige que el core
   acepte CORS y que el navegador custodie credenciales.
2. **Un proceso servidor entre medio** — una pieza más que mantener.

## Decisión

Se elige la opción 2. No es preferencia estética: hay cinco cosas que el
navegador **no puede** hacer, y cada una alcanza por sí sola.

1. **Custodia de credenciales.** El intercambio RFC 8693 exige el
   `client_secret` del agente *y* un access token OIDC de su dueño. Guardar
   cualquiera de los dos en el navegador es publicarlos.
2. **`/iam/v1/*` no está enrutado por el edge.** El BFF corre en el mismo host
   y llega a `127.0.0.1:8002` sin tocar infraestructura.
3. **CORS.** El core no lo tiene y no debe tenerlo. Mismo origen ⇒ el problema
   no existe. Este es el argumento decisivo para **no pedirle nada al core**.
4. **Receptor de webhooks.** Necesita una URL servidor con verificación HMAC.
5. **Coreografía de aprobaciones.** Ante un `403 IAM_APPROVAL_REQUIRED` alguien
   tiene que sellar la operación byte a byte y hablar con IAM **con el token de
   agente**, que el navegador no tiene por diseño.

## Consecuencias

- Positivas: cero cambios en el core; el navegador nunca ve una credencial; la
  renovación del token es invisible para quien está en la caja.
- Negativas / deuda asumida: un proceso más que desplegar y vigilar, y la
  tentación permanente de "resolverlo en el BFF". Contra eso, `AGENTS.md` §2.2
  y §2.3 son vinculantes: ni modelo de datos ni transformación de respuestas.
- Qué invalidaría esta decisión: que ORDO emitiera tokens de navegador de vida
  corta con refresh seguro y aceptara CORS. Entonces el BFF quedaría solo como
  receptor de webhooks, que es mucho menos de lo que justifica un proceso.
