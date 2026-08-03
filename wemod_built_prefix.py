#!/usr/bin/env python3
"""Download e merge de prefixos Wine pre-configurados para WeMod.
Adaptado do wemod-launcher (DeckCheatz/wemod-launcher).
Sem instalacao de dotnet48."""

import json
import os
import pathlib
import re
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from wemod_manager import (
    _ensure_vkd3d_utils,
    _get_wine_binary,
    _http_get,
    _log,
    WEMOD_DATA_DIR,
    WEMOD_MARKER,
    sync_wemod_login,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

WEMOD_PREFIXES_DIR = os.path.join(SCRIPT_DIR, 'wemod_prefixes')

BUILT_PREFIX_CACHE = os.path.join(WEMOD_DATA_DIR, 'prefix_cache')
BUILT_PREFIX_DIR = os.path.expanduser('~/.config/trainer_manager/built_prefixes')
BUILT_PREFIX_REPO_USER = 'rafaelcarpeta'
BUILT_PREFIX_REPO_NAME = 'Action-Shark'

_DOWNLOAD_UA = ('Mozilla/5.0 (X11; Linux x86_64; rv:135.0) '
                'Gecko/20100101 Firefox/135.0')


def _bp_parse_version(version_str: str) -> Optional[list]:
    if not version_str or not isinstance(version_str, str):
        return None
    # GE-Proton11-1, Proton 9.0-3, 9.0
    m = re.search(r'(?:GE-Proton)?(\d+)[.-](\d+)', version_str)
    if m:
        return [int(m.group(1)), int(m.group(2))]
    # fallback: dois numeros consecutivos separados por nao-digito
    nums = re.findall(r'\d+', version_str)
    if len(nums) >= 2:
        return [int(nums[0]), int(nums[1])]
    return None


def _bp_get_current_version(wineprefix: str) -> Optional[list]:
    version_file = os.path.join(os.path.dirname(wineprefix), 'version')
    if os.path.isfile(version_file):
        try:
            ver_str = Path(version_file).read_text().strip()
            return _bp_parse_version(ver_str)
        except OSError:
            pass
    return _bp_detect_version_fallback(wineprefix)


def _bp_detect_version_fallback(wineprefix: str) -> Optional[list]:
    try:
        wine_bin = _get_wine_binary(wineprefix)
        r = subprocess.run([wine_bin, '--version'],
                           capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            ver = _bp_parse_version(r.stdout.strip())
            if ver:
                _log(f'Versao detectada via wine --version: {ver[0]}.{ver[1]}')
                return ver
    except Exception:
        pass

    ppath = os.path.dirname(wineprefix)
    m = re.search(r'compatdata/(\d+)', ppath)
    if m:
        appid = m.group(1)
        steam_roots = [
            os.path.expanduser('~/.local/share/Steam'),
            os.path.expanduser('~/.steam/steam'),
            os.path.expanduser('~/.steam/root'),
        ]
        for root in steam_roots:
            for base in ('compatibilitytools.d', 'steamapps/common'):
                bd = os.path.join(root, base)
                if not os.path.isdir(bd):
                    continue
                for d in sorted(os.listdir(bd), reverse=True):
                    if 'proton' not in d.lower():
                        continue
                    vf = os.path.join(bd, d, 'version')
                    if os.path.isfile(vf):
                        try:
                            ver = _bp_parse_version(Path(vf).read_text().strip())
                            if ver:
                                return ver
                        except OSError:
                            pass
                    ps = os.path.join(bd, d, 'proton')
                    if os.path.isfile(ps):
                        try:
                            for line in open(ps, 'r', errors='replace'):
                                if line.startswith('CURRENT_PREFIX_VERSION='):
                                    m2 = re.match(
                                        r'^CURRENT_PREFIX_VERSION=[\"\']?(.+?)[\"\']?\s*$',
                                        line)
                                    if m2:
                                        ver = _bp_parse_version(m2.group(1))
                                        if ver:
                                            return ver
                        except OSError:
                            pass
                    ver = _bp_parse_version(d)
                    if ver:
                        return ver
    return None


def _bp_find_cached_zip(version_parts: list) -> Optional[str]:
    file_name = f'wemod_prefix{version_parts[0]}.{version_parts[1]}.zip'
    cached = os.path.join(BUILT_PREFIX_DIR, file_name)
    if os.path.isfile(cached):
        return cached
    cached = os.path.join(WEMOD_PREFIXES_DIR, file_name)
    if os.path.isfile(cached):
        _log(f'Migrando zip do projeto para {BUILT_PREFIX_DIR}')
        os.makedirs(BUILT_PREFIX_DIR, exist_ok=True)
        dst = os.path.join(BUILT_PREFIX_DIR, file_name)
        shutil.copy2(cached, dst)
        os.remove(cached)
        return dst
    cached = os.path.join(BUILT_PREFIX_CACHE, file_name)
    if os.path.isfile(cached):
        _log(f'Migrando zip do cache temporario para {BUILT_PREFIX_DIR}')
        os.makedirs(BUILT_PREFIX_DIR, exist_ok=True)
        dst = os.path.join(BUILT_PREFIX_DIR, file_name)
        shutil.copy2(cached, dst)
        os.remove(cached)
        return dst

    any_zip = _bp_find_any_zip(BUILT_PREFIX_DIR)
    if any_zip:
        return any_zip
    return None


def _bp_find_any_zip(search_dir: str) -> Optional[str]:
    """Retorna qualquer .zip disponivel em search_dir (ordem alfabetica)."""
    if not os.path.isdir(search_dir):
        return None
    for fname in sorted(os.listdir(search_dir)):
        if fname.endswith('.zip'):
            return os.path.join(search_dir, fname)
    return None


def _bp_get_assets_for_tag(repo_name: str, tag_name: str) -> list:
    """Retorna os assets reais de uma release pelo tag (sem hardcode de filename)."""
    try:
        url = f'https://api.github.com/repos/{repo_name}/releases/tags/{tag_name}'
        resp = _http_get(url)
        data = json.loads(resp.read().decode('utf-8'))
        assets = data.get('assets', []) if isinstance(data, dict) else []
        if assets:
            return [{
                'browser_download_url': a.get('browser_download_url', ''),
                'name': a.get('name', ''),
            } for a in assets]
    except Exception as e:
        _log(f'Falha ao buscar assets do tag {tag_name}: {e}')
    return []


def _bp_get_github_releases(repo_name: str) -> list:
    url = f'https://api.github.com/repos/{repo_name}/releases'
    try:
        resp = _http_get(url)
        data = json.loads(resp.read().decode('utf-8'))
        if isinstance(data, list) and len(data) > 0:
            return data
    except Exception as e:
        _log(f'Falha ao buscar releases ({repo_name}): {e}')

    # Fallback: tenta /releases/latest
    try:
        url_latest = f'https://api.github.com/repos/{repo_name}/releases/latest'
        resp = _http_get(url_latest)
        data = json.loads(resp.read().decode('utf-8'))
        if isinstance(data, dict) and 'tag_name' in data:
            _log(f'Release latest encontrada: {data["tag_name"]}')
            return [data]
    except Exception as e:
        _log(f'Falha ao buscar latest release ({repo_name}): {e}')

    # Fallback: tenta listar tags (requer menos permissoes)
    try:
        url_tags = f'https://api.github.com/repos/{repo_name}/tags'
        resp = _http_get(url_tags)
        data = json.loads(resp.read().decode('utf-8'))
        if isinstance(data, list) and len(data) > 0:
            _log(f'{len(data)} tag(s) encontrada(s), buscando assets por tag...')
            releases = []
            for tag in data:
                tag_name = tag.get('name', '')
                assets = _bp_get_assets_for_tag(repo_name, tag_name)
                releases.append({
                    'tag_name': tag_name,
                    'assets': assets,
                })
            return releases
    except Exception as e:
        _log(f'Falha ao buscar tags ({repo_name}): {e}')

    return []


def _bp_find_closest_compatible_release(releases, current_version_parts) -> tuple:
    closest_release = None
    closest_version = None
    closest_url = None
    priority = 6

    for release in releases:
        tag_name = release.get('tag_name', '')
        if not tag_name.startswith('PfxVer'):
            continue
        rvp = _bp_parse_version(tag_name)
        if not rvp or not current_version_parts:
            continue
        if not release.get('assets'):
            continue
        cvp = current_version_parts

        if rvp[0] == cvp[0] and rvp[1] == cvp[1]:
            closest_release = release
            closest_version = rvp
            closest_url = release['assets'][0]['browser_download_url']
            break
        elif rvp[0] == cvp[0] and rvp[1] < cvp[1]:
            if priority > 2 or (priority == 2 and (not closest_release or rvp[1] > closest_version[1])):
                priority = 2
                closest_release = release
                closest_version = rvp
                closest_url = release['assets'][0]['browser_download_url']
        elif rvp[0] == cvp[0] and rvp[1] > cvp[1]:
            if priority > 3 or (priority == 3 and (not closest_release or rvp[1] < closest_version[1])):
                priority = 3
                closest_release = release
                closest_version = rvp
                closest_url = release['assets'][0]['browser_download_url']
        elif rvp[0] < cvp[0]:
            if priority > 4 or (priority == 4 and (not closest_release or rvp[0] > closest_version[0] or (rvp[0] == closest_version[0] and rvp[1] > closest_version[1]))):
                priority = 4
                closest_release = release
                closest_version = rvp
                closest_url = release['assets'][0]['browser_download_url']
        elif rvp[0] > cvp[0]:
            if priority > 5 or (priority == 5 and (not closest_release or rvp[0] < closest_version[0] or (rvp[0] == closest_version[0] and rvp[1] < closest_version[1]))):
                priority = 5
                closest_release = release
                closest_version = rvp
                closest_url = release['assets'][0]['browser_download_url']

    return closest_version, closest_url


def _bp_download_zip(url: str, dst_path: str,
                     log_callback, progress_callback,
                     max_attempts: int = 3) -> bool:
    """Baixa url para dst_path com resume parcial e retry.

    O progresso usa chunk de 1 MiB (nao por chunk de socket) para nao
    inundar a fila da GUI e travar o app.
    """
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    for attempt in range(1, max_attempts + 1):
        try:
            done = _bp_download_zip_once(url, dst_path,
                                         log_callback, progress_callback)
            if done:
                log_callback('Download concluido')
                return True
            return False
        except Exception as e:
            if attempt < max_attempts:
                log_callback(f'Tentativa {attempt} falhou: {e}. '
                             f'Tentando novamente...')
            else:
                log_callback(f'Falha no download apos {max_attempts} '
                             f'tentativas: {e}')
                if os.path.isfile(dst_path):
                    os.remove(dst_path)
    return False


def _bp_download_zip_once(url: str, dst_path: str,
                          log_callback, progress_callback) -> bool:
    chunk_size = 1024 * 1024
    headers = {'User-Agent': _DOWNLOAD_UA}
    already = 0
    if os.path.isfile(dst_path):
        already = os.path.getsize(dst_path)
        if already > 0:
            headers['Range'] = f'bytes={already}-'

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as resp:
        status = getattr(resp, 'status', 200)
        total = int(resp.headers.get('content-length', 0))

        if status == 206 and already > 0:
            # resume: total agora e o que falta, entao soma o ja baixado
            total += already
            mode = 'ab'
            base = already
        else:
            if already > 0:
                log_callback('Servidor ignorou Range; reiniciando download')
            mode = 'wb'
            base = 0
            already = 0

        if total and base:
            pct = 10 + int(60 * base / total)
            progress_callback(f'Retomando download... {base // 1024 // 1024}MB'
                              f'/{total // 1024 // 1024}MB', pct)

        last_mb = -1
        with open(dst_path, mode) as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                already += len(chunk)
                if total:
                    mb = already // 1024 // 1024
                    if mb != last_mb:
                        last_mb = mb
                        tmb = total // 1024 // 1024
                        pct = 10 + int(60 * already / total)
                        progress_callback(f'Baixando prefixo... {mb}MB/{tmb}MB',
                                          pct)
    if total and already < total:
        raise OSError(f'Download incompleto: {already}/{total} bytes')
    return True


def _bp_extract_zip(zip_path: str, compatdata: str,
                    log_callback, progress_callback) -> bool:
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            files = zf.namelist()
            total_files = len(files)
            for i, member in enumerate(files):
                full_path = os.path.join(compatdata, member)
                dirname = os.path.dirname(full_path)
                if dirname and not os.path.isdir(dirname):
                    os.makedirs(dirname, exist_ok=True)
                if os.path.isfile(full_path) or os.path.islink(full_path):
                    os.remove(full_path)
                zf.extract(member, compatdata)
                pct = 70 + int(25 * (i + 1) / total_files)
                progress_callback(f'Extraindo... ({i+1}/{total_files})', pct)
    except Exception as e:
        log_callback(f'Falha ao extrair: {e}')
        return False
    return True


def _bp_finish_install(wineprefix: str, log_callback, progress_callback):
    pfx_marker = os.path.join(wineprefix, '.wemod_installer')
    if not os.path.exists(pfx_marker):
        log_callback('ATENCAO: .wemod_installer nao encontrado no prefixo extraido')

    try:
        # Cria estrutura de diretorios para sync_wemod_login
        roaming = os.path.join(wineprefix, 'drive_c', 'users',
                               'steamuser', 'AppData', 'Roaming')
        os.makedirs(roaming, exist_ok=True)
        log_callback('Sincronizando login...')
        sync_wemod_login(wineprefix)
    except Exception as e:
        log_callback(f'Aviso: sync login: {e}')

    try:
        _ensure_vkd3d_utils(wineprefix, log_callback=log_callback)
    except Exception:
        pass

    marker = os.path.join(wineprefix, WEMOD_MARKER)
    Path(marker).write_text('1')

    progress_callback('Concluido', 100)
    log_callback('Prefixo pre-configurado instalado!')


def download_built_prefix(wineprefix: str,
                          log_callback=None,
                          progress_callback=None,
                          repo_user: str = BUILT_PREFIX_REPO_USER,
                          repo_name: str = BUILT_PREFIX_REPO_NAME) -> bool:
    if log_callback is None:
        log_callback = _log
    if progress_callback is None:
        progress_callback = lambda s, p: None

    compatdata = os.path.dirname(wineprefix)

    current_version_parts = _bp_get_current_version(wineprefix)
    if not current_version_parts:
        log_callback('Versao do Proton nao encontrada para este prefixo')
        return False

    log_callback(f'Buscando prefixo compativel com versao '
                 f'{current_version_parts[0]}.{current_version_parts[1]}...')
    progress_callback('Buscando releases...', 5)

    repo_concat = f'{repo_user}/{repo_name}'
    releases = _bp_get_github_releases(repo_concat)
    if not releases:
        log_callback(f'Nenhuma release encontrada em {repo_concat}')
        return False

    closest_version, url = _bp_find_closest_compatible_release(
        releases, current_version_parts)
    if not closest_version or not url:
        log_callback(f'Nenhuma release compativel (PfxVer) em {repo_concat}')
        log_callback('Tentando primeira release com assets...')
        for rel in releases:
            assets = rel.get('assets', [])
            if assets:
                url = assets[0]['browser_download_url']
                closest_version = [0, 0]
                log_callback(f'Usando: {rel.get("tag_name", "?")}')
                break
    if not closest_version or not url:
        log_callback('Nenhuma release com assets encontrada')
        return False

    log_callback(f'Release: PfxVer{closest_version[0]}.{closest_version[1]}')

    # Checa cache local primeiro
    cached = _bp_find_cached_zip(closest_version)
    if cached:
        log_callback(f'Usando prefixo em cache: {cached}')
        progress_callback('Extraindo de cache...', 70)
        if not _bp_extract_zip(cached, compatdata, log_callback, progress_callback):
            return False
        _bp_finish_install(wineprefix, log_callback, progress_callback)
        return True

    # Download — usa o nome real do asset da release, salvo no diretorio
    # de built prefixes (sem hardcode de filename)
    file_name = os.path.basename(url.split('?')[0]) or \
        f'wemod_prefix{closest_version[0]}.{closest_version[1]}.zip'
    perm_path = os.path.join(BUILT_PREFIX_DIR, file_name)

    progress_callback('Baixando prefixo...', 10)
    if not _bp_download_zip(url, perm_path, log_callback, progress_callback):
        return False

    progress_callback('Extraindo prefixo...', 70)
    if not _bp_extract_zip(perm_path, compatdata, log_callback, progress_callback):
        return False

    pfx_expected = os.path.join(compatdata, 'pfx')
    if not os.path.isdir(pfx_expected):
        log_callback('AVISO: diretorio pfx/ nao encontrado apos extracao')
        log_callback(f'Esperado em: {pfx_expected}')
        log_callback('Verifique a estrutura do zip (pode conter subdiretorio aninhado)')

    _bp_finish_install(wineprefix, log_callback, progress_callback)
    return True


def _is_continuation(line: str) -> bool:
    """True se a linha é continuação de um valor multi-linha (não é novo valor nem seção)."""
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith('"') and not stripped.startswith('[')


def _merge_reg_value_lines(src_lines: list, dst_lines: list, src_override: bool = False) -> list:
    """Merge source value lines into destination.
    Se src_override=True: valores do source sobrescrevem os do destino
      (último valor com mesmo nome vence no Wine registry).
    Se src_override=False: só valores NOVOS do source são adicionados.
    Retorna a lista mesclada de linhas."""
    dst_names = set()
    merged = []
    i = 0
    while i < len(dst_lines):
        line = dst_lines[i]
        merged.append(line)
        m = re.match(r'^("(?:[^"]+)")=', line)
        if m:
            dst_names.add(m.group(1))
            i += 1
            while i < len(dst_lines) and _is_continuation(dst_lines[i]):
                merged.append(dst_lines[i])
                i += 1
        else:
            i += 1

    i = 0
    while i < len(src_lines):
        line = src_lines[i]
        m = re.match(r'^("(?:[^"]+)")=', line)
        if m:
            is_dup = m.group(1) in dst_names
            if src_override or not is_dup:
                merged.append(line)
                i += 1
                while i < len(src_lines) and _is_continuation(src_lines[i]):
                    merged.append(src_lines[i])
                    i += 1
            else:
                i += 1
                while i < len(src_lines) and _is_continuation(src_lines[i]):
                    i += 1
        else:
            i += 1

    return merged


def _merge_reg_file(src_path: str, dst_path: str, log_callback=None):
    """Merge source Wine registry into destination at chave/valor.
    Chaves que só existem em source são adicionadas.
    Chaves existentes em ambos: valores de destination são preservados,
    valores novos de source são adicionados."""
    if log_callback is None:
        log_callback = _log

    def parse_reg(path):
        with open(path, 'r', errors='replace') as f:
            content = f.read()
        lines = content.splitlines(keepends=True)

        meta = []
        sections = {}
        current_key = None
        buf = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith('['):
                m = re.match(r'^(\[.+\])(?:\s|$)', stripped)
                if m:
                    if current_key is not None:
                        sections[current_key] = buf
                    current_key = m.group(1)
                    buf = [line]
                    continue
            if current_key is not None:
                buf.append(line)
            else:
                meta.append(line)

        if current_key is not None:
            sections[current_key] = buf
        return meta, sections

    if not os.path.isfile(src_path):
        return
    if not os.path.isfile(dst_path):
        shutil.copy2(src_path, dst_path)
        log_callback(f'  {os.path.basename(src_path)} copiado (destino nao existia)')
        return

    src_meta, src_sections = parse_reg(src_path)
    dst_meta, dst_sections = parse_reg(dst_path)

    for key, src_lines in src_sections.items():
        if key not in dst_sections:
            dst_sections[key] = src_lines[:]
        else:
            dst_sections[key] = _merge_reg_value_lines(
                src_lines, dst_sections[key], src_override=True)

    merged = []
    for line in dst_meta:
        merged.append(line)
    for key in sorted(dst_sections.keys()):
        merged.extend(dst_sections[key])

    with open(dst_path, 'w') as f:
        f.writelines(merged)
    log_callback(f'  {os.path.basename(src_path)} mesclado ({len(src_sections)} secoes source, {len(dst_sections)} secoes destino)')


def merge_built_prefix(wineprefix: str,
                       source_compatdata: str,
                       log_callback=None,
                       progress_callback=None) -> bool:
    if log_callback is None:
        log_callback = _log
    if progress_callback is None:
        progress_callback = lambda s, p: None

    source_pfx = os.path.join(source_compatdata, 'pfx')
    if not os.path.isdir(source_pfx):
        log_callback(f'Prefixo fonte invalido: {source_compatdata}')
        return False

    log_callback(f'Copiando dados do WeMod de {source_compatdata}...')
    progress_callback('Copiando prefixo...', 0)

    dest_compatdata = os.path.dirname(wineprefix)

    if source_compatdata == dest_compatdata:
        log_callback('Prefixo fonte e destino sao identicos, merge nao necessario')
        progress_callback('Concluido', 100)
        return True

    ignore = [
        'pfx/drive_c/users',
        'pfx/dosdevices',
        'pfx/drive_c/Program Files (x86)',
        'pfx/drive_c/Program Files',
        'pfx/drive_c/ProgramData',
        'drive_c/openxr',
        'pfx/drive_c/vrclient',
        'version',
        'config_info',
    ]
    include_override = [
        'pfx/drive_c/ProgramData/Microsoft',
        'pfx/drive_c/Program Files (x86)/Microsoft.NET',
        'pfx/drive_c/Program Files (x86)/Windows NT',
        'pfx/drive_c/Program Files (x86)/Common Files',
        'pfx/drive_c/Program Files/Common Files',
        'pfx/drive_c/Program Files/Windows NT',
    ]

    all_files = []
    for item in pathlib.Path(source_compatdata).rglob('*'):
        if item.is_file():
            all_files.append(item)

    _REG_FILES = {'pfx/system.reg', 'pfx/user.reg', 'pfx/userdef.reg'}
    _FORCE_OVERWRITE_PREFIXES = (
        'pfx/drive_c/windows/Microsoft.NET',
        'pfx/drive_c/windows/system32/mscore',
        'pfx/drive_c/windows/syswow64/mscore',
        'pfx/drive_c/windows/system32/clr',
        'pfx/drive_c/windows/syswow64/clr',
    )

    copy_list = []
    reg_files = []
    for f in all_files:
        rfile = os.path.relpath(str(f), source_compatdata)
        if rfile in _REG_FILES:
            reg_files.append(rfile)
            continue
        use = True
        for i in ignore:
            if os.path.commonprefix([rfile, i]) == i:
                use = False
                break
        if not use:
            for i in include_override:
                if os.path.commonprefix([rfile, i]) == i:
                    use = True
                    break
        if use:
            copy_list.append(rfile)

    total = len(copy_list)
    if total == 0 and not reg_files:
        log_callback('Nenhum arquivo para copiar')
        return False

    for i, rfile in enumerate(copy_list):
        src = os.path.join(source_compatdata, rfile)
        dst = os.path.join(dest_compatdata, rfile)
        force = rfile.startswith(_FORCE_OVERWRITE_PREFIXES)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not force and os.path.lexists(dst):
                continue
            if os.path.lexists(dst):
                os.unlink(dst)
            shutil.copy2(src, dst, follow_symlinks=False)
        except OSError:
            pass
        pct = int(80 * (i + 1) / (total or 1))
        progress_callback(f'Copiando... ({i+1}/{max(total,1)})', pct)

    if reg_files:
        log_callback('Fazendo merge dos registros Wine...')
        progress_callback('Merge dos registros...', 80)
        for rfile in reg_files:
            src = os.path.join(source_compatdata, rfile)
            dst = os.path.join(dest_compatdata, rfile)
            _merge_reg_file(src, dst, log_callback)

    log_callback('Sincronizando login...')
    sync_wemod_login(wineprefix)

    try:
        _ensure_vkd3d_utils(wineprefix, log_callback=log_callback)
    except Exception:
        pass

    marker = os.path.join(wineprefix, WEMOD_MARKER)
    Path(marker).write_text('1')

    progress_callback('Concluido', 100)
    log_callback('Merge do prefixo concluido!')
    return True


def install_built_prefix(wineprefix: str,
                         log_callback=None,
                         progress_callback=None,
                         repo_user: str = BUILT_PREFIX_REPO_USER,
                         repo_name: str = BUILT_PREFIX_REPO_NAME) -> bool:
    if log_callback is None:
        log_callback = _log
    if progress_callback is None:
        progress_callback = lambda s, p: None

    current_version_parts = _bp_get_current_version(wineprefix)

    if not current_version_parts:
        log_callback('Versao do Proton nao detectada. Tentando download direto...')
        return download_built_prefix(wineprefix, log_callback, progress_callback,
                                     repo_user, repo_name)

    log_callback('Procurando prefixo padrao salvo em '
                 f'{BUILT_PREFIX_DIR}...')
    progress_callback('Buscando prefixos padrao...', 0)

    closest_zip = _bp_find_any_zip(BUILT_PREFIX_DIR)
    if not closest_zip:
        log_callback('Nenhum zip local. Baixando do GitHub...')
        return download_built_prefix(wineprefix, log_callback, progress_callback,
                                     repo_user, repo_name)

    log_callback(f'Prefixo padrao encontrado: '
                 f'{os.path.basename(closest_zip)}')
    tmp_extract = os.path.join(BUILT_PREFIX_DIR,
                               f'_merge_{os.path.basename(closest_zip)[:-4]}')
    os.makedirs(tmp_extract, exist_ok=True)
    try:
        with zipfile.ZipFile(closest_zip, 'r') as zf:
            zf.extractall(tmp_extract)
        ok = merge_built_prefix(wineprefix, tmp_extract,
                                log_callback, progress_callback)
    finally:
        shutil.rmtree(tmp_extract, ignore_errors=True)
    return ok
