---
name: revisar
description: revisar código propio o ajeno antes de darlo por bueno
---

# Revisión de código

Busca en este orden, porque así es como duele en producción:

## 1. Correctitud

- ¿Los bordes están cubiertos: vacío, uno, muchos, nulo, mal formado?
- ¿Qué pasa si falla a mitad? ¿Queda algo a medias?
- ¿Hay condiciones de carrera, o estado compartido que se pisa?
- ¿El manejo de errores traga excepciones en silencio?

## 2. Que de verdad funcione

- ¿Existen pruebas? ¿Prueban el comportamiento o solo que no revienta?
- ¿Se ejecutaron? Un "debería funcionar" no es evidencia.

## 3. Claridad

- ¿Se entiende qué hace una función sin leer sus entrañas?
- ¿Los nombres dicen la verdad?
- ¿Hay duplicación que vaya a desincronizarse?

## 4. Lo que NO es tarea de la revisión

No reescribas por gusto estético, no metas refactors ajenos al cambio, y no
inventes problemas para tener algo que decir. Si el código está bien, dilo.

Al reportar, sé concreto: archivo, línea, qué falla y con qué entrada.
