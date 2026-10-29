"""Automação de consulta e download de XML recebidos no DT-e da SEFAZ-AM.

O módulo reúne a orquestração da rotina, o controle da janela própria do Edge,
a validação dos dados baixados e a interface de progresso da execução manual.
O caminho agendado usa o Edge sem janela visível. A classe ``NavegadorNormal``
encapsula as operações de interface; as funções de domínio descrevem cada
etapa da consulta; ``ErroSeguro`` interrompe ações quando a tela é ambígua.

O fluxo não envia documentos ao Sankhya. A integração permanece desabilitada
por configuração e não faz parte do fluxo de download. Ações no menu legado
do DT-e usam comandos locais, restritos ao domínio, caminho e controles
oficiais esperados. Quando a identificação visual não é comprovada, a rotina
para sem clicar.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import hashlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
import zipfile
from ctypes import wintypes
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

FROZEN = bool(getattr(sys, "frozen", False))
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", ROOT))
APP_HOME = Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "RPA_SEFAZ" if FROZEN else ROOT
CONFIG_PATH = APP_HOME / "config.json"
STATE_PATH = APP_HOME / "estado.json"
LOG_DIR = APP_HOME / "logs"

# Os menus legados do DT-e aparecem no DOM mas não são expostos como controles
# individuais pelo UI Automation do Edge da usuária. Cada ação abaixo só é
# permitida no host/caminho oficiais, sobre UM elemento com id/texto confirmados
# nos prints do DevTools. Não lê cookies nem envia dados a outros endereços.
DTE_DOM_ACTIONS = {
    "categoria_nfe": (
        "javascript:void(function(){"
        "if(location.hostname!=='online.sefaz.am.gov.br'||location.pathname!=='/menu/dte.asp')return;"
        "var e=document.querySelectorAll('div.menuDte_categoria2[categoria=\"2\"]');"
        "if(e.length!==1)return;"
        "var t=e[0].querySelector('.menuDte_conteudoCategoria2');"
        "if(!t||t.textContent.trim()!=='NF-e')return;"
        "e[0].click()"
        "}())"
    ),
    "download_xml": (
        "javascript:void(function(){"
        "if(location.hostname!=='online.sefaz.am.gov.br'||location.pathname!=='/menu/dte.asp')return;"
        "var e=document.querySelectorAll('div.menuDte_itemMenu[idlink=\"42\"]');"
        "if(e.length!==1)return;"
        "var t=e[0].querySelector('.menuDte_itemMenu_titulo');"
        "var d=e[0].querySelector('.menuDte_itemMenu_descricao');"
        "if(!t||!t.textContent.trim().startsWith('NF-e - Download de Arquivos XML'))return;"
        "if(!d||!d.textContent.includes('Consultar arquivos XML das Notas Fiscais Enviadas e Recebidas'))return;"
        "var r=t.getBoundingClientRect();"
        "if(r.width<=0||r.height<=0)return;"
        "var p=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);"
        "if(!p||!e[0].contains(p))return;"
        "t.click()"
        "}())"
    ),
}

# Este seletor de diagnóstico valida o elemento HTML e posiciona marcadores
# temporários sobre ele. A captura local pode confirmar o ponto antes do clique.
DTE_XML_MARKER_SCRIPT = (
    "javascript:void(function(){"
    "if(location.hostname!=='online.sefaz.am.gov.br'||location.pathname!=='/menu/dte.asp')return;"
    "function status(c){var m=document.createElement('div');"
    "m.style.cssText='position:fixed;left:12px;top:120px;width:24px;height:24px;background:'+c+"
    "';pointer-events:none;z-index:2147483647';document.body.appendChild(m);"
    "setTimeout(function(){m.remove()},18000)}"
    "var e=document.querySelectorAll('div.menuDte_itemMenu[idlink=\"42\"]');"
    "if(e.length!==1){status('#FF6A00');return;}"
    "var t=e[0].querySelector('.menuDte_itemMenu_titulo');"
    "if(!t||!t.textContent.includes('NF-e - Download de Arquivos XML'))"
    "{status('#FFBB00');return;}"
    "var r=t.getBoundingClientRect(),l=Math.max(0,r.left),"
    "rr=Math.min(innerWidth,r.right),u=Math.max(0,r.top),b=Math.min(innerHeight,r.bottom);"
    "if(rr-l<25||b-u<6){status('#00DDEA');return;}"
    "var x=Math.round(l+Math.min(100,(rr-l)/2)),y=Math.round((u+b)/2);"
    "var h=document.elementFromPoint(x,y);"
    "if(!h||!e[0].contains(h)){status('#FF2222');return;}"
    "function mark(s,c){var m=document.createElement('div');"
    "m.style.cssText='position:fixed;left:'+(x-s/2)+'px;top:'+(y-s/2)+"
    "'px;width:'+s+'px;height:'+s+'px;background:'+c+"
    "';pointer-events:none;z-index:2147483647';"
    "document.body.appendChild(m);return m;}"
    "status('#2A62FD');"
    "var a=mark(28,'#05FA6A'),c=mark(16,'#FA05C4');"
    "setTimeout(function(){a.remove();c.remove()},18000)"
    "}())"
)


def locate_dom_marker(screenshot, bounds: tuple[int, int, int, int],
                      screenshot_origin: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    """Encontra quadrados concentricos desenhados SOBRE o alvo DOM.

    Não requer transmissão de coordenadas via titulo/clipboard nem OCR.
    A captura fica somente na memoria local do processo.
    """
    left, top, right, bottom = bounds
    screen_left, screen_top = screenshot_origin
    if right - left < 400 or bottom - top < 300:
        raise ErroSeguro("Janela do robô pequena demais para calibrar clique")
    # Bordas do Edge podem ultrapassar a área física da captura (janela
    # maximizada, monitores com DPI diferente ou parte fora da tela). Só a
    # interseção visível importa: o marcador precisa aparecer nela inteiro.
    visible_left = max(left, screen_left)
    visible_top = max(top, screen_top)
    visible_right = min(right, screen_left + screenshot.width)
    visible_bottom = min(bottom, screen_top + screenshot.height)
    if visible_right - visible_left < 300 or visible_bottom - visible_top < 200:
        raise ErroSeguro("Parte visivel da janela pequena demais para localizar o item XML")

    cropped = screenshot.crop((visible_left - screen_left, visible_top - screen_top,
                               visible_right - screen_left, visible_bottom - screen_top)).convert("RGB")
    width = cropped.width
    targets = ((250, 5, 196), (5, 250, 106))
    boxes = [[width, cropped.height, -1, -1, 0] for _ in targets]
    pixels = (cropped.get_flattened_data() if hasattr(cropped, "get_flattened_data")
              else cropped.getdata())
    for index, pixel in enumerate(pixels):
        for number, color in enumerate(targets):
            if all(abs(pixel[channel] - color[channel]) <= 4 for channel in range(3)):
                x, y = index % width, index // width
                box = boxes[number]
                box[0] = min(box[0], x)
                box[1] = min(box[1], y)
                box[2] = max(box[2], x)
                box[3] = max(box[3], y)
                box[4] += 1
    if any(box[4] < 30 for box in boxes):
        raise ErroSeguro("Marcadores HTML nao apareceram na captura de tela")
    if any(not (8 <= b[2] - b[0] + 1 <= 140 and 8 <= b[3] - b[1] + 1 <= 140)
           for b in boxes):
        raise ErroSeguro("Marcadores HTML duplicados ou distorcidos; sem clique")
    inner, outer = boxes
    inner_w, outer_w = inner[2] - inner[0] + 1, outer[2] - outer[0] + 1
    if not (1.3 <= outer_w / inner_w <= 2.4):
        raise ErroSeguro("Marcadores HTML nao estao nas proporcoes esperadas")
    center_inner = ((inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2)
    center_outer = ((outer[0] + outer[2]) / 2, (outer[1] + outer[3]) / 2)
    if max(abs(center_inner[0] - center_outer[0]),
           abs(center_inner[1] - center_outer[1])) > max(3, inner_w * 0.2):
        raise ErroSeguro("Marcadores HTML nao estao concentricos; sem clique")
    click_x = round(visible_left + (center_inner[0] + center_outer[0]) / 2)
    click_y = round(visible_top + (center_inner[1] + center_outer[1]) / 2)
    if not (left + 20 <= click_x <= right - 20 and
            top + 80 <= click_y <= bottom - 15):
        raise ErroSeguro("Clique calculado fora da regiao de conteudo do navegador")
    return click_x, click_y


def marker_diagnostic(screenshot, bounds: tuple[int, int, int, int],
                      screenshot_origin: tuple[int, int] = (0, 0)) -> str | None:
    """Lê a cor de diagnóstico desenhada pelo bookmarklet na janela do robô."""
    left, top, right, bottom = bounds
    screen_left, screen_top = screenshot_origin
    visible_left = max(left, screen_left)
    visible_top = max(top, screen_top)
    visible_right = min(right, screen_left + screenshot.width)
    visible_bottom = min(bottom, screen_top + screenshot.height)
    if visible_left >= visible_right or visible_top >= visible_bottom:
        return None
    cropped = screenshot.crop((visible_left - screen_left, visible_top - screen_top,
                               visible_right - screen_left, visible_bottom - screen_top)).convert("RGB")
    statuses = {
        (255, 106, 0): "HTML executou, mas idlink=42 nao foi unico/encontrado",
        (255, 187, 0): "HTML executou, mas titulo do item XML nao conferiu",
        (0, 221, 234): "HTML executou, mas titulo do item XML estava fora da area visivel",
        (255, 34, 34): "HTML executou, mas outro elemento cobria o ponto do clique",
        (42, 98, 253): "HTML localizou o item, mas a captura nao reconheceu os marcadores",
    }
    counts = {color: 0 for color in statuses}
    pixels = (cropped.get_flattened_data() if hasattr(cropped, "get_flattened_data")
              else cropped.getdata())
    for pixel in pixels:
        for color in statuses:
            if all(abs(pixel[channel] - color[channel]) <= 8 for channel in range(3)):
                counts[color] += 1
    color = max(counts, key=counts.get)
    return statuses[color] if counts[color] >= 30 else None


def locate_sefaz_banner(screenshot, template, bounds: tuple[int, int, int, int],
                        screenshot_origin: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    """Encontra a imagem oficial do banner na parte visível da janela criada."""
    from PIL import Image, ImageChops, ImageStat

    left, top, right, bottom = bounds
    screen_left, screen_top = screenshot_origin
    visible_left = max(left, screen_left)
    visible_top = max(top, screen_top)
    visible_right = min(right, screen_left + screenshot.width)
    visible_bottom = min(bottom, screen_top + screenshot.height)
    if visible_right - visible_left < 350 or visible_bottom - visible_top < 200:
        raise ErroSeguro("Janela pequena demais para localizar o banner do DT-e")
    area = screenshot.crop((visible_left - screen_left, visible_top - screen_top,
                            visible_right - screen_left, visible_bottom - screen_top)).convert("RGB")
    rgba = template.convert("RGBA")
    white = Image.new("RGBA", rgba.size, "white")
    white.alpha_composite(rgba)
    original = white.convert("RGB")
    source = area.load()

    for scale in (1.0, 0.8, 0.9, 1.1, 1.25, 1.5):
        candidate = (original if scale == 1.0 else original.resize(
            (round(original.width * scale), round(original.height * scale)),
            Image.Resampling.LANCZOS))
        if candidate.width > area.width or candidate.height > area.height:
            continue
        first = (round(315 * scale), round(50 * scale))
        second = (round(90 * scale), round(20 * scale))
        first_color, second_color = candidate.getpixel(first), candidate.getpixel(second)
        matches = []
        for y in range(first[1], area.height - candidate.height + first[1] + 1):
            for x in range(first[0], area.width - candidate.width + first[0] + 1):
                pixel = source[x, y]
                if any(abs(pixel[i] - first_color[i]) > 8 for i in range(3)):
                    continue
                x0, y0 = x - first[0], y - first[1]
                pixel2 = source[x0 + second[0], y0 + second[1]]
                if any(abs(pixel2[i] - second_color[i]) > 8 for i in range(3)):
                    continue
                cropped = area.crop((x0, y0, x0 + candidate.width, y0 + candidate.height))
                score = sum(ImageStat.Stat(ImageChops.difference(cropped, candidate)).mean) / 3
                if score <= 5:
                    matches.append((score, x0, y0))
        if matches:
            matches.sort()
            _, x0, y0 = matches[0]
            if any(abs(x - x0) > 8 or abs(y - y0) > 8 for _, x, y in matches[1:]):
                raise ErroSeguro("Mais de um banner DT-e parecido na janela; nenhum clique feito")
            return (visible_left + x0 + candidate.width // 2,
                    visible_top + y0 + candidate.height // 2)
    raise ErroSeguro("Banner oficial 'Acessar o DT-e' não localizado na janela")


def locate_xml_item_image(screenshot, template, bounds: tuple[int, int, int, int],
                          screenshot_origin: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    """Localiza uma única linha visual com o título e a descrição do item XML."""
    import pyscreeze

    left, top, right, bottom = bounds
    screen_left, screen_top = screenshot_origin
    visible_left = max(left, screen_left)
    visible_top = max(top, screen_top)
    visible_right = min(right, screen_left + screenshot.width)
    visible_bottom = min(bottom, screen_top + screenshot.height)
    if visible_right - visible_left < template.width or visible_bottom - visible_top < 300:
        raise ErroSeguro("Área visível pequena demais para localizar o item XML")
    area = screenshot.crop((visible_left - screen_left, visible_top - screen_top,
                            visible_right - screen_left, visible_bottom - screen_top)).convert("RGB")
    try:
        matches = list(pyscreeze.locateAll(template.convert("RGB"), area, grayscale=False))
    except pyscreeze.ImageNotFoundException:
        matches = []
    if len(matches) != 1:
        raise ErroSeguro(f"Linha visual do item XML não é única/visível ({len(matches)} resultados)")
    match = matches[0]
    # O recorte começa junto ao título; y+8 permanece dentro da linha azul.
    x = visible_left + match.left + 100
    y = visible_top + match.top + 8
    if not (left + 20 <= x <= right - 20 and top + 80 <= y <= bottom - 15):
        raise ErroSeguro("Ponto do item XML fora da área de conteúdo do navegador")
    return x, y


class ErroSeguro(RuntimeError):
    """Erro que interrompe a rotina antes de alguma ação ambígua."""


def log(etapa: str, msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    linha = f"[{datetime.now().isoformat(timespec='seconds')}] [{etapa}] {msg}"
    print(linha, flush=True)
    with (LOG_DIR / f"rpa_{date.today().isoformat()}.log").open("a", encoding="utf-8") as arq:
        arq.write(linha + "\n")


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    with path.open(encoding="utf-8") as arq:
        val = json.load(arq)
    if not isinstance(val, dict):
        raise ErroSeguro(f"Formato incorreto: {path.name}")
    return val


def save_state(**kwargs) -> None:
    state = read_json(STATE_PATH, {})
    state.update(kwargs)
    temp = STATE_PATH.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as arq:
        json.dump(state, arq, indent=2, ensure_ascii=False)
    os.replace(temp, STATE_PATH)


def get_desktop() -> Path:
    """Localiza a Área de Trabalho, inclusive quando redirecionada pelo OneDrive/GPO."""
    if sys.platform != "win32":
        raise ErroSeguro("A rotina de desktop é exclusiva do Windows")
    # FOLDERID_Desktop: {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
    import uuid
    from ctypes import POINTER

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    id_obj = uuid.UUID("B4BFCC3A-DB2C-424C-B029-7FE99A87C641")
    guid = GUID(id_obj.time_low, id_obj.time_mid, id_obj.time_hi_version,
                (ctypes.c_ubyte * 8).from_buffer_copy(id_obj.bytes[8:]))
    resultado = ctypes.c_wchar_p()
    fn = ctypes.windll.shell32.SHGetKnownFolderPath
    fn.argtypes = [POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, POINTER(ctypes.c_wchar_p)]
    fn.restype = ctypes.c_long
    status = fn(ctypes.byref(guid), 0, None, ctypes.byref(resultado))
    if status != 0:
        raise ErroSeguro(f"Não foi possível localizar a Área de Trabalho (HRESULT {status})")
    try:
        path = Path(resultado.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(resultado, ctypes.c_void_p))
    if not path.is_dir():
        raise ErroSeguro(f"Área de Trabalho indisponível: {path}")
    return path


def get_download_folder(config: dict) -> Path:
    """Diretório de downloads do navegador: configurado ou Downloads do Windows."""
    explicit = str(config.get("downloads_dir", "")).strip()
    if explicit:
        path = Path(os.path.expandvars(explicit)).expanduser()
    else:
        # Fallback: Downloads padrão. Se o navegador usa outra pasta, configurar
        # downloads_dir evita selecionar o ZIP de outra origem por engano.
        path = Path.home() / "Downloads"
    if not path.is_dir():
        raise ErroSeguro(f"Pasta de downloads inexistente: {path}")
    return path


def desktop_zip_name(start: date, end: date) -> str:
    return f"Notas_SEFAZ_{start:%d-%m-%Y}_a_{end:%d-%m-%Y}.zip"


def sankhya_periodo(today: date, config: dict) -> tuple[date, date]:
    """De 01/jan do ano corrente até o fim configurado do ano seguinte."""
    mes = int(config.get("sankhya_periodo_fim_mes", 12))
    dia = int(config.get("sankhya_periodo_fim_dia", 31))
    return date(today.year, 1, 1), date(today.year + 1, mes, dia)


def sefaz_periodo(today: date, ultimo_concluido: str | None = None) -> tuple[date, date]:
    """Ontem/hoje no teste, ou recupera pendências desde a última execução."""
    inicio = date.fromisoformat(ultimo_concluido) if ultimo_concluido else today - timedelta(days=1)
    if inicio > today:
        raise ErroSeguro("Última data concluída está no futuro; confira estado.json")
    return inicio, today


def sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as arq:
        for parte in iter(lambda: arq.read(1024 * 1024), b""):
            sha.update(parte)
    return sha.hexdigest()


def snapshot_zips(folder: Path) -> dict[str, tuple[int, int]]:
    return {str(f.resolve()): (f.stat().st_mtime_ns, f.stat().st_size)
            for f in folder.glob("*.zip") if f.is_file()}


def await_zip(folder: Path, prior: dict[str, tuple[int, int]], timeout: int = 120) -> Path:
    """Aceita um único ZIP novo e completo após clicar no Download."""
    deadline = time.monotonic() + timeout
    stable_path = None
    stable_size = -1
    stable_count = 0
    while time.monotonic() < deadline:
        changed = [f for f in folder.glob("*.zip") if f.is_file() and
                   (str(f.resolve()) not in prior or
                    (f.stat().st_mtime_ns, f.stat().st_size) != prior[str(f.resolve())])]
        if len(changed) > 1:
            raise ErroSeguro("Mais de um ZIP novo detectado. Não é seguro escolher o arquivo")
        if len(changed) == 1:
            file = changed[0]
            size = file.stat().st_size
            if stable_path == file and stable_size == size:
                stable_count += 1
            else:
                stable_path, stable_size, stable_count = file, size, 0
            # .crdownload do mesmo nome ainda pode existir até o fim.
            if stable_count >= 3 and not list(folder.glob(file.name + ".crdownload")):
                try:
                    validate_zip(file)
                    return file
                except (ErroSeguro, zipfile.BadZipFile):
                    pass
        time.sleep(1)
    raise ErroSeguro("ZIP não apareceu completo na pasta Downloads dentro do prazo")


def keep_zip_on_desktop(downloaded: Path, start: date, end: date,
                        downloaded_on: date | None = None) -> Path:
    """Move o ZIP para Desktop/Notas sefaz/nota DD-MM-AAAA sem sobrescrever."""
    day = downloaded_on or date.today()
    folder = get_desktop() / "Notas sefaz" / f"nota {day:%d-%m-%Y}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / desktop_zip_name(start, end)
    if path.exists():
        validate_zip(path)
        if sha256_file(downloaded) == sha256_file(path):
            downloaded.unlink(missing_ok=True)
            log("ARQUIVO", f"ZIP idêntico já estava na pasta diária: {path.parent.name}/{path.name}")
            return path
        path = folder / f"{path.stem}_{datetime.now():%H%M%S}.zip"
    shutil.move(str(downloaded), str(path))
    validate_zip(path)
    log("ARQUIVO", f"ZIP guardado: {path.parent.parent.name}/{path.parent.name}/{path.name} ({path.stat().st_size} bytes)")
    return path


def ensure_manual_shortcut() -> Path:
    """Cria no Desktop um atalho que inicia a consulta invisível sob demanda."""
    import win32com.client

    desktop = get_desktop()
    (desktop / "Notas sefaz").mkdir(parents=True, exist_ok=True)
    target_script = ROOT / "executar_manual.vbs"
    if FROZEN:
        raise ErroSeguro("O atalho manual é o próprio executável na Área de Trabalho")
    if not target_script.is_file():
        raise ErroSeguro("Arquivo do atalho manual ausente no pacote")
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = desktop / "Automacao Notas Sefaz.lnk"
    if shortcut.exists():
        current = shell.CreateShortcut(str(shortcut))
        if Path(current.TargetPath).name.casefold() != "wscript.exe" or "executar_manual.vbs" not in current.Arguments:
            shortcut = desktop / "Automacao Notas Sefaz - RPA.lnk"
    link = shell.CreateShortcut(str(shortcut))
    link.TargetPath = str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "wscript.exe")
    link.Arguments = f'//B //Nologo "{target_script}"'
    link.WorkingDirectory = str(ROOT)
    link.Description = "Baixa XML recebidos da SEFAZ-AM sem abrir janela do Edge"
    link.Save()
    return shortcut


def wait_for_network(config: dict) -> None:
    """Espera a internet voltar antes de iniciar o Edge invisível."""
    host = "online.sefaz.am.gov.br"
    max_hours = float(config.get("aguardar_internet_horas", 24))
    deadline = time.monotonic() + max_hours * 3600
    last_log = 0.0
    while True:
        try:
            with socket.create_connection((host, 443), timeout=6):
                log("REDE", "Conexão HTTPS com a SEFAZ disponível")
                return
        except OSError:
            now = time.monotonic()
            if now >= deadline:
                raise ErroSeguro(f"Internet ainda indisponível após {max_hours:g}h; próxima tentativa no próximo gatilho")
            if now - last_log >= 300:
                log("REDE", "Sem conexão com a SEFAZ; aguardando e tentando novamente em 60s")
                last_log = now
            time.sleep(60)


def _page_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=2500)
    except Exception:
        return ""


def _wait_page(context, predicate, timeout: float, description: str):
    deadline = time.monotonic() + timeout
    last_state = "sem páginas"
    while time.monotonic() < deadline:
        pages = [p for p in context.pages if not p.is_closed()]
        for page in reversed(pages):
            try:
                text = _page_text(page)
                path = urlsplit(page.url)
                last_state = (f"páginas={len(pages)}, host={path.hostname or 'vazio'}, "
                              f"caminho={path.path or '/'}, login={('Sessão não definida' in text)}, "
                              f"empresa={('Situação Cadastral' in text)}, painel={('NF-e' in text and 'Pesquisar' in text)}")
                if predicate(page, text):
                    return page
            except Exception:
                continue
        time.sleep(0.5)
    raise ErroSeguro(f"Página não confirmada no Edge invisível: {description} ({last_state})")


def download_sefaz_background(config: dict, start: date, end: date) -> Path | None:
    """Baixa XML com Edge headless e DOM; não abre janela nem usa cliques de tela."""
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

    login_url = str(config.get("sefaz_login_url", ""))
    if login_url != "https://online.sefaz.am.gov.br/dte/loginSSL.asp":
        raise ErroSeguro("URL de login fora do destino confirmado do banner SEFAZ")
    desktop = get_desktop()
    (desktop / "Notas sefaz").mkdir(parents=True, exist_ok=True)
    if not FROZEN:
        ensure_manual_shortcut()
    wait_for_network(config)
    downloads = get_download_folder(config)
    downloads.mkdir(parents=True, exist_ok=True)
    edge = browser_path("edge")
    if not edge.is_file():
        raise ErroSeguro("Microsoft Edge não encontrado para o modo invisível")
    profile = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "RPA_SEFAZ" / "EdgeHeadlessProfile"
    profile.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile), executable_path=str(edge), headless=True,
            accept_downloads=True, viewport={"width": 1440, "height": 1000},
            args=["--no-first-run", "--disable-features=msEdgeSidebarV2"])
        try:
            stage = "abrir página inicial"
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(config["sefaz_url"], wait_until="domcontentloaded", timeout=60000)
            stage = "localizar banner do DT-e"
            banner = page.locator('a[href*="loginSSL.asp"]')
            if banner.count() != 1:
                raise ErroSeguro(f"Banner de acesso ao DT-e não é único no DOM ({banner.count()})")
            if not banner.is_visible() or urlsplit(page.url).hostname != "online.sefaz.am.gov.br":
                raise ErroSeguro("Banner do DT-e não está visível no domínio oficial")
            banner.evaluate("element => element.click()")
            log("SEFAZ", "Banner Acessar o DT-e acionado no Edge invisível")

            stage = "autenticação por certificado"
            ie = str(config.get("empresa_inscricao_estadual", "")).strip()
            if not re.fullmatch(r"\d{2}\.\d{3}\.\d{3}-\d", ie):
                raise ErroSeguro("Inscrição estadual da matriz não configurada; execute instalar.bat e informe o valor solicitado")
            ie_digits = re.sub(r"\D", "", ie)
            page = _wait_page(context, lambda p, text: (
                "Situação Cadastral" in text or
                (urlsplit(p.url).hostname == "online.sefaz.am.gov.br" and
                 urlsplit(p.url).path == "/dte/sel_inscricao.asp" and
                 ie_digits in re.sub(r"\D", "", text)) or
                ("NF-e" in text and "Pesquisar" in text)),
                float(config.get("aguardar_certificado_segundos", 120)), "autenticação por certificado")
            text = _page_text(page)
            parsed_page = urlsplit(page.url)
            company_selection = ("Situação Cadastral" in text or
                                 (parsed_page.hostname == "online.sefaz.am.gov.br" and
                                  parsed_page.path == "/dte/sel_inscricao.asp"))
            if company_selection:
                stage = "selecionar inscrição estadual"
                frame_matches = []
                for frame in page.frames:
                    try:
                        counts = frame.evaluate("""target => {
                          const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
                          const els = [...document.querySelectorAll('a,[onclick],[role=button],button')];
                          return {anchors: els.filter(e => e.tagName === 'A' && norm(e.innerText || e.textContent).includes(target)).length,
                            clickables: els.filter(e => norm(e.innerText || e.textContent).includes(target)).length,
                            pageText: norm(document.body?.innerText).includes(target)};
                        }""", ie)
                        if counts["clickables"] or counts["pageText"]:
                            frame_matches.append((frame, counts))
                    except Exception:
                        continue
                links = sum(counts["anchors"] for _, counts in frame_matches)
                clickables = sum(counts["clickables"] for _, counts in frame_matches)
                if links != 1 or clickables != 1:
                    reports = ",".join(str(counts) for _, counts in frame_matches) or "nenhum elemento textual"
                    raise ErroSeguro(f"Inscrição estadual não é um link clicável único (links={links}, elementos={clickables}; {reports})")
                frame_matches[0][0].evaluate("""target => {
                  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
                  [...document.querySelectorAll('a')].find(e => norm(e.innerText || e.textContent).includes(target)).click();
                }""", ie)
                page = _wait_page(context, lambda p, text: "NF-e" in text and
                                  ("Pesquisar" in text or "Débitos Fiscais" in text),
                                  float(config.get("aguardar_painel_dte_segundos", 25)), "painel DT-e")
            log("CERTIFICADO", "Autenticação por certificado e painel DT-e confirmados sem janela visível")

            stage = "fechar avisos do DT-e"
            for _ in range(6):
                close = page.get_by_text("Fechar Avisos", exact=True)
                if close.count() == 0:
                    break
                if close.count() != 1:
                    raise ErroSeguro("Controle Fechar Avisos ambíguo no DT-e")
                if urlsplit(page.url).hostname != "online.sefaz.am.gov.br":
                    raise ErroSeguro("Aviso do DT-e fora do domínio oficial")
                close.evaluate("element => element.click()")
                page.wait_for_timeout(500)
            stage = "abrir categoria NF-e"
            category = page.locator('div.menuDte_categoria2[categoria="2"]')
            if category.count() != 1:
                raise ErroSeguro(f"Categoria NF-e não é única ({category.count()})")
            if category.locator(".menuDte_conteudoCategoria2").inner_text().strip() != "NF-e":
                raise ErroSeguro("Categoria NF-e não identificada de forma única")
            category.click(timeout=10000)
            stage = "abrir consulta XML"
            candidates = page.locator('div.menuDte_itemMenu[idlink="42"]').all()
            visible_items = []
            for candidate in candidates:
                try:
                    title = candidate.locator(".menuDte_itemMenu_titulo").inner_text().strip()
                    if candidate.is_visible() and title.startswith("NF-e - Download de Arquivos XML"):
                        visible_items.append(candidate)
                except Exception:
                    continue
            if len(visible_items) != 1:
                raise ErroSeguro(f"Item XML idlink=42/título não é visível e único ({len(visible_items)} de {len(candidates)})")
            item = visible_items[0]
            before_pages = set(context.pages)
            item.click(timeout=15000)
            query = _wait_page(context, lambda p, text: (
                urlsplit(p.url).hostname == "sistemas.sefaz.am.gov.br" and
                urlsplit(p.url).path == "/nfe-consulta-ex/consultarXML.do" and
                p.locator("#datepicker_de").evaluate_all(
                    "els => els.filter(e => e.getClientRects().length > 0).length") >= 1 and
                p.locator("#datepicker_ate").evaluate_all(
                    "els => els.filter(e => e.getClientRects().length > 0).length") >= 1 and
                "Solicitar" in text),
                float(config.get("aguardar_consulta_xml_segundos", 35)), "consulta de arquivos XML")
            if query not in before_pages:
                log("SEFAZ", "Consulta XML aberta em nova aba invisível")

            stage = "preencher datas e origem"
            for selector, label, value in (
                ("#datepicker_de", "Período De", start.strftime("%d/%m/%Y")),
                ("#datepicker_ate", "Período Até", end.strftime("%d/%m/%Y")),
            ):
                fields = [field for field in query.locator(selector).all() if field.is_visible()]
                if len(fields) != 1:
                    raise ErroSeguro(f"Campo {label} não é único/visível na consulta XML ({len(fields)})")
                field = fields[0]
                field.fill(value)
                if field.input_value() != value:
                    raise ErroSeguro(f"Campo {label} não confirmou a data")
                log("UIA", f"{label}: {value}")

            origin = "Documentos Fiscais Recebidos"
            selects = query.locator("select")
            matching = []
            for index in range(selects.count()):
                select = selects.nth(index)
                if select.is_visible():
                    options = select.locator("option").all_text_contents()
                    if origin in [option.strip() for option in options]:
                        matching.append(select)
            if len(matching) != 1:
                raise ErroSeguro(f"Origem Recebidos não encontrada em um select único ({len(matching)})")
            matching[0].select_option(label=origin)
            if matching[0].locator("option:checked").inner_text().strip() != origin:
                raise ErroSeguro("Origem Recebidos não permaneceu selecionada")
            stage = "solicitar consulta"
            submit_buttons = [button for button in query.get_by_role(
                "button", name="Solicitar", exact=True).all() if button.is_visible()]
            if len(submit_buttons) != 1:
                raise ErroSeguro(f"Botão Solicitar não é único/visível ({len(submit_buttons)})")
            submit = submit_buttons[0]
            submit.click(timeout=15000)
            stage = "aguardar resultado"
            result = _wait_page(context, lambda p, text: (
                "Nenhum registro encontrado" in text or
                "Nenhuma nota fiscal encontrada" in text or
                "Relação de Notas Fiscais Recebidas Encontradas" in text),
                45, "resultado da consulta")
            result_text = _page_text(result)
            if "Nenhum registro encontrado" in result_text or "Nenhuma nota fiscal encontrada" in result_text:
                log("SEFAZ", "Consulta concluída sem documentos recebidos")
                return None
            stage = "selecionar resultados"
            checkboxes = [checkbox for checkbox in result.locator("#selectAll").all()
                          if checkbox.is_visible()]
            if len(checkboxes) != 1:
                raise ErroSeguro(f"Checkbox geral selectAll não é único/visível ({len(checkboxes)})")
            select_all = checkboxes[0]
            select_all.check(timeout=10000)
            if not select_all.is_checked():
                raise ErroSeguro("Checkbox geral não permaneceu marcado")
            buttons = [button for button in result.get_by_role(
                "button", name="Download", exact=True).all() if button.is_visible()]
            if not buttons:
                raise ErroSeguro("Botão Download não encontrado na tabela")
            stage = "baixar ZIP"
            target = downloads / f"sefaz_{uuid.uuid4().hex}.zip"
            with result.expect_download(timeout=int(config.get("aguardar_download_segundos", 180)) * 1000) as info:
                buttons[0].click(timeout=15000)
            info.value.save_as(str(target))
            validate_zip(target)
            log("SEFAZ", "ZIP baixado e validado no Edge invisível")
            return keep_zip_on_desktop(target, start, end)
        except PlaywrightTimeoutError as exc:
            raise ErroSeguro(f"Tempo esgotado no Edge invisível em '{stage}'") from exc
        finally:
            context.close()


def show_manual_progress_window() -> int:
    """Exibe o progresso da consulta iniciada pelo atalho manual."""
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Automacao Notas Sefaz")
    root.resizable(False, False)
    width, height = 500, 205
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")

    frame = ttk.Frame(root, padding=22)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Consulta de notas recebidas", font=("Segoe UI", 14, "bold")).pack(anchor="w")
    status = ttk.Label(frame, text="Iniciando a consulta...", font=("Segoe UI", 10))
    status.pack(anchor="w", pady=(14, 5))
    progress = ttk.Progressbar(frame, mode="indeterminate", length=450)
    progress.pack(fill="x", pady=(2, 5))
    elapsed_label = ttk.Label(frame, text="Você pode continuar usando o computador.", foreground="#555555")
    elapsed_label.pack(anchor="w")
    button_frame = ttk.Frame(frame)
    button_frame.pack(fill="x", pady=(14, 0))
    close_button = ttk.Button(button_frame, text="Minimizar", command=root.iconify)
    close_button.pack(side="right")

    log_path = LOG_DIR / f"rpa_{date.today().isoformat()}.log"
    offset = log_path.stat().st_size if log_path.exists() else 0
    command = ([sys.executable, "--background-download", "--background-worker"] if FROZEN else
               [sys.executable, str(Path(__file__).resolve()), "--background-download", "--background-worker"])
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    try:
        worker = subprocess.Popen(
            command, cwd=str(ROOT), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            startupinfo=startupinfo)
    except Exception as exc:
        progress.stop()
        status.configure(text=f"Não foi possível iniciar a consulta ({type(exc).__name__}).")
        close_button.configure(text="Fechar", command=root.destroy)
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.mainloop()
        return 1

    started = time.monotonic()
    finished = False
    exit_result = 0

    def friendly_status(line: str) -> str | None:
        if "[REDE]" in line:
            return "Verificando a conexão com a internet..."
        if "[CERTIFICADO]" in line:
            return "Autenticando no portal da SEFAZ..."
        if "[UIA]" in line:
            return "Preenchendo o período da consulta..."
        if "[ARQUIVO]" in line or "[SEFAZ] ZIP baixado" in line:
            return "Salvando o ZIP na pasta de hoje..."
        if "[SEFAZ] Modo invisível" in line:
            return "Preparando a consulta..."
        if "[SEFAZ] Banner Acessar" in line:
            return "Acessando o DT-e..."
        if "[SEFAZ] Consulta concluída sem documentos" in line:
            return "Consulta concluída. Nenhum XML recebido no período."
        if "[FINALIZADO]" in line:
            return "Concluído. O ZIP está na pasta de hoje."
        if "[PARADO]" in line or "[ERRO]" in line:
            return "A consulta parou. Consulte o log para ver o motivo."
        return None

    def close_window():
        if not finished:
            root.iconify()
        else:
            root.destroy()

    def poll():
        nonlocal offset, finished, exit_result
        if log_path.exists():
            try:
                with log_path.open("r", encoding="utf-8") as log_file:
                    log_file.seek(offset)
                    new_lines = log_file.readlines()
                    offset = log_file.tell()
                for line in new_lines:
                    message = friendly_status(line)
                    if message:
                        status.configure(text=message)
            except (OSError, UnicodeError):
                pass
        elapsed = int(time.monotonic() - started)
        elapsed_label.configure(text=f"Em andamento há {elapsed // 60:02d}:{elapsed % 60:02d}.")
        exit_code = worker.poll()
        if exit_code is not None and not finished:
            finished = True
            exit_result = exit_code
            progress.stop()
            progress.configure(mode="determinate", value=100)
            if exit_code == 0:
                if "Nenhum XML recebido" not in status.cget("text"):
                    status.configure(text="Concluído. O ZIP está na pasta de hoje.")
                folder = get_desktop() / "Notas sefaz" / f"nota {date.today():%d-%m-%Y}"
                if folder.is_dir():
                    open_folder = ttk.Button(button_frame, text="Abrir pasta",
                                             command=lambda: os.startfile(str(folder)))
                    open_folder.pack(side="left")
            else:
                status.configure(text="A consulta parou. Consulte o log para ver o motivo.")
            elapsed_label.configure(text=f"Tempo total: {elapsed // 60:02d}:{elapsed % 60:02d}.")
            close_button.configure(text="Fechar", command=root.destroy)
            root.protocol("WM_DELETE_WINDOW", root.destroy)
        elif not finished:
            root.after(300, poll)

    root.protocol("WM_DELETE_WINDOW", close_window)
    progress.start(12)
    root.after(250, poll)
    root.mainloop()
    return exit_result


def validate_zip(path: Path) -> None:
    if not path.is_file() or path.suffix.lower() != ".zip":
        raise ErroSeguro("Arquivo não existe ou não é .zip")
    if path.stat().st_size < 22:
        raise ErroSeguro("Arquivo ZIP vazio/incompleto")
    with zipfile.ZipFile(path) as arq:
        if not arq.namelist() or arq.testzip() is not None:
            raise ErroSeguro("Arquivo ZIP inválido/corrompido")


def browser_kind(config: dict) -> str:
    kind = str(config.get("navegador", "edge")).casefold().strip()
    if kind not in {"edge", "chrome"}:
        raise ErroSeguro("navegador deve ser 'edge' ou 'chrome' em config.json")
    return kind


def validate_profile_directory(name: str) -> str:
    """Aceita somente um nome de perfil, nunca caminhos nem argumentos extras."""
    if name and not re.fullmatch(r"(?:Default|Profile [1-9][0-9]*)", name):
        raise ErroSeguro("Diretório do perfil deve ser 'Default' ou 'Profile N'")
    return name


def browser_path(kind: str) -> Path:
    if kind == "edge":
        relative = "Microsoft/Edge/Application/msedge.exe"
    elif kind == "chrome":
        relative = "Google/Chrome/Application/chrome.exe"
    else:
        raise ErroSeguro(f"Navegador não suportado: {kind}")
    candidatos = [
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / relative,
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / relative,
        Path(os.environ.get("LOCALAPPDATA", "")) / relative,
    ]
    for candidato in candidatos:
        if candidato.is_file():
            return candidato
    nome = "Microsoft Edge" if kind == "edge" else "Google Chrome"
    raise ErroSeguro(f"{nome} não encontrado nos caminhos habituais do Windows")


def send_unicode_literal(text: str) -> None:
    """Digita literalmente no controle em foco, sem clipboard ou layout ABNT2.

    KEYEVENTF_UNICODE injeta caracteres como teclado (VK_PACKET); não cola um
    javascript: pronto, que o Chromium costuma sanitizar ao usar Ctrl+V.
    """
    if sys.platform != "win32" or not text.isascii() or len(text) > 2400:
        raise ErroSeguro("Texto de automação do DT-e inválido")

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                    ("wParamH", wintypes.WORD)]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("data", INPUT_UNION)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    # O bookmarklet de marcação é bem maior que o de abrir a categoria. Enviar
    # tudo em uma chamada pode deixar o Edge processando eventos quando o
    # Enter chegar. Lotes curtos preservam a ordem e permitem verificar falha.
    for start in range(0, len(text), 80):
        events = []
        for char in text[start:start + 80]:
            events.append(INPUT(1, INPUT_UNION(ki=KEYBDINPUT(0, ord(char), 0x0004, 0, 0))))
            events.append(INPUT(1, INPUT_UNION(ki=KEYBDINPUT(0, ord(char), 0x0006, 0, 0))))
        array = (INPUT * len(events))(*events)
        sent = user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
        if sent != len(events):
            raise ErroSeguro(f"Falha ao digitar comando do DT-e ({sent}/{len(events)} eventos no lote)")
        time.sleep(0.02)


class NavegadorNormal:
    """Controla uma janela isolada do Edge ou Chrome sem assumir abas pessoais."""

    """Opera só uma janela NOVA do navegador habitual, preservando as existentes.

    UIA não disponibiliza DOM/CSS/Playwright. Nomes de acessibilidade variam
    com o site e exigem conferência presencial. Nunca assume a primeira aba.
    """

    def __init__(self, config: dict):
        self.config = config
        self.kind = browser_kind(config)
        self.nome = "EDGE" if self.kind == "edge" else "CHROME"
        self.process_name = "msedge.exe" if self.kind == "edge" else "chrome.exe"
        self.hwnd: int | None = None
        self._original_windows: set[int] = set()
        self._owned_windows: set[int] = set()

    def browser_windows(self) -> set[int]:
        import win32gui
        import win32process
        import psutil

        janelas: set[int] = set()

        def enum_callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) == "Chrome_WidgetWin_1":
                # Edge e Chrome compartilham a mesma classe de janela.
                # Identificar pelo executavel evita manipular abas do outro.
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    if psutil.Process(pid).name().casefold() == self.process_name:
                        janelas.add(hwnd)
                except (psutil.Error, OSError):
                    pass

        win32gui.EnumWindows(enum_callback, None)
        return janelas

    def start(self) -> None:
        if sys.platform != "win32":
            raise ErroSeguro("Automação do navegador normal só funciona no Windows")
        self._original_windows = self.browser_windows()
        log(self.nome, f"Janelas originais preservadas: {len(self._original_windows)}")
        # Edge/Chrome enviam --new-window ao processo do perfil comum;
        # NÃO cria outro user-data-dir e NÃO faz cópias de cookies/senhas.
        command = [str(browser_path(self.kind)), "--new-window", "about:blank"]
        profile = str(self.config.get(f"{self.kind}_profile_directory", "")).strip()
        if profile:
            command.insert(1, f"--profile-directory={validate_profile_directory(profile)}")
        else:
            log(self.nome, f"Perfil nao fixado; se nao encontrar a sessao, confira {self.kind}://version e configure {self.kind}_profile_directory")
        subprocess.Popen(command,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        limite = time.monotonic() + 20
        while time.monotonic() < limite:
            novas = self.browser_windows() - self._original_windows
            if len(novas) == 1:
                self.hwnd = next(iter(novas))
                self._owned_windows.add(self.hwnd)
                log(self.nome, f"Janela exclusiva da rotina criada no {self.nome} normal")
                self.focus()
                return
            if len(novas) > 1:
                raise ErroSeguro("Mais de uma janela criada; não é seguro escolher uma")
            time.sleep(0.3)
        raise ErroSeguro("Não foi possível identificar com segurança a janela criada")

    def focus(self) -> None:
        import win32gui
        from pywinauto import Application

        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            raise ErroSeguro("Janela do robô não existe mais")
        app = Application(backend="uia").connect(handle=self.hwnd)
        ultima_excecao = ""
        for tentativa in range(4):
            foreground = win32gui.GetForegroundWindow()
            # UIA pode devolver um controle-filho do navegador como foco atual.
            if foreground and win32gui.GetAncestor(foreground, 2) == self.hwnd:
                return
            try:
                app.window(handle=self.hwnd).set_focus()
            except Exception as exc:
                ultima_excecao = f"{type(exc).__name__}: {exc}"
            time.sleep(0.55)
            foreground = win32gui.GetForegroundWindow()
            if foreground and win32gui.GetAncestor(foreground, 2) == self.hwnd:
                if tentativa:
                    log(self.nome, f"Foco recuperado na janela do robô (tentativa {tentativa + 1})")
                return
        atual = win32gui.GetForegroundWindow()
        titulo = win32gui.GetWindowText(atual) if atual and win32gui.IsWindow(atual) else ""
        raise ErroSeguro(
            f"Não foi possível recuperar foco com segurança. "
            f"Janela do robô={self.hwnd}; foco atual={atual} ({titulo!r}). "
            f"{ultima_excecao}"
        )

    def require_foreground(self) -> None:
        """Confere o foco sem roubar foco do campo de formulário atual."""
        import win32gui

        atual = win32gui.GetForegroundWindow()
        if not self.hwnd or not atual or win32gui.GetAncestor(atual, 2) != self.hwnd:
            raise ErroSeguro("Outro aplicativo assumiu o foco; digitação cancelada")

    def root(self):
        from pywinauto import Desktop

        if not self.hwnd:
            raise ErroSeguro("Janela não inicializada")
        return Desktop(backend="uia").window(handle=self.hwnd)

    def navigate(self, url: str) -> None:
        import pyautogui

        self.focus()
        pyautogui.hotkey("ctrl", "l")
        pyautogui.write(url, interval=0.002)
        pyautogui.press("enter")
        time.sleep(float(self.config.get("intervalo_apos_navegar_segundos", 3)))
        self.focus()
        log(self.nome, f"Navegação solicitada: {url.split('/')[2]}")

    def click_sefaz_dom(self, action: str) -> None:
        """Aciona somente um dos dois seletores homologados do menu DT-e.

        A execução é restrita à janela do robô. O próprio JavaScript confere
        domínio, caminho, unicidade, rótulo e id antes de clicar no elemento.
        Não abre DevTools nem habilita depuração remota.
        """
        script = DTE_DOM_ACTIONS.get(action)
        if script is None:
            raise ErroSeguro("Comando DOM não permitido para o DT-e")
        self._run_dte_bookmarklet(script, action)

    def click_sefaz_banner(self) -> None:
        import pyautogui
        import win32gui
        from PIL import Image, ImageGrab

        if self.hwnd not in self._owned_windows:
            raise ErroSeguro("Banner permitido somente na janela criada pelo robô")
        template_path = RESOURCE_ROOT / "acessarDTe.png"
        if not template_path.is_file():
            raise ErroSeguro("Imagem oficial do banner não encontrada no pacote")
        template = Image.open(template_path)
        user32 = ctypes.windll.user32
        origin = (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77))
        deadline = time.monotonic() + int(self.config.get("aguardar_certificado_segundos", 120))
        last_reason = "banner ainda não visível"
        while time.monotonic() < deadline:
            screenshot = ImageGrab.grab(all_screens=True)
            try:
                point = locate_sefaz_banner(screenshot, template,
                                            win32gui.GetWindowRect(self.hwnd), origin)
            except ErroSeguro as exc:
                last_reason = str(exc)
                time.sleep(1)
                continue
            self.focus()
            self.require_foreground()
            pyautogui.click(*point)
            log("SEFAZ", "Clique físico no banner oficial 'Acessar o DT-e'")
            return
        raise ErroSeguro(f"Banner do DT-e não acionado: {last_reason}")

    def _run_dte_bookmarklet(self, script: str, label: str) -> None:
        self._run_official_bookmarklet(script, label, "/menu/dte.asp")

    def _run_official_bookmarklet(self, script: str, label: str,
                                  expected_path: str) -> None:
        """Digita somente JavaScript local guardado para a página oficial."""
        import pyautogui

        if self.hwnd not in self._owned_windows:
            raise ErroSeguro("Comando DOM permitido somente na janela criada pelo robô")
        if (not script.startswith("javascript:void(function(){") or
                "online.sefaz.am.gov.br" not in script or
                f"'{expected_path}'" not in script):
            raise ErroSeguro("Script fora da lista de comandos SEFAZ permitidos")
        self.focus()
        # A arvore UIA do Edge pode disparar KeyError: None durante a troca
        # dos divs do DT-e. O JavaScript valida o host, caminho e o controle
        # exatos sem precisar consultar novamente essa arvore temporaria.
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.15)
        self.require_foreground()
        send_unicode_literal(script)
        self.require_foreground()
        time.sleep(0.35)
        pyautogui.press("enter")
        log("SEFAZ", f"Comando DOM solicitado para {label}; aguardando confirmação da tela")

    def click_xml_with_calibrated_mouse(self) -> None:
        """Clica fisicamente no centro do marcador visual do item HTML exato.

        O alvo e marcado no proprio DOM e localizado na captura local, sem
        depender de nome de aba, UIA do div, clipboard ou coordenadas fixas.
        """
        import pyautogui
        import win32gui
        from PIL import ImageGrab

        self._run_dte_bookmarklet(DTE_XML_MARKER_SCRIPT, "marcar XML idlink=42")
        deadline = time.monotonic() + 9
        last_reason = "marcador ainda nao visivel"
        last_image = None
        user32 = ctypes.windll.user32
        virtual_origin = (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77))
        while time.monotonic() < deadline:
            self.require_foreground()
            image = ImageGrab.grab(all_screens=True)
            last_image = image
            try:
                point = locate_dom_marker(image, win32gui.GetWindowRect(self.hwnd),
                                          virtual_origin)
            except ErroSeguro as exc:
                last_reason = str(exc)
                time.sleep(0.4)
                continue
            self.require_foreground()
            pyautogui.click(*point)
            log("SEFAZ", "CLIQUE FISICO no centro do titulo XML (idlink=42)")
            return
        if last_image is not None:
            diagnostic = marker_diagnostic(last_image, win32gui.GetWindowRect(self.hwnd),
                                           virtual_origin)
            if diagnostic:
                last_reason = diagnostic
        raise ErroSeguro(
            "Item XML nao marcado na tela apos 9s; nenhum clique feito. "
            f"Ultima verificacao: {last_reason}"
        )

    def click_xml_with_visual_template(self) -> None:
        """Clica no título XML visto nas duas capturas reais do menu DT-e."""
        import pyautogui
        import win32gui
        from PIL import Image, ImageGrab

        if self.hwnd not in self._owned_windows:
            raise ErroSeguro("Clique XML permitido somente na janela criada pelo robô")
        path = self.current_official_path()
        if path and path != "online.sefaz.am.gov.br/menu/dte.asp":
            raise ErroSeguro("Aba ativa não está no menu oficial do DT-e")
        template_path = RESOURCE_ROOT / "xml_item_template.png"
        if not template_path.is_file():
            raise ErroSeguro("Referência visual do item XML ausente do pacote")
        template = Image.open(template_path)
        user32 = ctypes.windll.user32
        origin = (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77))
        deadline = time.monotonic() + 8
        last_reason = "item ainda não visível"
        while time.monotonic() < deadline:
            screenshot = ImageGrab.grab(all_screens=True)
            try:
                point = locate_xml_item_image(screenshot, template,
                                              win32gui.GetWindowRect(self.hwnd), origin)
            except ErroSeguro as exc:
                last_reason = str(exc)
                time.sleep(0.5)
                continue
            self.focus()
            self.require_foreground()
            pyautogui.click(*point)
            log("SEFAZ", "Clique físico no título e descrição confirmados do item Download XML")
            return
        raise ErroSeguro(f"Item XML não clicado pela referência visual: {last_reason}")

    def try_click_xml_menu_physical(self) -> bool:
        """Clica no item XML se UI Automation o expuser como alvo único.

        O alvo precisa ser visível, ter tamanho plausível e estar inteiramente
        dentro da janela criada pelo robô.
        """
        self.focus()
        window = self.root().rectangle()
        found = []
        target = "nf-e - download de arquivos xml"
        for kind in ({"Hyperlink"}, {"Text"}, {"Button"}, {"Group"}, {"Pane"}):
            candidates = self._matches([target], kind=kind, contains=True)
            for ctrl in candidates:
                try:
                    label = " ".join((ctrl.window_text() or "").casefold().split())
                    rc = ctrl.rectangle()
                    width, height = rc.right - rc.left, rc.bottom - rc.top
                    if (label.startswith(target) and len(label) <= 125 and
                            110 <= width <= 850 and 9 <= height <= 95 and
                            window.left <= rc.left < rc.right <= window.right and
                            window.top + 65 < rc.top < rc.bottom <= window.bottom):
                        found.append((ctrl, kind))
                except Exception:
                    continue
            if len(found) == 1:
                self.focus()
                self.require_foreground()
                found[0][0].click_input()
                log("SEFAZ", f"Clique FISICO no item Download XML ({next(iter(kind))})")
                return True
            if len(found) > 1:
                # Mais de um elemento acessível satisfaz as condições.
                # Não clicar no primeiro arbitrariamente.
                break
        log("SEFAZ", f"Clique fisico indisponivel: {len(found)} alvo(s) pequenos/unicos; usando DOM restrito")
        return False

    def _matches(self, names: Iterable[str], kind: set[str] | None = None,
                 contains: bool = False):
        wanted = [" ".join(n.casefold().split()) for n in names]
        found = []
        last_error = None
        for attempt in range(3):
            try:
                controls = self.root().descendants()
                break
            except KeyError as exc:
                last_error = exc
                time.sleep(0.45)
                log("UIA", f"Arvore do Edge em transicao ({type(exc).__name__}); tentativa {attempt + 1}/3")
        else:
            raise ErroSeguro("UIA do Edge indisponivel apos 3 tentativas (KeyError)") from last_error
        for ctrl in controls:
            try:
                if not ctrl.is_visible() or (kind and ctrl.element_info.control_type not in kind):
                    continue
                nome = " ".join((ctrl.window_text() or "").casefold().split())
                if nome and any((v in nome if contains else v == nome) for v in wanted):
                    found.append(ctrl)
            except Exception:
                continue
        return found

    def find_unique(self, names: Iterable[str], label: str, *, kinds: set[str] | None = None,
                    contains: bool = False):
        found = self._matches(names, kinds, contains)
        if len(found) != 1:
            raise ErroSeguro(f"Elemento {label} não é único/visível ({len(found)} resultados)")
        return found[0]

    def click_relative(self, names: Iterable[str], label: str, dx: int, dy: int = 0,
                       kinds: set[str] | None = None) -> None:
        """Clica em elemento vinculado espacialmente ao rótulo comprovado na UI."""
        import pyautogui

        self.focus()
        anchor = self.find_unique(names, label, kinds=kinds)
        rc = anchor.rectangle()
        try:
            scale = ctypes.windll.user32.GetDpiForWindow(self.hwnd) / 96.0
        except Exception:
            scale = 1.0
        x = rc.left + round(dx * scale)
        y = (rc.top + rc.bottom) // 2 + round(dy * scale)
        wc = self.root().rectangle()
        if not (wc.left < x < wc.right and wc.top < y < wc.bottom):
            raise ErroSeguro(f"Alvo relativo de {label} fora da janela do robô")
        self.require_foreground()
        pyautogui.click(x, y)
        log("UIA", f"Controle ao lado de {label} acionado")

    def control_near_label(self, labels: Iterable[str], label: str, control_type: str):
        """Acha controle do tipo esperado imediatamente à direita do rótulo."""
        self.focus()
        anchor = self.find_unique(labels, label, kinds={"Text"}, contains=True)
        rc = anchor.rectangle()
        cy = (rc.top + rc.bottom) // 2
        possible = []
        for box in self.root().descendants(control_type=control_type):
            if not box.is_visible():
                continue
            br = box.rectangle()
            if 0 <= br.left - rc.right <= 320 and abs((br.top + br.bottom) // 2 - cy) <= 18:
                possible.append(box)
        if len(possible) != 1:
            raise ErroSeguro(f"Controle {control_type} ao lado de {label}: {len(possible)} encontrados; parada segura")
        return possible[0]

    def field_near_label(self, labels: Iterable[str], label: str, value: str) -> None:
        """Busca caixa Edit à direita do rótulo, na mesma linha."""
        self._fill_control(self.control_near_label(labels, label, "Edit"), label, value)

    def field_by_id_or_label(self, automation_id: str, labels: Iterable[str], label: str,
                             value: str) -> None:
        """Prioriza id exato do input HTML; volta ao rótulo se UIA omiti-lo."""
        fields = []
        for item in self.root().descendants(control_type="Edit"):
            try:
                if item.is_visible() and item.element_info.automation_id == automation_id:
                    fields.append(item)
            except Exception:
                continue
        if len(fields) > 1:
            raise ErroSeguro(f"Mais de um campo com id {automation_id}")
        if len(fields) == 1:
            log("UIA", f"Campo {label} localizado pelo id {automation_id}")
            self.focus()
            self._fill_control(fields[0], label, value)
        else:
            log("UIA", f"Id {automation_id} não exposto pelo Edge; usando rótulo visual")
            self.field_near_label(labels, label, value)

    def select_origin_received(self) -> None:
        """Não permite baixar Emitidos quando a rotina pede Recebidos."""
        target = "Documentos Fiscais Recebidos"
        try:
            combo = self.control_near_label(["Origem dos Documentos Fiscais:"],
                                            "Origem dos documentos", "ComboBox")
        except ErroSeguro:
            # Algumas páginas HTML antigas não associam <label> ao <select>.
            # Só permite fallback quando a opção atualmente selecionada
            # identifica UMA única ComboBox dentre todas as da consulta.
            matches = []
            for candidate in self.root().descendants(control_type="ComboBox"):
                try:
                    if candidate.is_visible() and candidate.selected_text() in {
                        "Documentos Fiscais Emitidos", target
                    }:
                        matches.append(candidate)
                except Exception:
                    continue
            if len(matches) != 1:
                raise ErroSeguro(f"Campo Origem dos documentos inacessível/ambíguo ({len(matches)})")
            combo = matches[0]
            log("UIA", "ComboBox de origem identificada pelo valor já selecionado")
        try:
            current = combo.selected_text()
        except Exception:
            current = None
        if current != target:
            self.focus()
            try:
                combo.expand()
            except Exception:
                combo.click_input()
            choices = []
            for option in self.root().descendants(control_type="ListItem"):
                try:
                    if option.is_visible() and option.window_text().strip() == target:
                        choices.append(option)
                except Exception:
                    continue
            if len(choices) != 1:
                raise ErroSeguro(f"Opção Recebidos não identificada de forma única ({len(choices)})")
            choices[0].click_input()
            self.require_foreground()
        try:
            selected = combo.selected_text()
        except Exception as exc:
            raise ErroSeguro(f"Não foi possível confirmar origem selecionada: {exc}") from exc
        if selected != target:
            raise ErroSeguro(f"Origem incorreta após seleção: {selected!r}; esperado {target!r}")
        log("SEFAZ", f"Origem dos documentos confirmada: {target}")

    def _fill_control(self, control, label: str, value: str) -> None:
        import pyautogui
        import win32clipboard
        import win32con

        control.click_input()
        self.require_foreground()
        pyautogui.hotkey("ctrl", "a")
        old_text = None
        has_text = False
        try:
            win32clipboard.OpenClipboard()
            has_text = win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT)
            if has_text:
                old_text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(value, win32con.CF_UNICODETEXT)
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
        if has_text:
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.12)
        else:
            # Não apagar conteúdo não textual (por exemplo, imagem copiada).
            pyautogui.write(value, interval=0)
        pyautogui.press("tab")
        # Restaura o texto anterior para não deixar a data no clipboard.
        if has_text:
            try:
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                if old_text is not None:
                    win32clipboard.SetClipboardText(old_text, win32con.CF_UNICODETEXT)
            finally:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass
        # Datepicker jQuery: o valor precisa ter sido aceito pelo input,
        # independentemente de o calendário visual ter aparecido.
        try:
            actual = str(control.iface_value.CurrentValue).strip()
        except Exception:
            try:
                actual = str(control.text_block()).strip()
            except Exception as exc:
                raise ErroSeguro(f"Não foi possível ler o valor do campo {label}: {exc}") from exc
        if actual != value:
            raise ErroSeguro(f"Campo {label} não confirmou a data {value} (valor visível {actual!r})")
        log("UIA", f"{label}: {value}")

    def maybe_switch_popup(self, before: set[int], timeout: int = 5) -> None:
        """Se link abrir outra janela do navegador, identifica somente a nova."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            new = self.browser_windows() - before
            if len(new) > 1:
                raise ErroSeguro("Múltiplos popups do navegador criados; seleção ambígua")
            if len(new) == 1:
                self.hwnd = next(iter(new))
                self._owned_windows.add(self.hwnd)
                log(self.nome, "Popup do portal identificado; janelas pessoais preservadas")
                return
            time.sleep(0.3)

    def visible_tabs(self):
        """Conta abas superiores e exclui os painéis internos do DevTools.
        """
        if self.hwnd not in self._owned_windows:
            raise ErroSeguro("Leitura de abas fora da janela do robô bloqueada")
        for attempt in range(3):
            try:
                window_top = self.root().rectangle().top
                return [tab for tab in self.root().descendants(control_type="TabItem")
                        if tab.is_visible() and
                        window_top - 5 <= tab.rectangle().top and
                        tab.rectangle().bottom <= window_top + 85]
            except KeyError:
                log("UIA", f"Lista de abas em transicao; tentativa {attempt + 1}/3")
                time.sleep(0.4)
        raise ErroSeguro("UIA do Edge indisponivel ao listar abas apos 3 tentativas (KeyError)")

    def maybe_switch_xml_tab(self, previous_count: int, previous_hwnd: int,
                             timeout: float = 12,
                             before_windows: set[int] | None = None) -> None:
        """Se o portal criar uma nova aba, seleciona só a aba NF-e reconhecida.

        O link 'idlink=42' costuma abrir consultarXML.do em OUTRA aba da
        MESMA janela, portanto a procura anterior apenas por novos HWNDs
        perdia a pagina. Nao toca em abas existentes do perfil da usuaria.
        """
        if self.hwnd != previous_hwnd:
            # O portal criou uma janela nova, ja identificada por HWND.
            return
        if previous_count < 1:
            raise ErroSeguro("Nenhuma aba identificada na janela do robô antes da consulta")
        log(self.nome, f"Aguardando nova aba Nota Fiscal Eletrônica na janela do robô (abas antes={previous_count})")
        deadline = time.monotonic() + timeout
        observed_count = previous_count
        while time.monotonic() < deadline:
            if before_windows is not None:
                new_windows = self.browser_windows() - before_windows
                if len(new_windows) > 1:
                    raise ErroSeguro("Múltiplas janelas novas após o clique XML; seleção ambígua")
                if len(new_windows) == 1:
                    self.hwnd = next(iter(new_windows))
                    self._owned_windows.add(self.hwnd)
                    log(self.nome, "Janela da consulta XML identificada após autenticação")
                    return
            self.focus()
            tabs = self.visible_tabs()
            observed_count = len(tabs)
            if len(tabs) > previous_count + 1:
                raise ErroSeguro("Mais de uma aba extra apareceu; seleção ambígua")
            if len(tabs) == previous_count + 1:
                matches = []
                for tab in tabs:
                    label = (tab.window_text() or "").casefold()
                    if "nota fiscal eletr" in label:
                        matches.append(tab)
                if len(matches) == 1:
                    matches[0].click_input()
                    self.require_foreground()
                    log(self.nome, "Nova aba Nota Fiscal Eletrônica identificada e selecionada na janela do robô")
                    return
                if len(matches) > 1:
                    raise ErroSeguro("Mais de uma aba Nota Fiscal Eletrônica; seleção ambígua")
            # Se navegou na mesma aba, a proxima validacao confirma a pagina.
            if self.active_url_matches_xml_consultation():
                return
            time.sleep(0.5)
        log(self.nome, f"Nova aba de consulta não identificada no prazo (abas visíveis={observed_count}); verificando página ativa")

    def active_url_matches_xml_consultation(self) -> bool:
        """Valida so host/caminho oficial; nunca expõe tokens SSO/r no log."""
        possible = []
        for ctrl in self.root().descendants(control_type="Edit"):
            try:
                if not ctrl.is_visible():
                    continue
                value = str(ctrl.iface_value.CurrentValue).strip()
                if value.startswith("https://"):
                    possible.append(value)
            except Exception:
                continue
        if len(possible) != 1:
            return False
        current = urlsplit(possible[0])
        return (current.scheme == "https" and
                current.hostname == "sistemas.sefaz.am.gov.br" and
                current.path == "/nfe-consulta-ex/consultarXML.do")

    def current_official_path(self) -> str | None:
        """Lê apenas host e caminho da aba, sem registrar parâmetros de sessão."""
        possible = []
        for ctrl in self.root().descendants(control_type="Edit"):
            try:
                if ctrl.is_visible():
                    value = str(ctrl.iface_value.CurrentValue).strip()
                    if value.startswith("https://"):
                        possible.append(value)
            except Exception:
                continue
        if len(possible) != 1:
            return None
        current = urlsplit(possible[0])
        if current.hostname not in {"online.sefaz.am.gov.br", "sistemas.sefaz.am.gov.br"}:
            return None
        return current.hostname + current.path

    def action(self, names: Iterable[str], label: str, *, kinds: set[str] | None = None,
               contains: bool = False, timeout: int = 15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.focus()
            found = self._matches(names, kinds, contains)
            if len(found) == 1:
                found[0].click_input()
                log("UIA", f"Controle acionado: {label}")
                return
            if len(found) > 1:
                raise ErroSeguro(f"Controle ambíguo ({label}): {len(found)} elementos; não clicado")
            time.sleep(0.5)
        raise ErroSeguro(f"Controle não localizado ({label}); precisa homologar a interface")

    def field(self, names: Iterable[str], label: str, value: str) -> None:
        import pyautogui

        self.focus()
        found = self._matches(names, {"Edit"})
        if len(found) != 1:
            raise ErroSeguro(f"Campo {label} não identificado unicamente ({len(found)}); não preenchido")
        self._fill_control(found[0], label, value)

    def has_text(self, words: Iterable[str]) -> bool:
        return bool(self._matches(words, contains=True))

    def close_owned_window_if_safe(self) -> None:
        """Fecha somente janela própria quando contém uma única aba.

        Se a usuária abriu mais abas nessa janela, deixa-a intacta.
        """
        if not self._owned_windows:
            return
        import win32gui
        import win32con

        for hwnd in reversed(list(self._owned_windows)):
            if not win32gui.IsWindow(hwnd):
                continue
            self.hwnd = hwnd
            try:
                abas = self.visible_tabs()
                if len(abas) != 1:
                    log(self.nome, f"Janela mantida aberta: {len(abas)} abas; fechamento inseguro")
                    continue
                self.focus()
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                log(self.nome, "Fechada só janela/aba criada pelo robô")
            except Exception as exc:
                log(self.nome, f"Janela mantida aberta por segurança: {exc}")


def wait_certificate(chrome: NavegadorNormal, timeout: int) -> None:
    """Espera uma tela identificável após o certificado, sem clicar em diálogos.

    Avisos de sessão podem ser transitórios ou coexistir com a tela utilizável.
    Só prossegue ao reconhecer a seleção de empresa ou o painel DT-e.
    """
    log("CERTIFICADO", "Aguardando autenticação. Se houver seletor de certificado, escolha manualmente.")
    end = time.monotonic() + timeout
    seen_warnings: set[str] = set()
    last_observation = "tela de seleção da empresa e painel DT-e ainda não identificados"
    while time.monotonic() < end:
        try:
            # A IE será conferida de forma única antes do clique na próxima etapa.
            company_selection = chrome.has_text(["Situação Cadastral"])
            dte_panel = (chrome.has_text(["NF-e"]) and
                         (chrome.has_text(["Pesquisar"]) or
                          chrome.has_text(["Débitos Fiscais"])))
            if company_selection or dte_panel:
                log("CERTIFICADO", "Tela autenticada confirmada por controles da SEFAZ")
                return
            if chrome.has_text(["ERR_BAD_SSL_CLIENT_AUTH_CERT", "ERR_SSL_CLIENT_AUTH_CERT_NEEDED",
                                "nenhum certificado", "certificado digital não encontrado"]):
                warning = "certificado não aceito ou ausente"
                last_observation = warning
                if warning not in seen_warnings:
                    log("CERTIFICADO", "Aviso de certificado na tela; aguardando intervenção manual ou recuperação")
                    seen_warnings.add(warning)
            if chrome.has_text(["Sessão não definida"]):
                warning = "Sessão não definida"
                last_observation = warning
                if warning not in seen_warnings:
                    log("CERTIFICADO", "Aviso de sessão na tela; aguardando os controles da próxima etapa")
                    seen_warnings.add(warning)
        except Exception as exc:
            last_observation = f"leitura da interface indisponível: {type(exc).__name__}"
        time.sleep(1)
    try:
        page = chrome.current_official_path()
    except Exception:
        page = None
    raise ErroSeguro(
        f"Autenticação não confirmada após {timeout}s ({last_observation}; "
        f"página={page or 'não identificada'}). "
        "Nenhum clique em diálogo desconhecido foi feito"
    )


def close_sefaz_advisories(chrome: NavegadorNormal, limit: int = 6) -> None:
    """Fecha APENAS o modal oficial 'AVISO AOS CONTRIBUINTES' do DT-e.

    Não usa Escape, Enter ou botões 'X' genéricos: poderiam fechar o
    certificado digital ou outro diálogo que não pertence ao aviso.
    """
    for index in range(limit):
        if not chrome.has_text(["AVISO AOS CONTRIBUINTES"]):
            return
        chrome.action(["Fechar Avisos"], "Fechar Avisos do DT-e",
                      kinds={"Button", "Hyperlink", "Text", "Image"}, timeout=6)
        log("SEFAZ", f"Aviso aos contribuintes fechado ({index + 1}/{limit})")
        time.sleep(0.8)
    if chrome.has_text(["AVISO AOS CONTRIBUINTES"]):
        raise ErroSeguro("Persistem avisos do DT-e após várias tentativas; interrompido")


def wait_for_dte_panel(chrome: NavegadorNormal, timeout: float = 25) -> None:
    """Aguarda carregamento e avisos, sem tratar demora como falha de login.

    O clique da inscrição estadual pode abrir o painel em vários segundos.
    Uma única leitura de 'Débitos Fiscais' imediatamente após o clique
    gerava falso negativo, embora o Edge já estivesse autenticado.
    """
    log("SEFAZ", f"Aguardando painel do DT-e (até {timeout:g}s) e avisos oficiais")
    deadline = time.monotonic() + timeout
    last_markers = "nenhum controle de painel identificado"
    while time.monotonic() < deadline:
        try:
            close_sefaz_advisories(chrome)
            # Seleção de CNPJ não apresenta esses controles em conjunto.
            # Exigir o menu NF-e E um dos dois controles do dashboard impede
            # que um texto solto seja confundido com conclusão da navegação.
            nfe = chrome.has_text(["NF-e"])
            pesquisar = chrome.has_text(["Pesquisar"])
            debitos = chrome.has_text(["Débitos Fiscais"])
            if nfe and (pesquisar or debitos):
                close_sefaz_advisories(chrome)
                log("SEFAZ", "Painel do DT-e confirmado (menu NF-e e pesquisa/débitos)")
                return
            last_markers = f"NF-e={nfe}, Pesquisar={pesquisar}, Débitos Fiscais={debitos}"
        except ErroSeguro:
            raise
        except Exception as exc:
            # A árvore de acessibilidade pode ser reconstruída durante a
            # navegação, gerando erros transitórios na leitura do documento.
            last_markers = f"UIA temporariamente indisponível: {type(exc).__name__}"
        time.sleep(0.75)
    raise ErroSeguro(
        f"Painel do DT-e não confirmado após {timeout:g}s ({last_markers}). "
        "Confira a tela e o log; nenhum clique no menu foi feito"
    )


def select_company_sefaz(chrome: NavegadorNormal) -> None:
    """Seleciona a MATRIZ pela inscrição estadual clicável da primeira linha.

    A IE configurada é o hyperlink azul da matriz; outros identificadores
    empresariais da tabela não são usados para escolher a linha.
    """
    close_sefaz_advisories(chrome)
    if chrome.has_text(["NF-e"]) and (chrome.has_text(["Pesquisar"]) or
                                       chrome.has_text(["Débitos Fiscais"])):
        log("SEFAZ", "Empresa já selecionada no DT-e; sem clique na tabela de CNPJs")
        wait_for_dte_panel(chrome, timeout=float(chrome.config.get("aguardar_painel_dte_segundos", 25)))
        return
    ie = str(chrome.config.get("empresa_inscricao_estadual", "")).strip()
    if not chrome.has_text(["Situação Cadastral"]):
        raise ErroSeguro("Não foi possível distinguir a seleção de CNPJ do painel do DT-e")
    if not re.fullmatch(r"\d{2}\.\d{3}\.\d{3}-\d", ie):
        raise ErroSeguro("Inscrição estadual configurada em formato inválido")
    # Preferir Hyperlink: é exatamente a IE azul que a usuária clica.
    # Cada tipo é verificado separadamente para não confundir controles
    # ancestrais (Text) com o link e gerar falsa ambiguidade.
    for kinds in ({"Hyperlink"}, {"Button"}, {"Text"}):
        encontrados = chrome._matches([ie], kind=kinds)
        if len(encontrados) > 1:
            raise ErroSeguro(f"Múltiplos controles para inscrição estadual {ie}; não clicado")
        if len(encontrados) == 1:
            chrome.focus()
            encontrados[0].click_input()
            log("SEFAZ", f"Inscrição estadual da matriz acionada: {ie}")
            break
    else:
        raise ErroSeguro(f"Inscrição estadual {ie} não encontrada como link/botão/texto no Edge")
    # O aviso pode aparecer antes, durante ou depois do carregamento.
    # Validar o painel por mais de um controle, com espera real.
    wait_for_dte_panel(chrome, timeout=float(chrome.config.get("aguardar_painel_dte_segundos", 25)))
    log("SEFAZ", "Matriz selecionada e painel do DT-e confirmado")


def open_sefaz_nfe_category(chrome: NavegadorNormal, timeout: float = 8) -> None:
    """Abre a categoria NF-e validando o seletor oficial do menu DT-e.

    A interface acessível pode expor o texto do painel sem expor seus divs.
    O seletor DOM é restrito ao host, caminho e categoria esperados.
    """
    try:
        if chrome.has_text(["NF-e - Download de Arquivos XML"]):
            log("SEFAZ", "Categoria NF-e já aberta; item Download XML visível")
            return
    except ErroSeguro as exc:
        if "UIA do Edge indisponivel" not in str(exc):
            raise
        log("SEFAZ", "UIA temporariamente inacessivel antes do menu; seletor DOM vai validar a categoria")
    chrome.click_sefaz_dom("categoria_nfe")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if chrome.has_text(["NF-e - Download de Arquivos XML"]):
                log("SEFAZ", "Categoria NF-e aberta e item Download XML confirmado")
                return
        except ErroSeguro as exc:
            if "UIA do Edge indisponivel" not in str(exc):
                raise
            log("SEFAZ", "UIA do menu indisponivel; prosseguindo para validar o item pelo DOM oficial")
            return
        time.sleep(0.5)
    # Nem todo div legado aparece como controle acessível no Edge. O próximo
    # passo exige que o item Download XML seja identificado de forma única.
    # Se o menu não abriu, a ação seguinte não encontra um alvo válido.
    log("SEFAZ", "Menu XML nao identificado por UIA; proxima acao valida o div idlink=42 no proprio HTML")


def open_sefaz_xml_download(chrome: NavegadorNormal) -> None:
    """Aciona o item oficial Download XML por um alvo físico confirmado."""
    try:
        title = chrome.has_text(["NF-e - Download de Arquivos XML"])
        description = chrome.has_text(["Consultar arquivos XML das Notas Fiscais Enviadas e Recebidas"])
        if title and description and chrome.try_click_xml_menu_physical():
            log("SEFAZ", "Item XML acionado por clique fisico; aguardando pagina de consulta")
            return
    except ErroSeguro as exc:
        if "UIA do Edge indisponivel" not in str(exc):
            raise
        log("SEFAZ", "UIA inacessivel no titulo XML; usando o seletor HTML oficial")
    # O portal legado pode não expor o div como controle acessível. Nesse
    # caso, a referência visual do item completo precisa corresponder à tela.
    chrome.click_xml_with_visual_template()
    log("SEFAZ", "Clique físico no título XML enviado; aguardando nova aba")


def wait_for_xml_consultation(chrome: NavegadorNormal, timeout: float = 35) -> None:
    """Aguarda a consulta carregar na aba nova ou na aba atual.

    O URL observado nos prints tem parametros SSO/r efemeros: so o host e
    caminho podem ser comparados. Nunca reutilizar o URL completo de um log.
    """
    deadline = time.monotonic() + timeout
    last = "pagina ainda nao identificada"
    while time.monotonic() < deadline:
        try:
            chrome.focus()
            official_page = chrome.active_url_matches_xml_consultation()
            heading = chrome.has_text(["CONSULTA DE ARQUIVOS XML"])
            period_label = chrome.has_text(["Emitidos no Período De"])
            request_button = chrome.has_text(["Solicitar"])
            # Se o navegador não expuser a URL via UIA, exige o conjunto
            # titulo+campo+botao para nao validar uma aba errada.
            if (official_page and (heading or (period_label and request_button))) or \
               (heading and period_label and request_button):
                log("SEFAZ", "Tela de consulta XML confirmada na aba ativa")
                return
            last = (f"rota_oficial={official_page}, titulo={heading}, "
                    f"campo_periodo={period_label}, solicitar={request_button}")
        except ErroSeguro:
            raise
        except Exception as exc:
            last = f"acessibilidade em carregamento: {type(exc).__name__}"
        time.sleep(0.7)
    raise ErroSeguro(
        f"Tela 'CONSULTA DE ARQUIVOS XML' não confirmada após {timeout:g}s "
        f"({last}); verificar aba e log, sem digitar datas em tela incerta"
    )


def download_sefaz(chrome: NavegadorNormal, config: dict, start: date, end: date) -> Path | None:
    """Download da SEFAZ: correspondência pelos rótulos e posições relativas.

    O navegador deve salvar automaticamente na pasta Downloads (sem perguntar
    destino). Interrompe em caso de interface inesperada, sem baixar arquivo
    ambíguo nem manipular abas pessoais.
    """
    chrome.navigate(config["sefaz_url"])
    # O banner do portal é confirmado pela imagem de referência e acionado
    # fisicamente dentro da janela criada para a rotina.
    login_url = str(config.get("sefaz_login_url", ""))
    if login_url != "https://online.sefaz.am.gov.br/dte/loginSSL.asp":
        raise ErroSeguro("URL de login fora do destino confirmado do banner SEFAZ")
    log("SEFAZ", "Acionando o banner oficial 'Acessar o DT-e' na página inicial")
    chrome.click_sefaz_banner()
    wait_certificate(chrome, int(config.get("aguardar_certificado_segundos", 45)))
    select_company_sefaz(chrome)
    # A página pode exibir um ou mais avisos oficiais, cobrindo o menu NF-e.
    time.sleep(1)
    close_sefaz_advisories(chrome)
    open_sefaz_nfe_category(chrome)
    try:
        close_sefaz_advisories(chrome)
    except ErroSeguro as exc:
        if "UIA do Edge indisponivel" not in str(exc):
            raise
        # O aviso conhecido já foi fechado antes de abrir o menu. A etapa
        # seguinte ainda exige um alvo físico visível antes de clicar.
        log("SEFAZ", "Leitura de avisos apos abrir NF-e indisponivel; clique DOM verificara visibilidade")
    previous_hwnd = chrome.hwnd
    previous_tab_count = len(chrome.visible_tabs())
    before_popup = chrome.browser_windows()
    open_sefaz_xml_download(chrome)
    chrome.maybe_switch_popup(before_popup, timeout=5)
    chrome.maybe_switch_xml_tab(previous_tab_count, previous_hwnd, timeout=120,
                                before_windows=before_popup)
    wait_for_xml_consultation(chrome,
                              timeout=float(config.get("aguardar_consulta_xml_segundos", 35)))
    # IDs reais confirmados nos prints do DevTools: datepicker_de e
    # datepicker_ate. Se o Edge não mapear HTML id para AutomationId,
    # a correspondência pela posição ao lado dos rótulos continua válida.
    chrome.field_by_id_or_label("datepicker_de", ["Emitidos no Período De:"],
                                "Período De", start.strftime("%d/%m/%Y"))
    chrome.field_by_id_or_label("datepicker_ate", ["Até:"],
                                "Período Até", end.strftime("%d/%m/%Y"))
    chrome.select_origin_received()
    before_result = chrome.browser_windows()
    chrome.action(["Solicitar"], "Consultar notas", kinds={"Button", "Hyperlink", "Text"})
    time.sleep(3)
    chrome.maybe_switch_popup(before_result, timeout=3)
    no_rows = chrome.has_text(["Nenhum registro encontrado", "Nenhuma nota fiscal encontrada"])
    no_rows = no_rows or bool(chrome._matches(["0 itens encontrados"], contains=False))
    if no_rows:
        log("SEFAZ", "Consulta sem documentos")
        return None
    if not chrome.has_text(["Relação de Notas Fiscais Recebidas Encontradas"]):
        raise ErroSeguro("Tela de resultados não confirmada; download cancelado")
    all_checkboxes = [item for item in chrome.root().descendants(control_type="CheckBox")
                      if item.is_visible()]
    # O print com DevTools confirmou <input type="checkbox" id="selectAll">.
    # Edge pode expor esse id como automation_id; se não expuser, delimita
    # a caixa pelo cabeçalho UF Emit., sem clicar em qualquer outra linha.
    with_id = []
    for cb in all_checkboxes:
        try:
            if cb.element_info.automation_id == "selectAll":
                with_id.append(cb)
        except Exception:
            continue
    if len(with_id) > 1:
        raise ErroSeguro("Mais de uma caixa selectAll identificada; download cancelado")
    if with_id:
        header = with_id[0]
        log("SEFAZ", "Checkbox geral identificado pelo id selectAll")
    else:
        # HTML <th> pode ser exposto no Edge como HeaderItem, não Text.
        uf_header = chrome.find_unique(["UF Emit."], "Cabeçalho UF Emit.",
                                       kinds={"Text", "Header", "HeaderItem", "DataItem"},
                                       contains=True)
        uf_rc = uf_header.rectangle()
        uf_y = (uf_rc.top + uf_rc.bottom) // 2
        checkboxes = [item for item in all_checkboxes
                      if item.rectangle().left < uf_rc.left and
                      abs((item.rectangle().top + item.rectangle().bottom)//2 - uf_y) <= 20]
        if len(checkboxes) != 1:
            raise ErroSeguro(f"Checkbox geral inacessível/ambíguo ({len(checkboxes)}); download cancelado")
        header = checkboxes[0]
        log("SEFAZ", "Checkbox geral identificado ao lado do cabeçalho UF Emit.")
    try:
        toggle = header.get_toggle_state()
    except Exception as exc:
        raise ErroSeguro(f"Não foi possível verificar seleção geral: {exc}") from exc
    if toggle == 0:
        chrome.focus()
        header.click_input()
        if header.get_toggle_state() != 1:
            raise ErroSeguro("Checkbox geral não permaneceu marcado")
    elif toggle != 1:
        raise ErroSeguro(f"Estado indefinido no checkbox geral: {toggle}")
    log("SEFAZ", "Seleção geral confirmada")

    downloads = get_download_folder(config)
    before_files = snapshot_zips(downloads)
    # A imagem mostra "Download" no topo e no rodapé. Escolhe só o botão
    # acima da tabela, usando a posição do selectAll (ou header fallback).
    header_top = header.rectangle().top
    buttons = [b for b in chrome._matches(["Download"], kind={"Button", "Hyperlink", "Text"})
               if b.rectangle().bottom < header_top]
    if not buttons:
        raise ErroSeguro("Botão Download não encontrado")
    topmost = min(buttons, key=lambda b: b.rectangle().top)
    chrome.focus()
    topmost.click_input()
    log("SEFAZ", "Download acionado; aguardando um novo ZIP completo")
    file = await_zip(downloads, before_files,
                     timeout=int(config.get("aguardar_download_segundos", 180)))
    return keep_zip_on_desktop(file, start, end)


def dry_run(chrome: NavegadorNormal, config: dict, file: Path | None) -> None:
    chrome.navigate(config["sefaz_url"])
    log("TESTE", f"Portal SEFAZ aberto no {chrome.nome} normal; sem selecionar certificado")
    if file is not None:
        validate_zip(file)
        log("TESTE", f"ZIP de teste válido: {file.name} ({file.stat().st_size} bytes)")
        chrome.navigate(config["sankhya_url"])
        log("TESTE", "Página inicial do Sankhya aberta; sem clicar em Enviar")


def preview_sankhya(chrome: NavegadorNormal, config: dict) -> None:
    """Inspeciona o portal sem alterar filtros, enviar arquivo ou clicar em +."""
    url = str(config.get("sankhya_portal_importacao_url", "")).strip()
    if not url:
        raise ErroSeguro("Informe sankhya_portal_importacao_url em config.json (URL da tela principal de importação)")
    if not url.startswith("https://"):
        raise ErroSeguro("O URL do Sankhya deve usar HTTPS")
    start, end = sankhya_periodo(date.today(), config)
    log("SANKHYA", f"Filtro esperado: {start:%d/%m/%Y} até {end:%d/%m/%Y}; Pendentes / Todas")
    chrome.navigate(url)
    for label in ["Portal de importação de XML", "Período de Emissão", "Apresentar importações"]:
        if not chrome.has_text([label]):
            raise ErroSeguro(f"Tela Sankhya não confirmada; rótulo ausente: {label}")
    log("SANKHYA", "Tela principal encontrada. Nenhum filtro alterado e nenhum arquivo enviado")


def run(args: argparse.Namespace) -> int:
    if sys.platform != "win32":
        raise ErroSeguro("Este pacote precisa do Windows")
    config = read_json(CONFIG_PATH, {})
    if args.background_download:
        if not args.agendado and not args.background_worker:
            return show_manual_progress_window()
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\RPA_SEFAZ_Background_Download")
        if not mutex:
            raise ErroSeguro("Não foi possível criar o bloqueio de execução simultânea")
        if ctypes.windll.kernel32.GetLastError() == 183:
            ctypes.windll.kernel32.CloseHandle(mutex)
            log("AGENDA", "Já existe uma consulta ativa; esta chamada foi ignorada")
            return 0
        try:
            today = date.today()
            state = read_json(STATE_PATH, {})
            scheduled_time = str(config.get("hora_diaria", "07:30"))
            try:
                datetime.strptime(scheduled_time, "%H:%M")
            except ValueError as exc:
                raise ErroSeguro("hora_diaria precisa estar no formato HH:MM") from exc
            if args.agendado and datetime.now().strftime("%H:%M") < scheduled_time:
                log("AGENDA", f"Login antes das {scheduled_time}; aguardando horário diário")
                return 0
            if args.agendado and state.get("data_concluida") == today.isoformat():
                log("AGENDA", "Download automático de hoje já concluído")
                return 0
            start, end = sefaz_periodo(today, state.get("data_concluida") if args.agendado else None)
            log("SEFAZ", f"Modo invisível; período: {start:%d/%m/%Y} a {end:%d/%m/%Y}")
            result = download_sefaz_background(config, start, end)
            if result is None:
                if args.agendado:
                    save_state(status="sem_notas", data_concluida=end.isoformat())
                log("FINALIZADO", "Consulta concluída sem ZIP; Sankhya não foi acessado")
                return 0
            validate_zip(result)
            values = {"ultimo_download_nome": result.name,
                      "ultimo_download_data": today.isoformat(),
                      "ultimo_download_sha256": sha256_file(result)}
            if args.agendado:
                values.update(status="download_concluido", data_concluida=end.isoformat())
            save_state(**values)
            log("FINALIZADO", f"ZIP salvo em {result.parent}; Sankhya não foi acessado")
            return 0
        finally:
            if mutex:
                ctypes.windll.kernel32.CloseHandle(mutex)

    # UIAutomation e PyAutoGUI precisam usar a mesma escala física da tela.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    if args.producao and not config.get("modo_producao_habilitado", False):
        raise ErroSeguro("Produção bloqueada em config.json. Homologue antes de habilitar.")
    if args.agendado and not args.producao:
        raise ErroSeguro("Agendamento deve usar --producao, que está protegido pela configuração")
    if args.agendado and datetime.now().strftime("%H:%M") < config.get("hora_diaria", "07:30"):
        log("AGENDA", "Login anterior ao horário diário; aguardará gatilho das 07h30")
        return 0

    state = read_json(STATE_PATH, {})
    if args.producao and state.get("data_concluida") == date.today().isoformat():
        log("AGENDA", "Rotina de hoje já concluída. Não executar novamente")
        return 0
    if args.producao and state.get("status") == "envio_sem_confirmacao":
        raise ErroSeguro("Envio anterior aguarda conferência no Sankhya; bloqueado para evitar duplicidade")

    chrome = NavegadorNormal(config)
    chrome.start()
    preserve_window_on_error = False
    try:
        if args.teste_sankhya:
            preview_sankhya(chrome, config)
            return 0
        if not args.producao and not args.baixar_apenas:
            dry_run(chrome, config, args.zip_teste)
            return 0
        ultimo = state.get("data_concluida") if args.producao else None
        start, end = sefaz_periodo(date.today(), ultimo)
        log("SEFAZ", f"Período de consulta: {start:%d/%m/%Y} a {end:%d/%m/%Y}")
        result = download_sefaz(chrome, config, start, end)
        if result is None:
            if args.producao:
                save_state(status="sem_notas", data_concluida=end.isoformat())
            return 0
        validate_zip(result)
        save_state(ultimo_download_nome=result.name, ultimo_download_data=end.isoformat(),
                   ultimo_download_sha256=sha256_file(result))
        if args.baixar_apenas:
            log("FINALIZADO", "ZIP salvo na Área de Trabalho. Sankhya NÃO foi alterado")
            return 0
        # Mesmo após homologar a SEFAZ, este bloqueio deve ser substituído por
        # fluxo Sankhya verificado, sem selecionar qualquer aba pessoal.
        raise ErroSeguro("ZIP baixado, mas importação Sankhya requer homologação da interface real")
    except Exception:
        if args.baixar_apenas:
            preserve_window_on_error = True
            log("EDGE", "Janela do teste preservada para inspeção manual após a falha")
        raise
    finally:
        if not preserve_window_on_error:
            chrome.close_owned_window_if_safe()


def main() -> int:
    parser = argparse.ArgumentParser(description="Consulta e download de XML da SEFAZ-AM")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--teste", action="store_true", help="Abre sites, não realiza envio")
    grupo.add_argument("--baixar-apenas", action="store_true", help="Baixa ZIP da SEFAZ e guarda na Área de Trabalho; não acessa Sankhya")
    grupo.add_argument("--teste-sankhya", action="store_true", help="Confere a tela de importação sem alterar filtros ou enviar")
    grupo.add_argument("--producao", action="store_true", help="Requer homologação e config.json")
    grupo.add_argument("--background-download", action="store_true",
                        help="Baixa pela SEFAZ em Edge invisível; não acessa Sankhya")
    parser.add_argument("--agendado", action="store_true", help="Execução pelo Agendador do Windows")
    parser.add_argument("--background-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--zip-teste", type=Path, help="ZIP local para validação sem importar")
    args = parser.parse_args()
    if not any((args.teste, args.baixar_apenas, args.teste_sankhya, args.producao,
                args.background_download)):
        args.background_download = True
    try:
        return run(args)
    except (ErroSeguro, OSError, ValueError, zipfile.BadZipFile) as exc:
        log("PARADO", str(exc))
        return 2
    except Exception as exc:
        log("ERRO", f"Falha inesperada: {type(exc).__name__}: {exc}")
        frames = traceback.extract_tb(exc.__traceback__)
        context = " > ".join(f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                             for frame in frames[-8:])
        log("DIAGNOSTICO", f"Pilha resumida: {context}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
