"""Automação do painel da plataforma em segundo plano (navegador invisível).

Usa o Microsoft Edge que já vem no Windows (ou o Chrome, se o Edge falhar),
controlado pelo Selenium. O fluxo é o mesmo que a pessoa faz na mão:

1. Login em /painel/.
2. Usuários -> "Importar Arquivo" -> aviso (OK) -> arquivo -> confirmação (OK).
3. Matrículas -> o mesmo, com o import-curso.csv.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from selenium import webdriver
from selenium.common.exceptions import NoAlertPresentException, TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config import URL_PAINEL
from .gerador import sem_acento

URL_BASE = URL_PAINEL.split("/painel")[0]
URL_MATRICULAS = f"{URL_BASE}/dash/my/lms-enrollments/"

Log = Callable[[str], None]


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

    def _esperar(self, condicao, tempo: int | None = None):
        return WebDriverWait(self.driver, tempo or self.espera).until(condicao)

    # ---------- login ----------
    def login(self, usuario: str, senha: str) -> None:
        d = self.driver
        self.log("Entrando no painel...")
        d.get(URL_PAINEL)
        campo_senha = self._esperar(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']")))
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
        link = self._esperar(EC.presence_of_element_located(
            (By.XPATH, "//a[contains(@href, '/dash/')][normalize-space()='Usuários']")))
        self.url_usuarios = link.get_attribute("href")
        d.get(self.url_usuarios)

    # ---------- consulta ----------
    def emails_existentes(self, alunos: list[tuple[str, str]]) -> set[str]:
        """Recebe (e-mail, nome completo) e devolve os e-mails que já existem.

        A listagem mostra só nomes, então a busca é pelo e-mail e o resultado
        só conta se a linha tiver o primeiro e o último nome da pessoa. Assim,
        se a busca não filtrar, a lista inteira não vira "já existe".
        """
        d = self.driver
        existentes = set()
        for email, nome in alunos:
            self._ir_para_usuarios()
            busca = self._esperar(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "input[placeholder*='Pesquisar por usu']")))
            busca.clear()
            busca.send_keys(email)
            botoes = d.find_elements(By.XPATH, "//button[normalize-space()='Selecionar']")
            if botoes:
                botoes[0].click()
            else:
                busca.send_keys(Keys.ENTER)
            time.sleep(3)
            partes = sem_acento(nome).lower().split()
            for linha in d.find_elements(By.CSS_SELECTOR, "table tbody tr"):
                texto = sem_acento(linha.text).lower()
                if partes and partes[0] in texto and partes[-1] in texto:
                    existentes.add(email)
                    break
        return existentes

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
        botao = self._esperar(EC.element_to_be_clickable(
            (By.XPATH, "//*[self::a or self::button][normalize-space()='Importar Arquivo']")))
        d.execute_script("arguments[0].scrollIntoView({block: 'center'});", botao)
        botao.click()
        self._aceitar_alerta(5)  # "Selecione um arquivo no formato .csv..."

        entrada = self._esperar(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")))
        entrada.send_keys(str(Path(csv).resolve()))
        self.log(f"Arquivo {Path(csv).name} enviado, aguardando a confirmação...")

        alerta = self._esperar(EC.alert_is_present(), 20)  # "Ao prosseguir a importação..."
        if not confirmar:
            alerta.dismiss()
            self.log(f"Modo teste: importação de {o_que} cancelada antes de confirmar.")
            return "cancelado (modo teste)"
        alerta.accept()

        mensagem = self._mensagem_resultado()
        self.log(f"Resultado ({o_que}): {mensagem}")
        return mensagem

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
            avisos = self.driver.find_elements(
                By.CSS_SELECTOR, ".alert, .notice, .updated, .woocommerce-message, .woocommerce-error, [role='alert']")
            textos = [a.text.strip() for a in avisos if a.is_displayed() and a.text.strip()]
            if textos:
                return " | ".join(textos)
            time.sleep(1)
        return "sem mensagem da plataforma (confira no painel)"
