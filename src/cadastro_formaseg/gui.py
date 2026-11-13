"""Tela do app: abre a ficha, mostra os dados para conferir e gera os CSVs."""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, area_transferencia, credenciais, email_alunos, historico
from .config import carregar_cursos, pasta_certificados, pasta_dados, pasta_saida
from .ficha import Colaborador, ler_fichas
from .gerador import Aluno, cpf_valido, gerar_csv_alunos, gerar_csv_cursos, montar_aluno, montar_alunos, validar
from .monitoramento import (
    Resultado, conclusao_no_pdf, curso_combina, ler_exportacao, nome_certificado, nomes_colados, normalizar, procurar)

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
        ttk.Button(topo, text="Digitar colaborador...", command=self.digitar_colaborador).pack(side="left", padx=(6, 0))
        self.lbl_arquivo = ttk.Label(topo, text="Nenhuma ficha aberta")
        self.lbl_arquivo.pack(side="left", padx=10)
        ttk.Button(topo, text="Monitoramento", command=lambda: JanelaMonitoramento(self)).pack(side="right")

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
            messagebox.showwarning("Ficha", "Nenhuma ficha de registro de empregado encontrada nesse PDF.\n\n"
                                   "Se a ficha estiver mal formatada, use \"Digitar colaborador...\".")
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

    def digitar_colaborador(self):
        """Inclui na lista um colaborador digitado à mão (ficha que o app não consegue ler)."""
        dialogo = DialogoColaborador(self)
        if not dialogo.resultado:
            return
        usados = self._emails_existentes() | {a.email for a in self.alunos}
        aluno = montar_aluno(dialogo.resultado, usados)
        aluno.avisos.append("digitado à mão")
        historico.reaproveitar_emails([aluno], historico.ultimo_cadastro_por_nome())
        if aluno.email in {a.email for a in self.alunos}:  # o e-mail reaproveitado já está na lista
            aluno.email = montar_aluno(dialogo.resultado, usados).email
        self.alunos.append(aluno)
        self.lbl_arquivo.config(text=f"{len(self.alunos)} colaborador(es) na lista")
        self.escrever(f"Colaborador digitado: {aluno.nome} {aluno.sobrenome} ({aluno.email}).")
        self.btn_email.config(state="normal")
        self._recarregar_tabela(selecionar=len(self.alunos) - 1)

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
        # O mailto: só aceita texto simples: ele já leva o corpo em texto (quando cabe), para o
        # e-mail nunca abrir vazio. A versão formatada fica copiada para colar por cima (Ctrl+V).
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
        formatado = area_transferencia.copiar_html(email.html, email.corpo, self._hwnd())
        if not formatado:
            self._copiar(email.corpo)
        if com_corpo and formatado:
            aviso = ("O texto já está no e-mail. Para usar a versão formatada (padrão GAP), "
                     "clique no corpo da mensagem, aperte Ctrl+A e depois Ctrl+V.")
        elif com_corpo:
            aviso = "O texto já está no e-mail."
        else:
            aviso = ("O texto é grande demais para o link e foi copiado: clique no corpo da "
                     "mensagem e cole com Ctrl+V.")
        messagebox.showinfo("E-mail aos alunos", f"{aviso}\n\nConfira e clique em Enviar no Outlook.")
        return True

    def _hwnd(self) -> int | None:
        try:
            return int(self.frame(), 16)
        except (tk.TclError, ValueError):
            return None

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


class DialogoColaborador(tk.Toplevel):
    """Os mesmos dados que o app procura na ficha, digitados à mão."""

    CAMPOS = [
        ("nome_completo", "Nome completo *"), ("cpf", "CPF *"), ("cep", "CEP"),
        ("endereco", "Endereço (rua)"), ("numero", "Número"), ("complemento", "Complemento"),
        ("bairro", "Bairro"), ("cidade", "Cidade"), ("estado", "Estado (UF)"),
        ("telefone", "Telefone"), ("celular", "Celular"),
    ]

    def __init__(self, pai):
        super().__init__(pai)
        self.title("Digitar colaborador")
        self.resizable(False, False)
        self.transient(pai)
        self.resultado: Colaborador | None = None
        self.vars = {campo: tk.StringVar() for campo, _ in self.CAMPOS}

        quadro = ttk.Frame(self, padding=12)
        quadro.pack()
        ttk.Label(quadro, text="Preencha com os dados da ficha. E-mail, usuário e senha são gerados\n"
                               "pelas mesmas regras da leitura automática.").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        primeira = None
        for i, (campo, rotulo) in enumerate(self.CAMPOS, start=1):
            ttk.Label(quadro, text=rotulo).grid(row=i, column=0, sticky="w", padx=(0, 8), pady=2)
            entrada = ttk.Entry(quadro, textvariable=self.vars[campo], width=44)
            entrada.grid(row=i, column=1, sticky="we", pady=2)
            primeira = primeira or entrada
        botoes = ttk.Frame(quadro)
        botoes.grid(row=len(self.CAMPOS) + 1, column=0, columnspan=2, pady=(10, 0), sticky="e")
        ttk.Button(botoes, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(botoes, text="Incluir na lista", command=self._ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self.destroy())
        primeira.focus_set()
        self.grab_set()
        pai.wait_window(self)

    def _ok(self):
        dados = {campo: var.get().strip() for campo, var in self.vars.items()}
        if len(dados["nome_completo"].split()) < 2:
            messagebox.showwarning("Digitar colaborador", "Informe o nome completo (nome e sobrenome).", parent=self)
            return
        if not cpf_valido(dados["cpf"]):
            messagebox.showwarning("Digitar colaborador", "CPF inválido. Confira os números.", parent=self)
            return
        dados["nome_completo"] = dados["nome_completo"].upper()  # como vem da ficha
        dados["estado"] = dados["estado"].upper()
        self.resultado = Colaborador(**dados)
        self.destroy()


class DialogoLogin(tk.Toplevel):
    """Pede usuário e senha do admin. Nada é gravado em arquivo."""

    def __init__(self, pai, texto_ok: str = "Entrar e enviar"):
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
        ttk.Button(botoes, text=texto_ok, command=self._ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda _: self._ok())
        entrada.focus_set()
        self.grab_set()
        pai.wait_window(self)

    def _ok(self):
        if self.usuario.get().strip() and self.senha.get():
            self.resultado = (self.usuario.get().strip(), self.senha.get(), self.lembrar.get())
            self.destroy()


def guardar_para_diagnostico(arquivo: Path, nome: str = "") -> Path | None:
    """Copia a lista exportada para dados/erros, para entender o formato."""
    try:
        pasta = pasta_dados() / "erros"
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / f"{nome or datetime.now().strftime('%Y-%m-%d_%H%M%S_exportacao')}{arquivo.suffix}"
        shutil.copyfile(arquivo, destino)
        return destino
    except OSError:
        return None


def abrir_pasta(pasta: Path):
    if sys.platform == "win32":
        os.startfile(pasta)  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", str(pasta)])


class JanelaMonitoramento(tk.Toplevel):
    """Cola os nomes, busca o progresso nas Matrículas e baixa os certificados de quem concluiu."""

    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Monitoramento de treinamentos")
        self.geometry("1080x600")
        self.minsize(760, 480)
        self.fila: queue.Queue = queue.Queue()
        self.rodando = False
        self.linhas: list[tuple[str, ...]] = []

        quadro = ttk.Frame(self, padding=8)
        quadro.pack(fill="both", expand=True)
        ttk.Label(quadro, text="Nomes dos colaboradores (um por linha; pode colar vários de uma vez):").pack(anchor="w")
        self.txt_nomes = tk.Text(quadro, height=7, wrap="none")
        self.txt_nomes.pack(fill="x", pady=(2, 6))

        linha_filtro = ttk.Frame(quadro)
        linha_filtro.pack(fill="x", pady=(0, 6))
        ttk.Label(linha_filtro, text="Treinamento (opcional):").pack(side="left")
        self.filtro_curso = tk.StringVar()
        ttk.Entry(linha_filtro, textvariable=self.filtro_curso, width=30).pack(side="left", padx=6)
        ttk.Label(linha_filtro, foreground="#6b7280",
                  text="ex.: NR33 (acha NR-33, NR 33...). Vários: NR33, NR35. Vazio = todos.").pack(side="left")

        botoes = ttk.Frame(quadro)
        botoes.pack(fill="x")
        self.btn_buscar = ttk.Button(botoes, text="Buscar progresso", command=self.buscar)
        self.btn_buscar.pack(side="left")
        self.baixar = tk.BooleanVar(value=True)
        ttk.Checkbutton(botoes, text="Baixar certificado de quem tem 100%", variable=self.baixar).pack(side="left", padx=8)
        ttk.Button(botoes, text="Abrir pasta dos certificados",
                   command=lambda: abrir_pasta(pasta_certificados())).pack(side="right")
        ttk.Button(botoes, text="Copiar resultado", command=self.copiar).pack(side="right", padx=6)

        colunas = ("aluno", "curso", "progresso", "conclusao", "certificado")
        self.tabela = ttk.Treeview(quadro, columns=colunas, show="headings")
        for col, titulo, largura in [("aluno", "Aluno", 220), ("curso", "Curso", 320),
                                     ("progresso", "Progresso", 75), ("conclusao", "Conclusão", 85),
                                     ("certificado", "Certificado", 200)]:
            self.tabela.heading(col, text=titulo)
            self.tabela.column(col, width=largura, anchor="w")
        self.tabela.tag_configure("ok", foreground="#15803d")
        self.tabela.tag_configure("falta", foreground="#b45309")
        self.tabela.pack(fill="both", expand=True, pady=6)

        self.log = tk.Text(quadro, height=6, state="disabled", wrap="word")
        self.log.pack(fill="x")
        self.txt_nomes.focus_set()
        self.after(200, self._processar_fila)

    def escrever(self, texto: str):
        self.log.config(state="normal")
        self.log.insert("end", f"{datetime.now():%H:%M:%S}  {texto}\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def buscar(self):
        if self.rodando:
            return
        nomes = nomes_colados(self.txt_nomes.get("1.0", "end"))
        if not nomes:
            messagebox.showinfo("Monitoramento", "Cole ou digite ao menos um nome.", parent=self)
            return
        login = DialogoLogin(self, texto_ok="Entrar e buscar")
        if not login.resultado:
            return
        usuario, senha, lembrar = login.resultado
        if lembrar:
            credenciais.salvar(usuario, senha)
        self.rodando = True
        self.btn_buscar.config(state="disabled")
        self.tabela.delete(*self.tabela.get_children())
        self.linhas.clear()
        threading.Thread(target=self._buscar_em_segundo_plano,
                         args=(nomes, usuario, senha, self.baixar.get(), self.app.mostrar_navegador.get(),
                               self.filtro_curso.get().strip()),
                         daemon=True).start()

    def _buscar_em_segundo_plano(self, nomes, usuario, senha, baixar, visivel, filtro=""):
        from .plataforma import ErroPlataforma, Plataforma

        log = lambda texto: self.fila.put(("log", texto))  # noqa: E731
        try:
            with Plataforma(log=log, visivel=visivel) as p:
                p.login(usuario, senha)
                resultados = []
                try:
                    arquivo = p.exportar_matriculas()
                    guardar_para_diagnostico(arquivo, "ultima_exportacao")
                    try:
                        matriculas = ler_exportacao(arquivo, {**self.app.nome_por_id, **p.nomes_cursos})
                    except (OSError, ValueError):
                        copia = guardar_para_diagnostico(arquivo)
                        raise ErroPlataforma(
                            f"Não consegui ler a lista exportada ({arquivo.name}). Cópia em: {copia}") from None
                    alunos = {normalizar(m.aluno) for m in matriculas}
                    log(f"Lista exportada: {len(matriculas)} matrícula(s) de {len(alunos)} aluno(s).")
                    resultados = procurar(nomes, matriculas)
                except ErroPlataforma as erro:
                    log(f"AVISO: {erro}")
                # A exportação pode não trazer todas as matrículas: quem faltou é
                # procurado um a um na tela de Matrículas.
                faltam = [i for i, r in enumerate(resultados) if not r.matriculas] if resultados else list(range(len(nomes)))
                if not resultados:
                    resultados = [Resultado(nome, []) for nome in nomes]
                if faltam:
                    log(f"Procurando {len(faltam)} nome(s) um a um na tela de Matrículas...")
                for n, i in enumerate(faltam, 1):
                    nome = resultados[i].procurado
                    log(f"({n}/{len(faltam)}) {nome}")
                    try:
                        resultados[i] = procurar([nome], p.matriculas_do_aluno(nome))[0]
                    except ErroPlataforma as erro:
                        log(f"AVISO: {nome}: {str(erro).splitlines()[0]}")
                pasta = pasta_certificados()
                if filtro:
                    log(f"Analisando só os treinamentos com \"{filtro}\".")
                for r in resultados:
                    if not r.matriculas:
                        self.fila.put(("linha", (r.procurado, "não encontrado nas matrículas", "-", "", ""), "falta"))
                        continue
                    do_filtro = [m for m in r.matriculas if curso_combina(filtro, m.curso)]
                    if not do_filtro:
                        self.fila.put(("linha", (r.procurado, f"sem matrícula em \"{filtro}\"", "-", "", ""), "falta"))
                    for m in do_filtro:
                        if len(m.aluno.split()) < len(r.procurado.split()):
                            m.aluno = r.procurado  # a lista trouxe só o primeiro nome
                        situacao, tag = "", ""
                        if m.concluida:
                            situacao, tag = "concluído", "ok"
                            if baixar:
                                situacao, tag = self._certificado(p, m, pasta, log)
                        progresso = f"{m.progresso:g}%" if m.progresso is not None else (m.texto_progresso or "?")
                        conclusao = m.conclusao if m.concluida else ""
                        self.fila.put(("linha", (m.aluno, m.curso, progresso, conclusao, situacao), tag))
                achados = sum(1 for r in resultados if r.matriculas)
                self.fila.put(("fim", f"Pronto: {achados} de {len(nomes)} colaborador(es) encontrados."))
        except ErroPlataforma as erro:
            self.fila.put(("erro", str(erro)))
        except Exception as erro:  # qualquer falha inesperada do navegador
            detalhe = (getattr(erro, "msg", None) or str(erro)).strip().splitlines()
            self.fila.put(("erro", f"{type(erro).__name__}: {detalhe[0] if detalhe else 'sem detalhes'}"))
        finally:
            self.fila.put(("liberar", None))

    @staticmethod
    def _certificado(p, m, pasta: Path, log) -> tuple[str, str]:
        salvo = pasta / nome_certificado(m.aluno, m.curso)
        if salvo.exists():
            m.conclusao = m.conclusao or conclusao_no_pdf(salvo)
            return "já baixado", "ok"
        log(f"Baixando o certificado de {m.aluno} ({m.curso})...")
        try:
            destino, m.curso, conclusao = p.baixar_certificado(m.aluno, m.curso, pasta, m.email)
            m.conclusao = m.conclusao or conclusao
        except Exception as erro:  # um certificado com problema não para os outros
            detalhe = (getattr(erro, "msg", None) or str(erro)).strip().splitlines()
            log(f"ERRO no certificado de {m.aluno}: {detalhe[0] if detalhe else type(erro).__name__}")
            return "erro ao baixar (veja o registro)", "falta"
        return f"salvo: {destino.name}", "ok"

    def copiar(self):
        texto = "\n".join("\t".join(l) for l in [("Aluno", "Curso", "Progresso", "Conclusão", "Certificado")] + self.linhas)
        self.clipboard_clear()
        self.clipboard_append(texto)
        self.escrever("Resultado copiado (cole no Excel ou no e-mail).")

    def _processar_fila(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                tipo, *dado = self.fila.get_nowait()
                if tipo == "log":
                    self.escrever(dado[0])
                elif tipo == "linha":
                    valores, tag = dado
                    self.linhas.append(valores)
                    self.tabela.insert("", "end", values=valores, tags=(tag,) if tag else ())
                elif tipo == "erro":
                    self.escrever(f"ERRO: {dado[0]}")
                    messagebox.showerror("Erro no monitoramento", dado[0], parent=self)
                elif tipo == "fim":
                    self.escrever(dado[0])
                elif tipo == "liberar":
                    self.rodando = False
                    self.btn_buscar.config(state="normal")
        except queue.Empty:
            pass
        self.after(200, self._processar_fila)


def main():
    App().mainloop()
