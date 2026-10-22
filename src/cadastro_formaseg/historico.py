"""Histórico local dos e-mails já gerados, para evitar repetir em outro dia.

Fica em dados/historico.csv, ao lado do executável. Só guarda data, e-mail e
nome (nada de CPF).
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .config import pasta_dados
from .gerador import Aluno, sem_acento


def _arquivo() -> Path:
    return pasta_dados() / "historico.csv"


def emails_registrados() -> set[str]:
    arquivo = _arquivo()
    if not arquivo.exists():
        return set()
    with open(arquivo, encoding="utf-8", newline="") as f:
        return {linha["email"].lower() for linha in csv.DictReader(f, delimiter=";")}


def registrar(alunos) -> None:
    arquivo = _arquivo()
    novo = not arquivo.exists()
    with open(arquivo, "a", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f, delimiter=";", lineterminator="\r\n")
        if novo:
            escritor.writerow(["data", "email", "nome"])
        agora = datetime.now().strftime("%Y-%m-%d %H:%M")
        for a in alunos:
            escritor.writerow([agora, a.email, f"{a.nome} {a.sobrenome}"])


def chave_nome(nome: str) -> str:
    """Nome comparável: sem acento, minúsculo, espaços simples."""
    return " ".join(sem_acento(nome).lower().split())


def ultimo_cadastro_por_nome() -> dict[str, tuple[str, str]]:
    """{nome: (e-mail, data)} do cadastro mais recente de cada nome."""
    arquivo = _arquivo()
    if not arquivo.exists():
        return {}
    with open(arquivo, encoding="utf-8", newline="") as f:
        return {
            chave_nome(linha["nome"]): (linha["email"].lower(), linha["data"])
            for linha in csv.DictReader(f, delimiter=";")
        }


def reaproveitar_emails(alunos: list[Aluno], cadastros: dict[str, tuple[str, str]]) -> int:
    """Quem já foi cadastrado neste computador volta com o mesmo e-mail.

    Assim dá para reler a ficha só para mandar o e-mail aos alunos. Se for um
    homônimo, a conferência na plataforma troca o e-mail na hora do envio.
    """
    usados = {a.email for a in alunos}
    trocados = 0
    for aluno in alunos:
        anterior = cadastros.get(chave_nome(f"{aluno.nome} {aluno.sobrenome}"))
        if not anterior:
            continue
        email, data = anterior
        if email != aluno.email and email in usados:
            continue  # outro colaborador desta ficha já ficou com ele
        usados.discard(aluno.email)
        aluno.email = email
        usados.add(email)
        aluno.avisos.append(f"já cadastrado em {data[:10]}")
        trocados += 1
    return trocados
