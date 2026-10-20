"""Login de administrador guardado no Cofre de Credenciais do Windows.

Nada é salvo em arquivo: a senha só fica no cofre do próprio computador, e
só se a pessoa marcar "lembrar".
"""

from __future__ import annotations

import keyring
from keyring.errors import KeyringError

SERVICO = "CadastroFormaSeg"
CHAVE_USUARIO = "__usuario__"


def carregar() -> tuple[str, str]:
    try:
        usuario = keyring.get_password(SERVICO, CHAVE_USUARIO) or ""
        senha = keyring.get_password(SERVICO, usuario) or "" if usuario else ""
    except KeyringError:
        return "", ""
    return usuario, senha


def salvar(usuario: str, senha: str) -> None:
    keyring.set_password(SERVICO, CHAVE_USUARIO, usuario)
    keyring.set_password(SERVICO, usuario, senha)


def apagar() -> None:
    usuario, _ = carregar()
    for chave in (usuario, CHAVE_USUARIO):
        if not chave:
            continue
        try:
            keyring.delete_password(SERVICO, chave)
        except KeyringError:
            pass
