"""Monta o e-mail que avisa os alunos do cadastro e abre no Outlook.

O Outlook novo não tem a automação (COM) do Outlook clássico, então o
e-mail é aberto por um link mailto:, que o Windows entrega ao app de e-mail
padrão. Links muito longos são cortados pelo Windows; nesse caso o corpo vai
para a área de transferência e o link leva só destinatários e assunto.
"""

from __future__ import annotations

from urllib.parse import quote

from .config import URL_PAINEL
from .gerador import Aluno

# O Windows aceita ~2048 caracteres num link; fica uma folga.
LIMITE_MAILTO = 1900


def nomes_cursos(aluno: Aluno, nome_por_id: dict[str, str]) -> list[str]:
    return [nome_por_id.get(c, f"curso {c}") for c in aluno.cursos]


def montar_email(alunos: list[Aluno], nome_por_id: dict[str, str]) -> tuple[list[str], str, str]:
    """Devolve (destinatários, assunto, corpo)."""
    destinatarios = [a.email for a in alunos if a.email]
    cursos_por_aluno = [nomes_cursos(a, nome_por_id) for a in alunos]
    iguais = all(c == cursos_por_aluno[0] for c in cursos_por_aluno) if alunos else True
    cursos = cursos_por_aluno[0] if alunos and iguais else []

    linhas = ["Olá,", ""]
    if iguais and not cursos:
        assunto = "Cadastro na plataforma FormaSeg"
        linhas.append("Informamos que você foi cadastrado(a) na plataforma de treinamentos FormaSeg.")
    elif iguais:
        assunto = f"Cadastro no treinamento: {' / '.join(cursos)}"
        if len(cursos) == 1:
            linhas.append("Informamos que você foi cadastrado(a) na plataforma FormaSeg e matriculado(a) "
                          f"no treinamento {cursos[0]}.")
        else:
            linhas.append("Informamos que você foi cadastrado(a) na plataforma FormaSeg e matriculado(a) "
                          "nos treinamentos:")
            linhas += [f"- {c}" for c in cursos]
    else:
        assunto = "Cadastro nos treinamentos FormaSeg"
        linhas.append("Informamos que vocês foram cadastrados na plataforma FormaSeg, nos treinamentos abaixo:")
        linhas.append("")
        for aluno, seus in zip(alunos, cursos_por_aluno):
            nome = f"{aluno.nome} {aluno.sobrenome}".strip()
            linhas.append(f"- {nome}: {', '.join(seus) if seus else 'somente cadastro'}")

    linhas += [
        "",
        f"Acesso: {URL_PAINEL}",
        "Usuário: o seu e-mail (o mesmo para o qual esta mensagem foi enviada)",
        "Senha: o seu CPF, somente números",
        "",
        "Qualquer dúvida, estamos à disposição.",
    ]
    return destinatarios, assunto, "\n".join(linhas)


def link_mailto(destinatarios: list[str], assunto: str, corpo: str = "") -> str:
    """Link mailto: com destinatários separados por vírgula (RFC 6068)."""
    para = ",".join(quote(e, safe="@") for e in destinatarios)
    partes = [f"subject={quote(assunto, safe='')}"]
    if corpo:
        partes.append(f"body={quote(corpo.replace(chr(10), chr(13) + chr(10)), safe='')}")
    return f"mailto:{para}?{'&'.join(partes)}"


def preparar_link(destinatarios: list[str], assunto: str, corpo: str) -> tuple[str, bool, bool]:
    """Devolve (link, com_destinatarios, com_corpo), tirando o que não couber."""
    for com_dest, com_corpo in ((True, True), (True, False), (False, False)):
        link = link_mailto(destinatarios if com_dest else [], assunto, corpo if com_corpo else "")
        if len(link) <= LIMITE_MAILTO:
            return link, com_dest, com_corpo
    return link_mailto([], "Cadastro na plataforma FormaSeg"), False, False
