from cadastro_formaseg.config import carregar_cursos


def test_lista_de_cursos():
    cursos = carregar_cursos()
    assert len(cursos) == 12
    assert len({c.id for c in cursos}) == 12
    assert all(c.id.isdigit() for c in cursos)
