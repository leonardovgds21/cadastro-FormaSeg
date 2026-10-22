"""Automação do painel da plataforma em segundo plano (navegador invisível).

Usa o Microsoft Edge que já vem no Windows (ou o Chrome, se o Edge falhar),
controlado pelo Selenium. O fluxo é o mesmo que a pessoa faz na mão:

1. Login em /painel/.
2. Usuários -> "Importar Arquivo" -> aviso (OK) -> arquivo -> confirmação (OK).
3. Matrículas -> o mesmo, com o import-curso.csv.

Monitoramento: Matrículas -> "Exportar Matriculas" (lista com o progresso) e,
para quem concluiu, pesquisa o aluno -> Ações -> "Ver Certificado" -> PDF.
"""

from __future__ import annotations

import base64
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from selenium import webdriver
from selenium.common.exceptions import (
    NoAlertPresentException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config import URL_PAINEL, pasta_dados, pasta_downloads
from .gerador import email_base, sem_acento
from .monitoramento import Matricula, ler_progresso, mesmo_nome, nome_certificado, normalizar

URL_BASE = URL_PAINEL.split("/painel")[0]
URL_MATRICULAS = f"{URL_BASE}/dash/my/lms-enrollments/"

Log = Callable[[str], None]

# Acha o elemento cujo texto (ou value) contém o procurado, ignorando
# maiúsculas, espaços e ícones. "Contém" porque o botão pode trazer dentro
# dele o balão de ajuda ("Você pode querer ver o exemplo do arquivo CSV").
# Serve para <a>, <button>, <input>, <label>, <span> etc.; fica o elemento mais
# interno com o texto e sobe até o que é clicável. Prefere os visíveis.
_JS_ACHAR_BOTAO = """
const alvo = arguments[0];
const norm = t => (t || '').replace(/\\s+/g, ' ').trim().toLowerCase();
const visivel = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
const tem = e => norm(e.textContent).includes(alvo) || norm(e.value).includes(alvo);
const achados = [...document.querySelectorAll('a, button, input, label, span, div, li, p')].filter(tem);
const internos = achados.filter(e => !achados.some(o => o !== e && e.contains(o)));
const el = internos.find(visivel) || internos[0];
if (!el) return null;
return el.closest('a, button, label, [role=button], [onclick]') || el;
"""


def escolher_exportacao(opcoes: list, textos: list[str]):
    """Prefere a lista completa ("todas") e, depois, CSV > Excel; nunca PDF se houver outra."""
    def nota(texto: str) -> int:
        t = sem_acento(texto).lower()
        if not t or "pdf" in t:
            return -1
        pontos = 10 if any(p in t for p in ("todas", "todos", "tudo", "complet")) else 0
        for peso, chave in ((5, "csv"), (4, "excel"), (4, "xls"), (3, "planilha")):
            if chave in t:
                pontos += peso
                break
        return pontos

    candidatos = [(nota(t), -i, e) for i, (e, t) in enumerate(zip(opcoes, textos))]
    candidatos = [c for c in candidatos if c[0] >= 0]
    return max(candidatos, key=lambda c: c[:2])[2] if candidatos else None


class ErroPlataforma(Exception):
    pass


class Plataforma:
    def __init__(self, log: Log = print, visivel: bool = False, espera: int = 30):
        self.log = log
        self.visivel = visivel
        self.espera = espera
        self.driver: webdriver.Remote | None = None
        self.url_usuarios: str | None = None
        self.pasta_downloads = pasta_downloads()
        self.nomes_cursos: dict[str, str] = {}

    # ---------- navegador ----------
    def __enter__(self):
        self.driver = self._abrir_navegador()
        self.driver.set_page_load_timeout(90)
        return self

    def __exit__(self, *_):
        if self.driver:
            self.driver.quit()

    def _abrir_navegador(self):
        erros = []
        for nome, classe, opcoes in [
            ("Edge", webdriver.Edge, webdriver.EdgeOptions()),
            ("Chrome", webdriver.Chrome, webdriver.ChromeOptions()),
        ]:
            if not self.visivel:
                opcoes.add_argument("--headless=new")
            opcoes.add_argument("--window-size=1400,1000")
            opcoes.add_argument("--lang=pt-BR")
            opcoes.add_experimental_option("prefs", {
                "download.default_directory": str(self.pasta_downloads),
                "download.prompt_for_download": False,
                "plugins.always_open_pdf_externally": True,
            })
            try:
                driver = classe(options=opcoes)
                self.log(f"Navegador {nome} aberto{' (invisível)' if not self.visivel else ''}.")
                return driver
            except WebDriverException as erro:
                erros.append(f"{nome}: {erro.msg}")
        raise ErroPlataforma("Não consegui abrir o Edge nem o Chrome.\n" + "\n".join(erros))

    def _esperar(self, condicao, tempo: int | None = None, o_que: str | None = None):
        """Espera a condição. Com `o_que`, um tempo esgotado vira um erro claro
        dizendo o que faltou, com print e resumo da página salvos em dados/erros."""
        try:
            return WebDriverWait(
                self.driver, tempo or self.espera, ignored_exceptions=[StaleElementReferenceException]
            ).until(condicao)
        except TimeoutException:
            if not o_que:
                raise
            pasta = self.salvar_diagnostico(o_que)
            raise ErroPlataforma(
                f"Não encontrei {o_que} na página {self.driver.current_url}\n\n"
                f"Print e resumo da página salvos em:\n{pasta}"
            ) from None

    def salvar_diagnostico(self, etapa: str) -> Path | None:
        """Salva um print da tela e a lista de campos e botões da página."""
        d = self.driver
        try:
            pasta = pasta_dados() / "erros"
            pasta.mkdir(parents=True, exist_ok=True)
            base = pasta / datetime.now().strftime("%Y-%m-%d_%H%M%S")
            d.save_screenshot(str(base.with_suffix(".png")))
            linhas = [f"Etapa: {etapa}", f"URL: {d.current_url}", f"Título: {d.title}", "", "Campos:"]
            for e in d.find_elements(By.CSS_SELECTOR, "input, select, textarea"):
                linhas.append(
                    f"  <{e.tag_name} type={e.get_attribute('type')} name={e.get_attribute('name')} "
                    f"id={e.get_attribute('id')} placeholder={e.get_attribute('placeholder')} "
                    f"visível={e.is_displayed()}>")
            linhas += ["", "Botões e links:"]
            for e in d.find_elements(By.CSS_SELECTOR, "button, a, input[type='submit']"):
                texto = (e.text or e.get_attribute("value") or "").strip().replace("\n", " ")
                if texto:
                    linhas.append(f"  <{e.tag_name}> {texto[:60]}  href={e.get_attribute('href')}")
            base.with_suffix(".txt").write_text("\n".join(linhas), encoding="utf-8")
            return base.with_suffix(".png")
        except Exception:  # o diagnóstico nunca pode esconder o erro original
            return None

    # ---------- login ----------
    def login(self, usuario: str, senha: str) -> None:
        d = self.driver
        self.log("Entrando no painel...")
        d.get(URL_PAINEL)
        campo_senha = self._esperar(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']")),
                                   o_que="o campo de senha do login")
        form = campo_senha.find_element(By.XPATH, "./ancestor::form[1]")
        campo_usuario = form.find_element(
            By.CSS_SELECTOR, "input[type='text'], input[type='email'], input[name='username'], input[name='log']")
        campo_usuario.clear()
        campo_usuario.send_keys(usuario)
        campo_senha.clear()
        campo_senha.send_keys(senha + Keys.ENTER)
        try:
            self._esperar(EC.staleness_of(campo_senha), 30)
        except WebDriverException:  # inclui tempo esgotado e "node does not belong to the document" na troca de página
            pass
        if d.find_elements(By.CSS_SELECTOR, "input[type='password']") and "/painel" in d.current_url:
            erro = d.find_elements(By.CSS_SELECTOR, ".woocommerce-error, .login_error, .alert-danger")
            detalhe = erro[0].text.strip() if erro else ""
            raise ErroPlataforma(f"Login recusado. {detalhe}".strip())
        self.log("Login feito.")

    def _ir_para_usuarios(self) -> None:
        """Abre a listagem de usuários pelo menu lateral (o endereço é descoberto uma vez)."""
        d = self.driver
        if self.url_usuarios:
            d.get(self.url_usuarios)
            return
        d.get(URL_MATRICULAS)
        if d.find_elements(By.CSS_SELECTOR, "input[type='password']"):
            self.salvar_diagnostico("abrir a área administrativa")
            raise ErroPlataforma(
                "A plataforma voltou para a tela de login ao abrir a área administrativa. "
                "Confira o usuário e a senha (use \"Esquecer login salvo\" e digite de novo).")
        # O item do menu pode ter ícone, espaços ou ficar dentro do submenu
        # "Usuários e Matrículas"; pega o link cujo texto contém "Usuários" sem "Matrículas".
        link = self._esperar(
            lambda drv: next(
                (e for e in drv.find_elements(By.XPATH, "//a[contains(normalize-space(.), 'Usu')]")
                 if "matr" not in sem_acento(e.get_attribute("textContent") or "").lower()
                 and "usuario" in sem_acento(e.get_attribute("textContent") or "").lower()
                 and (e.get_attribute("href") or "").startswith("http")
                 and "#" not in (e.get_attribute("href") or "")),
                False),
            o_que="o link \"Usuários\" do menu lateral")
        self.url_usuarios = link.get_attribute("href")
        d.get(self.url_usuarios)

    # ---------- consulta ----------
    def emails_existentes(self, emails: list[str]) -> set[str]:
        """Devolve os e-mails da lista que já existem na plataforma.

        A busca "Pesquisar por usuário" da tela de Usuários é uma lista com
        pesquisa (select2): digita o e-mail e lê as opções, que mostram
        "NOME (#id – e-mail)". Conta como existente só se o e-mail aparecer
        exatamente numa opção.
        """
        existentes = set()
        for email in emails:
            self._ir_para_usuarios()
            exato = re.compile(r"(?<![\w.@+-])" + re.escape(email.lower()) + r"(?![\w.@+-])")
            if exato.search(self._buscar_com_repeticao(email)):
                existentes.add(email)
        return existentes

    def _buscar_com_repeticao(self, termo: str, tentativas: int = 3) -> str:
        """A página redesenha a busca enquanto carrega; se um elemento ficar
        obsoleto no meio, recarrega a tela e tenta de novo."""
        for tentativa in range(tentativas):
            try:
                return self._opcoes_da_busca(termo)
            except StaleElementReferenceException:
                if tentativa == tentativas - 1:
                    raise ErroPlataforma(
                        f"A busca \"Pesquisar por usuário\" mudou enquanto era lida ({tentativas} tentativas).")
                time.sleep(2)
                self._ir_para_usuarios()
        return ""

    def _opcoes_da_busca(self, termo: str) -> str:
        """Digita o termo na busca de usuários e devolve o texto das opções (minúsculo)."""
        d = self.driver
        lista = self._esperar(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "#dashlifter-filter-customer, select[name='customer_id']")),
            o_que="a busca \"Pesquisar por usuário\"")
        caixa = lista.find_element(By.XPATH, "following-sibling::span[contains(@class, 'select2')][1]"
                                             "//*[contains(@class, 'select2-selection')]")
        d.execute_script("arguments[0].scrollIntoView({block: 'center'});", caixa)
        caixa.click()
        campo = self._esperar(EC.visibility_of_element_located(
            (By.CSS_SELECTOR, ".select2-container--open .select2-search__field")),
            o_que="o campo de digitação da busca \"Pesquisar por usuário\"")
        campo.clear()
        campo.send_keys(termo)

        def carregou(drv):
            # Lê todas as opções numa única chamada: a lista é redesenhada a cada
            # resposta da pesquisa, e elementos guardados ficariam obsoletos.
            try:
                opcoes = drv.execute_script(
                    "return [...document.querySelectorAll('.select2-container--open .select2-results__option')]"
                    ".map(o => [o.className || '', (o.innerText || o.textContent || '').trim().toLowerCase()]);")
            except WebDriverException:
                return False
            if not opcoes:
                return False
            for classes, texto in opcoes:
                if "loading-results" in classes or not texto or any(
                        p in texto for p in ("pesquisando", "searching", "carregando", "loading", "digite", "please enter")):
                    return False
            return "\n".join(texto for _, texto in opcoes)

        texto = self._esperar(carregou, 20, o_que=f"o resultado da busca por {termo}")
        try:
            campo.send_keys(Keys.ESCAPE)
        except WebDriverException:  # o campo foi redesenhado; a próxima busca recarrega a página
            pass
        return texto

    # ---------- importação ----------
    def importar_usuarios(self, csv: Path, confirmar: bool = True) -> str:
        return self._importar(None, csv, "usuários", confirmar)

    def importar_matriculas(self, csv: Path, confirmar: bool = True) -> str:
        return self._importar(URL_MATRICULAS, csv, "matrículas", confirmar)

    def _importar(self, url: str | None, csv: Path, o_que: str, confirmar: bool) -> str:
        d = self.driver
        self.log(f"Abrindo a tela de {o_que}...")
        if url:
            d.get(url)
        else:
            self._ir_para_usuarios()
        # A página já traz o campo de arquivo escondido (ex.: <input type=file
        # id=users_csv>). Enviar o arquivo direto nele evita abrir a janela
        # "Abrir arquivo" do Windows, que o navegador automatizado não controla.
        # Se a página não pedir a confirmação assim, tenta pelo botão.
        alerta = None
        if self._tem_campo_arquivo():
            alerta = self._enviar_arquivo(csv, tempo=15)
            if not alerta:
                self.log("A página não pediu confirmação; tentando pelo botão \"Importar Arquivo\"...")
        if not alerta:
            botao = self._achar_botao_importar()
            if not botao:
                pasta = self.salvar_diagnostico(f"botão Importar Arquivo ({o_que})")
                raise ErroPlataforma(
                    f"Não encontrei o botão \"Importar Arquivo\" na tela de {o_que} "
                    f"na página {d.current_url}\n\nPrint e resumo da página salvos em:\n{pasta}")
            d.execute_script("arguments[0].scrollIntoView({block: 'center'});", botao)
            try:
                botao.click()
            except WebDriverException:  # coberto por outro elemento (aviso, menu): clica via JS
                d.execute_script("arguments[0].click();", botao)
            self._aceitar_alerta(5)  # "Selecione um arquivo no formato .csv..."
            alerta = self._enviar_arquivo(csv, tempo=20)
        if not alerta:
            pasta = self.salvar_diagnostico(f"confirmação da importação ({o_que})")
            raise ErroPlataforma(
                f"Enviei o arquivo, mas a plataforma não pediu a confirmação da importação de {o_que}.\n\n"
                f"Print e resumo da página salvos em:\n{pasta}")

        if not confirmar:
            alerta.dismiss()
            self.log(f"Modo teste: importação de {o_que} cancelada antes de confirmar.")
            return "cancelado (modo teste)"
        alerta.accept()

        mensagem = self._mensagem_resultado()
        self.log(f"Resultado ({o_que}): {mensagem}")
        return mensagem

    def _enviar_arquivo(self, csv: Path, tempo: int):
        """Coloca o CSV no campo de arquivo e devolve o alerta de confirmação (ou None)."""
        try:  # a confirmação pode já ter aparecido (campo preenchido numa tentativa anterior)
            return self.driver.switch_to.alert
        except NoAlertPresentException:
            pass
        entrada = self._esperar(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")),
                                o_que="o campo de arquivo da importação")
        entrada.send_keys(str(Path(csv).resolve()))
        self.log(f"Arquivo {Path(csv).name} enviado, aguardando a confirmação...")
        try:
            return self._esperar(EC.alert_is_present(), tempo)  # "Ao prosseguir a importação..."
        except TimeoutException:
            return None

    def _tem_campo_arquivo(self) -> bool:
        try:
            self._esperar(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")), 10)
            return True
        except TimeoutException:
            return False

    def _achar_botao_importar(self):
        """Procura o botão na página e, se não achar, dentro de iframes."""
        d = self.driver
        fim = time.time() + self.espera
        while time.time() < fim:
            d.switch_to.default_content()
            botao = d.execute_script(_JS_ACHAR_BOTAO, "importar arquivo")
            if botao:
                return botao
            for quadro in d.find_elements(By.TAG_NAME, "iframe"):
                try:
                    d.switch_to.frame(quadro)
                    botao = d.execute_script(_JS_ACHAR_BOTAO, "importar arquivo")
                    if botao:
                        return botao  # fica dentro do iframe para o resto da importação
                except WebDriverException:
                    pass
                d.switch_to.default_content()
            time.sleep(1)
        d.switch_to.default_content()
        return None

    def _aceitar_alerta(self, tempo: int) -> str | None:
        try:
            alerta = self._esperar(EC.alert_is_present(), tempo)
        except TimeoutException:
            return None
        texto = alerta.text
        alerta.accept()
        return texto

    def _mensagem_resultado(self) -> str:
        """Espera a página recarregar e lê o aviso verde (ou de erro) do topo."""
        fim = time.time() + 120
        while time.time() < fim:
            try:
                texto_alerta = self.driver.switch_to.alert.text
                self.driver.switch_to.alert.accept()
                return texto_alerta
            except NoAlertPresentException:
                pass
            try:
                avisos = self.driver.find_elements(
                    By.CSS_SELECTOR, ".alert, .notice, .updated, .woocommerce-message, .woocommerce-error, [role='alert']")
                textos = [a.text.strip() for a in avisos if a.is_displayed() and a.text.strip()]
            except WebDriverException:  # a página recarregou no meio da leitura; tenta de novo
                textos = []
            if textos:
                return " | ".join(textos)
            time.sleep(1)
        return "sem mensagem da plataforma (confira no painel)"

    # ---------- monitoramento ----------
    def exportar_matriculas(self) -> Path:
        """Clica em "Exportar Matriculas", escolhe CSV (ou Excel) e devolve o arquivo baixado."""
        d = self.driver
        self.log("Abrindo Matrículas para exportar a lista...")
        d.get(URL_MATRICULAS)
        self._liberar_downloads()
        for velho in self.pasta_downloads.iterdir():  # fica só a lista mais recente
            try:
                velho.unlink()
            except OSError:
                pass
        antes = set(self.pasta_downloads.iterdir())
        self.nomes_cursos = self._nomes_dos_cursos()
        botao = self._esperar(lambda drv: drv.execute_script(_JS_ACHAR_BOTAO, "exportar matriculas")
                              or drv.execute_script(_JS_ACHAR_BOTAO, "exportar matrículas"),
                              o_que="o botão \"Exportar Matriculas\"")
        visiveis_antes = set(self._clicaveis_visiveis())
        self._clicar(botao)
        time.sleep(1)
        opcoes = [e for e in self._clicaveis_visiveis() if e not in visiveis_antes and e != botao]
        textos = [(e.text or "").strip() for e in opcoes]
        if textos:
            self.log(f"Opções de exportação: {', '.join(t for t in textos if t)}")
        escolhida = escolher_exportacao(opcoes, textos)
        if escolhida:
            self.log(f"Exportando: {escolhida.text.strip()}")
            self._clicar(escolhida)
        janela = d.current_window_handle
        arquivo = self._esperar_download(antes, 90)
        for aba in d.window_handles:  # a exportação pode abrir uma aba à toa
            if aba != janela:
                d.switch_to.window(aba)
                d.close()
        d.switch_to.window(janela)
        if not arquivo:
            pasta = self.salvar_diagnostico("exportar matrículas")
            raise ErroPlataforma(
                "Cliquei em \"Exportar Matriculas\", mas nenhum arquivo foi baixado.\n\n"
                f"Print e resumo da página salvos em:\n{pasta}")
        self.log(f"Lista exportada: {arquivo.name}")
        return arquivo

    def _nomes_dos_cursos(self) -> dict[str, str]:
        """ID -> nome dos cursos, lidos das listas de filtro da página (se houver)."""
        try:
            return self.driver.execute_script("""
                const nomes = {};
                for (const o of document.querySelectorAll('select option')) {
                    const v = (o.value || '').trim(), t = (o.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (/^\\d+$/.test(v) && t && !/^\\d+$/.test(t)) nomes[v] = t;
                }
                return nomes;""") or {}
        except WebDriverException:
            return {}

    def _liberar_downloads(self):
        self.pasta_downloads.mkdir(parents=True, exist_ok=True)
        for comando, parametros in [
            ("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(self.pasta_downloads)}),
            ("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(self.pasta_downloads)}),
        ]:
            try:
                self.driver.execute_cdp_cmd(comando, parametros)
                return
            except WebDriverException:
                continue

    def _esperar_download(self, antes: set[Path], tempo: int) -> Path | None:
        """Espera um arquivo novo terminar de baixar (tamanho parado) e devolve o caminho.

        O navegador grava com outro nome e renomeia no fim, e antivírus ou
        OneDrive podem mexer no arquivo: por isso nada aqui conta que um
        arquivo visto continua existindo."""
        fim = time.time() + tempo
        anterior: dict[Path, int] = {}
        while time.time() < fim:
            atual = {}
            try:
                for a in self.pasta_downloads.iterdir():
                    if a not in antes and a.suffix.lower() not in (".crdownload", ".tmp", ".partial"):
                        atual[a] = a.stat().st_size
                baixando = any(a.suffix.lower() == ".crdownload" for a in self.pasta_downloads.iterdir())
            except OSError:  # arquivo sumiu ou foi renomeado no meio da leitura
                time.sleep(1)
                continue
            prontos = [a for a, tamanho in atual.items() if tamanho > 0 and anterior.get(a) == tamanho]
            if prontos and not baixando:
                return prontos[-1]
            anterior = atual
            time.sleep(1)
        return None

    def _clicaveis_visiveis(self) -> list:
        return self.driver.execute_script(
            "return [...document.querySelectorAll('a, button, li, [role=menuitem], .dropdown-item')]"
            ".filter(e => (e.offsetWidth || e.offsetHeight) && (e.textContent || '').trim()"
            " && !e.querySelector('a, button'));")

    def _clicar(self, elemento):
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elemento)
        try:
            elemento.click()
        except WebDriverException:  # coberto por outro elemento: clica via JS
            self.driver.execute_script("arguments[0].click();", elemento)

    def matriculas_do_aluno(self, nome: str, email: str = "") -> list[Matricula]:
        """Pesquisa o aluno em Matrículas e lê a tabela (aluno, curso, progresso)."""
        return [Matricula(a, c, ler_progresso(p), p) for a, c, p, _ in self._pesquisar_aluno(nome, email)]

    def _pesquisar_aluno(self, nome: str, email: str = "") -> list[list[str]]:
        d = self.driver
        d.get(URL_MATRICULAS)
        lista = self._esperar(lambda drv: self._filtro_aluno(), o_que="a busca por aluno em Matrículas")
        # A busca da plataforma procura o texto inteiro: "Liliana Borges" não acha
        # "Liliana Martins Borges". Tenta o e-mail, o nome, o login na regra do
        # app (liliana.borges) e o sobrenome mais longo.
        palavras = [w for w in sem_acento(nome).split() if len(w) > 2]
        termos = [email, nome, email_base(nome), max(palavras, key=len) if palavras else ""]
        termos = list(dict.fromkeys(t for t in termos if t))
        if not any(self._escolher_no_select2(lista, t, nome, email, avisar=False) for t in termos):
            self.log(f"\"{nome}\" não apareceu na busca por aluno.")
            return []
        botao = self._esperar(lambda drv: drv.execute_script(_JS_ACHAR_BOTAO, "pesquisar matriculas")
                              or drv.execute_script(_JS_ACHAR_BOTAO, "pesquisar matrículas"),
                              o_que="o botão \"Pesquisar Matriculas\"")
        tabela_antes = d.execute_script("return document.querySelector('table tbody');")
        self._clicar(botao)

        def leu(drv):
            try:
                recarregou = not tabela_antes or not drv.execute_script(
                    "return document.contains(arguments[0]);", tabela_antes)
            except WebDriverException:  # a referência antiga ficou obsoleta: a página recarregou
                recarregou = True
            try:
                linhas = drv.execute_script(_JS_LINHAS_MATRICULAS)
            except WebDriverException:
                return False
            if linhas is None:
                return False
            # sem recarregar, a tabela é trocada por AJAX: espera mostrar só o aluno
            if recarregou or (linhas and all(mesmo_nome(nome, l[0]) for l in linhas)):
                return ("ok", linhas)
            return False

        try:
            _, linhas = self._esperar(leu, 30)
        except TimeoutException:
            linhas = d.execute_script(_JS_LINHAS_MATRICULAS) or []
        return [l for l in linhas if mesmo_nome(nome, l[0])]

    def _filtro_aluno(self):
        """A lista com pesquisa (select2) de aluno/usuário do filtro de Matrículas."""
        return self.driver.execute_script("""
            const sels = [...document.querySelectorAll('select')];
            const por = f => sels.find(f);
            const txt = s => { const c = s.nextElementSibling; return ((c && c.textContent) || '') + ' '
                + (s.getAttribute('data-placeholder') || '') + ' ' + (s.name || '') + ' ' + (s.id || ''); };
            return por(s => s.id === 'dashlifter-filter-customer' || s.name === 'customer_id')
                || por(s => /customer|student|aluno|user/i.test((s.id || '') + ' ' + (s.name || '')))
                || por(s => /usu[aá]rio|aluno|colaborador/i.test(txt(s)) && !/empresa|filial/i.test(txt(s)))
                || null;""")

    def _escolher_no_select2(self, lista, termo: str, nome: str, email: str, avisar: bool = True) -> bool:
        """Digita o termo na lista com pesquisa e escolhe a opção do aluno."""
        d = self.driver
        caixa = lista.find_element(By.XPATH, "following-sibling::span[contains(@class, 'select2')][1]"
                                             "//*[contains(@class, 'select2-selection')]")
        self._clicar(caixa)
        campo = self._esperar(EC.visibility_of_element_located(
            (By.CSS_SELECTOR, ".select2-container--open .select2-search__field")),
            o_que="o campo de digitação da busca por aluno")
        campo.clear()
        campo.send_keys(termo)

        def carregou(drv):
            try:
                opcoes = drv.execute_script(
                    "return [...document.querySelectorAll('.select2-container--open .select2-results__option')]"
                    ".map(o => [o.className || '', (o.innerText || o.textContent || '').trim()]);")
            except WebDriverException:
                return False
            if not opcoes or any("loading-results" in c or not t or any(
                    p in t.lower() for p in ("pesquisando", "searching", "carregando", "loading", "digite", "please enter"))
                    for c, t in opcoes):
                return False
            return opcoes

        try:
            opcoes = self._esperar(carregou, 20)
        except TimeoutException:
            opcoes = []
        alvo = normalizar(nome)
        indice = None
        for i, (classes, texto) in enumerate(opcoes):
            if "message" in classes:  # "Nenhum resultado encontrado"
                continue
            nome_opcao = normalizar(texto.split("(")[0])
            if (email and email.lower() in texto.lower()) or nome_opcao == alvo:
                indice = i
                break
            email_opcao = re.search(r"[\w.+-]+@[\w.-]+", texto)
            if indice is None and mesmo_nome(nome, nome_opcao, email_opcao.group() if email_opcao else ""):
                indice = i
        if indice is None:
            campo.send_keys(Keys.ESCAPE)
            if avisar:
                self.log(f"\"{termo}\" não apareceu na busca por aluno.")
            return False
        opcao = d.execute_script(
            "return document.querySelectorAll('.select2-container--open .select2-results__option')[arguments[0]];",
            indice)
        try:
            opcao.click()
        except WebDriverException:
            d.execute_script(
                "arguments[0].dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));", opcao)
        return True

    def baixar_certificado(self, aluno: str, curso: str, pasta: Path, email: str = "") -> tuple[Path, str]:
        """Pesquisa o aluno, abre Ações -> "Ver Certificado" do curso e salva em PDF.

        Devolve o arquivo salvo e o nome completo do curso como está na tela."""
        d = self.driver
        linhas = self._pesquisar_aluno(aluno, email)
        alvo = normalizar(curso)
        escolhida = next((l for l in linhas if normalizar(l[1]) == alvo), None)
        if not escolhida and alvo:  # nome parcial do curso
            escolhida = next((l for l in linhas if all(p in normalizar(l[1]).split() for p in alvo.split())), None)
        if not escolhida:  # a lista só trouxe o ID do curso: serve a única matrícula concluída
            concluidas = [l for l in linhas if (ler_progresso(l[2]) or 0) >= 99.995]
            escolhida = concluidas[0] if len(concluidas) == 1 else None
        if escolhida:
            curso, indice = escolhida[1], escolhida[3]
            destino = pasta / nome_certificado(escolhida[0], curso)
        else:
            print_ = self.salvar_diagnostico(f"matrícula de {aluno} em {curso}")
            raise ErroPlataforma(f"Não achei a matrícula de {aluno} em \"{curso}\" na pesquisa. Print em {print_}")
        linha = d.execute_script(_JS_LINHA_MATRICULA, indice)
        link = self._link_certificado(linha)
        janela = d.current_window_handle
        abas_antes = set(d.window_handles)
        url = self._href_real(link)
        if url:
            pdf = self._baixar_se_for_pdf(url)
            if pdf:
                destino.write_bytes(pdf)
                return destino, curso
            d.switch_to.new_window("tab")
            d.get(url)
        else:
            self._clicar(link)
            nova = self._esperar(lambda drv: next((a for a in drv.window_handles if a not in abas_antes), False), 30,
                                 o_que="a aba do certificado")
            d.switch_to.window(nova)
        try:
            self._esperar(lambda drv: drv.execute_script("return document.readyState") == "complete", 60)
            time.sleep(2)  # imagens e assinaturas
            pdf = d.execute_cdp_cmd("Page.printToPDF", {
                "printBackground": True, "landscape": True, "preferCSSPageSize": True,
                "marginTop": 0, "marginBottom": 0, "marginLeft": 0, "marginRight": 0,
            })
            destino.write_bytes(base64.b64decode(pdf["data"]))
        finally:
            if d.current_window_handle != janela:
                d.close()
            d.switch_to.window(janela)
        return destino, curso

    def _link_certificado(self, linha):
        """O link "Ver Certificado" da linha (abre o menu Ações se precisar)."""
        d = self.driver
        achar = ".//a[contains(translate(normalize-space(.), 'CERTIFIDO', 'certifido'), 'certificado')]"
        links = linha.find_elements(By.XPATH, achar)
        if links and self._href_real(links[0]):
            return links[0]
        acoes = linha.find_elements(By.CSS_SELECTOR, "td:last-child button, td:last-child a, td:last-child [role=button]")
        if acoes:
            self._clicar(acoes[0])
            time.sleep(1)
        link = d.execute_script(_JS_ACHAR_BOTAO, "ver certificado")
        if not link:
            pasta = self.salvar_diagnostico("Ações -> Ver Certificado")
            raise ErroPlataforma(f"Não achei \"Ver Certificado\" no menu Ações. Print em {pasta}")
        return link

    def _href_real(self, link) -> str:
        """O endereço do link, ou "" se ele só roda um script (href="#" ou javascript:)."""
        bruto = (self.driver.execute_script("return arguments[0].getAttribute('href');", link) or "").strip()
        if not bruto or bruto.startswith("#") or bruto.lower().startswith("javascript"):
            return ""
        return link.get_attribute("href") or ""

    def _baixar_se_for_pdf(self, url: str) -> bytes | None:
        """Se o link já entrega um PDF, baixa direto (sem imprimir)."""
        try:
            dados = self.driver.execute_async_script("""
                const [url, fim] = arguments;
                fetch(url, {credentials: 'include'}).then(async r => {
                    if (!(r.headers.get('content-type') || '').includes('pdf')) return fim(null);
                    const b = new Uint8Array(await r.arrayBuffer());
                    let s = ''; for (let i = 0; i < b.length; i += 8192) s += String.fromCharCode(...b.subarray(i, i + 8192));
                    fim(btoa(s));
                }).catch(() => fim(null));""", url)
        except WebDriverException:
            return None
        return base64.b64decode(dados) if dados else None


# Linhas da tabela de Matrículas: [aluno, curso, progresso, nº da linha], achando as colunas
# pelo cabeçalho. Devolve null se a tabela ainda não existe.
_JS_LINHAS_MATRICULAS = """
const norm = t => (t || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/\\s+/g, ' ').trim().toLowerCase();
const tabela = [...document.querySelectorAll('table')].find(t => {
    const cab = [...t.querySelectorAll('th')].map(th => norm(th.textContent));
    return cab.some(c => c.includes('aluno')) && cab.some(c => c.includes('curso'));
});
if (!tabela) return null;
const cab = [...tabela.querySelectorAll('th')].map(th => norm(th.textContent));
const col = k => cab.findIndex(c => c.includes(k));
const [a, c, p] = [col('aluno'), col('curso'), col('progresso')];
return [...tabela.querySelectorAll('tbody tr')].map((tr, n) => {
    const td = [...tr.children];
    const txt = i => i >= 0 && td[i] ? td[i].innerText.replace(/\\s+/g, ' ').trim() : '';
    return [txt(a), txt(c), txt(p), n];
}).filter(l => l[0] && l[1]);
"""

# A linha (tr) de número arguments[0] da mesma tabela.
_JS_LINHA_MATRICULA = """
const norm = t => (t || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase();
const tabela = [...document.querySelectorAll('table')].find(t => {
    const cab = [...t.querySelectorAll('th')].map(th => norm(th.textContent));
    return cab.some(c => c.includes('aluno')) && cab.some(c => c.includes('curso'));
});
return tabela.querySelectorAll('tbody tr')[arguments[0]];
"""
