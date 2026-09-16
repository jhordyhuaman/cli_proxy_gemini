# MGM.md — memoria del proyecto mgm

Este archivo lo lee mgm al arrancar en esta carpeta.

## Idioma

Todo en español: código, comentarios, mensajes de la UI, nombres de tests y documentación.
Los nombres de la API pública que ya existen (`Tool`, `ToolResult`, `stream`, `health`) se
mantienen como están por consistencia; lo nuevo va en español.

## Cómo se prueba

```bash
.venv/bin/python -m pytest -q
```

La suite entera corre sin red y en menos de dos segundos. Si una prueba necesita red, está mal
planteada: usa `FakeTransport(script=[...])`. Si necesita procesos, usa `memory_pair()`, salvo en
`TestProcesoReal`, donde el proceso ES lo que se prueba.

## Reglas de esta casa

- Primero la prueba que falla, después el código. La skill `tdd` tiene el detalle.
- Ninguna herramienta lanza excepciones hacia el loop: devuelven `ToolResult(ok=False, …)`.
- El motor de permisos no habla con el usuario; devuelve `ask` y que decida quien llama.
- No metas el cuerpo de las skills en el prompt del sistema: rompe la carga progresiva.
- No construyas nada directamente sobre g4f. Todo pasa por el puerto `Transport`.

## Qué no tocar

`legacy/mgm.py` es el prototipo original, se conserva como referencia histórica.
`venv/` (sin punto) es el entorno Windows del prototipo: peso muerto, el entorno vivo es `.venv/`.
