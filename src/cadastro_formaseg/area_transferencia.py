"""Área de transferência do Windows com HTML (formato "HTML Format").

O Tkinter só copia texto simples. Para colar o e-mail formatado no Outlook,
o HTML vai junto com o texto simples, e cada programa usa o que entende.
"""

from __future__ import annotations

import sys
import time

_CABECALHO = ("Version:0.9\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\n"
              "StartFragment:{:010d}\r\nEndFragment:{:010d}\r\n")
_INICIO = "<html><head><meta charset=\"utf-8\"></head><body><!--StartFragment-->"
_FIM = "<!--EndFragment--></body></html>"


def formato_cf_html(fragmento: str) -> bytes:
    """Monta o conteúdo no formato CF_HTML (posições em bytes UTF-8)."""
    inicio, frag, fim = _INICIO.encode("utf-8"), fragmento.encode("utf-8"), _FIM.encode("utf-8")
    tam = len(_CABECALHO.format(0, 0, 0, 0))
    ini_frag = tam + len(inicio)
    fim_frag = ini_frag + len(frag)
    fim_html = fim_frag + len(fim)
    return _CABECALHO.format(tam, fim_html, ini_frag, fim_frag).encode("ascii") + inicio + frag + fim


def copiar_html(html: str, texto: str) -> bool:
    """Copia HTML + texto simples. Devolve False fora do Windows ou se falhar."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

    def colocar(formato: int, dados: bytes) -> None:
        memoria = kernel32.GlobalAlloc(0x0002, len(dados))  # GMEM_MOVEABLE
        if not memoria:
            raise OSError("sem memória para a área de transferência")
        ponteiro = kernel32.GlobalLock(memoria)
        ctypes.memmove(ponteiro, dados, len(dados))
        kernel32.GlobalUnlock(memoria)
        if not user32.SetClipboardData(formato, memoria):
            kernel32.GlobalFree(memoria)
            raise OSError("o Windows recusou os dados")

    for _ in range(10):  # outro programa pode estar com a área de transferência aberta
        if user32.OpenClipboard(None):
            break
        time.sleep(0.1)
    else:
        return False
    try:
        user32.EmptyClipboard()
        colocar(user32.RegisterClipboardFormatW("HTML Format"), formato_cf_html(html) + b"\0")
        colocar(13, (texto + "\0").encode("utf-16-le"))  # CF_UNICODETEXT
        return True
    except OSError:
        return False
    finally:
        user32.CloseClipboard()
