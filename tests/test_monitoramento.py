from openpyxl import Workbook

from cadastro_formaseg.monitoramento import (
    Matricula, ler_exportacao, ler_progresso, nome_certificado, nomes_colados, procurar)


def test_nomes_colados_um_por_linha_sem_repetidos():
    texto = "Maria de Souza\n\n  1. João  da Silva \nMARIA DE SOUZA\r\nAna Lima;Pedro Alves\n"
    assert nomes_colados(texto) == ["Maria de Souza", "João da Silva", "Ana Lima", "Pedro Alves"]


def test_progresso():
    assert ler_progresso("100%") == 100
    assert ler_progresso("15.06%") == 15.06
    assert ler_progresso("15,06 %") == 15.06
    assert ler_progresso("0.5") == 50
    assert ler_progresso("-") is None
    assert Matricula("a", "c", 100.0).concluida
    assert not Matricula("a", "c", 99.9).concluida


def test_le_csv_com_ponto_e_virgula(tmp_path):
    arquivo = tmp_path / "matriculas.csv"
    arquivo.write_text(
        "Aluno;E-mail;Curso;Início;Progresso;Nota\n"
        "bruno matias goncalo de oliveira;bruno.oliveira@x.com;NR 33 – Supervisor De Entrada – Teórico;01/09/26;100%;80.62%\n"
        "Liliana Martins Borges;;NR 33 – Supervisor De Entrada – Teórico;22/10/26;0%;N/D\n", encoding="utf-8-sig")
    m = ler_exportacao(arquivo)
    assert [x.aluno for x in m] == ["bruno matias goncalo de oliveira", "Liliana Martins Borges"]
    assert m[0].progresso == 100 and m[0].concluida and m[0].email == "bruno.oliveira@x.com"
    assert m[1].progresso == 0 and m[1].curso.startswith("NR 33")


def test_le_csv_com_nome_e_sobrenome_separados(tmp_path):
    arquivo = tmp_path / "m.csv"
    arquivo.write_text('"Nome","Sobrenome","Nome do Curso","Progresso (%)"\n"Ana","Lima","NR 06","50"\n',
                       encoding="cp1252")
    m = ler_exportacao(arquivo)
    assert (m[0].aluno, m[0].curso, m[0].progresso) == ("Ana Lima", "NR 06", 50)


def test_le_tabela_html_salva_como_xls(tmp_path):
    arquivo = tmp_path / "m.xls"
    arquivo.write_text("<html><table><tr><th>Aluno</th><th>Curso</th><th>Progresso</th></tr>"
                       "<tr><td>José  Ávila</td><td>NR 35</td><td>100%</td></tr></table></html>", encoding="utf-8")
    m = ler_exportacao(arquivo)
    assert (m[0].aluno, m[0].curso, m[0].concluida) == ("José Ávila", "NR 35", True)


def test_le_xlsx_com_titulo_antes_do_cabecalho(tmp_path):
    arquivo = tmp_path / "m.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["Relatório de matrículas"])
    ws.append(["Aluno", "Curso", "Progresso"])
    ws.append(["Ana Lima", "NR 06", "75%"])
    wb.save(arquivo)
    m = ler_exportacao(arquivo)
    assert (m[0].aluno, m[0].progresso) == ("Ana Lima", 75)


def test_procura_sem_acento_e_caixa_e_por_palavras():
    lista = [
        Matricula("bruno matias goncalo de oliveira", "NR 33", 100),
        Matricula("Bruno Matias Gonçalo de Oliveira", "NR 35", 10),
        Matricula("Ana Lima", "NR 06", 0),
    ]
    r = procurar(["BRUNO MATIAS GONÇALO DE OLIVEIRA", "bruno oliveira", "Carlos Souza"], lista)
    assert [m.curso for m in r[0].matriculas] == ["NR 33", "NR 35"]
    assert [m.curso for m in r[1].matriculas] == ["NR 33", "NR 35"]
    assert r[2].matriculas == []


def test_nome_do_certificado():
    assert nome_certificado("bruno de oliveira", "NR 33 – Supervisor: Teórico") == \
        "Bruno de Oliveira - NR 33 – Supervisor Teórico.pdf"
