# -*- coding: utf-8 -*-
"""
AgendaTGN · Scraper de l'Agenda de l'Ajuntament de Tarragona
=============================================================
Cada 2 dies (GitHub Actions):
  1. Cerca al cercador oficial (@@search-events) el rang AVUI -> AVUI+30 dies.
  2. Recull les URL dels actes (cada acte té un UID únic a la URL).
  3. Descarta els que ja existeixen a Notion (dedup per UID i per títol+data).
  4. Per cada acte nou, llegeix la fitxa de detall i extreu dades amb Gemini
     (regla estricta: NO INVENTAR -> "pendent de revisar").
  5. Crea l'entrada a 📥 INBOX AGENDA amb Estat revisió = "Pendent revisar".
  6. Actualitza el log de la font a 🌐 FONTS WEB.

Res no es publica automàticament. Tot queda pendent de revisió humana.
"""

import os
import re
import sys
import json
import time
import datetime as dt
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

import notion_io
import gemini_extract

# ----------------------------------------------------------------------------
# Configuració
# ----------------------------------------------------------------------------
BASE_URL = "https://agenda.tarragona.cat"
SEARCH_ENDPOINT = BASE_URL + "/@@search-events"
FONT_NOM = "Agenda Ajuntament Tarragona"      # ha de coincidir amb l'opció del select "Font" de l'INBOX
DIES_FINESTRA = int(os.environ.get("DIES_FINESTRA", "30"))
MAX_ACTES_PER_RUN = int(os.environ.get("MAX_ACTES_PER_RUN", "40"))
PAUSA_ENTRE_PETICIONS = 1.5   # segons — scraping responsable

HEADERS = {
    "User-Agent": "AgendaTGN-bot/1.0 (+https://instagram.com/agendatgn; seguiment editorial responsable)",
    "Accept-Language": "ca,es;q=0.8",
}

# Formats de data que provarem al cercador (el primer que retorni actes guanya)
FORMATS_DATA = ["%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"]


def log(msg):
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ----------------------------------------------------------------------------
# 1. Cerca al cercador oficial
# ----------------------------------------------------------------------------
def urls_actes_de_html(html):
    """Extreu les URL úniques d'actes (amb UID) d'una pàgina de resultats."""
    soup = BeautifulSoup(html, "html.parser")
    urls = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(BASE_URL, a["href"])
        if "/agenda/" in href and "UID=" in href:
            uid = parse_qs(urlparse(href).query).get("UID", [None])[0]
            if uid and uid not in urls:
                urls[uid] = href.split("#")[0]
    return urls  # dict {uid: url}


def cerca_actes(data_inici, data_fi):
    """Prova diversos formats de data al cercador i retorna {uid: url}."""
    session = requests.Session()
    session.headers.update(HEADERS)

    for fmt in FORMATS_DATA:
        params = {
            "start_date": data_inici.strftime(fmt),
            "end_date": data_fi.strftime(fmt),
            "category": "",
            "cicle": "",
            "ubicacio": "All",
            "searchableText": "",
        }
        try:
            r = session.get(SEARCH_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()
        except requests.RequestException as e:
            log(f"  Error de xarxa amb format {fmt}: {e}")
            continue

        urls = urls_actes_de_html(r.text)
        log(f"  Format {fmt}: {len(urls)} actes trobats")
        if urls:
            return urls, f"cercador ({fmt})"
        time.sleep(PAUSA_ENTRE_PETICIONS)

    # Pla B: portada (secció "Propers actes")
    log("  Cap format de data ha retornat actes. Pla B: portada.")
    try:
        r = session.get(BASE_URL, timeout=30)
        r.raise_for_status()
        urls = urls_actes_de_html(r.text)
        return urls, "portada (fallback — REVISAR ESTRUCTURA DEL CERCADOR)"
    except requests.RequestException as e:
        log(f"  Error llegint la portada: {e}")
        return {}, "error"


# ----------------------------------------------------------------------------
# 2. Fitxa de detall d'un acte
# ----------------------------------------------------------------------------
def text_fitxa_acte(url):
    """Descarrega la fitxa d'un acte i en retorna el text pla del contingut."""
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    content = soup.find(id="content") or soup.find("main") or soup.body
    text = content.get_text(separator="\n", strip=True) if content else ""
    # Imatge principal (si n'hi ha)
    img = None
    if content:
        tag = content.find("img", src=True)
        if tag:
            img = urljoin(BASE_URL, tag["src"])
    return text[:8000], img


# ----------------------------------------------------------------------------
# 3. Utilitats de dates i dedup
# ----------------------------------------------------------------------------
def normalitza_titol(t):
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def parse_data_iso(valor):
    """Converteix una data de Gemini (dd/mm/aaaa o ISO) a ISO. None si no es pot."""
    if not valor or "pendent" in valor.lower():
        return None
    valor = valor.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(valor[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ----------------------------------------------------------------------------
# Programa principal
# ----------------------------------------------------------------------------
def processa_ajuntament(mode_test):
    avui = dt.date.today()
    fi = avui + dt.timedelta(days=DIES_FINESTRA)
    log(f"=== Font: {FONT_NOM} · Finestra: {avui.isoformat()} -> {fi.isoformat()}")

    # --- Cerca ---
    urls, metode = cerca_actes(avui, fi)
    log(f"Mètode: {metode} · Actes candidats: {len(urls)}")

    if not urls:
        notion_io.actualitza_font(
            FONT_NOM, estat="Error",
            resultat=f"Run {avui.isoformat()}: 0 actes trobats ({metode}). Revisar la web.",
        )
        return

    # --- Dedup contra Notion ---
    existents = notion_io.entrades_existents(FONT_NOM)
    uids_existents = existents["uids"]
    claus_existents = existents["titol_data"]
    log(f"Entrades ja existents a INBOX d'aquesta font: {len(uids_existents)} UIDs")

    nous = {uid: url for uid, url in urls.items() if uid not in uids_existents}
    log(f"Actes nous (per UID): {len(nous)}")

    if mode_test:
        log("MODE TEST: no s'escriurà res a Notion. Llista d'actes nous:")
        for uid, url in list(nous.items())[:MAX_ACTES_PER_RUN]:
            log(f"  NOU -> {url}")
        return

    # --- Processament ---
    creats, duplicats_tou, errors = 0, 0, 0
    for uid, url in list(nous.items())[:MAX_ACTES_PER_RUN]:
        time.sleep(PAUSA_ENTRE_PETICIONS)
        try:
            text, imatge = text_fitxa_acte(url)
            dades = gemini_extract.extreu(text, url)

            data_iso = parse_data_iso(dades.get("data"))
            clau = (normalitza_titol(dades.get("titol")), data_iso or "")
            notes = f"Nova (run automàtic {avui.isoformat()})."
            if clau in claus_existents:
                notes = ("Possible duplicat — pendent de revisar "
                         f"(coincideix títol+data amb una entrada existent). Run {avui.isoformat()}.")
                duplicats_tou += 1

            notion_io.crea_entrada_inbox(
                dades=dades, url=url, data_iso=data_iso,
                imatge_url=imatge, font=FONT_NOM, notes=notes,
            )
            claus_existents.add(clau)
            creats += 1
            log(f"  CREAT: {dades.get('titol') or url}")
        except Exception as e:
            errors += 1
            log(f"  ERROR amb {url}: {e}")

    # --- Log de la font ---
    resum = (f"Run {avui.isoformat()}: {len(urls)} actes al cercador, "
             f"{creats} entrades noves, {duplicats_tou} possibles duplicats marcats, "
             f"{errors} errors. Mètode: {metode}.")
    estat = "OK" if errors == 0 and "fallback" not in metode else "Revisar estructura"
    notion_io.actualitza_font(FONT_NOM, estat=estat, resultat=resum)
    log(resum)


def processa_fonts_generiques(mode_test):
    """Resta de fonts actives de 🌐 FONTS WEB (MNAT, CaixaForum, Turisme...)."""
    import generic_source
    try:
        fonts = notion_io.fonts_actives()
    except Exception as e:
        log(f"ERROR llegint FONTS WEB: {e}")
        return
    for font in fonts:
        if font["nom"] == FONT_NOM:
            continue  # l'Ajuntament té el seu mòdul propi (cercador amb UID)
        try:
            generic_source.processa_font(font, mode_test=mode_test)
        except Exception as e:
            log(f"ERROR inesperat amb la font {font['nom']}: {e}")
        time.sleep(PAUSA_ENTRE_PETICIONS)


def main():
    mode_test = "--test" in sys.argv
    if mode_test:
        log("MODE TEST activat: no s'escriurà res a Notion.")

    # 1. Agenda Ajuntament (mòdul dedicat: cercador amb dates + UID únic)
    try:
        processa_ajuntament(mode_test)
    except Exception as e:
        log(f"ERROR inesperat amb {FONT_NOM}: {e}")

    # 2. Resta de fonts actives de 🌐 FONTS WEB (mòdul genèric amb Gemini)
    processa_fonts_generiques(mode_test)

    log("Run completat.")


if __name__ == "__main__":
    main()
