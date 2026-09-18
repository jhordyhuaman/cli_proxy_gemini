# mgm — Mi Gemini CLI

Un agente de IA que vive en tu terminal, en español, con herramientas reales, permisos, sesiones
persistentes, skills y subagentes. Pensado para una máquina con las manos atadas:

- **sin permisos de administrador** — todo se instala dentro de tu usuario;
- **sin API key** — usa la cookie de tu sesión web de Gemini;
- **sin depender de un solo proveedor** — el transporte es una pieza reemplazable.

---

## Instalación

### Windows (tu laptop del trabajo)

```bat
instalar.bat
```

o directamente:

```bat
powershell -ExecutionPolicy Bypass -File installer\instalar.ps1
```

El instalador **no pide administrador**. Busca tu Python 3.11+, crea `.venv` dentro de esta carpeta,
instala todo ahí, deja un lanzador en `%USERPROFILE%\.mgm\bin\mgm.cmd` y añade esa carpeta al PATH
de tu usuario. **Abre una terminal nueva** al terminar.

### macOS / Linux

```bash
installer/instalar.sh
```

### Comprobar

```bash
mgm --version
```

---

## Conectar tu cuenta de Gemini

mgm habla con Gemini a través de la cookie de tu sesión web. Para obtenerla:

1. Abre `gemini.google.com` en Chrome y entra con tu cuenta.
2. `F12` → pestaña **Application** → **Storage** → **Cookies** → `https://gemini.google.com`.
3. Copia el valor de **`__Secure-1PSID`** (solo el valor; dominio, expiración y demás columnas sobran).
4. Guárdala:

```bash
mgm --cookie "el_valor_que_copiaste"
```

**Forma rápida (recomendada):** en la pestaña **Network** de DevTools, haz clic en cualquier
petición a `gemini.google.com`, copia el header **`Cookie:`** completo (una línea
`nombre=valor; nombre=valor; ...`) y pégalo tal cual — mgm separa y guarda todas las cookies
de una vez, incluidas `__Secure-1PSIDTS` y `__Secure-1PSIDCC`, que g4f pide seguido:

```bash
mgm --cookie "__Secure-1PSID=g.a000...; __Secure-1PSIDTS=sidts-...; __Secure-1PSIDCC=AKEy..."
```

Queda en `~/.mgm/credentials.json` con permisos `0600`, **nunca en el código**. Compruébalo con:

```bash
mgm --transporte g4f
/salud      # debe decir "conectado como tu_correo (tu cuenta)"
```

> La cookie caduca cada cierto tiempo y Google puede pedirte re-login. Cuando pase, mgm te lo dice
> con claridad (distingue "cookie vencida" de "endpoint caído") y basta con repetir el paso 4.
>
> Ten presente que automatizar una cuenta corporativa puede chocar con las políticas de tu empresa.
> Esa decisión es tuya.

**`/salud` ahora SÍ valida tu cuenta.** Antes de sondear texto, mgm hace una petición real a
`gemini.google.com/app` con tu cookie y comprueba la marca de sesión autenticada:

- **Cookie válida** → verás `conectado como tu_correo@gmail.com (tu cuenta)` y además se prueba
  que el modelo responde texto.
- **Cookie vencida o rechazada** → `/salud` falla en rojo con un mensaje claro pidiendo que la
  renueves con `mgm --cookie "..."`, **sin** hacer la sonda de texto (que respondería igualmente
  con una sesión anónima y te mentiría).
- **Fallo de red** (sin internet, DNS, timeout) → se reporta como problema de conexión, nunca
  como "cookie vencida".

El detalle técnico: el proveedor Gemini de g4f responde incluso con cookie inválida (cae en
silencio a una sesión anónima), así que la única señal fiable es la página de la app de Gemini:
con sesión autenticada su HTML incluye un token interno y el correo de tu cuenta; sin ella,
ninguno de los dos. mgm sigue enviando tu cookie siempre que esté configurada y forzando el
proveedor `Gemini` (nunca cae en silencio a endpoints libres).

### Modelo

Por defecto mgm usa `gemini-auto`, que es el nombre que enruta al proveedor que usa tu cookie.
Ojo: el nombre suelto `gemini` **no existe** en g4f; mgm traduce ese alias por ti.

**Para tareas de código, pide un Pro explícitamente.** `gemini-auto` deja que el servidor elija y
en la práctica cae en un modelo *flash* (rápido y barato, pero flojo siguiendo formatos: parte mal
los archivos y corta las respuestas a la mitad). `/modelo` te dice cuál respondió de verdad y te
avisa si estás en un flash:

```bash
/modelo                     # ves el real, p. ej. "Respondiendo de verdad: gemini-3.6-flash"
/modelo gemini-3.8-pro      # cámbialo en caliente
```

```bash
mgm --modelo gemini-2.5-pro     # al arrancar
/modelo                         # ver el actual y los disponibles en tu g4f
/modelo gemini-2.5-pro          # cambiarlo en caliente
```

En `~/.mgm/config.toml` puedes fijarlo:

```toml
model = "gemini-auto"
provider = "Gemini"   # "auto" deja elegir a g4f — puede caer en endpoints anónimos
```

Sin cookie, mgm arranca en transporte `fake` (responde sin red) para que puedas probarlo todo.

---

## Uso

```bash
mgm                               # retoma sola la última sesión de esta carpeta (o abre una si es la primera vez)
mgm "arregla el login"            # una pregunta suelta
mgm -p "resume este repo"         # turno único, para scripts (también auto-continúa)
mgm -n                            # fuerza una sesión nueva, ignorando la anterior
mgm -r a1b2c3d4                   # retoma una sesión concreta por id
mgm --sesiones                    # lista las sesiones guardadas
mgm --actualizar                  # trae la última versión desde GitHub
mgm --modo plan                   # arranca en modo solo lectura
```

mgm **retoma tu sesión**: el historial de la carpeta se guarda y se recarga solo, así que iterar
sobre el mismo encargo continúa donde lo dejaste. Usa `-n` cuando sí quieras arrancar de cero.

**Un solo chat en Gemini, no uno por llamada.** Toda la sesión vive en la misma conversación de
`gemini.google.com`: en una prueba real, un CRUD completo (6 llamadas al modelo, con sus
herramientas) quedó en un único chat. Y sin perder el hilo: mgm sigue mandando él mismo el prompt
de sistema más lo que el modelo aún no ha visto, en vez de delegarle la memoria a Gemini. Se puede
apagar con `conversacion_continua = false` en `~/.mgm/config.toml`.

Al arrancar la sesión interactiva, mgm te dice con qué cuenta estás hablando —
`Conectado a Gemini como tu_correo@gmail.com`, o un aviso si estás en el endpoint
anónimo/gratuito en vez de tu cuenta.

Dentro de la sesión, escribe `@ruta/archivo` para adjuntar su contenido (con autocompletado).

### Comandos

| Comando | Qué hace |
|---|---|
| `/ayuda` | la lista completa |
| `/modo` | ver o cambiar el modo de permisos |
| `/permisos` | reglas de permiso guardadas |
| `/transporte` | ver o cambiar el transporte |
| `/salud` | probar que el transporte responde |
| `/modelo` | ver o cambiar el modelo de Gemini |
| `/contexto` | cuánto contexto llevas gastado |
| `/compactar` | resumir la conversación ahora |
| `/sesiones` | sesiones guardadas de esta carpeta |
| `/skills` | skills disponibles |
| `/memoria` | qué `MGM.md` se cargó |
| `/limpiar` | empezar de cero (sesión local Y conversación de Gemini) |
| `/actualizar` | traer la última versión desde GitHub |
| `/salir` | terminar |

---

## Los cuatro modos de permiso

| Modo | Leer | Escribir | Ejecutar |
|---|---|---|---|
| `plan` | ✅ | ❌ | ❌ |
| `ask` *(defecto)* | ✅ | pregunta | pregunta |
| `auto-edits` | ✅ | ✅ | pregunta |
| `libre` | ✅ | ✅ | ✅ |

Cuando mgm pide permiso te enseña **el diff exacto** antes de que decidas, y puedes responder:
`s` (una vez), `a` (toda la sesión), `p` (siempre en este proyecto) o `n` (no).

Las reglas se guardan como `bash(git status:*)` o `write_file(src/**)`. Una regla de prohibición
gana siempre, incluso en modo `libre`.

mgm no se da por terminado con solo dejar los archivos escritos: instala dependencias, corre lo
que hizo y lo comprueba (por ejemplo con `curl`) antes de avisarte. Para servidores o watchers que
deben seguir corriendo, `bash` acepta `background="true"`: arranca el proceso, sigue con la
verificación en la misma conversación y te entrega el resultado ya probado, no un "ahora ejecútalo
tú".

---

## Memoria del proyecto: `MGM.md`

Crea un `MGM.md` en tu proyecto con lo que mgm deba saber **siempre** sin que se lo repitas: cómo se
ejecutan los tests, qué convenciones sigues, qué no debe tocar. Se cargan en cascada:
`~/.mgm/MGM.md` (tus preferencias en todas partes) → los `MGM.md` de las carpetas padre → el del
proyecto, que manda sobre los demás.

## Skills

Instrucciones tuyas, reutilizables. mgm trae `tdd`, `depurar` y `revisar`. Para añadir una propia,
crea `.mgm/skills/mi_skill.md` en el proyecto (o `~/.mgm/skills/` para tenerla en todos):

```markdown
---
name: desplegar
description: cómo se despliega este servicio a producción
---

Los pasos concretos, tal como los harías tú.
```

Solo el nombre y la descripción entran en el prompt; el cuerpo se carga **solo si hace falta**, así
que puedes tener muchas sin quedarte sin contexto.

## Subagentes

mgm puede delegar una tarea larga en un subagente que corre **en otro proceso**, con su propio
contexto, y devuelve solo su informe final. Los subagentes no tienen tu cookie ni pueden escribir
por su cuenta: todo pasa por el proceso principal, que sigue siendo el único que te pregunta y el
único que consume tu cuota. Sus bitácoras quedan en `~/.mgm/logs/<sesión>/`.

---

## Desarrollo

```bash
.venv/bin/python -m pytest -q      # la suite completa corre sin red, en menos de 2 segundos
```

Arquitectura y decisiones de diseño: ver [CLAUDE.md](CLAUDE.md).
