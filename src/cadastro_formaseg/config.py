"""Caminhos do app e lista de cursos.

Quando roda como executável, tudo fica ao lado do .exe (config/, saida/,
dados/), para a pasta poder ser copiada inteira para outro computador.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

URL_PAINEL = "https://gapgestao.sstnr.com/painel/"
DOMINIO_EMAIL = "gapgestao.com.br"


def pasta_base() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def pasta_config() -> Path:
    return pasta_base() / "config"


def pasta_saida() -> Path:
    pasta = pasta_base() / "saida"
    pasta.mkdir(exist_ok=True)
    return pasta


def pasta_dados() -> Path:
    pasta = pasta_base() / "dados"
    pasta.mkdir(exist_ok=True)
    return pasta


@dataclass(frozen=True)
class Curso:
    nome: str
    id: str


def carregar_cursos(arquivo: Path | None = None) -> list[Curso]:
    arquivo = arquivo or pasta_config() / "cursos.json"
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    return [Curso(nome=c["nome"], id=str(c["id"])) for c in dados["cursos"]]


def area_de_trabalho() -> Path:
    """A Área de Trabalho de verdade do Windows (pode estar dentro do OneDrive)."""
    if sys.platform == "win32":
        import ctypes

        caminho = ctypes.create_unicode_buffer(260)
        # CSIDL_DESKTOPDIRECTORY = 0x10: segue o redirecionamento do OneDrive
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, caminho) == 0 and caminho.value:
            return Path(caminho.value)
    return Path.home() / "Desktop"


def pasta_certificados() -> Path:
    pasta = area_de_trabalho() / "certificados"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def pasta_downloads() -> Path:
    """Pasta temporária dos downloads do navegador, fora do OneDrive (que mexe
    nos arquivos enquanto eles são gravados)."""
    pasta = Path(tempfile.gettempdir()) / "CadastroFormaSeg" / "downloads"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta
