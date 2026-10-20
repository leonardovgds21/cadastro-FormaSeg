"""Leitura da "Ficha de Registro de Empregado" (PDF exportado do Domínio).

Cada página do PDF é um colaborador. A leitura usa a posição das palavras na
página (sem OCR e sem IA): procura os rótulos fixos da ficha ("Empregado",
"Residência", "CPF", "Telefone Celular"...) e pega o texto logo abaixo deles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber


@dataclass
class Colaborador:
    nome_completo: str = ""
    cpf: str = ""
    cep: str = ""
    endereco: str = ""
    numero: str = ""
    complemento: str = ""
    bairro: str = ""
    cidade: str = ""
    estado: str = ""
    telefone: str = ""
    celular: str = ""
    pagina: int = 0
    avisos: list[str] = field(default_factory=list)


_RE_CPF = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}")
_RE_CEP = re.compile(r"CEP:\s*(\d{5}-?\d{3})")
_RE_TELEFONE = re.compile(r"\d{2}-?\d{8,9}")


def ler_fichas(caminho_pdf: str | Path) -> list[Colaborador]:
    """Lê todas as páginas do PDF e devolve um colaborador por página."""
    colaboradores = []
    with pdfplumber.open(str(caminho_pdf)) as pdf:
        for numero, pagina in enumerate(pdf.pages, start=1):
            palavras = pagina.extract_words(keep_blank_chars=False, use_text_flow=False)
            if not _achar(palavras, "REGISTRO"):
                continue
            colaborador = _ler_pagina(palavras)
            colaborador.pagina = numero
            colaboradores.append(colaborador)
    return colaboradores


def _ler_pagina(palavras: list[dict]) -> Colaborador:
    c = Colaborador()

    # Nome: linha logo abaixo de "Empregado", só a coluna da esquerda
    # (à direita, na mesma linha, ficam os "Beneficiários").
    rotulo_empregado = _achar(palavras, "Empregado")
    rotulo_benef = _achar(palavras, "Beneficiários")
    rotulo_residencia = _achar(palavras, "Residência")
    if rotulo_empregado and rotulo_residencia:
        limite_x = rotulo_benef["x0"] - 2 if rotulo_benef else 9999
        nome = _texto_entre(palavras, rotulo_empregado["bottom"], rotulo_residencia["top"], 0, limite_x)
        c.nome_completo = " ".join(nome.split())
    if not c.nome_completo:
        c.avisos.append("Nome não encontrado")

    # Endereço: todas as linhas entre "Residência" e "Serviço".
    rotulo_servico = _achar(palavras, "Serviço")
    if rotulo_residencia and rotulo_servico:
        texto = _texto_entre(palavras, rotulo_residencia["bottom"], rotulo_servico["top"], 0, 9999)
        _preencher_endereco(c, texto)
    else:
        c.avisos.append("Endereço não encontrado")

    # CPF: o único número no formato 000.000.000-00 da página.
    texto_pagina = " ".join(p["text"] for p in palavras)
    achou_cpf = _RE_CPF.search(texto_pagina)
    if achou_cpf:
        c.cpf = achou_cpf.group(0)
    else:
        c.avisos.append("CPF não encontrado")

    # Telefones: valor na linha de baixo, na coluna de cada rótulo.
    rotulos_tel = [p for p in palavras if p["text"] == "Telefone"]
    rotulos_tel.sort(key=lambda p: p["x0"])
    if len(rotulos_tel) >= 2:
        residencial, celular = rotulos_tel[0], rotulos_tel[1]
        c.telefone = _valor_abaixo(palavras, residencial, residencial["x0"] - 10, celular["x0"] - 10)
        c.celular = _valor_abaixo(palavras, celular, celular["x0"] - 30, 9999)
    c.telefone = _so_telefone(c.telefone)
    c.celular = _so_telefone(c.celular)
    if not c.celular and not c.telefone:
        c.avisos.append("Nenhum telefone encontrado")
    return c


def _preencher_endereco(c: Colaborador, texto: str) -> None:
    """Separa "Rua X, 10, AP 1, BAIRRO, CIDADE, UF, - CEP: 00000-000"."""
    texto = " ".join(texto.split())
    achou_cep = _RE_CEP.search(texto)
    if achou_cep:
        cep = achou_cep.group(1).replace("-", "")
        c.cep = f"{cep[:5]}-{cep[5:]}"
        texto = texto[: achou_cep.start()]
    else:
        c.avisos.append("CEP não encontrado")

    partes = [p.strip() for p in texto.split(",")]
    partes = [p for p in partes if p and p != "-"]
    if len(partes) == 5:
        c.endereco, c.numero, c.bairro, c.cidade, c.estado = partes
    elif len(partes) == 6:
        c.endereco, c.numero, c.complemento, c.bairro, c.cidade, c.estado = partes
    elif len(partes) > 6:
        # Vírgulas extras: rua no começo; número, bairro, cidade e UF no fim.
        c.endereco = partes[0]
        c.numero = partes[1]
        c.estado, c.cidade, c.bairro = partes[-1], partes[-2], partes[-3]
        c.complemento = ", ".join(partes[2:-3])
        c.avisos.append("Endereço fora do padrão: confira o complemento")
    else:
        c.endereco = ", ".join(partes)
        c.avisos.append("Endereço fora do padrão: confira os campos")

    c.endereco = _capitalizar(c.endereco)
    c.complemento = _capitalizar(c.complemento)
    c.bairro = _capitalizar(c.bairro)
    c.cidade = _capitalizar(c.cidade)
    c.estado = c.estado.upper()


_MINUSCULAS = {"da", "das", "de", "do", "dos", "e"}


def _capitalizar(texto: str) -> str:
    """"RUA DAS FLORES (LOTE 2)" -> "Rua das Flores (Lote 2)"."""
    palavras = []
    for i, palavra in enumerate(texto.lower().split()):
        if i > 0 and palavra in _MINUSCULAS:
            palavras.append(palavra)
        else:
            palavras.append(re.sub(r"[a-zà-ú]", lambda m: m.group(0).upper(), palavra, count=1))
    return " ".join(palavras)


def _so_telefone(texto: str) -> str:
    achou = _RE_TELEFONE.search(texto or "")
    return achou.group(0) if achou else ""


def _achar(palavras: list[dict], texto: str) -> dict | None:
    for p in palavras:
        if p["text"] == texto:
            return p
    return None


def _texto_entre(palavras, topo, base, x_min, x_max) -> str:
    """Junta as palavras dentro do retângulo, na ordem de leitura."""
    dentro = [
        p for p in palavras
        if p["top"] > topo - 1 and p["bottom"] < base + 1 and x_min <= p["x0"] < x_max
    ]
    dentro.sort(key=lambda p: (round(p["top"]), p["x0"]))
    return " ".join(p["text"] for p in dentro)


def _valor_abaixo(palavras, rotulo, x_min, x_max) -> str:
    """Texto da linha logo abaixo do rótulo, entre x_min e x_max."""
    return _texto_entre(palavras, rotulo["bottom"], rotulo["bottom"] + 12, x_min, x_max)
