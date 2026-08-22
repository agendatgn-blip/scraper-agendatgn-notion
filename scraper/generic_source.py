# -*- coding: utf-8 -*-
"""
Mòdul genèric de seguiment per a la resta de fonts web (MNAT, CaixaForum,
Tarragona Turisme, MAMT, Diputació, Port Tarragona...).

A diferència de l'Ajuntament (que té cercador amb dates i UID únic), aquestes
webs tenen estructures molt diverses. Estratègia:
  1. Llegim la pàgina d'agenda de la font (i la principal si cal).
  2. Gemini extreu la LLISTA d'activitats visibles (regla: no inventar).
  3. Dedup contra Notion per URL exacta i per títol+data.
  4. Creem entrades a INBOX com a "Pendent revisar".

Si una pàgina retorna massa poc text (webs molt basades en JavaScript, com
CaixaForum), es marca la font com a "Revisar estructura" en comptes de forçar
una extracció poc fiable.
"""

import time
import datetime as dt

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

import notion_io
import gemini_extract

HEADERS = {
    "User-Agent": "AgendaTGN-bot/1.0 (+https://instagram.com/agendatgn; seguiment editorial responsable)",
    "Accept-Language": "ca,es;q=0.8",
}
PAUSA = 1.5
MIN_TEXT_UTIL = 400        # per sota d'això, sospitem web JS -> Revisar estructura
MAX_ACTIVITATS_PER_FONT = 25


def log(msg):
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _llegeix_pagina(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    cos = soup.find(id="content") or soup.find("main") or soup.body
    text = cos.get_text(separator="\n", strip=True) if cos else ""
    # Llista d'enllaços del contingut, perquè Gemini pugui associar URL a activitats
    enllacos = []
    if cos:
        for a in cos.find_all("a", href=True):
            t = a.get_text(strip=True)
            if t and len(t) > 3:
                enllacos.append(f"{t} -> {urljoin(url, a['href'])}")
    text_enllacos = "\n".join(enllacos[:120])
    return text[:9000], text_enllacos[:5000]


def processa_font(font, mode_test=False):
    """font: dict amb nom, url_agenda, url_principal (de 🌐 FONTS WEB)."""
    nom = font["nom"]
    url = font.get("url_agenda") or font.get("url_principal")
    avui = dt.date.today()
    log(f"--- Font: {nom} ({url})")

    if not url:
        notion_io.actualitza_font(nom, estat="Error",
                                  resultat=f"Run {avui.isoformat()}: la font no té URL.")
        return

    # 1. Llegir la pàgina
    try:
        text, enllacos = _llegeix_pagina(url)
    except requests.RequestException as e:
        log(f"  ERROR de xarxa: {e}")
        notion_io.actualitza_font(nom, estat="Error",
                                  resultat=f"Run {avui.isoformat()}: error de xarxa ({e}).")
        return

    if len(text) < MIN_TEXT_UTIL:
        log(f"  Text massa curt ({len(text)} caràcters). Probable web JavaScript.")
        notion_io.actualitza_font(
            nom, estat="Revisar estructura",
            resultat=(f"Run {avui.isoformat()}: la pàgina retorna molt poc text "
                      f"({len(text)} caràcters). Probablement carrega el contingut amb "
                      "JavaScript i cal un tractament específic."))
        return

    # 2. Extracció amb Gemini
    try:
        activitats = gemini_extract.extreu_llista(text, enllacos, url, avui)
    except Exception as e:
        log(f"  ERROR de Gemini: {e}")
        notion_io.actualitza_font(nom, estat="Error",
                                  resultat=f"Run {avui.isoformat()}: error d'extracció IA ({e}).")
        return

    log(f"  Activitats detectades per Gemini: {len(activitats)}")

    # 3. Dedup
    existents = notion_io.entrades_existents(nom, tambe_urls=True)
    creats, duplicats_tou, saltats = 0, 0, 0

    for act in activitats[:MAX_ACTIVITATS_PER_FONT]:
        import main as m  # reutilitzem parse_data_iso / normalitza_titol
        data_iso = m.parse_data_iso(act.get("data"))
        url_act = (act.get("url_font") or "").strip() or url
        clau = (m.normalitza_titol(act.get("titol")), data_iso or "")

        # URL exacta ja registrada -> saltar del tot
        if url_act != url and url_act in existents["urls"]:
            saltats += 1
            continue

        notes = f"Nova (run automàtic {avui.isoformat()})."
        if clau in existents["titol_data"]:
            notes = ("Possible duplicat — pendent de revisar (coincideix títol+data "
                     f"amb una entrada existent). Run {avui.isoformat()}.")
            duplicats_tou += 1

        if mode_test:
            log(f"  [TEST] {act.get('titol')} | {act.get('data')} | {url_act}")
            continue

        try:
            notion_io.crea_entrada_inbox(
                dades=act, url=url_act, data_iso=data_iso,
                imatge_url=None, font=nom, notes=notes,
            )
            existents["titol_data"].add(clau)
            existents["urls"].add(url_act)
            creats += 1
            log(f"  CREAT: {act.get('titol')}")
        except Exception as e:
            log(f"  ERROR creant '{act.get('titol')}': {e}")
        time.sleep(0.4)

    # 4. Log de la font
    if not mode_test:
        resum = (f"Run {avui.isoformat()}: {len(activitats)} activitats detectades, "
                 f"{creats} entrades noves, {duplicats_tou} possibles duplicats marcats, "
                 f"{saltats} ja existents (saltades).")
        notion_io.actualitza_font(nom, estat="OK", resultat=resum)
        log("  " + resum)
