from urllib.parse import unquote

from cadastro_formaseg.email_alunos import LIMITE_MAILTO, link_mailto, montar_emails, preparar_link
from cadastro_formaseg.gerador import Aluno

CURSOS = {"82853": "NR 33 – Supervisor de Entrada – Teórico", "74122": "NR 18 – Integração (16 horas)"}


def aluno(nome, email, cursos=()):
    return Aluno(nome=nome, sobrenome="Souza", cpf="", email=email, cursos=list(cursos))


def test_texto_padrao_com_treinamentos_e_data():
    emails, sem = montar_emails(
        [aluno("Maria", "maria@x.com", ["82853", "74122"]), aluno("Ana", "ana@x.com", ["82853", "74122"])],
        CURSOS, "22/10/2026")
    assert not sem and len(emails) == 1
    e = emails[0]
    assert e.destinatarios == ["maria@x.com", "ana@x.com"]
    assert e.assunto == "Treinamentos para atualização do certificado"
    assert e.corpo.startswith("Olá!\n\nSegue treinamentos para atualização do certificado!")
    assert "lhe inscreveu no curso de:\n\n• NR 33 – Supervisor de Entrada – Teórico\n• NR 18 – Integração (16 horas)\n" in e.corpo
    assert "Data de Início: 22/10/2026" in e.corpo
    assert "• Acesse: https://gapgestao.sstnr.com/painel/" in e.corpo
    assert "exigências do Ministério do Trabalho" in e.corpo  # sem quebra de linha no meio
    assert e.corpo.endswith("Qualquer dúvida entre em contato conosco.")


def test_um_email_por_treinamento_e_sem_matricula_fica_fora():
    emails, sem = montar_emails(
        [aluno("Maria", "m@x.com", ["82853"]), aluno("Ana", "a@x.com", ["74122"]),
         aluno("Rui", "r@x.com"), aluno("Lia", "l@x.com", ["82853"])], CURSOS, "22/10/2026")
    assert [e.destinatarios for e in emails] == [["m@x.com", "l@x.com"], ["a@x.com"]]
    assert [a.nome for a in sem] == ["Rui"]


def test_texto_padrao_cabe_no_link_com_alguns_alunos():
    alunos = [aluno("A", f"fulano.sobrenome{i}@gapgestao.com.br", ["82853", "74122"]) for i in range(5)]
    e = montar_emails(alunos, CURSOS, "22/10/2026")[0][0]
    _, dest, corpo = preparar_link(e.destinatarios, e.assunto, e.corpo)
    assert dest and corpo


def test_link_mailto():
    link = link_mailto(["a@x.com", "b@x.com"], "Olá & tchau", "linha 1\nlinha 2")
    assert link.startswith("mailto:a@x.com,b@x.com?subject=")
    assert "&" not in link.split("subject=")[1].split("&body=")[0]
    assert unquote(link.split("body=")[1]) == "linha 1\r\nlinha 2"


def test_link_longo_tira_corpo_e_depois_destinatarios():
    poucos = [f"aluno{i}@gapgestao.com.br" for i in range(5)]
    _, dest, corpo = preparar_link(poucos, "Assunto", "texto")
    assert dest and corpo
    _, dest, corpo = preparar_link(poucos, "Assunto", "x" * LIMITE_MAILTO)
    assert dest and not corpo
    muitos = [f"aluno{i}@gapgestao.com.br" for i in range(200)]
    link, dest, corpo = preparar_link(muitos, "Assunto", "texto")
    assert not dest and not corpo and len(link) <= LIMITE_MAILTO


def test_corpo_html_no_padrao_gap():
    e = montar_emails([aluno("Maria", "m@x.com", ["82853", "74122"])], CURSOS, "22/10/2026")[0][0]
    assert "data:image/png;base64," in e.html  # logo embutida
    assert "Olá! Tudo bem?" in e.html and "ATENÇÃO:" in e.html
    assert "1. Seus treinamentos" in e.html and "nos cursos abaixo" in e.html
    assert "NR 33 – Supervisor de Entrada – Teórico" in e.html and "22/10/2026" in e.html
    assert 'href="https://gapgestao.sstnr.com/painel/"' in e.html
    assert "seu CPF" in e.html


def test_corpo_html_um_curso_e_escape():
    e = montar_emails([aluno("Maria", "m@x.com", ["9"])], {"9": "NR <A> & B"}, "01/01/2027")[0][0]
    assert "1. Seu treinamento" in e.html and "no curso abaixo" in e.html
    assert "NR &lt;A&gt; &amp; B" in e.html


def test_logo_sem_arquivo_vira_texto(tmp_path):
    from cadastro_formaseg.email_alunos import logo_html
    assert "<img" not in logo_html(tmp_path / "nao_existe.png")


def test_formato_cf_html_posicoes():
    from cadastro_formaseg.area_transferencia import formato_cf_html
    dados = formato_cf_html("<b>Olá</b>")
    cab = dict(l.split(":", 1) for l in dados.split(b"\r\n")[1:5] for l in [l.decode()])
    assert dados[int(cab["StartFragment"]):int(cab["EndFragment"])].decode("utf-8") == "<b>Olá</b>"
    assert dados[int(cab["StartHTML"]):int(cab["EndHTML"])].decode().startswith("<html>")
    assert int(cab["EndHTML"]) == len(dados)
