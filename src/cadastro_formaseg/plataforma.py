"""Automação do painel da plataforma em segundo plano (navegador invisível).

Usa o Microsoft Edge que já vem no Windows (ou o Chrome, se o Edge falhar),
controlado pelo Selenium. O fluxo é o mesmo que a pessoa faz na mão:

1. Login em /painel/.
2. Usuários -> "Importar Arquivo" -> aviso (OK) -> arquivo -> confirmação (OK).
3. Matrículas -> o mesmo, com o import-curso.csv.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from selenium import webdriver
from selenium.common.exceptions import NoAlertPresentException, TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config import URL_PAINEL, pasta_dados
from .gerador import sem_acento

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


class ErroPlataforma(Exception):
    pass


class Plataforma:
    def __init__(self, log: Log = print, visivel: bool = False, espera: int = 30):
        self.log = log
        self.visivel = visivel
        self.espera = espera
        self.driver: webdriver.Remote | None = None
        self.url_usuarios: str | None = None

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
            return WebDriverWait(self.driver, tempo or self.espera).until(condicao)
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
        except TimeoutException:
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
            if exato.search(self._opcoes_da_busca(email)):
                existentes.add(email)
        return existentes

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
            opcoes = drv.find_elements(By.CSS_SELECTOR, ".select2-container--open .select2-results__option")
            textos = []
            for o in opcoes:
                classes = o.get_attribute("class") or ""
                texto = (o.text or "").strip().lower()
                if "loading-results" in classes or not texto or any(
                        p in texto for p in ("pesquisando", "searching", "carregando", "loading", "digite", "please enter")):
                    return False
                textos.append(texto)
            return "\n".join(textos) if textos else False

        texto = self._esperar(carregou, 20, o_que=f"o resultado da busca por {termo}")
        campo.send_keys(Keys.ESCAPE)
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
