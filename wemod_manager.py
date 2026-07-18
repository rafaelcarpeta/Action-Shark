#!/usr/bin/env python3
"""Gerenciamento do WeMod: download, instalacao em prefixo Wine, launch/stop."""

import json
import hashlib
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
    funcionar no Wine — sem ele o WeMod fecha silenciosamente.
    Coloca no app-{version}/ (junto do WeMod.exe) e na raiz."""
    app_dir = _get_wemod_app_dir()
    targets = [WEMOD_BIN_DIR]
    if app_dir:
        targets.append(app_dir)

    for target_dir in targets:
        dll = os.path.join(target_dir, 'version.dll')
        if os.path.isfile(dll) and os.path.getsize(dll) > 10000:
            continue
        try:
            os.makedirs(target_dir, exist_ok=True)
            _log(f'Baixando version.dll para {target_dir}...')
            resp = _http_get(VERSION_DLL_URL)
            with open(dll, 'wb') as f:
                shutil.copyfileobj(resp, f)
            if os.path.getsize(dll) > 10000:
                _log(f'version.dll baixado em {target_dir}')
            else:
                raise ValueError('version.dll muito pequeno, parece invalido')
        except Exception as e:
            _log(f'ERRO ao baixar version.dll: {e}')
            _log('WeMod pode nao funcionar sem version.dll')
            return False
    return True


def download_wemod() -> str:
    """Baixa o WeMod mais recente da CDN oficial (storage-cdn.wemod.com).
    O .nupkg e um ZIP com os binarios em lib/net45/.
    Mantem estrutura Squirrel (app-{versao}/, packages/, RELEASES, Update.exe).
    Retorna o caminho do WeMod.exe ou levanta excecao."""
    app_dir = _get_wemod_app_dir()
    if app_dir:
        exe = os.path.join(app_dir, 'WeMod.exe')
        if os.path.isfile(exe):
            _log(f'WeMod.exe ja existe em {exe}')
            _ensure_version_dll()
            _ensure_squirrel_structure()
            return exe

    # Tenta descobrir a versao mais recente via API do WeMod
    version = _get_latest_wemod_version() or '11.6.0'
    url = f'https://storage-cdn.wemod.com/app/releases/stable/WeMod-{version}-full.nupkg'
    zip_path = '/tmp/wemod_download.nupkg'

    _log(f'Baixando WeMod {version} de {url}...')
    resp = _http_get(url)
    with open(zip_path, 'wb') as f:
        shutil.copyfileobj(resp, f)
    nupkg_size = os.path.getsize(zip_path)
    _log(f'Download concluido ({nupkg_size} bytes)')

    if os.path.isdir(WEMOD_BIN_DIR):
        shutil.rmtree(WEMOD_BIN_DIR)
    os.makedirs(WEMOD_BIN_DIR, exist_ok=True)

    # Estrutura Squirrel:
    #   wemod_bin/
    #     Update.exe          (squirrel.exe copiado)
    #     squirrel.exe
    #     app-{version}/
    #       WeMod.exe + recursos
    #     packages/
    #       WeMod-{version}-full.nupkg
    #       RELEASES

    app_dir = os.path.join(WEMOD_BIN_DIR, f'app-{version}')
    packages_dir = os.path.join(WEMOD_BIN_DIR, 'packages')
    os.makedirs(app_dir, exist_ok=True)
    os.makedirs(packages_dir, exist_ok=True)

    # Extrai nupkg para app-{version}/
    with zipfile.ZipFile(zip_path, 'r') as zf:
        # O nupkg tem os arquivos em lib/net45/
        for member in zf.namelist():
            if member.startswith('lib/net45/'):
                # Remove prefixo lib/net45/
                target = member[len('lib/net45/'):]
                if not target:
                    continue
                target_path = os.path.join(app_dir, target)
                if member.endswith('/'):
                    os.makedirs(target_path, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with zf.open(member) as src, open(target_path, 'wb') as dst:
                        shutil.copyfileobj(src, dst)

    # Salva nupkg original em packages/
    nupkg_dst = os.path.join(packages_dir, f'WeMod-{version}-full.nupkg')
    shutil.copy2(zip_path, nupkg_dst)
    os.remove(zip_path)

    # Cria RELEASES (SHA1 do nupkg + tamanho)
    sha1 = hashlib.sha1(open(nupkg_dst, 'rb').read()).hexdigest()
    releases_path = os.path.join(packages_dir, 'RELEASES')
    with open(releases_path, 'w') as f:
        f.write(f'WeMod-{version}-full.nupkg {sha1} {nupkg_size}\n')

    # Copia squirrel.exe como Update.exe (Squirrel manager)
    squirrel_exe = os.path.join(app_dir, 'squirrel.exe')
    if os.path.isfile(squirrel_exe):
        shutil.copy2(squirrel_exe, os.path.join(WEMOD_BIN_DIR, 'squirrel.exe'))
        shutil.copy2(squirrel_exe, os.path.join(WEMOD_BIN_DIR, 'Update.exe'))
        os.remove(squirrel_exe)

    # Limpa lixo do Squirrel no app_dir
    for item in ('package', '_rels', '[Content_Types].xml', 'WeMod.nuspec'):
        path = os.path.join(app_dir, item)
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

    exe = os.path.join(app_dir, 'WeMod.exe')
    if not os.path.isfile(exe):
        raise FileNotFoundError('WeMod.exe nao encontrado apos extracao')

    os.chmod(exe, 0o755)
    _log(f'WeMod {version} instalado em {app_dir}')
    _ensure_version_dll()
    _ensure_squirrel_structure()
    return exe


def _get_wemod_app_dir() -> Optional[str]:
    """Retorna o diretorio app-{version}/ mais recente, ou None."""
    if not os.path.isdir(WEMOD_BIN_DIR):
        return None
    candidates = []
    for d in os.listdir(WEMOD_BIN_DIR):
        if d.startswith('app-'):
            full = os.path.join(WEMOD_BIN_DIR, d)
            if os.path.isdir(full) and os.path.isfile(os.path.join(full, 'WeMod.exe')):
                candidates.append(full)
    if not candidates:
        return None
    # Mais recente por nome de versao
    candidates.sort(reverse=True)
    return candidates[0]


def _ensure_squirrel_structure():
    """Garante que a estrutura Squirrel esta presente no WEMOD_BIN_DIR.
    Cria app-{version}/, Update.exe, RELEASES e packages/ se faltando.
    Migra estrutura plana antiga para o layout Squirrel."""
    if not os.path.isdir(WEMOD_BIN_DIR):
        return

    # ── Migracao: estrutura plana → app-{version}/ ────────────────
    # Se WeMod.exe estiver na raiz mas nao em app-*/, cria app-{version}/
    old_exe = os.path.join(WEMOD_BIN_DIR, 'WeMod.exe')
    if os.path.isfile(old_exe) and not _get_wemod_app_dir():
        _log('Migrando estrutura plana para Squirrel (app-{version}/)...')
        version = '11.6.0'  # fallback se nao conseguir detectar
        app_dir = os.path.join(WEMOD_BIN_DIR, f'app-{version}')
        os.makedirs(app_dir, exist_ok=True)
        # Move tudo da raiz para app-{version}/, exceto Update.exe, squirrel.exe, packages/
        keep_in_root = {'Update.exe', 'squirrel.exe', 'packages', 'version.dll'}
        for item in os.listdir(WEMOD_BIN_DIR):
            if item in keep_in_root or item.startswith('app-'):
                continue
            src = os.path.join(WEMOD_BIN_DIR, item)
            dst = os.path.join(app_dir, item)
            if src != dst:
                shutil.move(src, dst)
        _log(f'Arquivos migrados para {app_dir}')

    # Update.exe a partir de squirrel.exe
    squirrel_exe = os.path.join(WEMOD_BIN_DIR, 'squirrel.exe')
    update_exe = os.path.join(WEMOD_BIN_DIR, 'Update.exe')
    if not os.path.isfile(update_exe) and os.path.isfile(squirrel_exe):
        shutil.copy2(squirrel_exe, update_exe)
        _log('Update.exe criado a partir de squirrel.exe')

    # version.dll na raiz (Electron delay-load hook)
    app_dir = _get_wemod_app_dir()
    if app_dir:
        app_version_dll = os.path.join(app_dir, 'version.dll')
        root_version_dll = os.path.join(WEMOD_BIN_DIR, 'version.dll')
        if os.path.isfile(app_version_dll) and not os.path.isfile(root_version_dll):
            shutil.copy2(app_version_dll, root_version_dll)
        elif not os.path.isfile(root_version_dll):
            _ensure_version_dll()

    # packages/RELEASES se faltando
    if not app_dir:
        return
    version = os.path.basename(app_dir).replace('app-', '')
    packages_dir = os.path.join(WEMOD_BIN_DIR, 'packages')
    os.makedirs(packages_dir, exist_ok=True)

    nupkg_src = os.path.join(app_dir, f'WeMod-{version}-full.nupkg')
    nupkg_dst = os.path.join(packages_dir, f'WeMod-{version}-full.nupkg')
    if not os.path.isfile(nupkg_dst) and os.path.isfile(nupkg_src):
        shutil.move(nupkg_src, nupkg_dst)

    releases = os.path.join(packages_dir, 'RELEASES')
    if not os.path.isfile(releases) and os.path.isfile(nupkg_dst):
        sha1 = hashlib.sha1(open(nupkg_dst, 'rb').read()).hexdigest()
        sz = os.path.getsize(nupkg_dst)
        with open(releases, 'w') as f:
            f.write(f'WeMod-{version}-full.nupkg {sha1} {sz}\n')
        _log(f'RELEASES criado em {packages_dir}')


def is_wemod_downloaded() -> bool:
    """Verifica se o WeMod ja foi baixado e extraido."""
    app_dir = _get_wemod_app_dir()
    return app_dir is not None and os.path.isfile(os.path.join(app_dir, 'WeMod.exe'))


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


def _get_proton_script_version(pdir: str) -> Optional[str]:
    """Le CURRENT_PREFIX_VERSION do script 'proton' do Proton."""
    ps = os.path.join(pdir, 'proton')
    if not os.path.isfile(ps):
        return None
    try:
        for line in open(ps, 'r', errors='replace'):
            if line.startswith('CURRENT_PREFIX_VERSION='):
                m = re.match(r'^CURRENT_PREFIX_VERSION=[\"\']?(.+?)[\"\']?\s*$', line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None


def _proton_version_score(d: str, ver: str, base_dir: str) -> int:
    """Quao bem um diretorio Proton corresponde a uma versao.

    Retorna score:
      100 = nome do diretorio contem a versao (match exato)
       95 = CURRENT_PREFIX_VERSION do script 'proton' == ver (exato)
       90 = version file interno do Proton contem a versao
       80 = prefixo numerico (ex.: '11.0' de '11.0-100') aparece no version file
        0 = sem correspondencia
    """
    if ver in d:
        return 100
    # CURRENT_PREFIX_VERSION no proprio script proton
    pv = _get_proton_script_version(os.path.join(base_dir, d))
    if pv is not None and pv == ver:
        return 95
    vf = os.path.join(base_dir, d, 'version')
    if os.path.isfile(vf):
        try:
            content = Path(vf).read_text().strip()
        except OSError:
            return 0
        if ver in content:
            return 90
        # Tenta prefixo: "11.0-100" -> extrai "11.0" e busca no version file
        if '-' in ver:
            prefix = ver.split('-')[0]
            if prefix and prefix in content:
                return 80
    return 0


def _scan_proton_dirs(ver: str, min_score: int = 80) -> list[tuple[str, str, int]]:
    """Varre todos os Protons do Steam e retorna [(path_completo, nome_dir, score), ...]
    com score >= min_score, ordenados por score descendente."""
    steam_roots = [
        os.path.expanduser('~/.local/share/Steam'),
        os.path.expanduser('~/.steam/steam'),
        os.path.expanduser('~/.steam/root'),
    ]
    seen = set()
    results = []
    for root in steam_roots:
        for base in ('compatibilitytools.d', 'steamapps/common'):
            base_dir = os.path.join(root, base)
            if not os.path.isdir(base_dir):
                continue
            for d in sorted(os.listdir(base_dir), reverse=True):
                if 'proton' not in d.lower():
                    continue
                real = os.path.realpath(os.path.join(base_dir, d))
                if real in seen:
                    continue
                seen.add(real)
                score = _proton_version_score(d, ver, base_dir)
                if score >= min_score:
                    is_official = 0 if base == 'compatibilitytools.d' else 1
                    results.append((os.path.join(base_dir, d), d, score, is_official))
    results.sort(key=lambda x: (-x[2], -x[3], -len(x[1])))
    return [(p, n, s) for p, n, s, _ in results]


def _find_proton_in_steam(ver: str) -> Optional[str]:
    """Procura wine interno de um Proton do Steam."""
    for proton_dir, d, score in _scan_proton_dirs(ver):
        wine = _find_wine_in_dir(proton_dir)
        if wine:
            return wine
    return None


def _find_any_proton_wine() -> Optional[str]:
    """Varre todos os diretorios Proton (compatibilitytools.d e steamapps/common)
    e retorna o primeiro wine encontrado, independente da versao."""
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
    # ou ~/PortProton/data/prefixes/ (instalacao nativa)
    pp_base = os.path.expanduser(
        '~/.var/app/ru.linux_gaming.PortProton/data'
    )
    pp_native_base = os.path.expanduser('~/PortProton/data')
    if (pp_base in wineprefix and os.path.isdir(pp_base)) or \
       (pp_native_base in wineprefix and os.path.isdir(pp_native_base)):
        # determina qual base usar
        base = pp_base if os.path.isdir(pp_base) else pp_native_base

        # 1. Tenta ler .wine_ver dentro do prefixo (contém "GE-PROTON11-1")
        wine_ver_file = os.path.join(wineprefix, '.wine_ver')
        if os.path.isfile(wine_ver_file):
            ver = Path(wine_ver_file).read_text().strip()
            # Procura em dist/<ver>/files/bin/wine
            for d in (os.path.join(base, 'dist', ver),
                      os.path.join(base, ver)):
                wine = _find_wine_in_dir(d)
                if wine:
                    return wine

        # 2. Fallback: varre diretorios dentro de dist/
        dist_dir = os.path.join(base, 'dist')
        if os.path.isdir(dist_dir):
            for item in os.listdir(dist_dir):
                wine = _find_wine_in_dir(os.path.join(dist_dir, item))
                if wine:
                    return wine

        # 3. Fallback: varre a raiz do PortProton
        for item in os.listdir(base):
            wine = _find_wine_in_dir(os.path.join(base, item))
            if wine:
                return wine

    # Hydra Launcher: prefixo dentro ~/.config/hydralauncher/wine-prefixes/
    if _is_hydra_prefix(wineprefix):
        hydra_wine = _find_hydra_wine(wineprefix)
        if hydra_wine:
            _log(f'Wine do Hydra encontrado: {hydra_wine}')
            return hydra_wine
        _log('Wine do Hydra nao encontrado, tentando fallback...')

    # fallback: varre todos os Protons disponiveis (versao independente)
    _log('Proton nao encontrado pelo version file, varrendo todos os Protons...')
    wine = _find_any_proton_wine()
    if wine:
        _log(f'Wine encontrado via fallback: {wine}')
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
        errors='replace', timeout=timeout,
    )





def _is_portproton_prefix(wineprefix: str) -> bool:
    pp_base = os.path.expanduser(
        '~/.var/app/ru.linux_gaming.PortProton/data'
    )
    pp_native_base = os.path.expanduser('~/PortProton/data')
    return (pp_base in wineprefix and os.path.isdir(pp_base)) or \
           (pp_native_base in wineprefix and os.path.isdir(pp_native_base))


def _is_hydra_prefix(wineprefix: str) -> bool:
    hydra_base = os.path.expanduser('~/.config/hydralauncher/wine-prefixes')
    return wineprefix.startswith(hydra_base) and os.path.isdir(hydra_base)


def _find_hydra_wine(wineprefix: str) -> Optional[str]:
    version_file = os.path.join(wineprefix, 'version')
    if not os.path.isfile(version_file):
        return None
    ver = Path(version_file).read_text().strip()
    proton_cache = os.path.expanduser('~/.cache/protontricks/proton')
    if not os.path.isdir(proton_cache):
        return None
    for d in sorted(os.listdir(proton_cache), reverse=True):
        if ver.lower() in d.lower():
            wine = os.path.join(proton_cache, d, 'bin', 'wine')
            if os.path.isfile(wine):
                return wine
    return None


def _find_vkd3d_dirs() -> list:
    """Procura diretorios lib/vkd3d em instalacoes do Proton."""
    dirs = []
    candidates = [
        os.path.expanduser('~/.var/app/ru.linux_gaming.PortProton/data/dist'),
        os.path.expanduser('~/PortProton/data/dist'),
        os.path.expanduser('~/.local/share/Steam/compatibilitytools.d'),
        os.path.expanduser('~/.config/heroic/tools/proton'),
        os.path.expanduser('~/.local/share/Steam/steamapps/common'),
    ]
    seen = set()
    for base in candidates:
        if not os.path.isdir(base):
            continue
        for entry in os.listdir(base):
            if not entry.lower().startswith('proton') and 'proton' not in entry.lower():
                continue
            for sub in ('files',):
                d = os.path.join(base, entry, sub, 'lib', 'vkd3d')
                real = os.path.realpath(d)
                if os.path.isdir(os.path.join(d, 'x86_64-windows')) and real not in seen:
                    seen.add(real)
                    dirs.append(d)
    return dirs


def _ensure_vkd3d_utils(wineprefix: str, log_callback=None) -> None:
    """Copia libvkd3d-utils-1.dll para o prefixo caso esteja faltando."""
    if log_callback is None:
        log_callback = _log

    targets = [
        ('system32', 'libvkd3d-utils-1.dll'),
        ('syswow64', 'libvkd3d-utils-1.dll'),
    ]
    if all(os.path.isfile(os.path.join(wineprefix, 'drive_c', 'windows', *t)) for t in targets):
        log_callback('libvkd3d-utils-1.dll ja presente')
        return

    vkd3d_dirs = _find_vkd3d_dirs()
    if not vkd3d_dirs:
        log_callback('ATENCAO: libvkd3d-utils-1.dll nao encontrada em nenhum Proton')
        log_callback('WeMod pode nao iniciar corretamente')
        return

    src_dir = vkd3d_dirs[0]
    log_callback(f'Copiando libvkd3d-utils-1.dll de {src_dir}...')

    for arch, win_arch in [('x86_64-windows', 'system32'), ('i386-windows', 'syswow64')]:
        src = os.path.join(src_dir, arch, 'libvkd3d-utils-1.dll')
        dst = os.path.join(wineprefix, 'drive_c', 'windows', win_arch, 'libvkd3d-utils-1.dll')
        if os.path.isfile(src) and not os.path.isfile(dst):
            try:
                shutil.copy2(src, dst)
                log_callback(f'  {win_arch}/libvkd3d-utils-1.dll copiado')
            except Exception as e:
                log_callback(f'  ERRO ao copiar {win_arch}: {e}')


def _install_dotnet48_direct(wine_bin: str, wineprefix: str,
                              log_callback=None) -> bool:
    """Instala .NET Framework 4.8 + faz todo o setup que o winetricks faria:
    registry keys, DLL overrides, OnlyUseLatestCLR, etc.
    Usa native fusion (nao builtin) e limpa registros que fariam
    o installer do 4.8 pular."""
    import hashlib
    if log_callback is None:
        log_callback = _log

    cache_dir = os.path.join(WEMOD_DATA_DIR, 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    installer = os.path.join(cache_dir, 'ndp48-x86-x64-allos-enu.exe')
    expected_sha = '95889d6de3f2070c07790ad6cf2000d33d9a1bdfc6a381725ab82ab1c314fd53'

    # Download / verify with curl (mais confiavel que urllib para 142MB)
    url = ('https://download.visualstudio.microsoft.com/download/pr/7afca223-55d2-470a-8edc-6a1739ae3252/'
           'abd170b4b0ec15ad0222a809b761a036/ndp48-x86-x64-allos-enu.exe')
    for attempt in range(3):
        if os.path.isfile(installer):
            actual = hashlib.sha256(open(installer, 'rb').read()).hexdigest()
            if actual == expected_sha:
                break
            log_callback(f'Cached installer corrupto (tentativa {attempt+1}), baixando novamente...')
            os.remove(installer)
        if attempt > 0 or not os.path.isfile(installer):
            log_callback(f'Baixando .NET Framework 4.8 installer (142 MB)...')
            r = subprocess.run(
                ['curl', '-L', '-o', installer, '--connect-timeout', '30',
                 '--max-time', '600', '--retry', '2', '-sS', url],
                capture_output=True, text=True, timeout=660,
            )
            if r.returncode != 0:
                log_callback(f'curl: {r.stderr.strip() or r.stdout.strip()}')
                if os.path.isfile(installer):
                    os.remove(installer)
                if attempt == 2:
                    return False
                continue
    else:
        log_callback('Falha ao baixar .NET 4.8 installer apos 3 tentativas')
        return False
    log_callback('Download OK')

    # ── pre-install ──────────────────────────────────────────────
    # Remove registry keys that trick the 4.8 installer
    # (if .NET 4.0 was previously installed, Version=4.0.30319
    #  makes the 4.8 installer think nothing to do)
    log_callback('Limpando registros existentes do .NET v4...')
    for key in [
        r'HKLM\Software\Microsoft\NET Framework Setup\NDP\v4',
        r'HKLM\Software\Wow6432Node\Microsoft\NET Framework Setup\NDP\v4',
    ]:
        _run_wine(wine_bin, wineprefix, ['reg', 'delete', key, '/f'])

    # Set winver win7 for .NET 4.8 installer compatibility
    _run_wine(wine_bin, wineprefix, ['winecfg', '-v', 'win7'])

    # Run installer SEM overrides de fusion/mscoree — num prefixo limpo
    # as DLLs nativas ainda nao existem, entao fusion=native quebra.
    # O proprio installer cuida de extrair as DLLs; o override permanente
    # via registry vem no pos-install abaixo.
    # Se falhar com codigo 67 (wow64 incompativel), tenta fallback com
    # system wine (10.0, sem wow64 mode).
    log_callback('Instalando .NET Framework 4.8 (pode levar 20-40 min)...')
    installer_wines = [wine_bin]
    # Fallbacks para wow64 mode (Proton 11+)
    for cand in ['/usr/bin/wine64', '/usr/bin/wine']:
        if os.path.isfile(cand) and cand not in installer_wines:
            installer_wines.append(cand)

    for attempt, iwine in enumerate(installer_wines):
        if attempt > 0:
            ver = subprocess.run([iwine, '--version'],
                capture_output=True, text=True, timeout=10)
            log_callback(f'Tentativa {attempt+1}: {iwine} ({ver.stdout.strip()})')

        env = os.environ.copy()
        env['WINEPREFIX'] = wineprefix
        env['WINEDLLOVERRIDES'] = 'winemenubuilder.exe=d'
        env['PATH'] = os.path.dirname(iwine) + ':' + env.get('PATH', '')

        result = subprocess.run(
            [iwine, installer, '/sfxlang:1027', '/q', '/norestart'],
            env=env, capture_output=True, text=True, timeout=3600,
        )

        if result.returncode == 0:
            break
        log_callback(f'  Falhou (codigo {result.returncode})')
        if result.stderr:
            for line in result.stderr.strip().splitlines()[-5:]:
                log_callback(f'  stderr: {line}')
    else:
        log_callback('Todas as tentativas falharam')
        return False

    # ── post-install: registry keys que o winetricks faria ─────
    log_callback('Registrando .NET Framework 4.8 no prefixo...')

    # Override mscoree para native (permanente, via Wine registry)
    # Equivalente a: w_override_dlls native mscoree
    for overrides_key in [
        r'HKCU\Software\Wine\DllOverrides',
        r'HKLM\Software\Microsoft\Windows NT\CurrentVersion\Windows\DllOverrides',
    ]:
        _run_wine(wine_bin, wineprefix, [
            'reg', 'add', overrides_key,
            '/v', 'mscoree', '/t', 'REG_SZ', '/d', 'native', '/f'])

    # Escreve .NET Framework Setup keys (apps conferem isso)
    # Equivalente ao que dotnet40 faz, mas com version 4.8
    for base_key in [
        r'HKLM\Software\Microsoft\NET Framework Setup\NDP\v4\Full',
        r'HKLM\Software\Wow6432Node\Microsoft\NET Framework Setup\NDP\v4\Full',
    ]:
        _run_wine(wine_bin, wineprefix, [
            'reg', 'add', base_key,
            '/v', 'Install', '/t', 'REG_DWORD', '/d', '0001', '/f'])
        _run_wine(wine_bin, wineprefix, [
            'reg', 'add', base_key,
            '/v', 'Version', '/t', 'REG_SZ', '/d', '4.8.04084', '/f'])

    # OnlyUseLatestCLR (evita popup no Wine)
    for clr_key in [
        r'HKLM\Software\Microsoft\.NETFramework',
        r'HKLM\Software\Wow6432Node\.NETFramework',
    ]:
        _run_wine(wine_bin, wineprefix, [
            'reg', 'add', clr_key,
            '/v', 'OnlyUseLatestCLR', '/t', 'REG_DWORD', '/d', '0001', '/f'])

    # ── verify ─────────────────────────────────────────────────
    r = _run_wine(wine_bin, wineprefix, ['reg', 'query',
        r'HKLM\Software\Microsoft\NET Framework Setup\NDP\v4\Full',
        '/v', 'Version'])
    if r.returncode == 0:
        m = re.search(r'Version\s+REG_SZ\s+([\d.]+)', r.stdout)
        if m:
            ver = m.group(1)
            log_callback(f'.NET Framework {ver} registrado com sucesso')
            return True

    log_callback('ATENCAO: .NET 4.8 nao encontrado no registry apos instalacao')
    return False


def _is_dotnet48_installed(wineprefix: str, wine_bin: str) -> bool:
    """Verifica se .NET Framework 4.8+ ja esta instalado no prefixo.
    Checa registry + DLLs reais em v4.0.30319."""
    r = subprocess.run(
        [wine_bin, 'reg', 'query',
         r'HKLM\Software\Microsoft\NET Framework Setup\NDP\v4\Full',
         '/v', 'Version'],
        env={'WINEPREFIX': wineprefix},
        capture_output=True, text=True, errors='replace', timeout=30,
    )
    if r.returncode != 0:
        return False
    m = re.search(r'Version\s+REG_SZ\s+4\.(?:[8-9]|\d{2})', r.stdout)
    if not m:
        return False
    # Verifica se as DLLs realmente existem
    for arch in ('Framework', 'Framework64'):
        d = os.path.join(wineprefix, 'drive_c', 'windows',
                         'Microsoft.NET', arch, 'v4.0.30319')
        if os.path.isdir(d):
            dlls = [f for f in os.listdir(d)
                    if f.lower().endswith('.dll')]
            if len(dlls) > 50:
                return True
    return False


def _verify_installation(wineprefix: str, wine_bin: str,
                         log_callback=None) -> dict:
    """Verifica se todos os componentes necessarios estao no lugar.
    Retorna dict com status de cada item."""
    if log_callback is None:
        log_callback = _log

    results = {}

    # 1. .NET Framework 4.8 - registry
    r = _run_wine(wine_bin, wineprefix, ['reg', 'query',
        r'HKLM\Software\Microsoft\NET Framework Setup\NDP\v4\Full',
        '/v', 'Version'])
    if r.returncode == 0:
        m = re.search(r'Version\s+REG_SZ\s+([\d.]+)', r.stdout)
        if m:
            results['dotnet_registry'] = ('ok', f'.NET {m.group(1)} no registry')
        else:
            results['dotnet_registry'] = ('warn', 'registry key existe mas sem Version')
    else:
        results['dotnet_registry'] = ('fail', 'chave NDP\\v4\\Full nao encontrada')

    # 2. .NET Framework 4.8 - DLLs reais no prefixo
    winuser = _get_windows_user(wineprefix)
    dotnet_dirs = [
        os.path.join(wineprefix, 'drive_c', 'windows',
                     'Microsoft.NET', 'Framework', 'v4.0.30319'),
        os.path.join(wineprefix, 'drive_c', 'windows',
                     'Microsoft.NET', 'Framework64', 'v4.0.30319'),
    ]
    dotnet_files_ok = 0
    dotnet_files_total = 0
    for d in dotnet_dirs:
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.lower().endswith('.dll'):
                    dotnet_files_total += 1
                    fp = os.path.join(d, f)
                    if os.path.isfile(fp) and os.path.getsize(fp) > 0:
                        dotnet_files_ok += 1
    if dotnet_files_total >= 50 and dotnet_files_ok >= dotnet_files_total * 0.8:
        results['dotnet_dlls'] = ('ok',
            f'{dotnet_files_ok}/{dotnet_files_total} DLLs .NET validas')
    elif dotnet_files_total > 0:
        results['dotnet_dlls'] = ('warn',
            f'poucas DLLs .NET: {dotnet_files_ok}/{dotnet_files_total}')
    else:
        results['dotnet_dlls'] = ('fail',
            'nenhuma DLL .NET encontrada em v4.0.30319')

    # 3. mscoree override
    r = _run_wine(wine_bin, wineprefix, ['reg', 'query',
        r'HKCU\Software\Wine\DllOverrides', '/v', 'mscoree'])
    if r.returncode == 0 and 'native' in r.stdout.lower():
        results['mscoree'] = ('ok', 'mscoree=native ativo')
    else:
        results['mscoree'] = ('warn', 'mscoree override nao encontrado')

    # 4. WeMod.exe
    app_dir = _get_wemod_app_dir()
    wemod_exe_path = os.path.join(app_dir, 'WeMod.exe') if app_dir else WEMOD_EXE_PATH
    if os.path.isfile(wemod_exe_path):
        sz = os.path.getsize(wemod_exe_path)
        results['wemod_exe'] = ('ok', f'WeMod.exe ({sz//1024//1024}MB)')
    else:
        results['wemod_exe'] = ('fail', 'WeMod.exe nao encontrado')

    # 5. version.dll (opcional — pode ser omitido)
    version_dll = os.path.join(WEMOD_BIN_DIR, 'version.dll')
    if os.path.isfile(version_dll):
        results['version_dll'] = ('ok', 'version.dll presente')
    else:
        results['version_dll'] = ('warn', 'version.dll ausente — opcional')

    # 6. Login symlink
    WeModExternal = os.path.join(
        wineprefix, f'drive_c/users/{winuser}/AppData/Roaming/WeMod')
    if os.path.islink(WeModExternal) and os.path.isdir(WeModExternal):
        results['login_symlink'] = ('ok', 'symlink login OK')
    elif os.path.isdir(WeModExternal):
        results['login_symlink'] = ('warn', 'pasta login existe mas sem symlink')
    else:
        results['login_symlink'] = ('warn',
            'pasta login nao criada (criada no primeiro launch)')

    return results


def install_wemod_prefix(wineprefix: str,
                        log_callback=None,
                        progress_callback=None) -> bool:
    """Instala WeMod + .NET 4.8 + dependencias no prefixo.
    log_callback: funcao opcional chamada para cada linha de log em tempo real.
    progress_callback: funcao opcional(stage_name: str, percent: int).
    Retorna True se sucesso."""
    if log_callback is None:
        log_callback = _log
    if progress_callback is None:
        progress_callback = lambda s, p: None

    marker = os.path.join(wineprefix, WEMOD_MARKER)
    if os.path.isfile(marker):
        os.remove(marker)

    is_portproton = _is_portproton_prefix(wineprefix)
    progress_callback('Preparando…', 0)
    log_callback(f'Instalando WeMod em {wineprefix}...')
    wine_bin = _get_wine_binary(wineprefix)
    log_callback(f'Wine: {wine_bin}')

    if is_portproton:
        progress_callback('Configurando VKD3D…', 20)
        log_callback('Prefixo PortProton detectado — pulando winetricks')
        _ensure_vkd3d_utils(wineprefix, log_callback)
    else:
        # winetricks apenas para prefixos que nao sao PortProton
        winetricks_sh = os.path.join(WEMOD_DATA_DIR, 'winetricks')
        if not os.path.isfile(winetricks_sh):
            progress_callback('Baixando winetricks…', 5)
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

        progress_callback('winetricks: sdl, cjkfonts, vkd3d, dxvk2030…', 15)
        log_callback('winetricks: sdl, cjkfonts, vkd3d, dxvk2030...')
        subprocess.run(
            [winetricks_sh, 'sdl', 'cjkfonts', 'vkd3d', 'dxvk2030'],
            env=wt_env,
            timeout=600,
        )

        # Instala .NET 4.8 apenas se nao estiver presente
        if _is_dotnet48_installed(wineprefix, wine_bin):
            progress_callback('.NET 4.8 já instalado', 50)
            log_callback('.NET Framework 4.8 ja instalado, pulando')
        else:
            progress_callback('Instalando .NET 4.8 (pode levar 20-40 min)…', 30)
            log_callback('Instalando .NET Framework 4.8 (pode levar 20-40 min)...')
            dotnet_ok = _install_dotnet48_direct(wine_bin, wineprefix, log_callback)
            if dotnet_ok:
                progress_callback('.NET 4.8 instalado', 55)
                log_callback('.NET 4.8 instalado com sucesso')
            else:
                log_callback('ATENCAO: .NET 4.8 pode nao ter instalado corretamente')
                log_callback('WeMod pode reclamar sobre .NET')

    progress_callback('winecfg -v win10…', 65)
    log_callback('winecfg -v win10...')
    _run_wine(wine_bin, wineprefix, ['winecfg', '-v', 'win10'])

    # ── verificacao pos-instalacao ─────────────────────────────────
    progress_callback('Criando symlinks…', 75)
    log_callback('')
    log_callback('═' * 40)
    log_callback('VERIFICANDO INSTALACAO...')

    # Cria symlink C:\WeMod\ -> wemod_bin/app-{version}/
    c_wemod = os.path.join(wineprefix, 'drive_c', 'WeMod')
    app_dir = _get_wemod_app_dir()
    if app_dir and not os.path.islink(c_wemod):
        if os.path.isdir(c_wemod) or os.path.isfile(c_wemod):
            shutil.rmtree(c_wemod, ignore_errors=True)
            try:
                os.remove(c_wemod)
            except OSError:
                pass
        os.symlink(app_dir, c_wemod)
        log_callback(f'Symlink C:\\WeMod -> {app_dir}')

    # Cria symlink de login e ajusta posicao da janela
    sync_wemod_login(wineprefix)
    _fix_wemod_window_position(wineprefix)

    progress_callback('Verificando instalação…', 85)
    checks = _verify_installation(wineprefix, wine_bin, log_callback)
    errors = 0
    warnings = 0
    for item, (status, msg) in sorted(checks.items()):
        icon = {'ok': ' ✓', 'warn': ' ⚠', 'fail': ' ✗'}.get(status, ' ?')
        log_callback(f'  {icon} {item}: {msg}')
        if status == 'fail':
            errors += 1
        elif status == 'warn':
            warnings += 1
    log_callback('═' * 40)
    if errors:
        log_callback(f'RESULTADO: {errors} erro(s), {warnings} aviso(s) — instalacao INCOMPLETA')
    elif warnings:
        log_callback(f'RESULTADO: {warnings} aviso(s) — instalacao OK com ressalvas')
    else:
        log_callback('RESULTADO: todos os componentes OK')
    log_callback('')

    progress_callback('Finalizando…', 95)
    with open(marker, 'w') as f:
        f.write('1')
    log_callback('WeMod instalado com sucesso!')
    progress_callback('Concluído', 100)
    return errors == 0


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


def sync_wemod_login(wineprefix: str):
    """Compartilha dados de login do WeMod entre todos os prefixos via symlink."""
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
    """Retorna o caminho do script 'proton' associado ao prefixo."""
    version_file = os.path.join(os.path.dirname(wineprefix), 'version')
    if not os.path.isfile(version_file):
        return None
    ver = Path(version_file).read_text().strip()
    for proton_dir, d, score in _scan_proton_dirs(ver):
        cand = os.path.join(proton_dir, 'proton')
        if os.path.isfile(cand):
            return cand
    return None


def _fix_wemod_window_position(wineprefix: str):
    """Ajusta init.json do WeMod para x=0.

    No Electron sob Wine/XWayland, o WeMod soma o offset Xinerama do monitor
    primario ao carregar a posicao. Com x=0 no config, o Electron coloca a
    janela em 0 + offset (ex.: 1440), que e o inicio do monitor principal."""
    win_user = _get_windows_user(wineprefix)
    init_path = os.path.join(
        wineprefix, f'drive_c/users/{win_user}/AppData/Roaming/WeMod/App/init.json'
    )
    if not os.path.isfile(init_path):
        return
    try:
        import json
        with open(init_path) as f:
            data = json.load(f)
        bounds = data.get('windows', {}).get('app', {}).get('bounds', {})
        if bounds.get('x', 0) == 0:
            return  # ja corrigido
        bounds['x'] = 0
        bounds['y'] = 0
        with open(init_path, 'w') as f:
            json.dump(data, f, separators=(',', ':'))
        _log('init.json: x corrigido para 0')
    except Exception as e:
        _log(f'init.json: erro ao corrigir x: {e}')


def _get_wemod_window_id(wineprefix: str, timeout: float = 10.0) -> Optional[int]:
    """Aguarda a janela WeMod aparecer e retorna o X11 window ID."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            import subprocess
            out = subprocess.run(
                ['xdotool', 'search', '--name', 'WeMod'],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0 and out.stdout.strip():
                # Pega o ultimo wid (janela principal, nao tooltips)
                wids = out.stdout.strip().splitlines()
                # A janela principal costuma ter geometry > 1x1
                for wid in reversed(wids):
                    geo = subprocess.run(
                        ['xdotool', 'getwindowgeometry', wid],
                        capture_output=True, text=True,
                    )
                    if 'Geometry: 1x1' not in geo.stdout:
                        return int(wid)
                return int(wids[-1])
        except (OSError, subprocess.TimeoutExpired):
            pass
        time.sleep(0.5)
    return None


def _restore_wemod_window(wineprefix: str):
    """Restaura a janela WeMod se estiver minimizada (Iconic/HIDDEN).

    Electron sob Wine/XWayland frequentemente inicia com WM_STATE=Iconic."""
    wid = _get_wemod_window_id(wineprefix, timeout=8.0)
    if wid is None:
        _log('Janela WeMod nao encontrada para restaurar')
        return
    try:
        import subprocess
        # Verifica se esta iconic (minimizada)
        out = subprocess.run(
            ['xprop', '-id', str(wid), 'WM_STATE'],
            capture_output=True, text=True, timeout=3,
        )
        if 'Iconic' in out.stdout:
            subprocess.run(['xdotool', 'windowmap', str(wid)], timeout=3)
            subprocess.run(['xdotool', 'windowactivate', str(wid)], timeout=3)
            _log(f'Janela WeMod (WID {wid}) restaurada de Iconic')
        else:
            _log(f'Janela WeMod (WID {wid}) ja em estado Normal')
    except Exception as e:
        _log(f'Erro ao restaurar janela WeMod: {e}')


def _setup_proton_env(env: dict, wine_bin: str):
    """Configura LD_LIBRARY_PATH e WINEDLLPATH para o wine interno do Proton."""
    wine_dir = os.path.dirname(os.path.realpath(wine_bin))
    # wine_dir e algo como .../Proton-X/files/bin/
    base = os.path.dirname(wine_dir)  # .../Proton-X/files/
    parent = os.path.dirname(base)    # .../Proton-X/
    # Tenta montar os paths a partir da estrutura conhecida do Proton
    for candidate_base in (base, parent):
        lib32 = os.path.join(candidate_base, 'lib', 'wine')
        lib64 = os.path.join(candidate_base, 'lib64', 'wine')
        paths_32 = os.path.join(candidate_base, 'lib')
        paths_64 = os.path.join(candidate_base, 'lib64')

        dllpath_parts = []
        if os.path.isdir(lib64):
            dllpath_parts.append(lib64)
        if os.path.isdir(lib32):
            dllpath_parts.append(lib32)
        if dllpath_parts:
            env['WINEDLLPATH'] = ':'.join(dllpath_parts)

        ldpath_parts = []
        if os.path.isdir(paths_64):
            ldpath_parts.append(paths_64)
        if os.path.isdir(paths_32):
            ldpath_parts.append(paths_32)
        existing = env.get('LD_LIBRARY_PATH', '')
        if ldpath_parts:
            env['LD_LIBRARY_PATH'] = ':'.join(ldpath_parts) + (':' + existing if existing else '')
            break  # achou a estrutura, para


def launch_wemod(wineprefix: str) -> Optional[int]:
    """Inicia WeMod no prefixo com wine direto (nunca Proton wrapper).

    Usar 'proton run' colocaria o WeMod (Electron) dentro do Steam Linux
    Runtime container, causando conflito com o container do jogo."""
    marker = os.path.join(wineprefix, WEMOD_MARKER)
    if not os.path.isfile(marker):
        _log('WeMod nao instalado, instale primeiro')
        return None
    if is_wemod_running(wineprefix):
        _log('WeMod ja esta rodando')
        return _get_wemod_pid(wineprefix)

    sync_wemod_login(wineprefix)

    app_dir = _get_wemod_app_dir()
    if not app_dir:
        _log('Diretorio app-{version}/ do WeMod nao encontrado')
        return None

    # Garante symlink C:\WeMod\ -> wemod_bin/ para que assemblies .NET
    # (WeModAuxiliaryService.exe) sejam carregados da unidade C:,
    # onde o CLR hosting resolve mscoree.dll corretamente.
    c_drive = os.path.join(wineprefix, 'drive_c')
    c_wemod = os.path.join(c_drive, 'WeMod')
    if not os.path.islink(c_wemod):
        if os.path.isdir(c_wemod):
            shutil.rmtree(c_wemod, ignore_errors=True)
        os.symlink(app_dir, c_wemod)
        _log(f'Symlink criado: {c_wemod} -> {app_dir}')

    wemod_exe = os.path.join(c_wemod, 'WeMod.exe')
    if not os.path.isfile(wemod_exe):
        _log(f'WeMod.exe nao encontrado em {wemod_exe}')
        return None
    _ensure_version_dll()

    flags = [
        '--no-sandbox',
        '--disable-gpu',
        '--in-process-gpu',
        '--use-gl=swiftshader',
        '--disable-gpu-compositing',
        '--disable-accelerated-2d-canvas',
        '--disable-crash-reporter',
        '--no-zygote',
        '--force-device-scale-factor=1',
        '--disable-features=Vulkan,UseSkiaRenderer',
    ]

    _fix_wemod_window_position(wineprefix)

    logfile = f'/tmp/wemod_{os.path.basename(wineprefix)}.log'
    env = os.environ.copy()
    env['WINEPREFIX'] = wineprefix
    env['WINEDLLOVERRIDES'] = 'winedbg.exe=d;winemenubuilder.exe=d'
    env['DISABLE_CRASH_HANDLER'] = '1'
    env['GDK_BACKEND'] = 'x11'
    wine_bin = _get_wine_binary(wineprefix)
    _setup_proton_env(env, wine_bin)
    env['PATH'] = os.path.dirname(wine_bin) + ':' + env.get('PATH', '')
    cmd = [wine_bin, wemod_exe] + flags
    launch_desc = f'wine direto ({os.path.basename(wine_bin)})'

    proc = subprocess.Popen(
        cmd, env=env,
        stdout=open(logfile, 'w'),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _log(f'WeMod iniciado via {launch_desc} (PID {proc.pid}, log: {logfile})')
    import time
    time.sleep(3)
    we_pid = _get_wemod_pid(wineprefix)
    if we_pid:
        _log(f'WeMod.exe em execucao (PID {we_pid})')
    else:
        _log('ATENCAO: WeMod.exe nao detectado apos lancamento')

    _restore_wemod_window(wineprefix)

    return we_pid or proc.pid


def _get_wemod_children_pids(ppid: int) -> list[int]:
    """Retorna lista de PIDs filhos diretos de ppid."""
    children = []
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        try:
            status = Path(f'/proc/{entry}/status').read_text()
        except (OSError, PermissionError):
            continue
        m = re.search(r'^PPid:\s*(\d+)', status, re.M)
        if m and int(m.group(1)) == ppid:
            children.append(int(entry))
    return children


def _kill_process_tree(ppid: int):
    """Mata ppid e todos os filhos."""

    import time
    pids_to_kill = [ppid]
    # coleta recursivamente a árvore de processos
    queue = [ppid]
    while queue:
        parent = queue.pop()
        children = _get_wemod_children_pids(parent)
        pids_to_kill.extend(children)
        queue.extend(children)

    for pid in sorted(pids_to_kill, reverse=True):
        try:
            os.kill(pid, 9)
            _log(f'PID {pid} finalizado (SIGKILL)')
        except ProcessLookupError:
            pass
        except PermissionError:
            _log(f'Sem permissao para finalizar PID {pid}')
        time.sleep(0.01)


def stop_wemod(wineprefix: str):
    """Para o WeMod rodando no prefixo.
    Mata apenas o WeMod.exe e seus filhos — NAO mata wineserver
    para evitar derrubar outros processos (ex.: jogo) no mesmo prefixo."""
    pid = _get_wemod_pid(wineprefix)
    if pid:
        _log(f'Finalizando arvore WeMod a partir do PID {pid}...')
        _kill_process_tree(pid)
    else:
        _log('WeMod.exe nao encontrado rodando neste prefixo')

    # Varre /proc por qualquer outro processo .exe que esteja no prefixo
    # e que pareça ser do WeMod (evita processos órfãos)
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
        try:
            env_raw = Path(f'/proc/{entry}/environ').read_bytes().decode('utf-8', errors='replace')
        except (OSError, PermissionError):
            continue
        # Match exato: WINEPREFIX= seguido do path
        if f'WINEPREFIX={wineprefix}\0' in env_raw:
            try:
                os.kill(int(entry), 9)
                _log(f'Processo orfao WeMod PID {entry} finalizado')
            except (ProcessLookupError, PermissionError, OSError):
                pass


# ── status ───────────────────────────────────────────────────────────

def is_wemod_installed(wineprefix: str) -> bool:
    return os.path.isfile(os.path.join(wineprefix, WEMOD_MARKER))


def _get_wemod_pid(wineprefix: str) -> Optional[int]:
    """Procura processo WeMod.exe rodando neste prefixo.

    Match exato: cmdline contem 'WeMod.exe' e environ contem
    'WINEPREFIX=<wineprefix>\0' (delimitador null do /proc/environ)."""
    wineprefix_bytes = f'WINEPREFIX={wineprefix}\0'.encode('utf-8')
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        try:
            cmdline = Path(f'/proc/{entry}/cmdline').read_bytes().decode('utf-8', errors='replace')
        except (OSError, PermissionError):
            continue
        if 'WeMod.exe' not in cmdline:
            continue
        try:
            env_raw = Path(f'/proc/{entry}/environ').read_bytes()
        except (OSError, PermissionError):
            return int(entry)
        if wineprefix_bytes in env_raw:
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


def remove_wemod_prefix(wineprefix: str):
    """Remove apenas os artefatos do WeMod do prefixo, sem afetar o resto.

    Remove:
      - drive_c/WeMod/ (symlink)
      - drive_c/users/*/AppData/Roaming/WeMod (symlink)
      - .wemod_installed (marker)
    """
    stop_wemod(wineprefix)

    # drive_c/WeMod/ symlink
    c_wemod = os.path.join(wineprefix, 'drive_c', 'WeMod')
    if os.path.islink(c_wemod) or os.path.isdir(c_wemod):
        if os.path.islink(c_wemod):
            os.remove(c_wemod)
        else:
            shutil.rmtree(c_wemod, ignore_errors=True)
        _log(f'Removido {c_wemod}')

    # login symlink
    win_user = _get_windows_user(wineprefix)
    appdata_wemod = os.path.join(
        wineprefix, f'drive_c/users/{win_user}/AppData/Roaming/WeMod'
    )
    if os.path.islink(appdata_wemod):
        os.remove(appdata_wemod)
        _log(f'Removido symlink de login {appdata_wemod}')
    elif os.path.isdir(appdata_wemod):
        shutil.rmtree(appdata_wemod, ignore_errors=True)
        _log(f'Removido diretorio de login {appdata_wemod}')

    # .wemod_installed marker
    marker = os.path.join(wineprefix, WEMOD_MARKER)
    if os.path.isfile(marker):
        os.remove(marker)
        _log(f'Removido marker {marker}')
