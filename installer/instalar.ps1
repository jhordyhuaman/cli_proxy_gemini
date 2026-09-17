# Instalador de mgm para Windows — SIN permisos de administrador.
#
# Qué hace, todo dentro de tu usuario:
#   1. Busca un Python 3.11+ ya instalado.
#   2. Crea el entorno virtual .venv dentro de esta carpeta.
#   3. Instala mgm y sus dependencias ahí dentro.
#   4. Deja un lanzador en %USERPROFILE%\.mgm\bin\mgm.cmd
#   5. Añade esa carpeta al PATH de TU usuario (no al del sistema).
#
# Uso:  powershell -ExecutionPolicy Bypass -File installer\instalar.ps1

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $raiz ".venv"
$binDir = Join-Path $env:USERPROFILE ".mgm\bin"

function Escribir($texto, $color = "White") { Write-Host $texto -ForegroundColor $color }

Escribir "=== Instalando mgm (sin permisos de administrador) ===" "Cyan"
Escribir "Carpeta del proyecto: $raiz"

# --- 1. Buscar Python -------------------------------------------------------
$python = $null
foreach ($candidato in @("python", "python3", "py")) {
    try {
        $version = & $candidato -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and [version]$version -ge [version]"3.11") {
            $python = $candidato
            Escribir "[OK] Python $version encontrado como '$candidato'" "Green"
            break
        }
    } catch { }
}
if (-not $python) {
    Escribir "[ERROR] No encontré Python 3.11 o superior en tu PATH." "Red"
    Escribir "        Instálalo desde python.org marcando 'Add to PATH' (no necesita admin)." "Yellow"
    exit 1
}

# --- 2. Entorno virtual -----------------------------------------------------
$venvPython = Join-Path $venv "Scripts\python.exe"

# Si copiaste la carpeta desde otra máquina, el .venv que viene dentro es de
# ESE sistema y aquí no sirve para nada. Se detecta y se rehace.
if ((Test-Path $venv) -and -not (Test-Path $venvPython)) {
    Escribir "[AVISO] El .venv de esta carpeta es de otro sistema operativo. Lo rehago." "Yellow"
    Remove-Item -Recurse -Force $venv
}

if (-not (Test-Path $venv)) {
    Escribir "Creando entorno virtual en .venv ..."
    & $python -m venv $venv
    if ($LASTEXITCODE -ne 0) { Escribir "[ERROR] No se pudo crear el venv." "Red"; exit 1 }
}
if (-not (Test-Path $venvPython)) {
    Escribir "[ERROR] El venv quedó incompleto: falta $venvPython" "Red"; exit 1
}

# --- 3. Dependencias --------------------------------------------------------
Escribir "Instalando mgm y sus dependencias (puede tardar un par de minutos) ..."
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -e $raiz --quiet
if ($LASTEXITCODE -ne 0) {
    Escribir "[ERROR] Falló la instalación de dependencias." "Red"
    Escribir "        Si estás detrás de un proxy corporativo, configura HTTPS_PROXY y reintenta." "Yellow"
    exit 1
}
Escribir "[OK] Paquete instalado." "Green"

# --- 4. Lanzador ------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
$lanzador = Join-Path $binDir "mgm.cmd"
@"
@echo off
"$venvPython" -m mgm.cli %*
"@ | Set-Content -Path $lanzador -Encoding ASCII
Escribir "[OK] Lanzador creado en $lanzador" "Green"

# --- 5. PATH del usuario ----------------------------------------------------
# Al FRENTE, no al final: si ya tienes otro "mgm" en el PATH (una instalación
# global vieja, por ejemplo), Windows ejecuta el que aparece primero. Puesto
# al final, el nuestro nunca ganaba — eso es lo que le pasó a un usuario real.
$pathUsuario = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $pathUsuario) { $pathUsuario = "" }
$otrasEntradas = @($pathUsuario -split ";" | Where-Object { $_ -and $_ -ne $binDir })
$nuevoPath = (@($binDir) + $otrasEntradas) -join ";"
if ($nuevoPath -ne $pathUsuario) {
    [Environment]::SetEnvironmentVariable("Path", $nuevoPath, "User")
    Escribir "[OK] $binDir puesto al FRENTE del PATH de tu usuario." "Green"
    Escribir "     Abre una terminal NUEVA para que surta efecto." "Yellow"
} else {
    Escribir "[OK] El PATH ya estaba configurado correctamente." "Green"
}

# --- 6. Avisar si hay OTRO "mgm" que podría competir en el PATH -------------
$rutaActualizada = "$binDir;$env:Path"
$otrosMgm = @()
foreach ($carpeta in ($rutaActualizada -split ";" | Select-Object -Unique)) {
    if (-not $carpeta) { continue }
    foreach ($nombre in @("mgm.exe", "mgm.cmd", "mgm.bat")) {
        $candidato = Join-Path $carpeta $nombre
        if ((Test-Path $candidato) -and ($carpeta -ne $binDir)) { $otrosMgm += $candidato }
    }
}
if ($otrosMgm.Count -gt 0) {
    Escribir "[AVISO] Además del que acabas de instalar, hay otro(s) 'mgm' en tu PATH:" "Yellow"
    $otrosMgm | Select-Object -Unique | ForEach-Object { Escribir "         $_" "Yellow" }
    Escribir "         Si con una terminal nueva 'mgm' sigue sin andar, borra o renombra esos." "Yellow"
}

Escribir ""
Escribir "=== Listo ===" "Cyan"
Escribir "Abre una terminal nueva y prueba:" 
Escribir "    mgm --version"
Escribir "    mgm --cookie ""TU_COOKIE_DE_GEMINI""   (para conectar tu cuenta)"
Escribir "    mgm                                     (sesión interactiva)"
