"""Automação do painel da plataforma em segundo plano (navegador invisível).

Usa o Microsoft Edge que já vem no Windows (ou o Chrome, se o Edge falhar),
controlado pelo Selenium. O fluxo é o mesmo que a pessoa faz na mão:

1. Login em /painel/.
2. Usuários -> "Importar Arquivo" -> aviso (OK) -> arquivo -> confirmação (OK).
3. Matrículas -> o mesmo, com o import-curso.csv.
"""

from __future__ import annotations

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
                (By.CSS_SELECTOR, "input[placeholder*='Pesquisar por usu']")),
                o_que="o campo \"Pesquisar por usuário\"")
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
        botao = self._achar_botao_importar()
        if botao:
            d.execute_script("arguments[0].scrollIntoView({block: 'center'});", botao)
            try:
                botao.click()
            except WebDriverException:  # coberto por outro elemento (aviso, menu): clica via JS
                d.execute_script("arguments[0].click();", botao)
            self._aceitar_alerta(5)  # "Selecione um arquivo no formato .csv..."
        elif d.find_elements(By.CSS_SELECTOR, "input[type='file']"):
            self.log("Botão \"Importar Arquivo\" não encontrado; usando direto o campo de arquivo da página.")
        else:
            pasta = self.salvar_diagnostico(f"botão Importar Arquivo ({o_que})")
            raise ErroPlataforma(
                f"Não encontrei o botão \"Importar Arquivo\" na tela de {o_que} na página {d.current_url}\n\n"
                f"Print e resumo da página salvos em:\n{pasta}")

        entrada = self._esperar(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")),
                                o_que=f"o campo de arquivo da importação de {o_que}")
        entrada.send_keys(str(Path(csv).resolve()))
        self.log(f"Arquivo {Path(csv).name} enviado, aguardando a confirmação...")

        alerta = self._esperar(EC.alert_is_present(), 20, o_que=f"a confirmação da importação de {o_que}")  # "Ao prosseguir a importação..."
        if not confirmar:
            alerta.dismiss()
            self.log(f"Modo teste: importação de {o_que} cancelada antes de confirmar.")
            return "cancelado (modo teste)"
        alerta.accept()

        mensagem = self._mensagem_resultado()
        self.log(f"Resultado ({o_que}): {mensagem}")
        return mensagem

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
