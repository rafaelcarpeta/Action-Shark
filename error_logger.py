import os
import sys
import re
import time
import subprocess
import threading
import tempfile
import traceback
from datetime import datetime
from typing import Optional, Callable, Dict, Any

# Root installation directory of the app
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(APP_ROOT, 'logs')

# Known signatures of crashes or fatal errors in Wine/Proton and application output
CRASH_SIGNATURES = [
    'unhandled exception:',
    'unhandled page fault',
    'page fault on read access',
    'page fault on write access',
    'wine crash:',
    'fatal error:',
    'c0000005',
    'c000001d',
    'c00000fd',
    'c0000025',
    'err:seh:',
    'err:virtual:',
    'err:module:import_dll',
    'err:module:load_builtin_dll',
    'err:module:load_so_dll',
    'wine: could not load',
    'wine: bad exe format',
    'bad exe format for',
    'application has crashed',
    'aborted (core dumped)',
    'segmentation fault',
    'traceback (most recent call last):',
]


def get_logs_dir() -> str:
    """Returns the absolute path to the logs folder in the app's root installation directory,
    creating it if it does not already exist."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    return LOGS_DIR


def open_logs_folder() -> bool:
    """Opens the root logs directory in the system file manager."""
    target_dir = get_logs_dir()
    try:
        subprocess.Popen(['xdg-open', target_dir])
        return True
    except Exception:
        try:
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            return QDesktopServices.openUrl(QUrl.fromLocalFile(target_dir))
        except Exception:
            return False


def sanitize_name(name: Optional[str]) -> str:
    """Sanitizes game or app name to be safe for filenames."""
    if not name:
        return ""
    # Strip executable extensions if present
    name = re.sub(r'\.(exe|bat|cmd|sh)$', '', name.strip(), flags=re.IGNORECASE)
    # Replace non-word characters (excluding dashes) with underscores
    sanitized = re.sub(r'[^\w\-]+', '_', name).strip('_')
    return sanitized


def format_log_filename(
    game_name: Optional[str],
    app_name: Optional[str],
    problem_type: str = "error"
) -> str:
    """Formats a log filename that clearly discriminates the game and the app/trainer,
    along with the problem type and a timestamp."""
    clean_game = sanitize_name(game_name)
    clean_app = sanitize_name(app_name)
    clean_type = sanitize_name(problem_type) or "error"
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    if clean_game and clean_app:
        if clean_game.lower() == clean_app.lower():
            prefix = clean_game
        else:
            prefix = f"{clean_game}_{clean_app}"
    elif clean_game:
        prefix = clean_game
    elif clean_app:
        prefix = clean_app
    else:
        prefix = "App"

    return f"{prefix}_{clean_type}_{timestamp}.log"


def save_error_log(
    game_name: Optional[str],
    app_name: Optional[str],
    problem_type: str,
    details: str = "",
    stdout_content: str = "",
    stderr_content: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """Saves a structured error/crash log into the root logs directory.
    Returns the absolute path to the generated log file."""
    logs_dir = get_logs_dir()
    filename = format_log_filename(game_name, app_name, problem_type)
    filepath = os.path.join(logs_dir, filename)

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    content_lines = [
        "=" * 80,
        "Action Shark - Log de Erro / Crash",
        "=" * 80,
        f"Data/Hora:        {now_str}",
        f"Jogo/Alvo:        {game_name or 'N/A'}",
        f"Aplicação/Tool:   {app_name or 'N/A'}",
        f"Tipo de Problema: {problem_type}",
    ]

    if context:
        content_lines.append("")
        content_lines.append("Contexto de Execução:")
        for k, v in context.items():
            content_lines.append(f"  • {k}: {v}")

    if details:
        content_lines.append("")
        content_lines.append("Detalhes / Mensagem de Erro:")
        content_lines.append(details.strip())

    if stdout_content:
        content_lines.append("")
        content_lines.append("Saída Capturada (stdout/stderr):")
        content_lines.append("-" * 80)
        content_lines.append(stdout_content.rstrip())

    if stderr_content and stderr_content != stdout_content:
        content_lines.append("")
        content_lines.append("Saída de Erro (stderr):")
        content_lines.append("-" * 80)
        content_lines.append(stderr_content.rstrip())

    content_lines.append("=" * 80 + "\n")

    try:
        with open(filepath, 'w', encoding='utf-8', errors='replace') as f:
            f.write("\n".join(content_lines))
    except Exception as e:
        sys.stderr.write(f"[Action Shark] Falha ao gravar log em {filepath}: {e}\n")

    return filepath


def has_crash_signature(output_text: str) -> bool:
    """Detects if Wine/Proton or program output contains known crash markers."""
    if not output_text:
        return False
    lower = output_text.lower()
    return any(sig in lower for sig in CRASH_SIGNATURES)


def is_problem_exit(
    returncode: Optional[int],
    output_text: str,
    runtime_seconds: float
) -> bool:
    """Evaluates whether an exit was problematic (crash or initialization failure)
    versus a normal clean shutdown."""
    # 1. Non-zero positive exit codes indicate failure
    if returncode is not None and returncode > 0:
        return True

    # 2. Fatal terminating signals (SIGSEGV=-11, SIGABRT=-6, SIGBUS=-7, SIGILL=-4, SIGFPE=-8)
    if returncode is not None and returncode in (-11, -6, -7, -4, -8):
        return True

    # 3. Output contains Wine crash backtrace or error signatures
    if has_crash_signature(output_text):
        return True

    # 4. Immediate early exit (under 3 seconds) with non-zero code or signal
    if runtime_seconds < 3.0 and returncode is not None and returncode != 0:
        return True

    return False


def watch_process_execution(
    proc: subprocess.Popen,
    temp_logfile: str,
    game_name: Optional[str],
    app_name: Optional[str],
    context: Optional[Dict[str, Any]] = None,
    on_error_callback: Optional[Callable[[str, str], None]] = None,
) -> threading.Thread:
    """Monitors a subprocess asynchronously. If a crash or error occurs,
    writes the log file to LOGS_DIR and triggers on_error_callback.
    If the run is normal and clean, deletes the temp file and leaves LOGS_DIR untouched."""
    def _monitor():
        start_time = time.time()
        try:
            returncode = proc.wait()
        except Exception:
            returncode = proc.poll()
        runtime = time.time() - start_time

        output = ""
        try:
            if os.path.isfile(temp_logfile):
                with open(temp_logfile, 'r', encoding='utf-8', errors='replace') as f:
                    output = f.read()
        except Exception:
            pass

        if is_problem_exit(returncode, output, runtime):
            if runtime < 3.0 and returncode != 0:
                problem_type = f"Erro_de_Inicializacao (retcode {returncode})"
            else:
                problem_type = f"Crash (retcode {returncode})"

            log_file = save_error_log(
                game_name=game_name,
                app_name=app_name,
                problem_type=problem_type,
                details=f"Processo finalizado com código {returncode} após {runtime:.1f}s",
                stdout_content=output,
                context=context,
            )

            if on_error_callback:
                try:
                    on_error_callback(log_file, f"Problema detectado em {game_name or app_name}")
                except Exception:
                    pass

        # Always clean up the temporary log buffer file
        try:
            if os.path.isfile(temp_logfile):
                os.remove(temp_logfile)
        except OSError:
            pass

    t = threading.Thread(target=_monitor, daemon=True)
    t.start()
    return t


def setup_global_exception_handler():
    """Installs a sys.excepthook to capture unhandled Python exceptions and write
    crash logs in LOGS_DIR."""
    old_excepthook = sys.excepthook

    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            old_excepthook(exc_type, exc_value, exc_tb)
            return

        tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
        tb_str = "".join(tb_lines)

        save_error_log(
            game_name=None,
            app_name="Action_Shark",
            problem_type="Crash_da_Aplicacao",
            details=f"Exceção não tratada: {exc_type.__name__}: {exc_value}\n\nTraceback:\n{tb_str}",
        )
        old_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook
