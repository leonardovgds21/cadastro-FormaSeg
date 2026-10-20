"""Regras de e-mail, usuário e senha, e geração dos CSVs de importação."""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .config import DOMINIO_EMAIL
from .ficha import Colaborador

COLUNAS_ALUNOS = [
    "Nome", "Sobrenome", "CPF", "CEP", "Endereco", "Numero", "Complemento", "Bairro",
    "Cidade", "Estado", "Telefone", "Celular", "E-mail", "Nome de usuario", "Senha",
    "Empresa", "Filial", "Regra de Acesso",
]
COLUNAS_CURSOS = ["E-mail", "Curso/Combo"]

# Sufixos que não contam como "último nome": José da Silva Filho -> jose.silva
SUFIXOS = {"filho", "filha", "junior", "jr", "neto", "neta", "sobrinho", "sobrinha", "segundo", "terceiro"}
PARTICULAS = {"da", "das", "de", "do", "dos", "e"}


@dataclass
class Aluno:
    """Linha do cadastro, já com e-mail e senha gerados. Editável na tela."""

    nome: str
    sobrenome: str
    cpf: str
    cep: str = ""
    endereco: str = ""
    numero: str = ""
    complemento: str = ""
    bairro: str = ""
    cidade: str = ""
    estado: str = ""
    telefone: str = ""
    celular: str = ""
    email: str = ""
    senha: str = ""
    cursos: list[str] = field(default_factory=list)  # ids do Curso/Combo
    avisos: list[str] = field(default_factory=list)


def sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def cpf_valido(cpf: str) -> bool:
    d = [int(x) for x in so_digitos(cpf)]
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        soma = sum(d[i] * (n + 1 - i) for i in range(n))
        if (soma * 10) % 11 % 10 != d[n]:
            return False
    return True


def formatar_cpf(cpf: str) -> str:
    d = so_digitos(cpf)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else cpf


def formatar_telefone(telefone: str) -> str:
    """"34-984328671" -> "(34) 98432-8671"."""
    d = so_digitos(telefone)
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return telefone or ""


def nome_proprio(texto: str) -> str:
    """"MARIA APARECIDA DE SOUZA" -> "Maria Aparecida de Souza"."""
    palavras = texto.lower().split()
    return " ".join(
        p if i > 0 and p in PARTICULAS else p.capitalize()
        for i, p in enumerate(palavras)
    )


def separar_nome(nome_completo: str) -> tuple[str, str]:
    """Nome = primeira palavra; Sobrenome = todo o resto."""
    partes = nome_proprio(nome_completo).split()
    if not partes:
        return "", ""
    return partes[0], " ".join(partes[1:])


def _slug(palavra: str) -> str:
    return re.sub(r"[^a-z]", "", sem_acento(palavra).lower())


def email_base(nome_completo: str) -> str:
    """primeironome.ultimonome (sem acento, sem sufixo como Filho/Júnior)."""
    palavras = [_slug(p) for p in nome_completo.split()]
    palavras = [p for p in palavras if p]
    if not palavras:
        return ""
    primeiro = palavras[0]
    resto = [p for p in palavras[1:] if p not in PARTICULAS]
    while len(resto) > 1 and resto[-1] in SUFIXOS:
        resto.pop()
    ultimo = resto[-1] if resto else ""
    return f"{primeiro}.{ultimo}" if ultimo else primeiro


def email_disponivel(base: str, existentes: set[str]) -> str:
    """maria.souza, ou maria.souza2, maria.souza3... se já existir."""
    existentes = {e.lower() for e in existentes}
    email = f"{base}@{DOMINIO_EMAIL}"
    n = 2
    while email in existentes:
        email = f"{base}{n}@{DOMINIO_EMAIL}"
        n += 1
    return email


def montar_aluno(c: Colaborador, existentes: set[str]) -> Aluno:
    nome, sobrenome = separar_nome(c.nome_completo)
    aluno = Aluno(
        nome=nome,
        sobrenome=sobrenome,
        cpf=formatar_cpf(c.cpf),
        cep=c.cep,
        endereco=c.endereco,
        numero=c.numero,
        complemento=c.complemento,
        bairro=c.bairro,
        cidade=c.cidade,
        estado=c.estado,
        telefone=formatar_telefone(c.telefone),
        celular=formatar_telefone(c.celular),
        email=email_disponivel(email_base(c.nome_completo), existentes),
        senha=so_digitos(c.cpf),
        avisos=list(c.avisos),
    )
    if not cpf_valido(c.cpf):
        aluno.avisos.append("CPF inválido")
    return aluno


def montar_alunos(colaboradores: list[Colaborador], existentes: set[str]) -> list[Aluno]:
    """Gera os alunos sem repetir e-mail entre si nem com os já existentes."""
    usados = set(existentes)
    alunos = []
    for c in colaboradores:
        aluno = montar_aluno(c, usados)
        usados.add(aluno.email)
        alunos.append(aluno)
    return alunos


def validar(aluno: Aluno) -> list[str]:
    """Problemas que impedem gerar o CSV."""
    erros = []
    if not aluno.nome or not aluno.sobrenome:
        erros.append("nome e sobrenome são obrigatórios")
    if not cpf_valido(aluno.cpf):
        erros.append("CPF inválido")
    if not re.fullmatch(r"[a-z0-9.]+@[a-z0-9.-]+", aluno.email or ""):
        erros.append("e-mail inválido")
    if not aluno.senha:
        erros.append("senha vazia")
    return erros


def _escrever(caminho: Path, colunas: list[str], linhas: list[list[str]]) -> None:
    # Mesmo formato do exemplo da plataforma: ";" , UTF-8 sem BOM, fim de linha Windows.
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f, delimiter=";", lineterminator="\r\n")
        escritor.writerow(colunas)
        escritor.writerows(linhas)


def gerar_csv_alunos(alunos: list[Aluno], caminho: Path) -> Path:
    linhas = [
        [
            a.nome, a.sobrenome, a.cpf, a.cep, a.endereco, a.numero, a.complemento,
            a.bairro, a.cidade, a.estado, a.telefone, a.celular, a.email, a.email,
            a.senha, "", "", "",
        ]
        for a in alunos
    ]
    _escrever(caminho, COLUNAS_ALUNOS, linhas)
    return caminho


def gerar_csv_cursos(alunos: list[Aluno], caminho: Path) -> Path | None:
    """Uma linha por matrícula. Devolve None se ninguém tiver curso."""
    linhas = [[a.email, curso] for a in alunos for curso in a.cursos]
    if not linhas:
        return None
    _escrever(caminho, COLUNAS_CURSOS, linhas)
    return caminho
