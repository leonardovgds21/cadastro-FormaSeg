from urllib.parse import unquote

from cadastro_formaseg.email_alunos import LIMITE_MAILTO, link_mailto, montar_email, preparar_link
from cadastro_formaseg.gerador import Aluno

CURSOS = {"82557": "NR 33 – Vigia", "84075": "NR 06 – EPI"}


def aluno(nome, email, cursos=()):
    return Aluno(nome=nome, sobrenome="Souza", cpf="", email=email, cursos=list(cursos))


def test_mesmo_treinamento():
    para, assunto, corpo = montar_email(
        [aluno("Maria", "maria.souza@x.com", ["82557"]), aluno("Ana", "ana.souza@x.com", ["82557"])], CURSOS)
    assert para == ["maria.souza@x.com", "ana.souza@x.com"]
    assert assunto == "Cadastro no treinamento: NR 33 – Vigia"
    assert "matriculado(a) no treinamento NR 33 – Vigia." in corpo
    assert "Senha: o seu CPF" in corpo


def test_sem_matricula():
    _, assunto, corpo = montar_email([aluno("Maria", "m@x.com")], CURSOS)
    assert assunto == "Cadastro na plataforma FormaSeg"
    assert "matriculado" not in corpo


def test_treinamentos_diferentes_lista_por_aluno():
    _, _, corpo = montar_email(
        [aluno("Maria", "m@x.com", ["82557"]), aluno("Ana", "a@x.com", ["84075"]), aluno("Rui", "r@x.com")],
        CURSOS)
    assert "- Maria Souza: NR 33 – Vigia" in corpo
    assert "- Ana Souza: NR 06 – EPI" in corpo
    assert "- Rui Souza: somente cadastro" in corpo


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
