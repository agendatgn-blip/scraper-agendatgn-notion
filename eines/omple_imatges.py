#!/usr/bin/env python3
"""Re-omple la imatge i l'enllaç d'entrades de les entrades del scraper que no en tenen.

Recorre 📥 INBOX AGENDA buscant entrades de "Web scraper" vigents (no descartades
ni duplicades) sense "URL Drive imatge" o sense "URL entrades" i, per cadascuna:
  - Agenda Ajuntament: torna a llegir la fitxa (imatge gran + bloc "Venda d'entrades").
  - Altres fonts: llegeix la pàgina de l'activitat (og:image / imatge principal +
    enllaç a una plataforma de venda o amb text "Entrades", "Inscripcions"...).

Només omple camps BUITS (mai sobreescriu el que ja hi ha o el que has corregit a mà):
  - INBOX: "URL Drive imatge", "URL entrades" i la casella "Imatge pendent".
  - Si ja és activitat ("Activitat creada"): "Imatge" i "URL reserva" si estan buits.

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


def entrades_a_completar():
    avui = dt.date.today().isoformat()
    payload = {
        "filter": {"and": [
            {"property": "Tipus entrada", "select": {"equals": "Web scraper"}},
            {"property": "URL font", "url": {"is_not_empty": True}},
            {"property": "Estat revisió", "select": {"does_not_equal": "Descartada"}},
            {"property": "Estat revisió", "select": {"does_not_equal": "Duplicada"}},
            {"or": [
                {"property": "URL Drive imatge", "url": {"is_empty": True}},
                {"property": "URL entrades", "url": {"is_empty": True}},
            ]},
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


def busca(font, url, agenda_urls, cache_web):
    """Torna (imatge, enllaç d'entrades) de la pàgina de l'activitat."""
    if font == ajuntament.FONT_NOM:
        try:
            fitxa = ajuntament.llegeix_fitxa(url)
            img = fitxa.get("imatge")
            if img and not imatges.es_imatge_valida(img):
                img = None
            return img, ajuntament.enllac_entrades_fitxa(fitxa)
        except Exception as e:
            log(f"  Avís fitxa {url}: {e}")
            return imatges.analitza_pagina(url)

    if url in agenda_urls.get(font, set()):
        return None, None   # l'entrada no té pàgina pròpia
    img, entrades = imatges.analitza_pagina(url)
    # Si la imatge coincideix amb la "per defecte" de la web, no serveix
    for u_ag in agenda_urls.get(font, set()):
        if u_ag not in cache_web:
            cache_web[u_ag] = imatges.imatge_de_pagina(u_ag)
        if img and img == cache_web[u_ag]:
            img = None
    return img, entrades


def props_activitat(page_id):
    r = requests.get(f"{API}/pages/{page_id}", headers=HEADERS, timeout=30)
    return r.json().get("properties", {}) if r.ok else {}


def main():
    entrades = entrades_a_completar()
    log(f"Entrades del scraper vigents sense imatge o sense enllaç d'entrades: {len(entrades)}"
        + ("  [MODE TEST: no s'escriu res]" if MODE_TEST else ""))
    agenda_urls = urls_agenda_fonts()
    cache_web = {}
    n_img = n_ent = n_act = errors = 0

    for i, p in enumerate(entrades, 1):
        props = p["properties"]
        url, font, titol = _url(props, "URL font"), _select(props, "Font"), _titol(props)
        te_img, te_ent = bool(_url(props, "URL Drive imatge")), bool(_url(props, "URL entrades"))
        try:
            img, ent = busca(font, url, agenda_urls, cache_web)
        except Exception as e:
            errors += 1
            log(f"[{i}] ERROR {titol}: {e}")
            continue

        nova_img = img if (img and not te_img) else None
        nova_ent = ent if (ent and not te_ent) else None
        n_img += bool(nova_img)
        n_ent += bool(nova_ent)
        log(f"[{i}] {titol[:55]} | imatge: {'nova' if nova_img else ('ja en tenia' if te_img else '—')}"
            f" | entrades: {nova_ent or ('ja en tenia' if te_ent else '—')}")

        if not MODE_TEST:
            try:
                canvis = {"Imatge pendent": {"checkbox": not (te_img or nova_img)}}
                if nova_img:
                    canvis["URL Drive imatge"] = {"url": nova_img}
                if nova_ent:
                    canvis["URL entrades"] = {"url": nova_ent}
                notion_io._patch(f"/pages/{p['id']}", {"properties": canvis})

                rel = (props.get("Activitat creada") or {}).get("relation", [])
                if rel and (img or ent):
                    pa = props_activitat(rel[0]["id"])
                    canvis_act = {}
                    if img and "Imatge" in pa and not pa["Imatge"].get("files"):
                        canvis_act["Imatge"] = {"files": [{"name": "imatge.jpg", "external": {"url": img}}]}
                    if ent and "URL reserva" in pa and not pa["URL reserva"].get("url"):
                        canvis_act["URL reserva"] = {"url": ent}
                    if canvis_act:
                        notion_io._patch(f"/pages/{rel[0]['id']}", {"properties": canvis_act})
                        n_act += 1
            except Exception as e:
                errors += 1
                log(f"  ERROR escrivint a Notion: {e}")
        time.sleep(PAUSA)

    resum = (f"Revisades {len(entrades)}: {n_img} imatges noves, {n_ent} enllaços d'entrades nous, "
             f"{n_act} activitats completades, {errors} errors. "
             "Les que continuen sense imatge faran servir la imatge tipus.")
    log(resum)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(f"### Re-omplir imatges i entrades\n\n{resum}\n")


if __name__ == "__main__":
    main()
