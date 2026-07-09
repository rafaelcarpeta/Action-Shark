#!/usr/bin/env python3
"""Gerenciamento do WeMod: download, instalacao em prefixo Wine, launch/stop."""

import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Optional

# ── paths ────────────────────────────────────────────────────────────

WEMOD_DATA_DIR = os.path.expanduser(
    '~/.config/trainer_manager/wemod_data'
)
WEMOD_BIN_DIR = os.path.join(WEMOD_DATA_DIR, 'wemod_bin')
WEMOD_EXE_PATH = os.path.join(WEMOD_BIN_DIR, 'WeMod.exe')
WEMOD_MARKER = '.wemod_installed'
WEMOD_INSTALL_LOG = os.path.join(WEMOD_DATA_DIR, 'install.log')
WEMOD_LOGIN_DIR = os.path.join(WEMOD_DATA_DIR, 'wemod_login')

# chaves do config
CFG_WEMOD_EXE_DOWNLOADED = 'wemod_exe_downloaded'


# ── helpers internos ─────────────────────────────────────────────────

def _log(msg: str):
    Path(WEMOD_DATA_DIR).mkdir(parents=True, exist_ok=True)
    with open(WEMOD_INSTALL_LOG, 'a') as f:
        f.write(msg + '\n')


def _http_get(url: str, stream: bool = False):
    import urllib.request
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:135.0) '
                               'Gecko/20100101 Firefox/135.0'},
    )
    return urllib.request.urlopen(req, timeout=60)


def _winpath(linux_path: str) -> str:
    return 'Z:' + linux_path.replace('/', '\\')


# ── WeMod.exe download ─────────────────────────────────────────────

VERSION_DLL_URL = (
    'https://raw.githubusercontent.com/DeckCheatz/wemod-launcher/main/'
    'wemod_data/wemod_bin/version.dll'
)
VERSION_DLL_PATH = os.path.join(WEMOD_BIN_DIR, 'version.dll')


def _ensure_version_dll():
    """Baixa version.dll do GitHub se não existir.

    version.dll e um delayload hook que faz o Electron do WeMod
    funcionar no Wine — sem ele o WeMod fecha silenciosamente."""
    if os.path.isfile(VERSION_DLL_PATH) and os.path.getsize(VERSION_DLL_PATH) > 10000:
        return True
    try:
        os.makedirs(WEMOD_BIN_DIR, exist_ok=True)
        _log(f'Baixando version.dll de {VERSION_DLL_URL}...')
        resp = _http_get(VERSION_DLL_URL)
        with open(VERSION_DLL_PATH, 'wb') as f:
            shutil.copyfileobj(resp, f)
        if os.path.getsize(VERSION_DLL_PATH) > 10000:
            _log('version.dll baixado com sucesso')
            return True
        else:
            raise ValueError('version.dll muito pequeno, parece invalido')
    except Exception as e:
        _log(f'ERRO ao baixar version.dll: {e}')
        _log('WeMod pode nao funcionar sem version.dll')
        return False


def download_wemod() -> str:
    """Baixa o WeMod mais recente da CDN oficial (storage-cdn.wemod.com).
    O .nupkg e um ZIP com os binarios em lib/net45/.
    Retorna o caminho do WeMod.exe ou levanta excecao."""
    if os.path.isfile(WEMOD_EXE_PATH):
        _log(f'WeMod.exe ja existe em {WEMOD_BIN_DIR}')
        _ensure_version_dll()
        return WEMOD_EXE_PATH

    # Tenta descobrir a versao mais recente via API do WeMod
    version = _get_latest_wemod_version() or '11.6.0'
    url = f'https://storage-cdn.wemod.com/app/releases/stable/WeMod-{version}-full.nupkg'
    zip_path = '/tmp/wemod_download.nupkg'

    _log(f'Baixando WeMod {version} de {url}...')
    resp = _http_get(url)
    with open(zip_path, 'wb') as f:
        shutil.copyfileobj(resp, f)
    _log(f'Download concluido ({os.path.getsize(zip_path)} bytes)')

    if os.path.isdir(WEMOD_BIN_DIR):
        shutil.rmtree(WEMOD_BIN_DIR)
    os.makedirs(WEMOD_BIN_DIR, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(WEMOD_BIN_DIR)
    os.remove(zip_path)

    # Move binarios do subdiretorio onde WeMod.exe reside para a raiz
    src_root = WEMOD_BIN_DIR
    for root, dirs, files in os.walk(WEMOD_BIN_DIR):
        if 'WeMod.exe' in files:
            src_root = root
            break
    if src_root != WEMOD_BIN_DIR:
        for item in os.listdir(src_root):
            src = os.path.join(src_root, item)
            dst = os.path.join(WEMOD_BIN_DIR, item)
            if src != dst:
                shutil.move(src, dst)
        # Remove subdiretorios vazios
        for root, dirs, files in os.walk(WEMOD_BIN_DIR, topdown=False):
            if root != WEMOD_BIN_DIR and not os.listdir(root):
                os.rmdir(root)

    for item in ('package', '_rels', '[Content_Types].xml', 'WeMod.nuspec'):
        path = os.path.join(WEMOD_BIN_DIR, item)
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

    if not os.path.isfile(WEMOD_EXE_PATH):
        raise FileNotFoundError('WeMod.exe nao encontrado apos extracao')

    os.chmod(WEMOD_EXE_PATH, 0o755)
    _log(f'WeMod {version} extraido para {WEMOD_BIN_DIR}')
    _ensure_version_dll()
    return WEMOD_EXE_PATH


def _get_latest_wemod_version() -> Optional[str]:
    """Consulta a API de releases do WeMod para pegar a versao estavel mais recente."""
    try:
        resp = _http_get('https://api.wemod.com/client/channels/stable/RELEASES')
        body = resp.read().decode('utf-8', errors='replace')
        # O RELEASES tem linhas como: "WeMod-11.6.0-full.nupkg ..."
        for line in body.strip().splitlines():
            parts = line.strip().split()
            if parts and 'WeMod-' in parts[0]:
                m = re.search(r'WeMod-([\d.]+)-full', parts[0])
                if m:
                    return m.group(1)
    except Exception as e:
        _log(f'Nao foi possivel obter a versao mais recente: {e}')
    return None


# ── instalacao no prefixo ────────────────────────────────────────────

def _find_wine_in_dir(base_dir: str) -> Optional[str]:
    """Procura wine64/wine em <base_dir>/files/bin/ ou <base_dir>/bin/."""
    for sub in ('files/bin', 'bin'):
        for name in ('wine64', 'wine'):
            candidate = os.path.join(base_dir, sub, name)
            if os.path.isfile(candidate):
                return candidate
    return None


def _find_proton_in_steam(ver: str) -> Optional[str]:
    """Procura wine interno de um Proton do Steam."""
    steam_roots = [
        os.path.expanduser('~/.local/share/Steam'),
        os.path.expanduser('~/.steam/steam'),
        os.path.expanduser('~/.steam/root'),
    ]
    for root in steam_roots:
        for base in ('compatibilitytools.d', 'steamapps/common'):
            base_dir = os.path.join(root, base)
            if not os.path.isdir(base_dir):
                continue
            for d in sorted(os.listdir(base_dir), reverse=True):
                if ver and ver not in d:
                    continue
                if 'proton' not in d.lower():
                    continue
                wine = _find_wine_in_dir(os.path.join(base_dir, d))
                if wine:
                    return wine
    return None


def _get_wine_binary(wineprefix: str) -> str:
    """Retorna o binario wine real (files/bin/wine) para usar com WINEPREFIX.
    Proton como wrapper nao funciona, precisamos do wine interno."""
    # Steam / Proton: tenta achar pelo version file no parent
    version_file = os.path.join(os.path.dirname(wineprefix), 'version')
    if os.path.isfile(version_file):
        ver = Path(version_file).read_text().strip()
        wine = _find_proton_in_steam(ver)
        if wine:
            return wine

    # PortProton: prefixo dentro ~/.var/app/ru.linux_gaming.PortProton/data/prefixes/
    pp_base = os.path.expanduser(
        '~/.var/app/ru.linux_gaming.PortProton/data'
    )
    if pp_base in wineprefix and os.path.isdir(pp_base):
        # 1. Tenta ler .wine_ver dentro do prefixo (contém "GE-PROTON11-1")
        wine_ver_file = os.path.join(wineprefix, '.wine_ver')
        if os.path.isfile(wine_ver_file):
            ver = Path(wine_ver_file).read_text().strip()
            # Procura em dist/<ver>/files/bin/wine
            for d in (os.path.join(pp_base, 'dist', ver),
                      os.path.join(pp_base, ver)):
                wine = _find_wine_in_dir(d)
                if wine:
                    return wine

        # 2. Fallback: varre diretorios dentro de dist/
        dist_dir = os.path.join(pp_base, 'dist')
        if os.path.isdir(dist_dir):
            for item in os.listdir(dist_dir):
                wine = _find_wine_in_dir(os.path.join(dist_dir, item))
                if wine:
                    return wine

        # 3. Fallback: varre a raiz do PortProton
        for item in os.listdir(pp_base):
            wine = _find_wine_in_dir(os.path.join(pp_base, item))
            if wine:
                return wine

    # fallback: wine do sistema
    for c in ('/usr/bin/wine64', '/usr/bin/wine',
              '/usr/local/bin/wine64', '/usr/local/bin/wine'):
        if os.path.isfile(c):
            return c
    return shutil.which('wine64') or shutil.which('wine') or 'wine'


def _run_wine(wine_bin: str, wineprefix: str, args: list,
              timeout: Optional[int] = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env['WINEPREFIX'] = wineprefix
    env['WINEDLLOVERRIDES'] = 'winemenubuilder.exe=d'
    # winetricks precisa de PATH apontando para o diretorio do wine
    env['PATH'] = os.path.dirname(wine_bin) + ':' + env.get('PATH', '')
    cmd = [wine_bin] + args
    _log(f'$ WINEPREFIX={wineprefix} {" ".join(cmd)}')
    return subprocess.run(
        cmd, env=env, capture_output=True, text=True,
        timeout=timeout,
    )





def install_wemod_prefix(wineprefix: str,
                        log_callback=None) -> bool:
    """Instala WeMod + .NET 4.8 + dependencias no prefixo.
    log_callback: funcao opcional chamada para cada linha de log em tempo real.
    Retorna True se sucesso."""
    if log_callback is None:
        log_callback = _log

    marker = os.path.join(wineprefix, WEMOD_MARKER)
    if os.path.isfile(marker):
        os.remove(marker)

    log_callback(f'Instalando WeMod em {wineprefix}...')
    wine_bin = _get_wine_binary(wineprefix)
    log_callback(f'Wine: {wine_bin}')

    # 1. winetricks
    winetricks_sh = os.path.join(WEMOD_DATA_DIR, 'winetricks')
    if not os.path.isfile(winetricks_sh):
        log_callback('Baixando winetricks...')
        resp = _http_get(
            'https://github.com/Winetricks/winetricks/raw/master/src/winetricks'
        )
        with open(winetricks_sh, 'wb') as f:
            shutil.copyfileobj(resp, f)
        os.chmod(winetricks_sh, 0o755)

    wt_env = os.environ.copy()
    wt_env['WINEPREFIX'] = wineprefix
    wt_env['WINEDLLOVERRIDES'] = 'winemenubuilder.exe=d'
    wt_env['PATH'] = os.path.dirname(wine_bin) + ':' + wt_env.get('PATH', '')

    log_callback('winetricks: sdl, cjkfonts, vkd3d, dxvk2030...')
    subprocess.run(
        [winetricks_sh, 'sdl', 'cjkfonts', 'vkd3d', 'dxvk2030'],
        env=wt_env,
        timeout=600,
    )

    log_callback('winetricks: dotnet48 (pode levar 20-40 min)...')
    subprocess.run(
        [winetricks_sh, '-f', 'dotnet48'],
        env=wt_env,
        timeout=3600,
    )

    # Verifica .NET 4.8
    fx_path = os.path.join(wineprefix, 'drive_c', 'windows',
                           'Microsoft.NET', 'Framework64', 'v4.0.30319')
    if os.path.isdir(fx_path) and os.path.isfile(os.path.join(fx_path, 'clr.dll')):
        log_callback('.NET 4.8 instalado com sucesso')
    else:
        log_callback('ATENCAO: .NET 4.8 pode nao ter instalado corretamente')
        log_callback('WeMod pode reclamar sobre .NET')

    log_callback('winecfg -v win10...')
    _run_wine(wine_bin, wineprefix, ['winecfg', '-v', 'win10'])

    with open(marker, 'w') as f:
        f.write('1')
    log_callback('WeMod instalado com sucesso!')
    return True


# ── sync login data (symlink) ─────────────────────────────────────────

def _get_windows_user(wineprefix: str) -> str:
    """Descobre o nome do usuario Windows dentro do prefixo."""
    users_dir = os.path.join(wineprefix, 'drive_c', 'users')
    if not os.path.isdir(users_dir):
        return 'steamuser'
    for entry in sorted(os.listdir(users_dir)):
        entry_lower = entry.lower()
        if entry_lower in ('public', 'default user', 'all users', 'default',
                           'desktop.ini', 'administrator'):
            continue
        user_path = os.path.join(users_dir, entry)
        if os.path.isdir(user_path) and not os.path.islink(user_path):
            return entry
    return 'steamuser'


def sync_wemod_login(wineprefix: str, interactive: bool = True):
    win_user = _get_windows_user(wineprefix)
    WeModExternal = os.path.join(
        wineprefix, f'drive_c/users/{win_user}/AppData/Roaming/WeMod'
    )
    os.makedirs(WEMOD_LOGIN_DIR, exist_ok=True)

    central_has = len(os.listdir(WEMOD_LOGIN_DIR)) > 0
    external_is_link = os.path.islink(WeModExternal)
    external_is_dir = os.path.isdir(WeModExternal) and not os.path.islink(WeModExternal)

    if external_is_link and os.path.realpath(WeModExternal) == WEMOD_LOGIN_DIR:
        _log(f'Symlink {WeModExternal} ja aponta para {WEMOD_LOGIN_DIR}')
        return

    if external_is_link:
        _log(f'Removendo symlink invalido: {WeModExternal}')
        os.remove(WeModExternal)
        external_is_link = False

    if external_is_dir:
        external_has = len(os.listdir(WeModExternal)) > 0
        if central_has and external_has:
            _log('Dados em central e prefixo; mantendo central')
        elif not central_has and external_has:
            _log(f'Migrando dados do prefixo para central: {WEMOD_LOGIN_DIR}')
            if os.path.isdir(WEMOD_LOGIN_DIR):
                shutil.rmtree(WEMOD_LOGIN_DIR)
            shutil.copytree(WeModExternal, WEMOD_LOGIN_DIR)
        shutil.rmtree(WeModExternal, ignore_errors=True)
    elif os.path.exists(WeModExternal):
        os.remove(WeModExternal)

    if not os.path.exists(WeModExternal):
        _log(f'Criando symlink: {WeModExternal} -> {WEMOD_LOGIN_DIR}')
        os.symlink(WEMOD_LOGIN_DIR, WeModExternal)


# ── launch / stop ────────────────────────────────────────────────────

def _get_proton_binary(wineprefix: str) -> Optional[str]:
    """Retorna o caminho do script 'proton' (waitforexitandrun) associado ao prefixo."""
    version_file = os.path.join(os.path.dirname(wineprefix), 'version')
    if not os.path.isfile(version_file):
        return None
    ver = Path(version_file).read_text().strip()
    steam_roots = [
        os.path.expanduser('~/.local/share/Steam'),
        os.path.expanduser('~/.steam/steam'),
        os.path.expanduser('~/.steam/root'),
    ]
    for root in steam_roots:
        for base in ('compatibilitytools.d', 'steamapps/common'):
            base_dir = os.path.join(root, base)
            if not os.path.isdir(base_dir):
                continue
            for d in sorted(os.listdir(base_dir), reverse=True):
                if ver and ver not in d:
                    continue
                if 'proton' not in d.lower():
                    continue
                cand = os.path.join(base_dir, d, 'proton')
                if os.path.isfile(cand):
                    return cand
    return None


def launch_wemod(wineprefix: str) -> Optional[int]:
    """Inicia WeMod como processo background via cmd /c start com wine direto.

    Usa wine puro (sem Proton) para evitar conflito de lock do compatdata
    com o Steam. O batch faz `start "" WeMod.exe --flags` para spawnar o
    WeMod desanexado e fica em loop aguardando o processo sair."""
    marker = os.path.join(wineprefix, WEMOD_MARKER)
    if not os.path.isfile(marker):
        _log('WeMod nao instalado, instale primeiro')
        return None
    if is_wemod_running(wineprefix):
        _log('WeMod ja esta rodando')
        return _get_wemod_pid(wineprefix)

    sync_wemod_login(wineprefix)

    wemod_exe = WEMOD_EXE_PATH
    if not os.path.isfile(wemod_exe):
        _log(f'WeMod.exe nao encontrado em {wemod_exe}')
        return None
    _ensure_version_dll()

    wemod_win = _winpath(wemod_exe)
    flags = ' '.join([
        '--disable-gpu',
        '--no-sandbox',
        '--in-process-gpu',
        '--disable-gpu-compositing',
        '--use-gl=swiftshader',
    ])
    bat_path = '/tmp/wemod_start.bat'
    with open(bat_path, 'w') as f:
        f.write(f'@echo off\n')
        f.write(f'start "" "{wemod_win}" {flags}\n')
        f.write(f':loop\n')
        f.write(f'@ping localhost -n 6 >nul\n')
        f.write(f'tasklist /FI "IMAGENAME eq WeMod.exe" 2>nul | find "WeMod.exe" >nul\n')
        f.write(f'if errorlevel 1 exit\n')
        f.write(f'goto loop\n')

    logfile = f'/tmp/wemod_{os.path.basename(wineprefix)}.log'
    wine_bin = _get_wine_binary(wineprefix)
    env = os.environ.copy()
    env['WINEPREFIX'] = wineprefix
    env['WINEDLLOVERRIDES'] = 'winemenubuilder.exe=d'
    env['PATH'] = os.path.dirname(wine_bin) + ':' + env.get('PATH', '')
    cmd = [wine_bin, 'cmd', '/c', 'Z:\\tmp\\wemod_start.bat']

    proc = subprocess.Popen(
        cmd, env=env,
        stdout=open(logfile, 'w'),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _log(f'WeMod iniciado via batch (PID {proc.pid}, log: {logfile})')
    import time
    time.sleep(3)
    we_pid = _get_wemod_pid(wineprefix)
    if we_pid:
        _log(f'WeMod.exe em execucao (PID {we_pid})')
    else:
        _log('ATENCAO: WeMod.exe nao detectado apos lancamento')
    return we_pid or proc.pid


def stop_wemod(wineprefix: str):
    """Para o WeMod rodando no prefixo."""
    # Mata o WeMod.exe primeiro
    pid = _get_wemod_pid(wineprefix)
    if pid:
        try:
            os.kill(pid, 9)
            _log(f'WeMod.exe PID {pid} finalizado (SIGKILL)')
        except ProcessLookupError:
            _log(f'WeMod.exe PID {pid} ja nao existe')
        except PermissionError:
            _log(f'Sem permissao para matar PID {pid}')

    # Mata o processo proton/batch que mantem o WeMod vivo
    compat_data = os.path.dirname(wineprefix)
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        try:
            cmdline = Path(f'/proc/{entry}/cmdline').read_bytes().decode('utf-8', errors='replace')
        except (OSError, PermissionError):
            continue
        if 'wemod_start.bat' not in cmdline and 'WeMod.exe' not in cmdline:
            continue
        try:
            env_raw = Path(f'/proc/{entry}/environ').read_bytes().decode('utf-8', errors='replace')
        except (OSError, PermissionError):
            continue
        if wineprefix in env_raw or compat_data in env_raw:
            try:
                os.kill(int(entry), 9)
                _log(f'Processo auxiliar PID {entry} finalizado')
            except (ProcessLookupError, PermissionError, OSError):
                pass

    # Mata o wineserver
    try:
        subprocess.run(
            ['wineserver', '-k'],
            env={'WINEPREFIX': wineprefix},
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


# ── status ───────────────────────────────────────────────────────────

def is_wemod_installed(wineprefix: str) -> bool:
    return os.path.isfile(os.path.join(wineprefix, WEMOD_MARKER))


def _get_wemod_pid(wineprefix: str) -> Optional[int]:
    """Procura processo WeMod.exe rodando neste prefixo.

    Tenta match por:
    1. Nome do processo cmdline contendo 'WeMod.exe'
    2. WINEPREFIX ou STEAM_COMPAT_DATA_PATH no environ apontando para o prefixo"""
    compat_data = os.path.dirname(wineprefix)
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        try:
            cmdline = Path(f'/proc/{entry}/cmdline').read_bytes().decode('utf-8', errors='replace')
        except (OSError, PermissionError):
            continue
        if 'WeMod.exe' not in cmdline:
            continue
        # Confirma que e deste prefixo
        try:
            env_raw = Path(f'/proc/{entry}/environ').read_bytes().decode('utf-8', errors='replace')
        except (OSError, PermissionError):
            # Se nao der pra ler environ, confirma pelo cmdline mesmo
            return int(entry)
        if wineprefix in env_raw or compat_data in env_raw:
            return int(entry)
    return None


def is_wemod_running(wineprefix: str) -> bool:
    return _get_wemod_pid(wineprefix) is not None


def get_status(wineprefix: str) -> str:
    """Retorna string descritiva: 'Nao instalado', 'Instalado', 'Rodando'."""
    if not is_wemod_installed(wineprefix):
        return 'Nao instalado'
    if is_wemod_running(wineprefix):
        return 'Rodando'
    return 'Instalado'
