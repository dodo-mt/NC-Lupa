"""Ikona Lupa skenera pri hodinách (system tray).

- sken každú hodinu (prvý 2 min po štarte), --auto logika (raz za 7 dní úplný)
- menu: Skenovať teraz, Úplný sken, Otvoriť Lupu, Otvoriť log, stav, Ukončiť
- upozornenia Windows: L:\\ nedostupný, chyby skenu, zlyhané publikovanie, nové zákazky,
  výsledok ručne spusteného skenu
Spustenie:  lupa-sken.exe --tray [--root L:\\] [--db L:\\_Lupa\\lupa.db]
"""
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import win32api
import win32con
import win32event
import win32gui
import winerror

import config
import scanner

log = logging.getLogger("lupa.tray")

INTERVAL = 3600          # bežný sken každú hodinu
FIRST_DELAY = 120        # prvý sken po štarte (sieťový disk sa pripája)
RETRY_NO_ROOT = 300      # L:\ nedostupný – skúsiť znova o 5 min

WM_TRAY = win32con.WM_USER + 20
WM_APP_UPDATE = win32con.WM_USER + 21
NIN_BALLOONUSERCLICK = win32con.WM_USER + 5
NIIF_INFO, NIIF_WARNING, NIIF_ERROR = 1, 2, 3
ID_SCAN, ID_FULL, ID_LUPA, ID_LOG, ID_QUIT = range(1001, 1006)


def asset(name: str) -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str(base / "assets" / name)


def fmt_time(ts: float | None) -> str:
    if not ts:
        return "–"
    t = time.localtime(ts)
    return time.strftime("%H:%M" if time.localtime().tm_yday == t.tm_yday else "%d.%m. %H:%M", t)


class Tray:
    def __init__(self, root: str, db_path: Path):
        self.root = root
        self.db_path = db_path
        self.scanning = False
        self.progress_tip = ""
        self.last = None            # výsledok posledného skenu (dict z run_scan)
        self.last_time = None
        self.next_time = time.time() + FIRST_DELAY
        self.no_root_count = 0
        self.balloon_action = None  # čo urobiť po kliknutí na upozornenie
        self.notify_queue = []      # (titulok, text, ikona, akcia) – z vlákna skenu pre GUI
        self.request = None         # 'manual' | 'full' – ručne vyžiadaný sken
        self.wake = threading.Event()
        self.lock = threading.Lock()
        self._last_post = 0.0

        self.taskbar_msg = win32gui.RegisterWindowMessage("TaskbarCreated")
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = "LupaSkenTray"
        wc.lpfnWndProc = {
            WM_TRAY: self.on_tray,
            WM_APP_UPDATE: self.on_update,
            win32con.WM_COMMAND: self.on_command,
            win32con.WM_DESTROY: self.on_destroy,
            self.taskbar_msg: self.on_taskbar_created,
        }
        win32gui.RegisterClass(wc)
        self.hwnd = win32gui.CreateWindow(wc.lpszClassName, "Lupa sken", 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None)

        size = win32api.GetSystemMetrics(win32con.SM_CXSMICON)
        flags = win32con.LR_LOADFROMFILE
        self.icon_idle = win32gui.LoadImage(0, asset("lupa.ico"), win32con.IMAGE_ICON, size, size, flags)
        self.icon_busy = win32gui.LoadImage(0, asset("lupa-scan.ico"), win32con.IMAGE_ICON, size, size, flags)
        self._icon_added = False
        self.refresh_icon()

        threading.Thread(target=self.worker, daemon=True).start()

    # --- ikona a tooltip ---------------------------------------------------
    def tip(self) -> str:
        if self.scanning:
            return (self.progress_tip or "Lupa sken – skenujem…")[:127]
        lines = ["Lupa sken"]
        if self.last:
            r = self.last
            if r["status"] == "no_root":
                lines.append(f"{self.root} nedostupný")
            else:
                lines.append(f"Posledný: {fmt_time(self.last_time)} · chyby {r['errors']}")
        lines.append(f"Ďalší: {fmt_time(self.next_time)}")
        return "\n".join(lines)[:127]

    def refresh_icon(self):
        hicon = self.icon_busy if self.scanning else self.icon_idle
        data = (self.hwnd, 0, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP, WM_TRAY, hicon, self.tip())
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY if self._icon_added else win32gui.NIM_ADD, data)
            self._icon_added = True
        except win32gui.error:
            self._icon_added = False  # panel úloh ešte nie je – pridá sa pri TaskbarCreated

    def balloon(self, title: str, text: str, icon=NIIF_INFO, action=None):
        log.info("Upozornenie: %s – %s", title, text.replace("\n", " | "))
        self.balloon_action = action
        data = (self.hwnd, 0, win32gui.NIF_INFO, WM_TRAY, self.icon_idle, "", text[:255], 10000, title[:63], icon)
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, data)
        except win32gui.error as e:
            log.warning("Upozornenie sa nedá zobraziť: %s", e)

    def post_update(self, force=True):
        now = time.time()
        if force or now - self._last_post > 0.3:
            self._last_post = now
            win32gui.PostMessage(self.hwnd, WM_APP_UPDATE, 0, 0)

    # --- správy okna -------------------------------------------------------
    def on_update(self, hwnd, msg, wparam, lparam):
        self.refresh_icon()
        with self.lock:
            queue, self.notify_queue = self.notify_queue, []
        for n in queue:
            self.balloon(*n)
        return 0

    def on_taskbar_created(self, hwnd, msg, wparam, lparam):
        self._icon_added = False  # Prieskumník sa reštartoval – ikonu pridať znova
        self.refresh_icon()
        return 0

    def on_tray(self, hwnd, msg, wparam, lparam):
        if lparam == win32con.WM_RBUTTONUP:
            self.show_menu()
        elif lparam == win32con.WM_LBUTTONDBLCLK:
            self.open_lupa()
        elif lparam == NIN_BALLOONUSERCLICK:
            if self.balloon_action == "log":
                self.open_log()
            elif self.balloon_action == "lupa":
                self.open_lupa()
        return 0

    def show_menu(self):
        m = win32gui.CreatePopupMenu()
        gray = win32con.MF_STRING | win32con.MF_GRAYED

        def add(text, cmd=0, flags=win32con.MF_STRING):
            win32gui.AppendMenu(m, flags, cmd, text)

        add(f"Lupa sken v{config.VERSION}", 0, gray)
        add("", 0, win32con.MF_SEPARATOR)
        if self.scanning:
            add(self.progress_tip or "Skenujem…", 0, gray)
        elif self.last:
            r = self.last
            if r["status"] == "no_root":
                add(f"Posledný sken: {fmt_time(self.last_time)} – {self.root} nedostupný", 0, gray)
            else:
                add(f"Posledný sken: {fmt_time(self.last_time)} · {r['jobs']} zákaziek · chyby {r['errors']}", 0, gray)
        else:
            add("Zatiaľ bez skenu", 0, gray)
        add(f"Ďalší sken: {fmt_time(self.next_time)}", 0, gray)
        add("", 0, win32con.MF_SEPARATOR)
        busy = win32con.MF_GRAYED if self.scanning else 0
        add("Skenovať teraz", ID_SCAN, win32con.MF_STRING | busy)
        add("Úplný sken", ID_FULL, win32con.MF_STRING | busy)
        add("", 0, win32con.MF_SEPARATOR)
        add("Otvoriť Lupu", ID_LUPA)
        add("Otvoriť log", ID_LOG)
        add("", 0, win32con.MF_SEPARATOR)
        add("Ukončiť", ID_QUIT)
        win32gui.SetMenuDefaultItem(m, ID_LUPA, False)

        pos = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self.hwnd)
        win32gui.TrackPopupMenu(m, win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON, pos[0], pos[1], 0, self.hwnd, None)
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)
        win32gui.DestroyMenu(m)

    def on_command(self, hwnd, msg, wparam, lparam):
        cmd = win32api.LOWORD(wparam)
        if cmd in (ID_SCAN, ID_FULL) and not self.scanning:
            self.request = "full" if cmd == ID_FULL else "manual"
            self.wake.set()
        elif cmd == ID_LUPA:
            self.open_lupa()
        elif cmd == ID_LOG:
            self.open_log()
        elif cmd == ID_QUIT:
            win32gui.DestroyWindow(self.hwnd)
        return 0

    def on_destroy(self, hwnd, msg, wparam, lparam):
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self.hwnd, 0))
        except win32gui.error:
            pass
        win32gui.PostQuitMessage(0)
        return 0

    # --- akcie -------------------------------------------------------------
    def open_lupa(self):
        exe = self.db_path.parent / "Lupa.exe"
        try:
            if exe.exists():
                os.startfile(exe)
            elif not getattr(sys, "frozen", False):
                pyw = Path(sys.executable).with_name("pythonw.exe")
                subprocess.Popen([str(pyw if pyw.exists() else sys.executable),
                                  str(Path(__file__).resolve().parent / "app.py")])
            else:
                self.balloon("Lupa", f"Nenašiel sa {exe}", NIIF_WARNING)
        except OSError as e:
            self.balloon("Lupa", f"Lupu sa nepodarilo spustiť: {e}", NIIF_ERROR)

    def open_log(self):
        try:
            os.startfile(scanner.LOCAL_LOG)
        except OSError as e:
            self.balloon("Lupa sken", f"Log sa nedá otvoriť: {e}", NIIF_WARNING)

    # --- sken vo vlákne ----------------------------------------------------
    def on_progress(self, i, n, name):
        self.progress_tip = f"Lupa sken – {i}/{n}: {name}"
        self.post_update(force=False)

    def worker(self):
        while True:
            self.wake.wait(timeout=max(1.0, self.next_time - time.time()))
            self.wake.clear()
            kind = self.request
            self.request = None
            if kind is None and time.time() < self.next_time:
                continue

            self.scanning = True
            self.progress_tip = ""
            self.post_update()
            res = scanner.run_scan(self.root, self.db_path, full=(kind == "full"), auto=(kind != "full"),
                                   progress=self.on_progress)
            self.scanning = False
            if res["status"] != "busy":
                self.last, self.last_time = res, time.time()
            retry = res["status"] == "no_root"
            self.next_time = time.time() + (RETRY_NO_ROOT if retry else INTERVAL)
            self.notify(res, manual=kind is not None)
            self.post_update()

    def notify(self, r: dict, manual: bool):
        """Rozhodne, či a aké upozornenie ukázať. Pri bežnom hodinovom skene len pri probléme."""
        n = None
        if r["status"] == "no_root":
            self.no_root_count += 1
            # pri štarte sa disk ešte môže pripájať – hlásiť až pri 2. neúspechu (alebo hneď pri ručnom)
            if manual or self.no_root_count == 2:
                n = ("Lupa sken – disk nedostupný",
                     f"{self.root} nie je dostupný, sken sa nespustil. Skúsim znova o {RETRY_NO_ROOT // 60} min.",
                     NIIF_WARNING, None)
        else:
            if self.no_root_count >= 2:
                log.info("Koreň je znova dostupný.")
            self.no_root_count = 0

        if r["status"] == "busy" and manual:
            n = ("Lupa sken", "Sken už práve beží.", NIIF_INFO, None)
        elif r["status"] == "error":
            n = ("Lupa sken – chyba", f"Sken zlyhal: {r['message']}\nKlikni pre log.", NIIF_ERROR, "log")
        elif r["status"] == "ok":
            lines = []
            icon, action = NIIF_INFO, "lupa"
            if r["published"] is False:
                lines.append("Databázu sa nepodarilo uložiť (obsadená) – skúsim pri ďalšom skene.")
                icon, action = NIIF_WARNING, "log"
            if r["errors"]:
                lines.append(f"Chyby pri skene: {r['errors']} (prístup, dlhé cesty…). Klikni pre log.")
                icon, action = NIIF_WARNING, "log"
            if r["new_jobs"]:
                names = ", ".join(r["new_jobs"][:5]) + (f" (+{len(r['new_jobs']) - 5})" if len(r["new_jobs"]) > 5 else "")
                lines.append(f"Nové zákazky: {names}")
            if manual and not lines:
                lines.append(f"Hotovo za {r['seconds']:.0f} s · {r['jobs']} zákaziek · zmenené {r['changed']}")
            if lines:
                title = "Lupa – úplný sken" if r["full"] and manual else "Lupa sken"
                n = (title, "\n".join(lines), icon, action)
        if n:
            with self.lock:
                self.notify_queue.append(n)


def run(root: str, db_path: Path) -> int:
    # len jedna ikona naraz
    mutex = win32event.CreateMutex(None, False, "Lupa.SkenTray")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        log.info("Ikona Lupa skenu už beží – končím.")
        return 0
    log.info("Ikona pri hodinách spustená, v%s (koreň %s, DB %s)", config.VERSION, root, db_path)
    Tray(root, db_path)
    win32gui.PumpMessages()
    log.info("Ikona pri hodinách ukončená.")
    del mutex
    return 0
