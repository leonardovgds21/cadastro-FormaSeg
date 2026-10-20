"""Tela do app: abre a ficha, mostra os dados para conferir e gera os CSVs."""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, historico
from .config import carregar_cursos, pasta_saida
from .ficha import ler_fichas
from .gerador import Aluno, gerar_csv_alunos, gerar_csv_cursos, montar_alunos, validar

SEM_MATRICULA = "Somente cadastro (sem matrícula)"

CAMPOS = [
    ("nome", "Nome"), ("sobrenome", "Sobrenome"), ("cpf", "CPF"),
    ("email", "E-mail / usuário"), ("senha", "Senha"),
    ("cep", "CEP"), ("endereco", "Endereço"), ("numero", "Número"),
    ("complemento", "Complemento"), ("bairro", "Bairro"), ("cidade", "Cidade"),
    ("estado", "Estado (UF)"), ("telefone", "Telefone"), ("celular", "Celular"),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Cadastro FormaSeg {__version__}")
        self.geometry("1100x680")
        self.minsize(960, 600)

        self.cursos = carregar_cursos()
        self.nome_por_id = {c.id: c.nome for c in self.cursos}
        self.id_por_nome = {c.nome: c.id for c in self.cursos}
        self.alunos: list[Aluno] = []
        self.atual: Aluno | None = None
        self.vars = {campo: tk.StringVar() for campo, _ in CAMPOS}
        for campo, var in self.vars.items():
            var.trace_add("write", lambda *_, c=campo: self._campo_editado(c))
        self._carregando = False
        self.ultima_saida: Path | None = None

        self._montar_tela()

    # ---------- montagem ----------
    def _montar_tela(self):
        topo = ttk.Frame(self, padding=8)
        topo.pack(fill="x")
        ttk.Button(topo, text="Abrir ficha (PDF)...", command=self.abrir_ficha).pack(side="left")
        self.lbl_arquivo = ttk.Label(topo, text="Nenhuma ficha aberta")
        self.lbl_arquivo.pack(side="left", padx=10)

        corpo = ttk.PanedWindow(self, orient="horizontal")
        corpo.pack(fill="both", expand=True, padx=8)

        # Lista de colaboradores
        esquerda = ttk.Frame(corpo)
        corpo.add(esquerda, weight=2)
        colunas = ("nome", "email", "cursos", "avisos")
        self.tabela = ttk.Treeview(esquerda, columns=colunas, show="headings", selectmode="browse")
        for col, titulo, largura in [
            ("nome", "Colaborador", 200), ("email", "E-mail", 220),
            ("cursos", "Cursos", 60), ("avisos", "Avisos", 160),
        ]:
            self.tabela.heading(col, text=titulo)
            self.tabela.column(col, width=largura, anchor="w")
        self.tabela.tag_configure("aviso", foreground="#b45309")
        self.tabela.pack(fill="both", expand=True)
        self.tabela.bind("<<TreeviewSelect>>", lambda _: self._selecionar())

        # Formulário
        direita = ttk.Frame(corpo, padding=(10, 0))
        corpo.add(direita, weight=3)
        form = ttk.LabelFrame(direita, text="Dados do colaborador (confira e corrija se precisar)", padding=8)
        form.pack(fill="x")
        for i, (campo, rotulo) in enumerate(CAMPOS):
            linha, coluna = divmod(i, 2)
            ttk.Label(form, text=rotulo).grid(row=linha, column=coluna * 2, sticky="w", padx=(0, 4), pady=2)
            ttk.Entry(form, textvariable=self.vars[campo], width=30).grid(
                row=linha, column=coluna * 2 + 1, sticky="we", pady=2, padx=(0, 10))
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        # Treinamentos
        trein = ttk.LabelFrame(direita, text="Treinamentos", padding=8)
        trein.pack(fill="both", expand=True, pady=8)
        self.combo = ttk.Combobox(trein, state="readonly", values=[SEM_MATRICULA] + [c.nome for c in self.cursos])
        self.combo.current(0)
        self.combo.grid(row=0, column=0, sticky="we")
        ttk.Button(trein, text="Adicionar", command=self.adicionar_curso).grid(row=0, column=1, padx=4)
        self.lista_cursos = tk.Listbox(trein, height=5)
        self.lista_cursos.grid(row=1, column=0, sticky="nsew", pady=4)
        botoes = ttk.Frame(trein)
        botoes.grid(row=1, column=1, sticky="n", pady=4)
        ttk.Button(botoes, text="Remover", command=self.remover_curso).pack(fill="x")
        ttk.Button(botoes, text="Aplicar a todos", command=self.aplicar_a_todos).pack(fill="x", pady=4)
        trein.columnconfigure(0, weight=1)
        trein.rowconfigure(1, weight=1)

        # Rodapé
        rodape = ttk.Frame(self, padding=8)
        rodape.pack(fill="x")
        ttk.Button(rodape, text="Gerar CSVs", command=self.gerar_csvs).pack(side="left")
        self.btn_abrir_saida = ttk.Button(rodape, text="Abrir pasta dos CSVs", command=self.abrir_saida, state="disabled")
        self.btn_abrir_saida.pack(side="left", padx=6)
        self._montar_botoes_extras(rodape)

        self.log = tk.Text(self, height=7, state="disabled", wrap="word")
        self.log.pack(fill="x", padx=8, pady=(0, 8))

    def _montar_botoes_extras(self, rodape):
        """Ponto de extensão para botões de outras etapas (ex.: envio)."""

    # ---------- ações ----------
    def abrir_ficha(self):
        caminho = filedialog.askopenfilename(
            title="Escolha a ficha de empregado", filetypes=[("PDF", "*.pdf")])
        if not caminho:
            return
        try:
            colaboradores = ler_fichas(caminho)
        except Exception as erro:  # PDF corrompido, protegido etc.
            messagebox.showerror("Erro ao ler a ficha", str(erro))
            return
        if not colaboradores:
            messagebox.showwarning("Ficha", "Nenhuma ficha de registro de empregado encontrada nesse PDF.")
            return
        existentes = self._emails_existentes()
        self.alunos = montar_alunos(colaboradores, existentes)
        self.lbl_arquivo.config(text=f"{Path(caminho).name}  ({len(self.alunos)} colaborador(es))")
        self.escrever(f"Ficha lida: {len(self.alunos)} colaborador(es).")
        self._recarregar_tabela(selecionar=0)

    def _emails_existentes(self) -> set[str]:
        return historico.emails_registrados()

    def adicionar_curso(self):
        if not self.atual:
            return
        escolha = self.combo.get()
        if escolha == SEM_MATRICULA:
            self.atual.cursos.clear()
        else:
            curso_id = self.id_por_nome[escolha]
            if curso_id not in self.atual.cursos:
                self.atual.cursos.append(curso_id)
        self._mostrar_cursos()
        self._atualizar_linha(self.atual)

    def remover_curso(self):
        if not self.atual:
            return
        for i in reversed(self.lista_cursos.curselection()):
            if self.atual.cursos:
                del self.atual.cursos[i]
        self._mostrar_cursos()
        self._atualizar_linha(self.atual)

    def aplicar_a_todos(self):
        if not self.atual:
            return
        for aluno in self.alunos:
            aluno.cursos = list(self.atual.cursos)
            self._atualizar_linha(aluno)
        self.escrever("Treinamentos aplicados a todos os colaboradores.")

    def gerar_csvs(self) -> Path | None:
        if not self.alunos:
            messagebox.showinfo("Gerar CSVs", "Abra uma ficha primeiro.")
            return None
        problemas = [
            f"{a.nome} {a.sobrenome}: {', '.join(erros)}"
            for a in self.alunos if (erros := validar(a))
        ]
        if problemas:
            messagebox.showerror("Corrija antes de gerar", "\n".join(problemas))
            return None
        emails = [a.email for a in self.alunos]
        if len(set(emails)) != len(emails):
            messagebox.showerror("Corrija antes de gerar", "Há e-mails repetidos na lista.")
            return None

        pasta = pasta_saida() / datetime.now().strftime("%Y-%m-%d_%H%M%S")
        pasta.mkdir(parents=True)
        gerar_csv_alunos(self.alunos, pasta / "import.csv")
        cursos = gerar_csv_cursos(self.alunos, pasta / "import-curso.csv")
        historico.registrar(self.alunos)
        self.ultima_saida = pasta
        self.btn_abrir_saida.config(state="normal")
        self.escrever(f"CSVs gerados em {pasta}")
        if not cursos:
            self.escrever("Nenhum treinamento escolhido: só o cadastro (import.csv) foi gerado.")
        return pasta

    def abrir_saida(self):
        if not self.ultima_saida:
            return
        if sys.platform == "win32":
            os.startfile(self.ultima_saida)  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(self.ultima_saida)])

    # ---------- tabela e formulário ----------
    def _recarregar_tabela(self, selecionar: int | None = None):
        self.tabela.delete(*self.tabela.get_children())
        for i, aluno in enumerate(self.alunos):
            self.tabela.insert("", "end", iid=str(i))
            self._atualizar_linha(aluno)
        if selecionar is not None and self.alunos:
            self.tabela.selection_set(str(selecionar))

    def _atualizar_linha(self, aluno: Aluno):
        iid = str(self.alunos.index(aluno))
        avisos = "; ".join(aluno.avisos + validar(aluno))
        self.tabela.item(
            iid,
            values=(f"{aluno.nome} {aluno.sobrenome}", aluno.email, len(aluno.cursos) or "-", avisos),
            tags=("aviso",) if avisos else (),
        )

    def _selecionar(self):
        selecao = self.tabela.selection()
        if not selecao:
            return
        self.atual = self.alunos[int(selecao[0])]
        self._carregando = True
        for campo, var in self.vars.items():
            var.set(getattr(self.atual, campo))
        self._carregando = False
        self._mostrar_cursos()

    def _campo_editado(self, campo: str):
        if self._carregando or not self.atual:
            return
        setattr(self.atual, campo, self.vars[campo].get().strip())
        self._atualizar_linha(self.atual)

    def _mostrar_cursos(self):
        self.lista_cursos.delete(0, "end")
        if not self.atual:
            return
        if not self.atual.cursos:
            self.lista_cursos.insert("end", SEM_MATRICULA)
        for curso_id in self.atual.cursos:
            self.lista_cursos.insert("end", f"{self.nome_por_id.get(curso_id, '?')}  [{curso_id}]")

    def escrever(self, texto: str):
        self.log.config(state="normal")
        self.log.insert("end", f"{datetime.now():%H:%M:%S}  {texto}\n")
        self.log.see("end")
        self.log.config(state="disabled")
        self.update_idletasks()


def main():
    App().mainloop()
