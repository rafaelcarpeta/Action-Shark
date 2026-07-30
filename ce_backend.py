import ctypes
import os
import struct
import subprocess
import time
from ctypes import c_void_p, c_char_p, c_int, c_uint64, c_uint32, c_uint8, c_bool, POINTER, Structure, byref, c_size_t
from pathlib import Path
from typing import Optional

CE_DATA_DIR = os.path.expanduser('~/.config/trainer_manager/ce_data')
CE_LOG = os.path.join(CE_DATA_DIR, 'ce_backend.log')
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIBS_DIR = os.path.join(SCRIPT_DIR, 'libs')


def _log(msg: str):
    Path(CE_DATA_DIR).mkdir(parents=True, exist_ok=True)
    with open(CE_LOG, 'a') as f:
        f.write(f'{time.strftime("%H:%M:%S")} {msg}\n')


def _find_ce_install() -> Optional[str]:
    candidates = [
        os.path.expanduser('~/CheatEngineLinux77'),
        '/opt/CheatEngineLinux77',
    ]
    for path in candidates:
        binary = os.path.join(path, 'cheatengine-x86_64')
        if os.path.isfile(binary):
            return path
    return None


# ── Native memory I/O (process_vm_readv/writev) ──────────────────────

_libc = ctypes.CDLL(None, use_errno=True)

def _process_vm_readv(pid: int, addr: int, size: int) -> Optional[bytes]:
    buf = (ctypes.c_char * size)()
    local_iov = (ctypes.c_void_p * 2)(ctypes.addressof(buf), size)
    remote_iov = (ctypes.c_void_p * 2)(addr, size)
    ret = _libc.process_vm_readv(
        pid, local_iov, 1, remote_iov, 1, 0)
    if ret != size:
        return None
    return bytes(buf)


def _process_vm_writev(pid: int, addr: int, data: bytes) -> bool:
    buf = ctypes.create_string_buffer(data)
    local_iov = (ctypes.c_void_p * 2)(ctypes.addressof(buf), len(data))
    remote_iov = (ctypes.c_void_p * 2)(addr, len(data))
    ret = _libc.process_vm_writev(
        pid, local_iov, 1, remote_iov, 1, 0)
    return ret == len(data)


# ── Process / Module helpers ─────────────────────────────────────────

def _get_process_pid(process_name_or_pid):
    """Resolve PID from name or return int if already PID."""
    if isinstance(process_name_or_pid, int):
        return process_name_or_pid
    if isinstance(process_name_or_pid, str) and process_name_or_pid.isdigit():
        return int(process_name_or_pid)
    for p in Path('/proc').iterdir():
        if p.name.isdigit():
            try:
                cmdline = (p / 'cmdline').read_bytes().decode('utf-8', errors='replace').strip('\0')
                if process_name_or_pid.lower() in cmdline.lower():
                    return int(p.name)
            except (OSError, PermissionError):
                pass
    return None


def _get_module_base(pid: int, module_name: str) -> Optional[int]:
    try:
        for line in open(f'/proc/{pid}/maps'):
            if module_name.lower() in line and 'r-xp' in line:
                return int(line.split('-')[0], 16)
    except (OSError, PermissionError, IndexError):
        pass
    return _get_module_base_libce(pid, module_name)


def _get_module_base_libce(pid: int, module_name: str) -> Optional[int]:
    try:
        ce = _CeApi()
        handle = ce.OpenProcess(pid)
        if not handle:
            return None
        try:
            size = ce.GetModuleSize(handle, module_name.encode())
            if size and size > 0:
                symbols = ce.GetSymbolListFromMemory(handle, module_name.encode())
                if symbols:
                    return symbols[0].address
        finally:
            ce.CloseHandle(handle)
    except Exception:
        pass
    return None


def _resolve_address(pid: int, address_str: str, module_bases: dict) -> Optional[int]:
    """Resolve 'module.exe+0x123ABC' or '0x123ABC' or symbol name to address."""
    addr = address_str.strip()
    if not addr:
        return None

    if '+' in addr:
        parts = addr.split('+', 1)
        mod = parts[0].strip()
        offset_str = parts[1].strip()
        try:
            offset = int(offset_str, 16) if offset_str.startswith('0x') else int(offset_str)
        except ValueError:
            return None

        if mod.lower() == 'base.exe':
            mod = ''

        base = module_bases.get(mod)
        if base is not None:
            return base + offset
        base = _get_module_base(pid, mod)
        if base:
            module_bases[mod] = base
            return base + offset
        return None

    if addr.startswith('0x') or addr.startswith('0X'):
        try:
            return int(addr, 16)
        except ValueError:
            return None

    try:
        return int(addr)
    except ValueError:
        pass

    return None


# ── libceapi.so wrapper ──────────────────────────────────────────────

class _CeApi:
    def __init__(self):
        self._lib = None
        self._load()

    def _load(self):
        lib_path = os.path.join(LIBS_DIR, 'libceapi.so')
        if not os.path.isfile(lib_path):
            raise RuntimeError(f'libceapi.so not found at {lib_path}')
        self._lib = ctypes.CDLL(lib_path)

    def OpenProcess(self, pid: int) -> Optional[int]:
        self._lib.OpenProcess.argtypes = [c_int]
        self._lib.OpenProcess.restype = c_void_p
        return self._lib.OpenProcess(pid)

    def CloseHandle(self, handle: int):
        self._lib.CloseHandle.argtypes = [c_void_p]
        self._lib.CloseHandle.restype = c_bool
        self._lib.CloseHandle(handle)

    def ReadProcessMemory(self, handle: int, address: int, size: int) -> Optional[bytes]:
        buf = ctypes.create_string_buffer(size)
        self._lib.ReadProcessMemory.argtypes = [c_void_p, c_void_p, c_void_p, c_size_t, POINTER(c_size_t)]
        self._lib.ReadProcessMemory.restype = c_bool
        bytes_read = c_size_t()
        ok = self._lib.ReadProcessMemory(handle, address, buf, size, byref(bytes_read))
        if not ok:
            return None
        return buf.raw[:bytes_read.value]

    def WriteProcessMemory(self, handle: int, address: int, data: bytes) -> bool:
        self._lib.WriteProcessMemory.argtypes = [c_void_p, c_void_p, c_void_p, c_size_t, POINTER(c_size_t)]
        self._lib.WriteProcessMemory.restype = c_bool
        bytes_written = c_size_t()
        ok = self._lib.WriteProcessMemory(handle, address, data, len(data), byref(bytes_written))
        return ok

    def AOBScan(self, handle: int, pattern: bytes, start: int = 0, end: int = 0x7FFFFFFFFFFFFFFF) -> list:
        self._lib.AOBScan.argtypes = [c_void_p, c_char_p, c_uint64, c_uint64]
        self._lib.AOBScan.restype = POINTER(c_uint64)
        results_ptr = self._lib.AOBScan(handle, pattern, start, end)
        if not results_ptr:
            return []
        results = []
        i = 0
        while results_ptr[i] != 0:
            results.append(results_ptr[i])
            i += 1
        self._lib.free.restype = None
        self._lib.free.argtypes = [c_void_p]
        self._lib.free(results_ptr)
        return results

    def FindSymbol(self, handle: int, name: str) -> Optional[int]:
        self._lib.FindSymbol.argtypes = [c_void_p, c_char_p]
        self._lib.FindSymbol.restype = c_uint64
        addr = self._lib.FindSymbol(handle, name.encode())
        return addr if addr != 0 else None

    def GetModuleSize(self, handle: int, name: bytes) -> Optional[int]:
        self._lib.GetModuleSize.argtypes = [c_void_p, c_char_p]
        self._lib.GetModuleSize.restype = c_uint64
        return self._lib.GetModuleSize(handle, name)

    def GetSymbolListFromMemory(self, handle: int, module_name: bytes) -> list:
        self._lib.GetSymbolListFromMemory.restype = c_void_p
        ptr = self._lib.GetSymbolListFromMemory(handle, module_name)
        if not ptr:
            return []
        symbols = []
        i = 0
        while True:
            entry = ctypes.c_uint64.from_address(ptr + i * 16)
            if not entry:
                break
            name_ptr = ctypes.c_void_p.from_address(ptr + i * 16 + 8)
            if not name_ptr:
                break
            name = ctypes.c_char_p.from_address(name_ptr.value)
            symbols.append({'address': entry.value, 'name': name.value.decode()})
            i += 1
        return symbols

    def VirtualQueryEx(self, handle: int, address: int) -> Optional[dict]:
        self._lib.VirtualQueryEx.argtypes = [c_void_p, c_void_p]
        self._lib.VirtualQueryEx.restype = c_uint64
        result = self._lib.VirtualQueryEx(handle, address)
        if result == 0:
            return None
        return {'size': result}


# ── High-level API ────────────────────────────────────────────────────

class CEController:
    def __init__(self):
        self._ce_api: Optional[_CeApi] = None
        self._process_handle: Optional[int] = None
        self._pid: Optional[int] = None
        self._module_bases: dict = {}

    @property
    def connected(self) -> bool:
        return self._process_handle is not None

    def open_process(self, pid: int) -> bool:
        try:
            self._ce_api = _CeApi()
            handle = self._ce_api.OpenProcess(pid)
            if handle:
                self._process_handle = handle
                self._pid = pid
                self._module_bases = {}
                _log(f'Opened process {pid}')
                return True
            _log(f'Failed to open process {pid}')
            return False
        except Exception as e:
            _log(f'Error opening process: {e}')
            return False

    def close(self):
        if self._process_handle and self._ce_api:
            try:
                self._ce_api.CloseHandle(self._process_handle)
            except Exception:
                pass
        self._process_handle = None
        self._pid = None
        self._ce_api = None

    def read_bytes(self, address: int, size: int) -> Optional[bytes]:
        if self._process_handle and self._ce_api:
            return self._ce_api.ReadProcessMemory(self._process_handle, address, size)
        if self._pid:
            return _process_vm_readv(self._pid, address, size)
        return None

    def write_bytes(self, address: int, data: bytes) -> bool:
        if self._process_handle and self._ce_api:
            return self._ce_api.WriteProcessMemory(self._process_handle, address, data)
        if self._pid:
            return _process_vm_writev(self._pid, address, data)
        return False

    def resolve_address(self, address_str: str) -> Optional[int]:
        if not self._pid:
            return None
        return _resolve_address(self._pid, address_str, self._module_bases)

    def read_value(self, address: int, var_type: str):
        size_map = {
            'byte': 1, '2 bytes': 2, 'word': 2, '4 bytes': 4,
            'dword': 4, 'integer': 4, 'float': 4, '8 bytes': 8,
            'qword': 8, 'double': 8,
        }
        size = size_map.get(var_type.lower(), 4)
        data = self.read_bytes(address, size)
        if data is None:
            return None
        if var_type.lower() in ('float',):
            return struct.unpack('<f', data)[0]
        if var_type.lower() in ('double',):
            return struct.unpack('<d', data)[0]
        if size == 1:
            return data[0]
        if size == 2:
            return struct.unpack('<H', data)[0]
        if size == 4:
            return struct.unpack('<I', data)[0]
        if size == 8:
            return struct.unpack('<Q', data)[0]
        return int.from_bytes(data, 'little')

    def write_value(self, address: int, var_type: str, value) -> bool:
        size_map = {
            'byte': 1, '2 bytes': 2, 'word': 2, '4 bytes': 4,
            'dword': 4, 'integer': 4, 'float': 4, '8 bytes': 8,
            'qword': 8, 'double': 8,
        }
        size = size_map.get(var_type.lower(), 4)
        if var_type.lower() in ('float',):
            data = struct.pack('<f', float(value))
        elif var_type.lower() in ('double',):
            data = struct.pack('<d', float(value))
        elif size == 1:
            data = struct.pack('<B', int(value))
        elif size == 2:
            data = struct.pack('<H', int(value))
        elif size == 4:
            data = struct.pack('<I', int(value))
        elif size == 8:
            data = struct.pack('<Q', int(value))
        else:
            data = struct.pack('<I', int(value))
        return self.write_bytes(address, data)

    def find_symbol(self, name: str) -> Optional[int]:
        if not self._ce_api or not self._process_handle:
            return None
        try:
            return self._ce_api.FindSymbol(self._process_handle, name)
        except Exception:
            return None

    def aob_scan(self, pattern: str) -> list:
        if not self._ce_api or not self._process_handle:
            return []
        try:
            return self._ce_api.AOBScan(self._process_handle, pattern.encode())
        except Exception:
            return []


def find_game_process(prefix_path: str) -> Optional[int]:
    """Find the game process running in a Wine/Proton prefix."""
    prefix_path = os.path.normpath(prefix_path)
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            env = (p / 'environ').read_bytes().decode('utf-8', errors='replace')
            if prefix_path in env:
                return int(p.name)
        except (OSError, PermissionError):
            pass
    return None


def find_ce_install() -> Optional[str]:
    return _find_ce_install()
