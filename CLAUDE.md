# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Qué es

`mgm` ("Mi Gemini CLI") es un agente de IA de terminal en español, tipo Claude Code, escrito en
Python. Existe por una restricción concreta: su autor trabaja en una laptop Windows **sin permisos
de administrador** y con una cuenta **Gemini Pro corporativa que solo funciona por la web** — sin
API key y sin acceso al Gemini CLI oficial (que con cuentas Workspace exige `GOOGLE_CLOUD_PROJECT`).
De ahí que el transporte primario sea g4f con la cookie de sesión del navegador.

Todo el código, los comentarios, la UI y los tests están **en español**. Mantenlo así.

## Comandos

```bash
.venv/bin/python -m pytest -q              # toda la suite (~272 tests, <2s)
.venv/bin/python -m pytest tests/test_agent_loop.py -q       # un archivo
.venv/bin/python -m pytest -k "permisos" -q                  # por nombre
.venv/bin/python -m pytest tests/test_subagent.py::TestProcesoReal -q   # solo los e2e con proceso real

.venv/bin/mgm --transporte fake -p "hola"  # turno único sin red
.venv/bin/mgm --workspace /tmp/x           # REPL en otra carpeta
.venv/bin/mgm --cookie "VALOR"             # guarda la cookie en ~/.mgm/credentials.json (0600)
.venv/bin/mgm -n                           # sesión nueva a propósito (por defecto se auto-continúa)
.venv/bin/mgm --actualizar                 # trae la última versión desde GitHub (git pull o zip)

installer/instalar.sh                      # instalación de usuario (mac/linux)
powershell -ExecutionPolicy Bypass -File installer\instalar.ps1   # idem Windows, sin admin
```

No hay linter ni build configurados. `g4f` **no** está instalado en `.venv` a propósito: se importa
de forma perezosa y los tests corren siempre contra `FakeTransport`.

Para reproducir un fallo REAL contra Gemini (con la cookie del usuario ya guardada), instálalo
temporalmente y déjalo como estaba al terminar:

```bash
.venv/bin/pip install g4f      # reproducir en vivo
.venv/bin/pip uninstall -y g4f # dejar el entorno como estaba
```

Vale la pena: los dos fallos más feos que ha tenido este proyecto (generador de g4f sin cerrar, y
la continuidad de conversación rompiendo el contrato de herramientas) solo se vieron así.

## Arquitectura

El sistema se apoya en dos decisiones que explican casi todo lo demás.

**1. El transporte es un puerto reemplazable.** Nadie construye sobre g4f directamente. El puerto
(`transport/base.py`) pide solo `stream()` y `health()`; detrás hay tres implementaciones
(`G4FCookieTransport`, `GeminiCLITransport` sin implementar aún, `FakeTransport`). Encima va
`InferenceBroker`, que serializa las llamadas con un candado, reintenta con backoff y **distingue
`AuthError` de `TransportError`** — cookie vencida frente a endpoint caído, que se arreglan de forma
distinta. Cuando g4f se rompa, se cambia una línea de config y el resto sigue igual.

**2. Los subagentes son procesos hijo, y el padre es el guardián único.** Un subagente
(`agentd.py`, lanzado con `python -m mgm.agentd`) habla JSONL por stdin/stdout con el padre y **no
tiene la cookie, no habla con el modelo y no puede escribir ni ejecutar nada por su cuenta**:

- toda inferencia viaja al padre como `llm_request` → el padre la sirve desde su broker;
- toda herramienta que no sea `delegable` (solo lectura) viaja como `tool_request` → el padre la
  pasa por su motor de permisos, pregunta al usuario si toca, y la ejecuta él.

Por eso cinco subagentes en paralelo no abren cinco sesiones contra Gemini ni disparan cinco
preguntas de permiso descoordinadas. `agent/subagent.py` es el lado padre; `ipc/` es el protocolo.

### Flujo de un turno

`cli.py` (teclado) → `app.py` (ensamblado) → `agent/loop.py`:

1. `broker.stream()` devuelve chunks; `protocol/xml_parser.py` los va parseando **incrementalmente**
   (las etiquetas pueden partirse entre chunks) y emite texto o `ToolCallEvent`.
2. Si no hubo tool calls, el turno **termina**. No existe etiqueta de "finish": si el modelo quiere
   hablar, habla; si quiere actuar, emite herramientas.
3. Por cada llamada: `permissions/engine.py` decide `allow`/`ask`/`deny`; `ask` sube al `asker`
   (en la UI, `ui/prompt.py`, que muestra el diff antes de preguntar).
4. Se ejecuta y **el resultado se realimenta como mensaje `user`**. Una denegación no aborta el
   turno: vuelve al modelo como `[DENEGADO] …` para que se adapte.

### Reglas que el código respeta y conviene no romper

- **El motor de permisos nunca habla con el usuario.** Devuelve `ask` y quien llama decide cómo
  preguntar. Por eso es testeable sin terminal y reutilizable desde el supervisor de subagentes.
- **Las herramientas nunca lanzan excepciones hacia el loop.** Devuelven `ToolResult(ok=False, …)`.
  El registro envuelve cualquier excepción inesperada (`registry.execute`). Una tool rota no puede
  tumbar el agente.
- **Precedencia de permisos, en orden:** regla `deny` → modo `plan` → regla `allow` → defecto del
  modo. Un `deny` gana incluso en modo `libre`; `plan` gana sobre un `allow` guardado.
- **Las escrituras están confinadas al workspace** (`resolve_write_path`); las lecturas no.
- **Carga progresiva de skills**: en el prompt del sistema solo van `name` + `description`
  (`render_catalog`). El cuerpo llega solo si el modelo pide la skill con `<tool name="skill">`.
  Si metes el cuerpo en el prompt, rompes lo único que hace escalable tener muchas skills.
- **El stream de g4f NO es solo texto.** Mezcla el texto con objetos de control del proveedor
  (`JsonResponse`, `Conversation`). `es_texto()` filtra: solo se emiten `str` no vacíos. Si haces
  `str(pieza)` a ciegas, metes tramas del protocolo (`{'data': [['wrb.fr'…`) en la conversación.
  Verificado contra g4f 8.4.9 real.
- **El proveedor se fuerza a `Gemini`** cuando hay cookie. Con `provider="auto"` g4f puede caer en
  un endpoint libre anónimo sin avisar, y creerías estar usando la cuenta Pro. Dicho esto, el
  proveedor `Gemini` tiene `needs_auth=False` y **también responde sin cookie válida**: una sonda
  de texto prueba conexión, no autenticación. Por eso `health()` primero llama a
  `verificar_sesion()` (GET a `gemini.google.com/app`; sesión válida ⇔ el HTML contiene el token
  `SNlM0e`; el correo sale con regex) y solo sondea texto si la sesión es válida. Errores de red
  en esa verificación son `TransportError` de conexión, nunca "cookie vencida".
- **El modelo por defecto es `gemini-auto`**, no `"gemini"` — ese nombre no existe en g4f y da
  `Model not found`. `resolver_modelo()` traduce los alias cómodos.
- **El prompt del sistema no vive en `loop.messages`.** Se antepone en `_wire_messages()`, así que
  el historial persistido queda limpio y el prompt se puede refrescar entre turnos.
- **El contexto completo viaja en CADA llamada, y eso no es negociable.** Existe el cableado para
  reutilizar la conversación del servidor de Gemini (`Chunk.state`, `Transport.stream(state=...)`,
  `AgentLoop.conversation_state`, `SessionMeta.conversation_state`, y el `conversation=` de g4f),
  pero viene **apagado** (`conversacion_continua = false`). Motivo, verificado en vivo: en cuanto
  se manda `conversation=`, g4f envía SOLO el último mensaje del usuario y delega la memoria en
  Gemini — el modelo deja de ver el prompt de sistema y el contrato de herramientas a mitad de un
  encargo, y empieza a emitir XML roto. Para un loop agéntico, la memoria la manda mgm.
- **El generador de g4f se cierra SIEMPRE** (`_cerrar`, en el mismo hilo). Si se abandona, lo
  cierra el recolector de basura más tarde en otro hilo: g4f intenta apagar ahí su event loop y
  suelta `Cannot run the event loop while another loop is running` + `Unclosed client session`
  por stderr, en cualquier momento — y en el REPL eso se come lo que el usuario está tecleando.
  El REPL además envuelve el prompt en `patch_stdout()` como segunda línea de defensa.

### Mapa de módulos

| Módulo | Responsabilidad |
|---|---|
| `transport/` | puerto, implementaciones, broker (candado + reintentos + clasificación de errores) |
| `protocol/xml_parser.py` | parser incremental de `<tool …>` tolerante a chunks partidos y XML sin cerrar |
| `tools/` | contrato (`risk`, `delegable`, `subject`), 8 herramientas, registro |
| `permissions/` | reglas (`bash(git status:*)`, globs), motor con 4 modos, persistencia |
| `agent/` | loop, prompts, eventos, supervisor de subagentes |
| `ipc/` | sobres JSONL y canal asíncrono (`memory_pair()` para probar sin procesos) |
| `session/` | persistencia JSONL, presupuesto y compactación de contexto, memoria `MGM.md` |
| `skills/` | cargador con frontmatter + skills incluidas (`tdd`, `depurar`, `revisar`) |
| `ui/` | tema de rich, diffs, autocompletado, pregunta de permiso |
| `app.py` / `commands.py` / `cli.py` | ensamblado, comandos de barra, argumentos y REPL |
| `actualizar.py` | autoactualización desde GitHub (`git pull` o zip sin git) |

## Cómo se prueban las cosas aquí

Todo corre **sin red y sin procesos**, salvo donde el punto es justamente el proceso:

- `FakeTransport(script=[...])` guiona las respuestas del modelo; una entrada puede ser un `str`,
  una lista de chunks (para probar el parser incremental) o una **excepción** (para probar fallos).
- `memory_pair()` en `ipc/channel.py` da dos canales conectados en memoria: permite probar todo el
  protocolo padre↔hijo sin lanzar nada.
- `TestProcesoReal` en `tests/test_subagent.py` **sí** lanza `python -m mgm.agentd` de verdad. Es la
  prueba de que la arquitectura de procesos funciona; si la tocas, ejecútala.
- `EventRecorder` captura los eventos del loop para afirmar sobre lo que pasó, no sobre el texto.

Al añadir una herramienta hay que tocar cuatro sitios: la clase (con su `risk` y su `subject`),
`default_registry()`, el catálogo de docs se genera solo, y un test en `tests/test_registry.py`.

## Legado

`legacy/mgm.py` es el prototipo original de un solo archivo. Se conserva como referencia y **no se
importa desde ningún sitio**. `venv/` (sin punto) es el entorno Windows del prototipo, con binarios
`win_amd64` y rutas a `C:\Users\xp69105`: es peso muerto en macOS. El entorno vivo es `.venv/`.
`Abre` es una transcripción de terminal de aquella época, no código.
