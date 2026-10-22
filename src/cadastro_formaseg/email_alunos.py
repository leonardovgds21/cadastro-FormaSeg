"""Monta o e-mail que avisa os alunos do cadastro e abre no Outlook.

O Outlook novo não tem a automação (COM) do Outlook clássico, então o
e-mail é aberto por um link mailto:, que o Windows entrega ao app de e-mail
padrão. Links muito longos são cortados pelo Windows; nesse caso o corpo vai
para a área de transferência e o link leva só destinatários e assunto.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from .config import URL_PAINEL
from .gerador import Aluno

# O Windows aceita ~2048 caracteres num link; fica uma folga.
LIMITE_MAILTO = 1900
# Podem ir sem codificar no assunto/corpo de um mailto (RFC 6068), o que encurta o link.
SEGUROS = "!'()*,:@/"


ASSUNTO = "Treinamentos para atualização do certificado"

MODELO = """Olá!

Segue treinamentos para atualização do certificado!

A empresa GAP GESTÃO AMBIENTAL E PROJETOS LTDA. lhe inscreveu no curso de:

{cursos}

Ficamos felizes que você esteja se aperfeiçoando.

Os cursos possuem conteúdos completos e vídeos para melhor fixação dos temas, conforme exigências do \
Ministério do Trabalho e Emprego e Secretaria de Estado da Educação e do Desporto.

O prazo padrão de término do curso é de 30 dias após a data de início, sendo que a empresa poderá \
estabelecer prazos menores caso necessário.

Data de Início: {data}

• Login: seu e-mail GAP
• Senha: seu CPF
• Acesse: {url}

Lembramos que a empresa irá acompanhar todo o seu desenvolvimento no curso, como acessos, conteúdos \
estudados, notas e certificação.

Bons estudos!

Qualquer dúvida entre em contato conosco."""


@dataclass
class Email:
    destinatarios: list[str]
    assunto: str
    corpo: str
    cursos: list[str]


def montar_emails(alunos: list[Aluno], nome_por_id: dict[str, str], data: str) -> tuple[list[Email], list[Aluno]]:
    """Um e-mail para cada conjunto de treinamentos (o texto diz "lhe inscreveu no curso de").

    Devolve (e-mails, alunos sem treinamento), que ficam de fora.
    """
    grupos: dict[tuple[str, ...], list[str]] = {}
    sem_curso = []
    for aluno in alunos:
        if not aluno.cursos:
            sem_curso.append(aluno)
        elif aluno.email:
            grupos.setdefault(tuple(aluno.cursos), []).append(aluno.email)
    emails = []
    for ids, destinatarios in grupos.items():
        cursos = [nome_por_id.get(c, f"curso {c}") for c in ids]
        corpo = MODELO.format(cursos="\n".join(f"• {c}" for c in cursos), data=data, url=URL_PAINEL)
        emails.append(Email(destinatarios, ASSUNTO, corpo, cursos))
    return emails, sem_curso


def link_mailto(destinatarios: list[str], assunto: str, corpo: str = "") -> str:
    """Link mailto: com destinatários separados por vírgula (RFC 6068)."""
    para = ",".join(quote(e, safe="@") for e in destinatarios)
    partes = [f"subject={quote(assunto, safe=SEGUROS)}"]
    if corpo:
        partes.append(f"body={quote(corpo.replace(chr(10), chr(13) + chr(10)), safe=SEGUROS)}")
    return f"mailto:{para}?{'&'.join(partes)}"


def preparar_link(destinatarios: list[str], assunto: str, corpo: str) -> tuple[str, bool, bool]:
    """Devolve (link, com_destinatarios, com_corpo), tirando o que não couber."""
    for com_dest, com_corpo in ((True, True), (True, False), (False, False)):
        link = link_mailto(destinatarios if com_dest else [], assunto, corpo if com_corpo else "")
        if len(link) <= LIMITE_MAILTO:
            return link, com_dest, com_corpo
    return link_mailto([], "Cadastro na plataforma FormaSeg"), False, False
