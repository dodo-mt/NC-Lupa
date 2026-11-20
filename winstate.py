"""Pamätanie polohy okien – poloha, veľkosť, maximalizácia, monitor.

Použitie pre každé okno:  winstate.attach(window, "main")
Ukladá sa do %LOCALAPPDATA%\\Lupa\\window.json pri zatvorení okna, obnoví sa pred zobrazením.
Používa natívne GetWindowPlacement / SetWindowPlacement – správne aj pri viacerých
monitoroch s rôznym DPI. Ak monitor, na ktorom sa okno zatvorilo, už nie je, okno sa
otvorí v predvolenej polohe (v strede).
"""
import ctypes
import json
import logging
from ctypes import wintypes

import config

log = logging.getLogger("lupa.winstate")

STATE_FILE = config.THUMBS_DIR.parent / "window.json"

SW_HIDE = 0
SW_SHOWMINIMIZED = 2
SW_SHOWMAXIMIZED = 3
WPF_RESTORETOMAXIMIZED = 2
MONITOR_DEFAULTTONULL = 0


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


_user32 = ctypes.windll.user32
_user32.GetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
_user32.SetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
_user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
_user32.MonitorFromRect.restype = wintypes.HANDLE


def _read_all() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _hwnd(window) -> int:
    return int(window.native.Handle.ToInt64())


def _save(window, name: str):
    wp = WINDOWPLACEMENT(length=ctypes.sizeof(WINDOWPLACEMENT))
    if not _user32.GetWindowPlacement(_hwnd(window), ctypes.byref(wp)):
        return
    if wp.showCmd == SW_SHOWMINIMIZED:
        maximized = bool(wp.flags & WPF_RESTORETOMAXIMIZED)
    else:
        maximized = wp.showCmd == SW_SHOWMAXIMIZED
    r = wp.rcNormalPosition
    data = _read_all()
    data[name] = {"rect": [r.left, r.top, r.right, r.bottom], "maximized": maximized}
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as e:
        log.warning("Polohu okna sa nepodarilo uložiť: %s", e)


def _restore(window, name: str) -> bool:
    """Nastaví uloženú polohu (okno je ešte skryté). Vráti True, ak sa má maximalizovať."""
    st = _read_all().get(name)
    if not st:
        return False
    rect = wintypes.RECT(*st["rect"])
    if not _user32.MonitorFromRect(ctypes.byref(rect), MONITOR_DEFAULTTONULL):
        log.info("Monitor okna '%s' nie je pripojený – predvolená poloha.", name)
        return False
    # WinForms by pri prvom zobrazení okno vycentroval – vypnúť
    from System.Windows.Forms import FormStartPosition  # pythonnet, načítaný cez pywebview
    window.native.StartPosition = FormStartPosition.Manual
    wp = WINDOWPLACEMENT(length=ctypes.sizeof(WINDOWPLACEMENT), showCmd=SW_HIDE, rcNormalPosition=rect)
    _user32.SetWindowPlacement(_hwnd(window), ctypes.byref(wp))
    return bool(st.get("maximized"))


def attach(window, name: str):
    """Napojí pamätanie polohy na pywebview okno (volať pred webview.start)."""
    want_max = {"v": False}

    def before_show(window):
        try:
            want_max["v"] = _restore(window, name)
        except Exception as e:  # poloha okna nesmie zhodiť aplikáciu
            log.warning("Obnovenie polohy okna zlyhalo: %s", e)

    def shown(window):
        if want_max["v"]:
            window.maximize()

    def closing(window):
        try:
            _save(window, name)
        except Exception as e:
            log.warning("Uloženie polohy okna zlyhalo: %s", e)

    window.events.before_show += before_show
    window.events.shown += shown
    window.events.closing += closing
