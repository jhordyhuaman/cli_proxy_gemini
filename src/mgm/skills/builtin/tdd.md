---
name: tdd
description: escribir o arreglar código guiado por pruebas — úsala ANTES de escribir la implementación
---

# Desarrollo guiado por pruebas

El ciclo es rojo → verde → refactor, y el orden no es negociable.

## 1. Rojo: escribe la prueba primero

Antes de tocar la implementación, escribe una prueba que falle por la razón
correcta. Ejecútala y **mira el fallo**. Si pasa a la primera, la prueba no
está probando lo que crees: arréglala antes de seguir.

Una prueba que nunca viste fallar no es una prueba, es una esperanza.

## 2. Verde: el código mínimo

Escribe lo mínimo que haga pasar la prueba. Nada de funcionalidad "que ya que
estamos". Ejecuta las pruebas y confirma que pasan — **ejecutándolas de
verdad con `bash`**, no leyendo el código y suponiendo.

## 3. Refactor

Con las pruebas en verde, limpia. Vuelve a ejecutarlas después de cada
cambio. Si se ponen rojas, el refactor rompió algo: deshaz y vuelve a
intentar en pasos más chicos.

## Qué probar

- El comportamiento observable, no los detalles internos.
- Los bordes: vacío, cero, uno, muchos, negativo, nulo, mal formado.
- El caso de error tanto como el feliz.
- Un `assert` que solo comprueba que no revienta no comprueba casi nada.

## Prohibido

- Declarar "listo" sin haber ejecutado las pruebas en esta sesión.
- Cambiar la prueba para que pase cuando lo que falla es el código.
- Borrar o marcar como omitida una prueba que estorba.
