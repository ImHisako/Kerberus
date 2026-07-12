from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path


ERROR_ALREADY_EXISTS = 183
_mutex_handle: int | None = None
_lock_stream = None


def acquire_single_instance() -> bool:
    """Hold a per-Windows-session mutex for the lifetime of this process."""
    global _mutex_handle
    if os.name != "nt":
        global _lock_stream
        import fcntl

        root = Path(os.environ.get("XDG_RUNTIME_DIR", Path.home() / ".cache")) / "kerberus"
        root.mkdir(parents=True, exist_ok=True)
        _lock_stream = (root / "instance.lock").open("a+")
        try:
            fcntl.flock(_lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            _lock_stream.close()
            _lock_stream = None
            return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, r"Local\KerberusMessenger-v1")
    if not handle:
        return True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _mutex_handle = handle
    return True


def notify_already_running() -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(
            None,
            "Kerberus è già aperto. Usa la finestra esistente.",
            "Kerberus",
            0x40,
        )
    else:
        print("Kerberus è già aperto. Usa la finestra esistente.", file=sys.stderr)
