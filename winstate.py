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

STATE_FILE = config.LOCAL_DIR / "window.json"

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


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


_user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.MonitorFromWindow.restype = wintypes.HANDLE
_user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
_user32.MonitorFromPoint.restype = wintypes.HANDLE
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
MONITOR_DEFAULTTONEAREST = 2


def _work_area(hmon) -> tuple[int, int, int, int] | None:
    mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    if not hmon or not _user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return None
    r = mi.rcWork
    return r.left, r.top, r.right, r.bottom


def _read_all() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _hwnd(window) -> int:
    return int(window.native.Handle.ToInt64())


def _save(window, name: str, relative: bool = False):
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
    if relative:                                       # poloha voči pracovnej ploche monitora, na ktorom okno bolo
        wr = wintypes.RECT()
        area = None
        if _user32.GetWindowRect(_hwnd(window), ctypes.byref(wr)):
            area = _work_area(_user32.MonitorFromWindow(_hwnd(window), MONITOR_DEFAULTTONEAREST))
        if area:
            data[name]["rel"] = [wr.left - area[0], wr.top - area[1], wr.right - wr.left, wr.bottom - wr.top]
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


def _umiestni(window, x: int, y: int, w: int, h: int):
    """Presunie (ešte skryté) okno na obrazovkové súradnice – cez Win32, WinForms Location by sa pri prvom zobrazení
    prepísalo predvolenou polohou."""
    SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
    _user32.SetWindowPos(_hwnd(window), None, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE)


def _restore_active(window, name: str) -> bool:
    """Okno sa otvorí na AKTÍVNOM monitore (tam, kde je kurzor myši / práve pracuješ) na mieste, kde bolo
    naposledy zatvorené (poloha a veľkosť voči pracovnej ploche monitora). Bez uloženej polohy = predvolená."""
    st = _read_all().get(name)
    rel = st.get("rel") if st else None
    if not rel:
        return _restore(window, name)
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    area = _work_area(_user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST))
    if not area:
        return _restore(window, name)
    dx, dy, w, h = rel
    w, h = min(w, area[2] - area[0]), min(h, area[3] - area[1])        # nesmie presiahnuť monitor
    x = max(area[0], min(area[0] + dx, area[2] - w))                   # a celé okno ostane na monitore
    y = max(area[1], min(area[1] + dy, area[3] - h))
    from System.Windows.Forms import FormStartPosition
    window.native.StartPosition = FormStartPosition.Manual
    _umiestni(window, x, y, w, h)
    return False


def _restore_centered(window, name: str, parent) -> bool:
    """Okno sa otvorí uprostred rodičovského okna (hlavné okno Lupy), s naposledy použitou veľkosťou.
    Nesmie presiahnuť monitor, na ktorom rodič je. Ak rodič nie je k dispozícii, platí aktívny monitor."""
    try:
        hwnd = _hwnd(parent)
        pr = wintypes.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(pr)) or _user32.IsIconic(hwnd):
            raise ValueError("rodič nie je viditeľný")
        area = _work_area(_user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST))
        if not area:
            raise ValueError("monitor rodiča")
    except Exception:
        return _restore_active(window, name)
    from System.Windows.Forms import FormStartPosition
    rel = (_read_all().get(name) or {}).get("rel")
    w, h = (rel[2], rel[3]) if rel else (window.native.Size.Width, window.native.Size.Height)
    w, h = min(w, area[2] - area[0]), min(h, area[3] - area[1])
    x = (pr.left + pr.right - w) // 2
    y = (pr.top + pr.bottom - h) // 2
    x = max(area[0], min(x, area[2] - w))
    y = max(area[1], min(y, area[3] - h))
    window.native.StartPosition = FormStartPosition.Manual
    _umiestni(window, x, y, w, h)
    return False


def attach(window, name: str, active_monitor: bool = False, center_on=None):
    """Napojí pamätanie polohy na pywebview okno (volať pred webview.start).
    active_monitor=True: okno sa otvorí na aktívnom monitore (kde je kurzor), inak na monitore, kde bolo zatvorené.
    center_on = rodičovské pywebview okno: okno sa otvorí v jeho strede (veľkosť sa pamätá)."""
    want_max = {"v": False}

    def before_show(window):
        try:
            if center_on is not None:
                want_max["v"] = _restore_centered(window, name, center_on)
            else:
                want_max["v"] = (_restore_active if active_monitor else _restore)(window, name)
        except Exception as e:  # poloha okna nesmie zhodiť aplikáciu
            log.warning("Obnovenie polohy okna zlyhalo: %s", e)

    def shown(window):
        if want_max["v"]:
            window.maximize()

    def closing(window):
        try:
            _save(window, name, relative=active_monitor or center_on is not None)
        except Exception as e:
            log.warning("Uloženie polohy okna zlyhalo: %s", e)

    window.events.before_show += before_show
    window.events.shown += shown
    window.events.closing += closing


def show_centered(window, name: str, parent):
    """Pre okno vytvorené s hidden=True (druhé okno za behu: before_show už prebehlo, kým sa dalo napojiť):
    umiestni ho do stredu rodiča a až potom ukáže. Pamätanie veľkosti riešia attach(..., center_on=parent)."""
    try:
        _restore_centered(window, name, parent)
    except Exception as e:
        log.warning("Vycentrovanie okna '%s' zlyhalo: %s", name, e)
    window.show()
