#!/usr/bin/env python3
"""Re-omple la imatge de les entrades del scraper que en van quedar sense.

Recorre 📥 INBOX AGENDA buscant entrades de "Web scraper" sense
"URL Drive imatge" (i que no estiguin descartades ni duplicades) i, per cadascuna:
  - Agenda Ajuntament: torna a llegir la fitxa i n'agafa la imatge gran.
  - Altres fonts: busca og:image / imatge principal de la pàgina de l'activitat.

Si en troba una:
  - l'escriu a "URL Drive imatge" i desmarca "Imatge pendent";
  - si l'entrada ja és una activitat ("Activitat creada") i aquesta no té
    "Imatge", també l'hi posa (així el PDF i les xarxes ja la fan servir).
Si no en troba: marca "Imatge pendent" (es farà servir la imatge tipus).

Només activitats vigents (data d'avui en endavant o sense data).
Variables: NOTION_TOKEN; OMPLE_TEST=si per no escriure res; OMPLE_MAX (per defecte 400).
"""

import os
import sys
import time
import datetime as dt

import requests

ARREL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ARREL, "scraper"))
os.environ.setdefault("GEMINI_API_KEY", "no-cal")   # main.py l'exigeix en importar; aquí no es fa servir

import notion_io  # noqa: E402
import imatges  # noqa: E402
import main as ajuntament  # noqa: E402

MODE_TEST = os.environ.get("OMPLE_TEST", "no").lower() in ("si", "sí", "1", "true", "yes")
MAX = int(os.environ.get("OMPLE_MAX", "400") or 400)
PAUSA = 1.5
API = notion_io.API
HEADERS = notion_io.HEADERS


def log(msg):
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _url(props, nom):
    return ((props.get(nom) or {}).get("url") or "").strip()


def _select(props, nom):
    return (((props.get(nom) or {}).get("select")) or {}).get("name") or ""


def _titol(props):
    t = (props.get("Nom provisional") or {}).get("title", [])
    return "".join(x.get("plain_text", "") for x in t)


def entrades_sense_imatge():
    avui = dt.date.today().isoformat()
    payload = {
        "filter": {"and": [
            {"property": "Tipus entrada", "select": {"equals": "Web scraper"}},
            {"property": "URL Drive imatge", "url": {"is_empty": True}},
            {"property": "URL font", "url": {"is_not_empty": True}},
            {"property": "Estat revisió", "select": {"does_not_equal": "Descartada"}},
            {"property": "Estat revisió", "select": {"does_not_equal": "Duplicada"}},
            {"or": [
                {"property": "Data detectada", "date": {"on_or_after": avui}},
                {"property": "Data detectada", "date": {"is_empty": True}},
            ]},
        ]},
        "page_size": 100,
    }
    resultats = []
    while True:
        data = notion_io._post(f"/databases/{notion_io.DB_INBOX}/query", payload)
        resultats.extend(data.get("results", []))
        if data.get("has_more") and len(resultats) < MAX:
            payload["start_cursor"] = data["next_cursor"]
        else:
            break
    return resultats[:MAX]


def urls_agenda_fonts():
    """URL de la pàgina d'agenda de cada font: si l'entrada apunta aquí, no és pàgina pròpia."""
    try:
        return {f["nom"]: {f.get("url_agenda"), f.get("url_principal")} - {None}
                for f in notion_io.fonts_actives()}
    except Exception as e:
        log(f"Avís: no s'han pogut llegir les FONTS WEB ({e})")
        return {}


def busca_imatge(font, url, agenda_urls, cache_web):
    if font == ajuntament.FONT_NOM:
        try:
            fitxa = ajuntament.llegeix_fitxa(url)
            if fitxa.get("imatge") and imatges.es_imatge_valida(fitxa["imatge"]):
                return fitxa["imatge"]
        except Exception as e:
            log(f"  Avís fitxa {url}: {e}")
        return imatges.imatge_de_pagina(url)

    if url in agenda_urls.get(font, set()):
        return None   # l'entrada no té pàgina pròpia
    img = imatges.imatge_de_pagina(url)
    # Si coincideix amb la imatge "per defecte" de la web, no serveix
    for u_ag in agenda_urls.get(font, set()):
        if u_ag not in cache_web:
            cache_web[u_ag] = imatges.imatge_de_pagina(u_ag)
        if img and img == cache_web[u_ag]:
            return None
    return img


def activitat_sense_imatge(page_id):
    r = requests.get(f"{API}/pages/{page_id}", headers=HEADERS, timeout=30)
    if not r.ok:
        return False
    prop = r.json().get("properties", {}).get("Imatge")
    return prop is not None and not prop.get("files")


def main():
    entrades = entrades_sense_imatge()
    log(f"Entrades del scraper sense imatge (vigents): {len(entrades)}"
        + ("  [MODE TEST: no s'escriu res]" if MODE_TEST else ""))
    agenda_urls = urls_agenda_fonts()
    cache_web = {}
    trobades = no_trobades = activitats = errors = 0

    for i, p in enumerate(entrades, 1):
        props = p["properties"]
        url, font, titol = _url(props, "URL font"), _select(props, "Font"), _titol(props)
        try:
            img = busca_imatge(font, url, agenda_urls, cache_web)
        except Exception as e:
            errors += 1
            log(f"[{i}] ERROR {titol}: {e}")
            continue

        if img:
            trobades += 1
            log(f"[{i}] OK  {titol[:60]} -> {img}")
        else:
            no_trobades += 1
            log(f"[{i}] --  {titol[:60]} (sense imatge: es farà servir la tipus)")

        if not MODE_TEST:
            try:
                canvis = {"Imatge pendent": {"checkbox": not img}}
                if img:
                    canvis["URL Drive imatge"] = {"url": img}
                notion_io._patch(f"/pages/{p['id']}", {"properties": canvis})

                rel = (props.get("Activitat creada") or {}).get("relation", [])
                if img and rel and activitat_sense_imatge(rel[0]["id"]):
                    notion_io._patch(f"/pages/{rel[0]['id']}", {"properties": {
                        "Imatge": {"files": [{"name": "imatge.jpg", "external": {"url": img}}]}}})
                    activitats += 1
            except Exception as e:
                errors += 1
                log(f"  ERROR escrivint a Notion: {e}")
        time.sleep(PAUSA)

    resum = (f"Revisades {len(entrades)}: {trobades} amb imatge trobada, {no_trobades} sense "
             f"(quedaran amb la imatge tipus), {activitats} activitats actualitzades, {errors} errors.")
    log(resum)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(f"### Re-omplir imatges\n\n{resum}\n")


if __name__ == "__main__":
    main()
