"""Testes sem Windows, navegador, certificado ou conexão com a SEFAZ/Sankhya."""

import tempfile
import types
import unittest
import zipfile
from datetime import date
from pathlib import Path

from download_sefaz_xml import (
    CONFIG_PATH,
    DTE_DOM_ACTIONS,
    DTE_XML_MARKER_SCRIPT,
    ErroSeguro,
    NavegadorNormal,
    browser_kind,
    locate_dom_marker,
    locate_sefaz_banner,
    locate_xml_item_image,
    marker_diagnostic,
    close_sefaz_advisories,
    desktop_zip_name,
    open_sefaz_nfe_category,
    open_sefaz_xml_download,
    read_json,
    sankhya_periodo,
    sefaz_periodo,
    select_company_sefaz,
    validate_profile_directory,
    validate_zip,
    wait_certificate,
    wait_for_dte_panel,
    wait_for_xml_consultation,
)
from unittest.mock import patch


class TestLogic(unittest.TestCase):
    def test_aviso_de_sessao_nao_impede_tela_de_empresa_confirmada(self):
        class FakeBrowser:
            config = {"empresa_inscricao_estadual": "12.345.678-9"}
            nome = "EDGE"
            leituras = 0

            def has_text(self, names):
                if names == ["Situação Cadastral"]:
                    self.leituras += 1
                    return self.leituras >= 3
                return names == ["Sessão não definida"]

        fake = FakeBrowser()
        with patch("download_sefaz_xml.time.sleep"), patch("download_sefaz_xml.log"):
            wait_certificate(fake, timeout=2)
        self.assertEqual(fake.leituras, 3)

    def test_aviso_de_sessao_sem_tela_confirmada_termina_por_prazo(self):
        class FakeBrowser:
            config = {}
            nome = "EDGE"

            def has_text(self, names):
                return names == ["Sessão não definida"]

        with patch("download_sefaz_xml.time.monotonic", side_effect=[0, 0, 2]), \
             patch("download_sefaz_xml.time.sleep"), patch("download_sefaz_xml.log"):
            with self.assertRaisesRegex(ErroSeguro, "Sessão não definida"):
                wait_certificate(FakeBrowser(), timeout=1)

    def test_launcher_verifica_pillow_antes_de_abrir_edge(self):
        launcher = (CONFIG_PATH.parent / "_python.bat").read_text(encoding="utf-8")
        self.assertIn("'PIL'", launcher)
        self.assertIn("importlib.util.find_spec", launcher)
        self.assertIn('"%RPA_PYEXE%" %RPA_PYARGS% -m pip install', launcher)
        self.assertIn("--agendado", launcher)
        self.assertLess(launcher.index("importlib.util.find_spec"),
                        launcher.index("download_sefaz_xml.py"))

    def test_nfe_menu_lateral_usa_seletor_dom_exato(self):
        class FakeBrowser:
            menu_open = False
            actions = []

            def has_text(self, names):
                return names == ["NF-e - Download de Arquivos XML"] and self.menu_open

            def click_sefaz_dom(self, action):
                self.actions.append(action)
                self.menu_open = True

        browser = FakeBrowser()
        with patch("download_sefaz_xml.log"):
            open_sefaz_nfe_category(browser, timeout=1)
        self.assertTrue(browser.menu_open)
        self.assertEqual(browser.actions, ["categoria_nfe"])

    def test_menu_consegue_continuar_quando_uia_tem_keyerror(self):
        class FakeBrowser:
            actions = []

            def has_text(self, names):
                raise ErroSeguro("UIA do Edge indisponivel apos 3 tentativas (KeyError)")

            def click_sefaz_dom(self, action):
                self.actions.append(action)

            def click_xml_with_visual_template(self):
                self.actions.append("fisico_visual")

        browser = FakeBrowser()
        with patch("download_sefaz_xml.log"):
            open_sefaz_nfe_category(browser, timeout=1)
            open_sefaz_xml_download(browser)
        self.assertEqual(browser.actions, ["categoria_nfe", "fisico_visual"])

    def test_arvore_uia_keyerror_transitorio_retentado(self):
        class Control:
            def is_visible(self):
                return True

            def window_text(self):
                return "NF-e - Download de Arquivos XML"

        class Root:
            calls = 0

            def descendants(self):
                self.calls += 1
                if self.calls < 3:
                    raise KeyError(None)
                return [Control()]

        browser = NavegadorNormal({"navegador": "edge"})
        root = Root()
        browser.root = lambda: root
        with patch("download_sefaz_xml.time.sleep"), patch("download_sefaz_xml.log"):
            result = browser._matches(["NF-e - Download de Arquivos XML"])
        self.assertEqual(len(result), 1)
        self.assertEqual(root.calls, 3)

    def test_bookmarklets_so_nos_seletores_e_host_oficiais(self):
        self.assertEqual(set(DTE_DOM_ACTIONS), {"categoria_nfe", "download_xml"})
        for action, script in DTE_DOM_ACTIONS.items():
            self.assertTrue(script.startswith("javascript:void(function(){"))
            self.assertIn("location.hostname!=='online.sefaz.am.gov.br'", script)
            self.assertIn("location.pathname!=='/menu/dte.asp'", script)
            self.assertIn("e.length!==1", script)
            self.assertIn(".click()", script)
            self.assertNotIn("fetch(", script)
            self.assertNotIn("XMLHttpRequest", script)
        self.assertIn('div.menuDte_categoria2[categoria="2"]',
                      DTE_DOM_ACTIONS["categoria_nfe"])
        self.assertIn('div.menuDte_itemMenu[idlink="42"]',
                      DTE_DOM_ACTIONS["download_xml"])
        self.assertIn("document.elementFromPoint", DTE_DOM_ACTIONS["download_xml"])
        self.assertIn("t.click()", DTE_DOM_ACTIONS["download_xml"])

    def test_localizador_dom_nao_clica_nem_usa_sso(self):
        script = DTE_XML_MARKER_SCRIPT
        self.assertTrue(script.startswith("javascript:void(function(){"))
        self.assertIn("location.hostname!=='online.sefaz.am.gov.br'", script)
        self.assertIn('div.menuDte_itemMenu[idlink="42"]', script)
        self.assertIn("document.elementFromPoint", script)
        self.assertIn("#FA05C4", script)
        self.assertIn("#05FA6A", script)
        self.assertIn("pointer-events:none", script)
        self.assertIn("setTimeout", script)
        self.assertNotIn(".click()", script)
        self.assertNotIn("SSO=", script)
        self.assertNotIn("document.title", script)

    def test_marcador_concentrico_para_clique_fisico_sem_posicoes_fixas(self):
        from PIL import Image, ImageDraw

        screenshot = Image.new("RGB", (1200, 900), (240, 240, 240))
        draw = ImageDraw.Draw(screenshot)
        # Janela ocupa (100, 100)-(1100, 800); DPR/zoom combinados = 1.5.
        draw.rectangle((379, 529, 420, 570), fill=(5, 250, 106))
        draw.rectangle((388, 538, 411, 561), fill=(250, 5, 196))
        self.assertEqual(locate_dom_marker(screenshot, (100, 100, 1100, 800)),
                         (400, 550))
        # Se a pagina ou DevTools encobrir os marcadores, NAO clica.
        screenshot_missing = Image.new("RGB", (1200, 900), (240, 240, 240))
        with self.assertRaises(ErroSeguro):
            locate_dom_marker(screenshot_missing, (100, 100, 1100, 800))

    def test_marcador_em_janela_parcialmente_fora_da_captura(self):
        from PIL import Image, ImageDraw

        screenshot = Image.new("RGB", (1200, 900), (240, 240, 240))
        draw = ImageDraw.Draw(screenshot)
        draw.rectangle((379, 529, 420, 570), fill=(5, 250, 106))
        draw.rectangle((388, 538, 411, 561), fill=(250, 5, 196))
        self.assertEqual(locate_dom_marker(screenshot, (-40, -20, 1300, 980)),
                         (400, 550))
        with self.assertRaisesRegex(ErroSeguro, "Parte visivel"):
            locate_dom_marker(screenshot, (1100, 700, 1800, 1200))

    def test_banner_oficial_localizado_apesar_de_um_pixel_diferente(self):
        from PIL import Image

        template = Image.open(CONFIG_PATH.parent / "acessarDTe.png")
        screenshot = Image.new("RGB", (926, 974), "white")
        screenshot.paste(template, (502, 193), template)
        screenshot.putpixel((600, 230), (10, 20, 30))
        self.assertEqual(locate_sefaz_banner(
            screenshot, template, (-8, -8, 934, 982)), (677, 233))
        with self.assertRaisesRegex(ErroSeguro, "não localizado"):
            locate_sefaz_banner(Image.new("RGB", (926, 974), "white"),
                                template, (-8, -8, 934, 982))

    def test_diagnostico_visual_explica_item_xml_coberto(self):
        from PIL import Image, ImageDraw

        screenshot = Image.new("RGB", (800, 600), (240, 240, 240))
        ImageDraw.Draw(screenshot).rectangle((32, 170, 55, 193), fill=(255, 34, 34))
        self.assertIn("outro elemento cobria", marker_diagnostic(
            screenshot, (-10, -10, 810, 610)))

    def test_item_xml_visual_exige_correspondencia_unica(self):
        from PIL import Image

        template = Image.open(CONFIG_PATH.parent / "xml_item_template.png").convert("RGB")
        screenshot = Image.new("RGB", (920, 970), "white")
        screenshot.paste(template, (199, 555))
        self.assertEqual(locate_xml_item_image(
            screenshot, template, (0, 0, 920, 970)), (299, 563))
        screenshot.paste(template, (199, 650))
        with self.assertRaisesRegex(ErroSeguro, "não é única"):
            locate_xml_item_image(screenshot, template, (0, 0, 920, 970))

    def test_acao_completa_localiza_dom_e_clica_mouse_real(self):
        from PIL import Image, ImageDraw, ImageGrab

        screenshot = Image.new("RGB", (1200, 900), (240, 240, 240))
        d = ImageDraw.Draw(screenshot)
        d.rectangle((379, 529, 420, 570), fill=(5, 250, 106))
        d.rectangle((388, 538, 411, 561), fill=(250, 5, 196))
        clicks = []

        class FakeBrowser:
            hwnd = 17
            executed = []

            def _run_dte_bookmarklet(self, script, label):
                self.executed.append((script, label))

            def require_foreground(self):
                pass

        fake_gui = types.SimpleNamespace(
            GetWindowRect=lambda hwnd: (100, 100, 1100, 800),
        )
        fake_auto = types.SimpleNamespace(click=lambda x, y: clicks.append((x, y)))
        fake_win_dll = types.SimpleNamespace(
            user32=types.SimpleNamespace(GetSystemMetrics=lambda number: 0)
        )
        with patch.dict("sys.modules", {"pyautogui": fake_auto, "win32gui": fake_gui}), \
             patch("download_sefaz_xml.ctypes.windll", fake_win_dll, create=True), \
             patch.object(ImageGrab, "grab", return_value=screenshot), \
             patch("download_sefaz_xml.log"):
            fake = FakeBrowser()
            NavegadorNormal.click_xml_with_calibrated_mouse(fake)
        self.assertEqual(clicks, [(400, 550)])
        self.assertIn("idlink=\"42\"", fake.executed[0][0])

    def test_validacao_url_consulta_ignora_token_sso_dinamico(self):
        class Edit:
            def __init__(self, address):
                self.iface_value = type("Value", (), {"CurrentValue": address})()

            def is_visible(self):
                return True

        class Root:
            def __init__(self, address):
                self.field = Edit(address)

            def descendants(self, control_type):
                self_test.assertEqual(control_type, "Edit")
                return [self.field]

        self_test = self
        browser = NavegadorNormal({"navegador": "edge"})
        browser.root = lambda: Root(
            "https://sistemas.sefaz.am.gov.br/nfe-consulta-ex/consultarXML.do?SSO=token1&r=novo"
        )
        self.assertTrue(browser.active_url_matches_xml_consultation())
        browser.root = lambda: Root(
            "https://outro.site/nfe-consulta-ex/consultarXML.do?SSO=token2"
        )
        self.assertFalse(browser.active_url_matches_xml_consultation())

    def test_aba_nfe_nova_pode_ser_selecionada_sem_tocar_aba_original(self):
        class Tab:
            def __init__(self, text):
                self.label = text
                self.clicked = False

            def window_text(self):
                return self.label

            def click_input(self):
                self.clicked = True

        original = Tab("DT-e")
        newly_opened = Tab("Nota Fiscal Eletrônica - Secretaria")
        browser = NavegadorNormal({"navegador": "edge"})
        browser.hwnd = 101
        browser._owned_windows.add(101)
        browser.focus = lambda: None
        browser.visible_tabs = lambda: [original, newly_opened]
        browser.require_foreground = lambda: None
        browser.active_url_matches_xml_consultation = lambda: False
        with patch("download_sefaz_xml.log"):
            browser.maybe_switch_xml_tab(previous_count=1, previous_hwnd=101)
        self.assertTrue(newly_opened.clicked)
        self.assertFalse(original.clicked)

    def test_consulta_em_janela_nova_apos_certificado_com_duas_abas_anteriores(self):
        browser = NavegadorNormal({"navegador": "edge"})
        browser.hwnd = 101
        browser._owned_windows.add(101)
        browser.browser_windows = lambda: {50, 101, 202}
        browser.focus = lambda: None
        browser.visible_tabs = lambda: (_ for _ in ()).throw(
            AssertionError("Não buscar abas quando a consulta abriu em outra janela"))
        with patch("download_sefaz_xml.log"):
            browser.maybe_switch_xml_tab(previous_count=2, previous_hwnd=101,
                                         before_windows={50, 101}, timeout=1)
        self.assertEqual(browser.hwnd, 202)
        self.assertIn(202, browser._owned_windows)

    def test_abas_devtools_nao_sao_contadas_como_abas_edge(self):
        class Tab:
            def __init__(self, top, bottom):
                self.top, self.bottom = top, bottom

            def is_visible(self):
                return True

            def rectangle(self):
                return self

        class Root:
            def rectangle(self):
                return type("Window", (), {"top": 0})()

            def descendants(self, control_type):
                self_test.assertEqual(control_type, "TabItem")
                return [Tab(5, 42), Tab(95, 128), Tab(105, 130)]

        self_test = self
        browser = NavegadorNormal({"navegador": "edge"})
        browser.hwnd = 123
        browser._owned_windows.add(123)
        browser.root = lambda: Root()
        self.assertEqual(len(browser.visible_tabs()), 1)

    def test_consulta_xml_espera_ate_abrir_a_tela_certa(self):
        class FakeBrowser:
            attempts = 0

            def focus(self):
                pass

            def active_url_matches_xml_consultation(self):
                self.attempts += 1
                return self.attempts >= 3

            def has_text(self, names):
                return self.attempts >= 3 and names[0] in {
                    "CONSULTA DE ARQUIVOS XML", "Emitidos no Período De", "Solicitar"
                }

        browser = FakeBrowser()
        with patch("download_sefaz_xml.time.sleep"), patch("download_sefaz_xml.log"):
            wait_for_xml_consultation(browser, timeout=1)
        self.assertEqual(browser.attempts, 3)

    def test_comando_dom_rejeita_acao_desconhecida(self):
        navegador = NavegadorNormal({"navegador": "edge"})
        with self.assertRaisesRegex(ErroSeguro, "não permitido"):
            navegador.click_sefaz_dom("outro_item")

    def test_painel_dte_demora_e_depois_carrega(self):
        class FakeBrowser:
            attempts = 0

            def has_text(self, names):
                if names == ["AVISO AOS CONTRIBUINTES"]:
                    return False
                if names == ["NF-e"]:
                    self.attempts += 1
                    return self.attempts >= 4
                return names == ["Pesquisar"] and self.attempts >= 4

        fake = FakeBrowser()
        with patch("download_sefaz_xml.time.sleep"), patch("download_sefaz_xml.log"):
            wait_for_dte_panel(fake, timeout=1)
        self.assertEqual(fake.attempts, 4)

    def test_painel_dte_pode_fechar_aviso_antes_de_confirmar(self):
        class FakeBrowser:
            aviso_aberto = True

            def has_text(self, names):
                if names == ["AVISO AOS CONTRIBUINTES"]:
                    return self.aviso_aberto
                return not self.aviso_aberto and names[0] in {"NF-e", "Pesquisar"}

            def action(self, names, label, **kwargs):
                self_test.assertEqual(names, ["Fechar Avisos"])
                self.aviso_aberto = False

        self_test = self
        fake = FakeBrowser()
        with patch("download_sefaz_xml.time.sleep"), patch("download_sefaz_xml.log"):
            wait_for_dte_panel(fake, timeout=1)
        self.assertFalse(fake.aviso_aberto)

    def test_menu_nf_e_escolhe_titulo_confirmado_pelo_devtools(self):
        class FakeBrowser:
            def __init__(self):
                self.actions = []

            def has_text(self, names):
                return names in (["NF-e - Download de Arquivos XML"],
                                 ["Consultar arquivos XML das Notas Fiscais Enviadas e Recebidas"])

            def click_xml_with_visual_template(self):
                self.actions.append("fisico_visual")

            def try_click_xml_menu_physical(self):
                self.actions.append("tentativa_fisica")
                return False

        fake = FakeBrowser()
        with patch("download_sefaz_xml.log"):
            open_sefaz_xml_download(fake)
        self.assertEqual(fake.actions, ["tentativa_fisica", "fisico_visual"])

    def test_menu_nf_e_prefere_clique_fisico_sem_comando_dom(self):
        class FakeBrowser:
            actions = []

            def has_text(self, names):
                return True

            def try_click_xml_menu_physical(self):
                self.actions.append("fisico")
                return True

            def click_sefaz_dom(self, action):
                raise AssertionError("Nao executar JS depois do clique fisico")

        fake = FakeBrowser()
        with patch("download_sefaz_xml.log"):
            open_sefaz_xml_download(fake)
        self.assertEqual(fake.actions, ["fisico"])

    def test_clique_fisico_so_em_titulo_pequeno_visivel_e_unico(self):
        class Rect:
            left, top, right, bottom = 550, 350, 920, 380

        class WindowRect:
            left, top, right, bottom = 0, 0, 1400, 900

        class Item:
            clicked = False

            def window_text(self):
                return "NF-e - Download de Arquivos XML(NF-e, NFC-e, CT-e)"

            def rectangle(self):
                return Rect()

            def click_input(self):
                self.clicked = True

        class Root:
            def rectangle(self):
                return WindowRect()

        item = Item()
        browser = NavegadorNormal({"navegador": "edge"})
        browser.focus = lambda: None
        browser.require_foreground = lambda: None
        browser.root = lambda: Root()
        browser._matches = lambda names, kind=None, contains=False: (
            [item] if kind == {"Text"} else []
        )
        with patch("download_sefaz_xml.log"):
            self.assertTrue(browser.try_click_xml_menu_physical())
        self.assertTrue(item.clicked)

    def test_menu_nf_e_sem_descricao_uia_exige_guarda_no_dom(self):
        class FakeBrowser:
            actions = []

            def has_text(self, names):
                return False

            def click_xml_with_visual_template(self):
                self.actions.append("fisico_visual")

        fake = FakeBrowser()
        with patch("download_sefaz_xml.log"):
            open_sefaz_xml_download(fake)
        self.assertEqual(fake.actions, ["fisico_visual"])

    def test_selecao_matriz_clica_na_ie_azul_e_nao_no_cnpj(self):
        class FakeLink:
            was_clicked = False

            def click_input(self):
                self.was_clicked = True

        class FakeBrowser:
            config = {"empresa_inscricao_estadual": "12.345.678-9"}

            def __init__(self):
                self.link = FakeLink()

            def has_text(self, names):
                if names[0] == "Situação Cadastral":
                    return True
                return self.link.was_clicked and names[0] in {
                    "NF-e", "Pesquisar", "Débitos Fiscais"
                }

            def _matches(self, names, kind=None):
                if names != ["12.345.678-9"]:
                    raise AssertionError("Alvo nao e a IE configurada para teste")
                return [self.link] if kind == {"Hyperlink"} else []

            def focus(self):
                pass

            def click_relative(self, *args, **kwargs):
                raise AssertionError("Nao deve clicar perto do CNPJ por pixel")

        fake = FakeBrowser()
        with patch("download_sefaz_xml.time.sleep"), patch("download_sefaz_xml.log"):
            select_company_sefaz(fake)
        self.assertTrue(fake.link.was_clicked)

    def test_dashboard_nao_clica_novamente_no_cnpj(self):
        class FakeBrowser:
            config = {}

            def has_text(self, names):
                return names[0] in {"Débitos Fiscais", "Pesquisar", "NF-e"}

            def click_relative(self, *args, **kwargs):
                raise AssertionError("Nao deve clicar no CNPJ ja selecionado")

        with patch("download_sefaz_xml.log"):
            select_company_sefaz(FakeBrowser())

    def test_dashboard_com_debitos_sem_pesquisar_tambem_prossegue(self):
        class FakeBrowser:
            config = {}

            def has_text(self, names):
                return names[0] in {"NF-e", "Débitos Fiscais"}

            def action(self, *args, **kwargs):
                raise AssertionError("Nao deve clicar em uma empresa novamente")

        with patch("download_sefaz_xml.log"):
            select_company_sefaz(FakeBrowser())

    def test_modal_oficial_e_fechado_sem_escape_generico(self):
        class FakeBrowser:
            closed = False

            def has_text(self, names):
                return names == ["AVISO AOS CONTRIBUINTES"] and not self.closed

            def action(self, names, label, **kwargs):
                if names != ["Fechar Avisos"]:
                    raise AssertionError("Tentativa de fechar dialogo desconhecido")
                self.closed = True

        test_browser = FakeBrowser()
        with patch("download_sefaz_xml.time.sleep"), patch("download_sefaz_xml.log"):
            close_sefaz_advisories(test_browser)
        self.assertTrue(test_browser.closed)

    def test_navegador_da_usuaria_e_edge(self):
        config = read_json(CONFIG_PATH, {})
        self.assertEqual(browser_kind(config), "edge")
        self.assertEqual(browser_kind({"navegador": "chrome"}), "chrome")
        with self.assertRaises(ErroSeguro):
            browser_kind({"navegador": "internet-explorer"})

    def test_perfil_sem_caminho_externo(self):
        for name in ("", "Default", "Profile 1", "Profile 10"):
            self.assertEqual(validate_profile_directory(name), name)
        for name in ("C:\\Users\\teste", "../../Default", "--remote-debugging-port=9222"):
            with self.assertRaises(ErroSeguro):
                validate_profile_directory(name)

    def test_sefaz_login_host(self):
        config = read_json(CONFIG_PATH, {})
        self.assertEqual(config["sefaz_login_url"],
                         "https://online.sefaz.am.gov.br/dte/loginSSL.asp")

    def test_sefaz_year_rollover(self):
        self.assertEqual(sefaz_periodo(date(2026, 10, 28)),
                         (date(2026, 10, 27), date(2026, 10, 28)))
        self.assertEqual(sefaz_periodo(date(2027, 1, 1)),
                         (date(2026, 12, 31), date(2027, 1, 1)))
        self.assertEqual(sefaz_periodo(date(2026, 10, 28), "2026-10-25"),
                         (date(2026, 10, 25), date(2026, 10, 28)))
        start = date(2026, 12, 31)
        end = date(2027, 1, 1)
        self.assertEqual(desktop_zip_name(start, end),
                         "Notas_SEFAZ_31-12-2026_a_01-01-2027.zip")

    def test_origem_recebidos_e_confirmada_antes_de_solicitar(self):
        from download_sefaz_xml import NavegadorNormal

        class FakeCombo:
            chosen = "Documentos Fiscais Emitidos"

            def selected_text(self):
                return self.chosen

            def select(self, target):
                self.chosen = target

            def expand(self):
                pass

        class FakeOption:
            def is_visible(self):
                return True

            def window_text(self):
                return "Documentos Fiscais Recebidos"

            def click_input(self):
                combo.select("Documentos Fiscais Recebidos")

        class FakeRoot:
            def descendants(self, control_type):
                return [FakeOption()] if control_type == "ListItem" else []

        combo = FakeCombo()
        browser = NavegadorNormal({"navegador": "edge"})
        browser.control_near_label = lambda *args: combo
        browser.focus = lambda: None
        browser.require_foreground = lambda: None
        browser.root = lambda: FakeRoot()
        with patch("download_sefaz_xml.log"):
            browser.select_origin_received()
        self.assertEqual(combo.selected_text(), "Documentos Fiscais Recebidos")

    def test_sankhya_next_year(self):
        self.assertEqual(sankhya_periodo(date(2026, 10, 28), {}),
                         (date(2026, 1, 1), date(2027, 12, 31)))
        self.assertEqual(sankhya_periodo(date(2027, 1, 1), {}),
                         (date(2027, 1, 1), date(2028, 12, 31)))

    def test_sankhya_date_optional(self):
        self.assertEqual(sankhya_periodo(date(2026, 10, 28),
                                         {"sankhya_periodo_fim_mes": 12,
                                          "sankhya_periodo_fim_dia": 1})[1],
                         date(2027, 12, 1))

    def test_zip_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid = root / "nfe.zip"
            invalid = root / "quebrado.zip"
            with zipfile.ZipFile(valid, "w") as arq:
                arq.writestr("nfe.xml", "<xml/>")
            invalid.write_bytes(b"nao e zip")
            validate_zip(valid)
            with self.assertRaises((ErroSeguro, zipfile.BadZipFile)):
                validate_zip(invalid)


if __name__ == "__main__":
    unittest.main()
