"""Monta o e-mail que avisa os alunos do cadastro e abre no Outlook.

O Outlook novo não tem a automação (COM) do Outlook clássico, então o
e-mail é aberto por um link mailto:, que o Windows entrega ao app de e-mail
padrão, com destinatários e assunto. O mailto: só aceita texto simples, então
o corpo formatado (HTML, no padrão visual da GAP) vai para a área de
transferência e é colado com Ctrl+V. O texto simples fica como reserva.
"""

from __future__ import annotations

import base64
import html
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .config import URL_PAINEL, pasta_config
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
    html: str = ""


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
        emails.append(Email(destinatarios, ASSUNTO, corpo, cursos, corpo_html(cursos, data)))
    return emails, sem_curso


# ---------- corpo em HTML (padrão visual dos e-mails da GAP) ----------
VERDE = "#2e7d4f"
VERDE_ESCURO = "#24613d"
FONTE = "font-family:'Segoe UI',Arial,sans-serif;font-size:14px;color:#333333;"


def logo_html(arquivo: Path | None = None) -> str:
    """Logo da GAP embutida na mensagem (config/logo_gap.png). Sem o arquivo, vai o nome em texto."""
    arquivo = arquivo or pasta_config() / "logo_gap.png"
    try:
        dados = base64.b64encode(arquivo.read_bytes()).decode("ascii")
    except OSError:
        return f'<span style="font-size:32px;font-weight:bold;color:#55606a;">GAP</span>'
    return f'<img src="data:image/png;base64,{dados}" alt="GAP" height="40" style="height:40px;border:0;">'


def _titulo(texto: str) -> str:
    return (f'<p style="margin:22px 0 10px;padding-left:10px;border-left:4px solid {VERDE};'
            f'font-size:17px;font-weight:bold;color:{VERDE_ESCURO};">{texto}</p>')


def _tabela(linhas: list[tuple[str, str]]) -> str:
    celulas = "".join(
        '<tr>'
        f'<td style="{FONTE}width:170px;padding:9px 12px;background:#f5f6f5;font-weight:bold;'
        f'border-bottom:1px solid #e3e6e3;">{rotulo}</td>'
        f'<td style="{FONTE}padding:9px 12px;border-bottom:1px solid #e3e6e3;">{valor}</td>'
        '</tr>'
        for rotulo, valor in linhas
    )
    return (f'<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;'
            f'max-width:620px;border:1px solid #e3e6e3;">{celulas}</table>')


def corpo_html(cursos: list[str], data: str) -> str:
    """O mesmo conteúdo do texto simples, no layout dos e-mails da GAP."""
    url = html.escape(URL_PAINEL)
    link = f'<a href="{url}" style="color:#1a6fb5;">{url}</a>'
    plural = len(cursos) > 1
    linhas_cursos = [("Treinamento" if len(cursos) == 1 else f"Treinamento {n}", html.escape(c))
                     for n, c in enumerate(cursos, 1)]
    return f"""<div style="{FONTE}max-width:640px;line-height:1.5;">
<div style="padding-bottom:12px;border-bottom:1px solid #e3e6e3;">{logo_html()}</div>
<p style="margin:18px 0 10px;">Olá! Tudo bem?</p>
<p style="margin:0 0 10px;">Seguem os treinamentos para <b>atualização do seu certificado</b>. A empresa
<b>GAP GESTÃO AMBIENTAL E PROJETOS LTDA.</b> inscreveu você {"nos cursos abaixo" if plural else "no curso abaixo"}. Ficamos felizes que você
esteja se aperfeiçoando!</p>
<p style="margin:0 0 14px;">Abaixo estão os seus dados de acesso e algumas orientações importantes.</p>
<div style="padding:12px 16px;background:#eef6f0;border-left:4px solid {VERDE};">
<b style="color:{VERDE_ESCURO};">ATENÇÃO:</b> o prazo padrão para concluir o curso é de
<b>30 dias após a data de início</b>. A empresa poderá estabelecer prazos menores, caso necessário.
</div>
{_titulo("1. Seus treinamentos" if plural else "1. Seu treinamento")}
{_tabela(linhas_cursos + [("Data de início", html.escape(data))])}
{_titulo("2. Seus dados de acesso")}
{_tabela([
    ("Plataforma", link),
    ("Login", "<b>seu e-mail GAP</b> (o mesmo que recebeu esta mensagem)"),
    ("Senha", "<b>seu CPF</b> (somente números)"),
])}
{_titulo("3. Como acessar")}
<ol style="margin:0 0 0 0;padding-left:22px;">
<li style="margin-bottom:4px;">Abra a plataforma: {link}</li>
<li style="margin-bottom:4px;">Informe o seu e-mail GAP e a senha (seu CPF, somente números).</li>
<li style="margin-bottom:4px;">Pronto: escolha o treinamento e bons estudos!</li>
</ol>
<p style="margin:18px 0 10px;">Os cursos possuem conteúdos completos e vídeos para melhor fixação dos temas,
conforme exigências do Ministério do Trabalho e Emprego e Secretaria de Estado da Educação e do Desporto.</p>
<p style="margin:0 0 10px;">Lembramos que a empresa irá acompanhar todo o seu desenvolvimento no curso,
como acessos, conteúdos estudados, notas e certificação.</p>
<p style="margin:0;">Bons estudos! Qualquer dúvida, entre em contato conosco.</p>
</div>"""


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
