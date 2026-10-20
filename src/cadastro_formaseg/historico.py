"""Histórico local dos e-mails já gerados, para evitar repetir em outro dia.

Fica em dados/historico.csv, ao lado do executável. Só guarda data, e-mail e
nome (nada de CPF).
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .config import pasta_dados


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
