"""Testes da leitura da ficha.

As fichas reais ficam em assets/ (fora do Git, pois têm dados pessoais).
Sem elas, os testes com PDF são pulados.
"""

from pathlib import Path

import pytest

from cadastro_formaseg.ficha import Colaborador, _capitalizar, _preencher_endereco, ler_fichas

ASSETS = Path(__file__).resolve().parents[1] / "assets"
FICHAS = sorted(ASSETS.glob("Ficha*.pdf"))


@pytest.mark.skipif(not FICHAS, reason="sem fichas de exemplo em assets/")
@pytest.mark.parametrize("pdf", FICHAS, ids=lambda p: p.name)
def test_le_todas_as_paginas_sem_avisos(pdf):
    colaboradores = ler_fichas(pdf)
    assert colaboradores
    for c in colaboradores:
        assert not c.avisos, c.avisos
        assert len(c.nome_completo.split()) >= 2
        assert len(c.cpf) == 14
        assert len(c.cep) == 9
        assert c.endereco and c.numero and c.bairro and c.cidade
        assert len(c.estado) == 2


def test_endereco_sem_complemento():
    c = Colaborador()
    _preencher_endereco(c, "Rua AMAZONAS (LOT BORDAS DO LAGO), 610, SAO LOURENCO, CAMPO VERDE, MT, - CEP: 78844-046")
    assert (c.endereco, c.numero, c.complemento) == ("Rua Amazonas (Lot Bordas do Lago)", "610", "")
    assert (c.bairro, c.cidade, c.estado, c.cep) == ("Sao Lourenco", "Campo Verde", "MT", "78844-046")


def test_endereco_com_complemento():
    c = Colaborador()
    _preencher_endereco(c, "Rua PRAGA, 125, AP 102, LARANJEIRAS, UBERLANDIA, MG, - CEP: 38410-259")
    assert (c.endereco, c.numero, c.complemento, c.bairro) == ("Rua Praga", "125", "Ap 102", "Laranjeiras")


def test_endereco_fora_do_padrao_gera_aviso():
    c = Colaborador()
    _preencher_endereco(c, "Rua X, 1, CIDADE, - CEP: 00000-000")
    assert c.avisos


def test_capitalizar():
    assert _capitalizar("AVENIDA SETE DE SETEMBRO") == "Avenida Sete de Setembro"
