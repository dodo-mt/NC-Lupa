"""Cieľ odkazu Windows (.lnk) – bez COM, len prečítaním súboru (formát MS-SHLLINK).

Odkazy v nových zákazkách ukazujú na staré zákazky („ako sme to robili vtedy“). Skener uloží
cieľ do files.target, Lupa podľa neho skočí v strome na cieľovú zákazku. Cieľ sa neotvára
ani nekontroluje (to by bolo cez sieť pomalé).
"""
import os
import struct

HEADER_SIZE = 0x4C
HAS_ID_LIST = 0x01
HAS_LINK_INFO = 0x02
HAS_NAME = 0x04
HAS_RELATIVE_PATH = 0x08
IS_UNICODE = 0x80
VOLUME_AND_LOCAL_PATH = 0x01
NETWORK_AND_SUFFIX = 0x02
VALID_DEVICE = 0x01
MAX_SIZE = 1 << 20   # .lnk má zvyčajne pár kB – väčší súbor nie je odkaz


def _cstr(buf: bytes, off: int) -> str:
    end = buf.find(b"\0", off)
    return buf[off:end if end >= 0 else len(buf)].decode("mbcs", errors="replace")


def _wstr(buf: bytes, off: int) -> str:
    end = off
    while end + 1 < len(buf) and buf[end:end + 2] != b"\0\0":
        end += 2
    return buf[off:end].decode("utf-16-le", errors="replace")


def _join(base: str, suffix: str) -> str:
    if not suffix:
        return base
    return base.rstrip("\\") + "\\" + suffix.lstrip("\\")


def _relative(data: bytes, flags: int, pos: int) -> str | None:
    """Relatívna cesta zo StringData (záloha, keď odkaz nemá LinkInfo)."""
    if not flags & HAS_RELATIVE_PATH:
        return None
    unicode = flags & IS_UNICODE
    if flags & HAS_NAME:   # NAME_STRING je pred RELATIVE_PATH – preskočiť
        n = struct.unpack_from("<H", data, pos)[0]
        pos += 2 + n * (2 if unicode else 1)
    n = struct.unpack_from("<H", data, pos)[0]
    raw = data[pos + 2:pos + 2 + n * (2 if unicode else 1)]
    return raw.decode("utf-16-le" if unicode else "mbcs", errors="replace") or None


def parse(data: bytes, lnk_dir: str = "") -> str | None:
    """Cieľová cesta z obsahu .lnk; None, ak sa nedá zistiť. lnk_dir = priečinok odkazu
    (pre relatívnu cestu)."""
    if len(data) < HEADER_SIZE or struct.unpack_from("<I", data, 0)[0] != HEADER_SIZE:
        return None
    flags = struct.unpack_from("<I", data, 0x14)[0]
    pos = HEADER_SIZE
    if flags & HAS_ID_LIST:
        pos += 2 + struct.unpack_from("<H", data, pos)[0]
    if not flags & HAS_LINK_INFO:
        rel = _relative(data, flags, pos)
        return os.path.normpath(os.path.join(lnk_dir, rel)) if rel and lnk_dir else None
    li = data[pos:pos + struct.unpack_from("<I", data, pos)[0]]
    head, li_flags, _vol, local_off, net_off, suffix_off = struct.unpack_from("<IIIIII", li, 4)
    uni = head >= 0x24
    if uni:
        local_off_u, suffix_off_u = struct.unpack_from("<II", li, 28)
        suffix = _wstr(li, suffix_off_u) if suffix_off_u else ""
    else:
        suffix = _cstr(li, suffix_off) if suffix_off else ""

    if li_flags & NETWORK_AND_SUFFIX and net_off:
        # sieťový disk: radšej písmeno jednotky (L:) ako \\server\share – tak sú cesty v DB
        cn = li[net_off:]
        cn_flags, name_off, dev_off = struct.unpack_from("<III", cn, 4)
        name_off_u = dev_off_u = 0
        if name_off > 0x14:
            name_off_u, dev_off_u = struct.unpack_from("<II", cn, 20)
        device = ""
        if cn_flags & VALID_DEVICE and dev_off:
            device = _wstr(cn, dev_off_u) if dev_off_u else _cstr(cn, dev_off)
        net = _wstr(cn, name_off_u) if name_off_u else _cstr(cn, name_off)
        return _join(device or net, suffix)
    if li_flags & VOLUME_AND_LOCAL_PATH and (local_off or uni):
        base = _wstr(li, local_off_u) if uni and local_off_u else _cstr(li, local_off)
        return _join(base, suffix)
    return None


def _com_target(path: str) -> str | None:
    """Záloha cez Windows (IShellLink) – napr. odkaz len so zoznamom ID (cieľ v čase vytvorenia
    neexistoval). Odkaz sa len načíta, cieľ sa nehľadá (Resolve sa nevolá)."""
    try:
        import pythoncom
        from win32com.shell import shell
        pythoncom.CoInitialize()   # skener môže bežať vo vlákne ikony skenu
        try:
            link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None,
                                              pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
            link.QueryInterface(pythoncom.IID_IPersistFile).Load(path, 0)
            return link.GetPath(shell.SLGP_RAWPATH)[0] or None
        finally:
            pythoncom.CoUninitialize()
    except Exception:  # pywin32 chýba / poškodený odkaz
        return None


def target(path: str) -> str | None:
    """Cieľ odkazu zo súboru; pri chybe (práva, poškodený súbor) None – skener nesmie spadnúť."""
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_SIZE)
        found = parse(data, os.path.dirname(path))
    except (OSError, struct.error, IndexError, ValueError):
        found = None
    return found or _com_target(path)
