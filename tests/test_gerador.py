from cadastro_formaseg.ficha import Colaborador
from cadastro_formaseg.gerador import (
    COLUNAS_ALUNOS, cpf_valido, email_base, email_disponivel, formatar_telefone,
    gerar_csv_alunos, gerar_csv_cursos, montar_alunos, separar_nome,
)

CPF_FICTICIO = "123.456.789-09"


def test_email_base():
    assert email_base("MARIA APARECIDA DE SOUZA") == "maria.souza"
    assert email_base("JOÃO DA CONCEIÇÃO") == "joao.conceicao"
    assert email_base("JOSE DA SILVA FILHO") == "jose.silva"
    assert email_base("PEDRO D'ÁVILA JÚNIOR") == "pedro.davila"
    assert email_base("ANA MARIA-CLARA LIMA") == "ana.lima"


def test_homonimos_recebem_numero():
    existentes = {"maria.souza@gapgestao.com.br", "maria.souza2@gapgestao.com.br"}
    assert email_disponivel("maria.souza", set()) == "maria.souza@gapgestao.com.br"
    assert email_disponivel("maria.souza", existentes) == "maria.souza3@gapgestao.com.br"


def test_homonimos_no_mesmo_lote():
    c = Colaborador(nome_completo="MARIA DE SOUZA", cpf=CPF_FICTICIO)
    a1, a2 = montar_alunos([c, c], set())
    assert a1.email == "maria.souza@gapgestao.com.br"
    assert a2.email == "maria.souza2@gapgestao.com.br"


def test_senha_e_nome():
    c = Colaborador(nome_completo="MARIA APARECIDA DE SOUZA", cpf=CPF_FICTICIO, celular="34-984328671")
    (a,) = montar_alunos([c], set())
    assert (a.nome, a.sobrenome) == ("Maria", "Aparecida de Souza")
    assert a.senha == "12345678909"
    assert a.celular == "(34) 98432-8671"
    assert not a.avisos


def test_separar_nome():
    assert separar_nome("ALEXANDRE SILVA DA COSTA") == ("Alexandre", "Silva da Costa")


def test_cpf_valido():
    assert cpf_valido(CPF_FICTICIO)
    assert not cpf_valido("123.456.789-00")
    assert not cpf_valido("111.111.111-11")


def test_formatar_telefone():
    assert formatar_telefone("62-33334444") == "(62) 3333-4444"
    assert formatar_telefone("") == ""


def test_csvs(tmp_path):
    c = Colaborador(nome_completo="MARIA DE SOUZA", cpf=CPF_FICTICIO)
    (a,) = montar_alunos([c], set())
    alunos_csv = gerar_csv_alunos([a], tmp_path / "import.csv")
    texto = alunos_csv.read_bytes().decode("utf-8")
    linhas = texto.split("\r\n")
    assert linhas[0] == ";".join(COLUNAS_ALUNOS)
    assert linhas[1].startswith("Maria;de Souza;123.456.789-09;")
    assert ";maria.souza@gapgestao.com.br;maria.souza@gapgestao.com.br;12345678909;;;" in linhas[1]

    assert gerar_csv_cursos([a], tmp_path / "import-curso.csv") is None
    a.cursos = ["82557", "84075"]
    cursos_csv = gerar_csv_cursos([a], tmp_path / "import-curso.csv")
    assert cursos_csv.read_bytes().decode("utf-8").split("\r\n")[:3] == [
        "E-mail;Curso/Combo",
        "maria.souza@gapgestao.com.br;82557",
        "maria.souza@gapgestao.com.br;84075",
    ]
