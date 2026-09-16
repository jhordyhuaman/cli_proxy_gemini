import os
import sys
import re
import subprocess
import g4f
import nest_asyncio
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

nest_asyncio.apply()
console = Console()

# ==========================================
# 1. DEFINICIÓN DE ROLES Y SKILLS
# ==========================================

AGENT_PROMPT = """Eres 'mgm', un Agente de IA Autónomo en la terminal Windows.
Usas 'Skills' (herramientas) EXCLUSIVAMENTE mediante bloques XML.

SKILLS:
<skill type="file" path="ruta">código</skill>
<skill type="cmd">comando de terminal</skill>
<skill type="finish">Mensaje final</skill>

REGLAS ESTRICTAS DE AUTO-EVALUACIÓN (Framework ReAct):
1. PROHIBIDO usar <skill type="finish"> inmediatamente después de crear un archivo.
2. Si creaste lógica de Backend o Scripts, DEBES ejecutar un test usando <skill type="cmd"> para verificar que funciona.
3. Si el comando arroja un error en la consola, ESTÁ PROHIBIDO terminar. Debes analizar el error, usar <skill type="file"> para corregirlo y volver a probar con <skill type="cmd">.
4. Solo puedes usar <skill type="finish"> cuando las pruebas en terminal pasen exitosamente o cuando se trate de código Frontend (HTML/CSS) que requiera validación visual del usuario.
"""

# ==========================================
# 2. MOTOR DE EJECUCIÓN (SKILL MANAGER)
# ==========================================

class SkillManager:
    @staticmethod
    def execute_file(path, content):
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content.strip())
            return f"[ÉXITO] Archivo {path} creado/actualizado correctamente."
        except Exception as e:
            return f"[ERROR] No se pudo crear el archivo {path}: {e}"

    @staticmethod
    def execute_cmd(cmd):
        # SEGURIDAD: Confirmación manual antes de ejecutar comandos del LLM
        console.print(f"\n[bold yellow]⚠️ La IA quiere ejecutar el siguiente comando:[/bold yellow]")
        console.print(Panel(cmd, border_style="yellow"))
        auth = console.input("[bold cyan]¿Permitir ejecución? (y/n): [/bold cyan]").strip().lower()
        
        if auth != 'y':
            return "[ERROR] El usuario denegó el permiso para ejecutar este comando."
        
        console.print("[dim]Ejecutando...[/dim]")
        try:
            # Ejecuta el comando y captura la salida
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=os.getcwd())
            output = result.stdout + result.stderr
            if not output.strip():
                output = "[Comando ejecutado con éxito, sin salida en consola]"
            return f"[RESULTADO DEL COMANDO]:\n{output}"
        except Exception as e:
            return f"[ERROR DEL SISTEMA]: {e}"

# ==========================================
# 3. NÚCLEO DEL AGENTE (LOOP AUTÓNOMO)
# ==========================================

class AgentLoop:
    def __init__(self):
        self.messages = [{"role": "user", "content": AGENT_PROMPT}]
    
    def parse_and_execute(self, response_text):
        """Busca etiquetas <skill> y ejecuta las herramientas reales."""
        pattern = r'<skill\s+type="([^"]+)"(?:\s+path="([^"]+)")?>\s*(.*?)\s*</skill>'
        matches = list(re.finditer(pattern, response_text, re.DOTALL | re.IGNORECASE))
        
        system_feedback = ""
        is_finished = False

        if not matches:
            return response_text, system_feedback, is_finished

        console.print("\n[bold magenta]Ejecutando Skills...[/bold magenta]")
        
        for match in matches:
            skill_type = match.group(1).lower()
            path = match.group(2)
            content = match.group(3)

            if skill_type == "file":
                res = SkillManager.execute_file(path, content)
                console.print(f"  [green]✓[/green] Skill: [bold]File[/bold] -> {path}")
                system_feedback += f"\n{res}"
                
            elif skill_type == "cmd":
                res = SkillManager.execute_cmd(content)
                console.print(f"  [cyan]⚡[/cyan] Skill: [bold]CMD[/bold]")
                system_feedback += f"\n{res}"
                
            elif skill_type == "finish":
                console.print(f"  [bold green]🏁 Plan Terminado:[/bold green]")
                console.print(Markdown(content))
                is_finished = True

        return "", system_feedback, is_finished

    def run_plan(self, goal):
        """Bucle iterativo (El Agente habla con la terminal hasta acabar)."""
        console.print(f"\n[bold blue]=== INICIANDO MODO PLANIFICADOR ===[/bold blue]")
        console.print(f"Objetivo: [white]{goal}[/white]\n")
        
        # Le inyectamos el objetivo
        self.messages.append({"role": "user", "content": f"OBJETIVO DEL PLAN: {goal}\nEjecuta tu primera acción usando los tags <skill>."})
        
        iteration = 1
        max_iterations = 10 # Límite de seguridad para que no se quede en bucle infinito

        while iteration <= max_iterations:
            console.print(f"[dim]Iteración {iteration}/{max_iterations}... Pensando...[/dim]")
            
            try:
                # 1. Llamar al LLM
                response = g4f.ChatCompletion.create(
                    model=g4f.models.gemini,
                    provider=Gemini, # Forzamos el uso del proveedor oficial
                    messages=self.messages, # O agent.messages dependiendo de la línea
                    cookies={"__Secure-1PSID": "CLF8mXUwzHDm10lo/AzZd5y0BkFuXQLui5"}
                )
                self.messages.append({"role": "assistant", "content": response})

                # 2. Parsear y Ejecutar las herramientas
                display_text, feedback, is_finished = self.parse_and_execute(response)
                
                if display_text.strip():
                    console.print(Markdown(display_text))

                # 3. Evaluar si terminó
                if is_finished:
                    console.print("\n[bold green]=== PLAN COMPLETADO EXITOSAMENTE ===[/bold green]")
                    break
                
                # 4. Retroalimentar a la IA con los resultados de la terminal
                if feedback:
                    console.print(f"[dim]Enviando resultados de la terminal a la IA...[/dim]")
                    self.messages.append({
                        "role": "user", 
                        "content": f"Resultados de tus acciones anteriores:\n{feedback}\n\nAnaliza este resultado. Si hubo errores, corrígelos usando tus skills. Si todo está bien, continúa con el siguiente paso o usa <skill type='finish'>."
                    })
                else:
                    # Si no usó herramientas pero tampoco terminó, le forzamos a seguir
                    self.messages.append({"role": "user", "content": "Por favor, continúa con el plan usando las etiquetas <skill>."})
                
                iteration += 1

            except Exception as e:
                console.print(f"[error]Error en la conexión del agente:[/error] {e}")
                break
        
        if iteration > max_iterations:
            console.print("\n[bold red]⚠️ El plan superó el límite de iteraciones y fue pausado por seguridad.[/bold red]")

# ==========================================
# 4. INTERFAZ PRINCIPAL
# ==========================================

def main():
    os.system('cls' if os.name == 'nt' else 'clear')
    banner = "[bold cyan]mgm v4.0 - Autonomous Agent Edition[/bold cyan]\n[dim]Soporta modo /plan y Skills (Superpowers)[/dim]"
    console.print(Panel(banner, border_style="cyan"))
    
    agent = AgentLoop()

    while True:
        try:
            cwd = os.getcwd()
            user_input = console.input(f"\n[user]mgm[/user] [dim]({os.path.basename(cwd)})[/dim] [bold cyan]>[/bold cyan] ").strip()
            
            if user_input.lower() in ['/exit', 'salir']:
                break
            if not user_input:
                continue

            # INTERCEPTAR COMANDO /PLAN
            if user_input.lower().startswith("/plan "):
                goal = user_input[6:].strip()
                agent.run_plan(goal)
            else:
                # Modo chat normal (sin bucle autónomo)
                agent.messages.append({"role": "user", "content": user_input})
                with console.status("[bold cyan]Pensando...[/bold cyan]"):
                    resp = g4f.ChatCompletion.create(model=g4f.models.gemini, messages=agent.messages)
                
                display_text, feedback, _ = agent.parse_and_execute(resp)
                if display_text:
                    console.print(Markdown(display_text))
                agent.messages.append({"role": "assistant", "content": resp})

        except KeyboardInterrupt:
            console.print("\n[warning]Operación cancelada.[/warning]")
            
if __name__ == "__main__":
    main()