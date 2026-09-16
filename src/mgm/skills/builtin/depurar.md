---
name: depurar
description: investigar un bug, una prueba que falla o algo que no se comporta como esperas
---

# Depuración sistemática

La tentación es parchear lo primero que parece culpable. Casi siempre se
arregla el síntoma y el bug vuelve con otra cara.

## 1. Reproduce

Consigue un caso que falle **siempre**. Si solo falla a veces, encuentra qué
lo dispara antes de seguir. Un bug que no puedes reproducir tampoco puedes
verificar que lo arreglaste.

## 2. Lee el error entero

El mensaje completo y la traza completa. La línea que importa rara vez es la
primera. Busca el punto donde tus datos dejan de valer lo que creías.

## 3. Formula una hipótesis concreta

"Algo falla en la autenticación" no es una hipótesis. "El token se lee antes
de que el archivo de credenciales exista, así que llega vacío" sí lo es:
predice algo comprobable.

## 4. Compruébala antes de arreglar

Añade una traza, un print, una prueba que aísle esa línea. Confirma que la
causa es la que crees. Si no lo es, vuelve al paso 3 — no empieces a cambiar
cosas a ver si suena la flauta.

## 5. Arregla la causa, no el síntoma

Con la causa confirmada, escribe **primero** una prueba que falle por ese
bug. Luego arréglalo. Esa prueba es lo que impide que vuelva.

## 6. Verifica

Ejecuta la prueba nueva y toda la suite. Un arreglo que rompe otras tres
cosas no es un arreglo.
