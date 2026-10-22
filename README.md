# cadastro-FormaSeg

App desktop (Windows) que lê a ficha de registro de empregado (PDF do Domínio),
gera e-mail, usuário e senha, e cadastra/matricula os alunos na plataforma
FormaSeg (gapgestao.sstnr.com) pela importação de CSV, com um navegador
invisível. Não usa IA.

## Usar

Copie a pasta `executavel/CadastroFormaSeg` para o computador e abra
`CadastroFormaSeg.exe`. Instruções em `LEIA-ME.txt`.

## Estrutura

| Arquivo | O que faz |
|---|---|
| `src/cadastro_formaseg/ficha.py` | Lê o PDF (um colaborador por página) |
| `src/cadastro_formaseg/gerador.py` | Regras de e-mail/senha e CSVs `import.csv` e `import-curso.csv` |
| `src/cadastro_formaseg/gui.py` | Tela (Tkinter) |
| `src/cadastro_formaseg/email_alunos.py` | E-mail aos alunos (link mailto: para o Outlook) |
| `src/cadastro_formaseg/plataforma.py` | Login e importação no painel (Selenium + Edge) |
| `src/cadastro_formaseg/credenciais.py` | Login no Cofre de Credenciais do Windows |
| `config/cursos.json` | Lista de treinamentos (nome e ID) |

## Desenvolver

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m pytest
python main.py
```

`build.bat` roda os testes e gera `executavel/CadastroFormaSeg`.

As fichas e CSVs reais ficam em `assets/` e `saida/`, que **não** vão para o
Git (dados pessoais).
