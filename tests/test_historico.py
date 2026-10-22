from cadastro_formaseg.gerador import Aluno
from cadastro_formaseg.historico import chave_nome, reaproveitar_emails


def aluno(nome, sobrenome, email):
    return Aluno(nome=nome, sobrenome=sobrenome, cpf="", email=email)


def test_ja_cadastrado_volta_com_o_mesmo_email():
    cadastros = {chave_nome("Maria de Souza"): ("maria.souza@gapgestao.com.br", "2026-10-20 09:00")}
    maria = aluno("MARIA", "DE SOUZA", "maria.souza2@gapgestao.com.br")
    ana = aluno("Ana", "Lima", "ana.lima@gapgestao.com.br")
    assert reaproveitar_emails([maria, ana], cadastros) == 1
    assert maria.email == "maria.souza@gapgestao.com.br"
    assert maria.avisos == ["já cadastrado em 2026-10-20"]
    assert ana.email == "ana.lima@gapgestao.com.br" and not ana.avisos


def test_homonimos_na_mesma_ficha_nao_ficam_com_o_mesmo_email():
    cadastros = {chave_nome("João Silva"): ("joao.silva@gapgestao.com.br", "2026-10-20 09:00")}
    a1 = aluno("João", "Silva", "joao.silva2@gapgestao.com.br")
    a2 = aluno("Joao", "Silva", "joao.silva3@gapgestao.com.br")
    reaproveitar_emails([a1, a2], cadastros)
    assert a1.email == "joao.silva@gapgestao.com.br"
    assert a2.email == "joao.silva3@gapgestao.com.br"
