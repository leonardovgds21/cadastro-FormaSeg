"""Tela do app: abre a ficha, mostra os dados para conferir e gera os CSVs."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, credenciais, email_alunos, historico
from .config import carregar_cursos, pasta_saida
from .ficha import ler_fichas
from .gerador import Aluno, gerar_csv_alunos, gerar_csv_cursos, montar_alunos, validar

SEM_MATRICULA = "Somente cadastro (sem matrícula)"
AVISO_JA_EXISTE = "já existe, só matrícula (confira se é a mesma pessoa)"

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
        self.fila: queue.Queue = queue.Queue()
        self.enviando = False

        self._montar_tela()
        self.after(200, self._processar_fila)

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
        self.btn_email = ttk.Button(rodape, text="Enviar e-mail aos alunos", command=self.enviar_email, state="disabled")
        self.btn_email.pack(side="left")
        self._montar_botoes_extras(rodape)

        self.log = tk.Text(self, height=7, state="disabled", wrap="word")
        self.log.pack(fill="x", padx=8, pady=(0, 8))

    def _montar_botoes_extras(self, rodape):
        self.btn_enviar = ttk.Button(rodape, text="Enviar para a plataforma", command=self.enviar)
        self.btn_enviar.pack(side="right")
        self.modo_teste = tk.BooleanVar(value=False)
        self.mostrar_navegador = tk.BooleanVar(value=False)
        ttk.Checkbutton(rodape, text="Mostrar navegador", variable=self.mostrar_navegador).pack(side="right", padx=8)
        ttk.Checkbutton(rodape, text="Modo teste (não confirma a importação)",
                        variable=self.modo_teste).pack(side="right", padx=8)
        ttk.Button(rodape, text="Esquecer login salvo", command=self.esquecer_login).pack(side="right", padx=8)

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
        ja_cadastrados = historico.reaproveitar_emails(self.alunos, historico.ultimo_cadastro_por_nome())
        self.lbl_arquivo.config(text=f"{Path(caminho).name}  ({len(self.alunos)} colaborador(es))")
        self.escrever(f"Ficha lida: {len(self.alunos)} colaborador(es).")
        if ja_cadastrados:
            self.escrever(f"{ja_cadastrados} já cadastrado(s) neste computador: mantive o e-mail usado antes.")
        self.btn_email.config(state="normal")
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
        novos = gerar_csv_alunos(self.alunos, pasta / "import.csv")
        cursos = gerar_csv_cursos(self.alunos, pasta / "import-curso.csv")
        historico.registrar(self.alunos)
        self.ultima_saida = pasta
        self.btn_abrir_saida.config(state="normal")
        self.escrever(f"CSVs gerados em {pasta}")
        if not novos:
            self.escrever("Todos já existem na plataforma: só a matrícula (import-curso.csv) foi gerada.")
        if not cursos:
            self.escrever("Nenhum treinamento escolhido: só o cadastro (import.csv) foi gerado.")
        sem_nada = [f"{a.nome} {a.sobrenome}" for a in self.alunos if a.ja_existe and not a.cursos]
        if sem_nada:
            self.escrever("Já existem e estão sem treinamento (nada a fazer): " + ", ".join(sem_nada))
        return pasta

    def abrir_saida(self):
        if not self.ultima_saida:
            return
        if sys.platform == "win32":
            os.startfile(self.ultima_saida)  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(self.ultima_saida)])

    # ---------- e-mail aos alunos ----------
    def enviar_email(self):
        """Abre e-mails novos no Outlook (app de e-mail padrão): um por conjunto de treinamentos."""
        if not self.alunos:
            return
        emails, sem_curso = email_alunos.montar_emails(
            self.alunos, self.nome_por_id, datetime.now().strftime("%d/%m/%Y"))
        if sem_curso:
            nomes = ", ".join(f"{a.nome} {a.sobrenome}" for a in sem_curso)
            self.escrever(f"Sem treinamento, ficaram fora do e-mail: {nomes}")
        if not emails:
            messagebox.showinfo("E-mail aos alunos", "Escolha o treinamento dos alunos antes de enviar o e-mail.")
            return
        for n, email in enumerate(emails, 1):
            if n > 1 and not messagebox.askokcancel(
                    "E-mail aos alunos",
                    f"Agora o e-mail {n} de {len(emails)} (alunos de outro treinamento):\n\n"
                    + "\n".join(email.cursos)):
                return
            if not self._abrir_email(email):
                return

    def _abrir_email(self, email: email_alunos.Email) -> bool:
        link, com_dest, com_corpo = email_alunos.preparar_link(email.destinatarios, email.assunto, email.corpo)
        destinatarios = "; ".join(email.destinatarios)
        try:
            if sys.platform == "win32":
                os.startfile(link)  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", link])
        except OSError as erro:
            self._copiar(destinatarios)
            messagebox.showerror(
                "E-mail aos alunos",
                f"Não consegui abrir o app de e-mail ({erro}).\n\n"
                "Os e-mails dos alunos foram copiados: cole no campo Para de um e-mail novo.\n\n"
                "Dica: no Windows, em Configurações > Aplicativos > Aplicativos padrão, "
                "escolha o Outlook (novo) para o tipo de link MAILTO.")
            return False
        self.escrever(f"E-mail aberto ({', '.join(email.cursos)}) para: {destinatarios}")
        if not com_dest:
            self._copiar(destinatarios)
            messagebox.showinfo("E-mail aos alunos",
                                "São muitos destinatários para caber no link. Os e-mails foram copiados:\n"
                                "cole no campo Para (ou Cco) do e-mail que abriu.\n\n"
                                "Clique OK depois de colar para copiar o texto da mensagem.")
        if not com_corpo:
            self._copiar(email.corpo)
            messagebox.showinfo("E-mail aos alunos",
                                "O texto da mensagem é grande demais para o link e foi copiado:\n"
                                "cole no corpo do e-mail (Ctrl+V).")
        else:
            self._copiar(destinatarios)
        return True

    def _copiar(self, texto: str):
        self.clipboard_clear()
        self.clipboard_append(texto)
        self.update()

    # ---------- envio para a plataforma ----------
    def enviar(self):
        if self.enviando:
            return
        if not self.alunos:
            messagebox.showinfo("Enviar", "Abra uma ficha primeiro.")
            return
        problemas = [a for a in self.alunos if validar(a)]
        if problemas:
            self.gerar_csvs()  # mostra os problemas
            return
        login = DialogoLogin(self)
        if not login.resultado:
            return
        usuario, senha, lembrar = login.resultado
        if lembrar:
            credenciais.salvar(usuario, senha)
        self.enviando = True
        self.btn_enviar.config(state="disabled")
        threading.Thread(
            target=self._enviar_em_segundo_plano,
            args=(usuario, senha, self.modo_teste.get(), self.mostrar_navegador.get()),
            daemon=True,
        ).start()

    def _enviar_em_segundo_plano(self, usuario, senha, teste, visivel):
        from .plataforma import ErroPlataforma, Plataforma

        log = lambda texto: self.fila.put(("log", texto))  # noqa: E731
        try:
            with Plataforma(log=log, visivel=visivel) as p:
                p.login(usuario, senha)
                log("Conferindo se os e-mails já existem na plataforma...")
                try:
                    existentes = p.emails_existentes([a.email for a in self.alunos])
                except ErroPlataforma as erro:
                    log(f"AVISO: {erro}")
                    if not teste and not self._perguntar(
                            "Não consegui conferir se os e-mails já existem na plataforma.\n\n"
                            "Se algum já existir, a importação pode alterar o cadastro dessa pessoa.\n\n"
                            "Continuar mesmo assim?"):
                        log("Envio cancelado.")
                        return
                    existentes = set()
                self.fila.put(("ja_existem", existentes))
                self.fila.put(("gerar", None))
                pasta = self._aguardar_csvs()
                if not pasta:
                    return
                usuarios = pasta / "import.csv"
                if usuarios.exists():
                    p.importar_usuarios(usuarios, confirmar=not teste)
                else:
                    log("Nenhum usuário novo para cadastrar.")
                cursos = pasta / "import-curso.csv"
                if cursos.exists():
                    if not teste and usuarios.exists():
                        time.sleep(3)  # dá tempo da plataforma criar os usuários
                    p.importar_matriculas(cursos, confirmar=not teste)
                self.fila.put(("fim", "Modo teste concluído." if teste else "Envio concluído. Confira no painel."))
        except ErroPlataforma as erro:
            self.fila.put(("erro", str(erro)))
        except Exception as erro:  # qualquer falha inesperada do navegador
            # A mensagem do Selenium traz um stacktrace sem utilidade; fica só a 1ª linha.
            detalhe = (getattr(erro, "msg", None) or str(erro)).strip().splitlines()
            self.fila.put(("erro", f"{type(erro).__name__}: {detalhe[0] if detalhe else 'sem detalhes'}"))
        finally:
            self.fila.put(("liberar", None))

    def _perguntar(self, texto: str) -> bool:
        """Faz uma pergunta Sim/Não na tela a partir da tarefa em segundo plano."""
        resposta: queue.Queue = queue.Queue()
        self.fila.put(("perguntar", (texto, resposta)))
        return resposta.get()

    def _aguardar_csvs(self) -> Path | None:
        resposta: queue.Queue = queue.Queue()
        self._resposta_csv = resposta
        return resposta.get()

    def _processar_fila(self):
        try:
            while True:
                tipo, dado = self.fila.get_nowait()
                if tipo == "log":
                    self.escrever(dado)
                elif tipo == "gerar":
                    self._resposta_csv.put(self.gerar_csvs())
                elif tipo == "perguntar":
                    texto, resposta = dado
                    resposta.put(messagebox.askyesno("Conferência de e-mails", texto))
                elif tipo == "ja_existem":
                    self._marcar_existentes(dado)
                elif tipo == "erro":
                    self.escrever(f"ERRO: {dado}")
                    messagebox.showerror("Erro no envio", dado)
                elif tipo == "fim":
                    self.escrever(dado)
                    messagebox.showinfo("Envio", dado)
                elif tipo == "liberar":
                    self.enviando = False
                    self.btn_enviar.config(state="normal")
        except queue.Empty:
            pass
        self.after(200, self._processar_fila)

    def _marcar_existentes(self, existentes: set[str]):
        """Quem já tem o e-mail na plataforma não é cadastrado de novo: só matriculado."""
        existentes = {e.lower() for e in existentes}
        for aluno in self.alunos:
            aluno.ja_existe = aluno.email.lower() in existentes
            self._atualizar_linha(aluno)
        nomes = [f"{a.nome} {a.sobrenome} ({a.email})" for a in self.alunos if a.ja_existe]
        if nomes:
            self.escrever(f"{len(nomes)} já existe(m) na plataforma, só matrícula (confira se é a mesma pessoa): "
                          + "; ".join(nomes))

    def esquecer_login(self):
        credenciais.apagar()
        self.escrever("Login salvo apagado deste computador.")

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
        avisos = "; ".join(([AVISO_JA_EXISTE] if aluno.ja_existe else []) + aluno.avisos + validar(aluno))
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
        if campo == "email":
            self.atual.ja_existe = False  # e-mail novo: a próxima conferência decide
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


class DialogoLogin(tk.Toplevel):
    """Pede usuário e senha do admin. Nada é gravado em arquivo."""

    def __init__(self, pai):
        super().__init__(pai)
        self.title("Login da plataforma")
        self.resizable(False, False)
        self.transient(pai)
        self.resultado = None
        usuario, senha = credenciais.carregar()
        self.usuario = tk.StringVar(value=usuario)
        self.senha = tk.StringVar(value=senha)
        self.lembrar = tk.BooleanVar(value=bool(senha))

        quadro = ttk.Frame(self, padding=12)
        quadro.pack()
        ttk.Label(quadro, text="Usuário (e-mail do admin)").grid(row=0, column=0, sticky="w")
        entrada = ttk.Entry(quadro, textvariable=self.usuario, width=36)
        entrada.grid(row=1, column=0, pady=(0, 8))
        ttk.Label(quadro, text="Senha").grid(row=2, column=0, sticky="w")
        ttk.Entry(quadro, textvariable=self.senha, show="•", width=36).grid(row=3, column=0, pady=(0, 8))
        ttk.Checkbutton(quadro, text="Lembrar neste computador (Cofre do Windows)",
                        variable=self.lembrar).grid(row=4, column=0, sticky="w")
        botoes = ttk.Frame(quadro)
        botoes.grid(row=5, column=0, pady=(10, 0), sticky="e")
        ttk.Button(botoes, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(botoes, text="Entrar e enviar", command=self._ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda _: self._ok())
        entrada.focus_set()
        self.grab_set()
        pai.wait_window(self)

    def _ok(self):
        if self.usuario.get().strip() and self.senha.get():
            self.resultado = (self.usuario.get().strip(), self.senha.get(), self.lembrar.get())
            self.destroy()


def main():
    App().mainloop()
