# -*- coding: utf-8 -*-
"""Lectura i escriptura segura a Notion (API oficial, versió 2022-06-28)."""

import os
import re
import datetime as dt
from urllib.parse import urlparse, parse_qs

import requests

NOTION_TOKEN = os.environ["NOTION_TOKEN"]

# IDs reals del workspace d'AgendaTGN (ja verificats)
DB_INBOX = "508d39ecd1e84c8ea4ef97c6c9bc0580"      # 📥 INBOX AGENDA
DB_FONTS = "20a03b8603cd4700a90f6e644d9f1350"      # 🌐 FONTS WEB · Seguiment

API = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def _post(path, payload):
    r = requests.post(f"{API}{path}", headers=HEADERS, json=payload, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Notion {r.status_code}: {r.text[:400]}")
    return r.json()


def _patch(path, payload):
    r = requests.patch(f"{API}{path}", headers=HEADERS, json=payload, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Notion {r.status_code}: {r.text[:400]}")
    return r.json()


def _rt(text, limit=1900):
    """Rich text truncat (Notion limita a 2000 caràcters per bloc)."""
    return [{"text": {"content": (text or "")[:limit]}}]


def _normalitza(t):
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


# ----------------------------------------------------------------------------
# Dedup: entrades existents de la font
# ----------------------------------------------------------------------------
def fonts_actives():
    """Llegeix 🌐 FONTS WEB i retorna les fonts amb Activa = true."""
    fonts = []
    payload = {
        "filter": {"property": "Activa", "checkbox": {"equals": True}},
        "page_size": 100,
    }
    data = _post(f"/databases/{DB_FONTS}/query", payload)
    for page in data.get("results", []):
        props = page.get("properties", {})
        titol_rt = (props.get("Nom font", {}) or {}).get("title", [])
        fonts.append({
            "page_id": page["id"],
            "nom": titol_rt[0]["plain_text"] if titol_rt else "",
            "url_principal": (props.get("URL principal", {}) or {}).get("url"),
            "url_agenda": (props.get("URL agenda", {}) or {}).get("url"),
        })
    return fonts


def entrades_existents(font_nom, tambe_urls=False):
    """Retorna els UIDs (de 'URL font'), les claus (títol normalitzat, data)
    i opcionalment les URLs completes de les entrades d'aquesta font a l'INBOX."""
    uids, claus, urls_set = set(), set(), set()
    payload = {
        "filter": {"property": "Font", "select": {"equals": font_nom}},
        "page_size": 100,
    }
    while True:
        data = _post(f"/databases/{DB_INBOX}/query", payload)
        for page in data.get("results", []):
            props = page.get("properties", {})
            # UID de la URL font
            url = (props.get("URL font", {}) or {}).get("url")
            if url:
                urls_set.add(url)
                uid = parse_qs(urlparse(url).query).get("UID", [None])[0]
                if uid:
                    uids.add(uid)
            # Clau títol + data
            titol_rt = (props.get("Títol detectat", {}) or {}).get("rich_text", [])
            titol = titol_rt[0]["plain_text"] if titol_rt else ""
            date_obj = (props.get("Data detectada", {}) or {}).get("date") or {}
            data_start = (date_obj.get("start") or "")[:10]
            claus.add((_normalitza(titol), data_start))
        if data.get("has_more"):
            payload["start_cursor"] = data["next_cursor"]
        else:
            break
    resultat = {"uids": uids, "titol_data": claus}
    if tambe_urls:
        resultat["urls"] = urls_set
    return resultat


# ----------------------------------------------------------------------------
# Creació d'entrades a INBOX AGENDA
# ----------------------------------------------------------------------------
def crea_entrada_inbox(dades, url, data_iso, imatge_url, font, notes):
    titol = dades.get("titol") or "pendent de revisar"
    hora = dades.get("hora") or "pendent de revisar"

    props = {
        "Nom provisional": {"title": [{"text": {"content": titol[:200]}}]},
        "Títol detectat": {"rich_text": _rt(titol)},
        "Hora detectada": {"rich_text": _rt(hora)},
        "Lloc detectat": {"rich_text": _rt(dades.get("lloc") or "pendent de revisar")},
        "Organitzador detectat": {"rich_text": _rt(dades.get("organitzador") or "pendent de revisar")},
        "Preu detectat": {"rich_text": _rt(dades.get("preu") or "pendent de revisar")},
        "Data text": {"rich_text": _rt(dades.get("data") or "pendent de revisar")},
        "Text detectat": {"rich_text": _rt(dades.get("text_visible") or "")},
        "Resum suggerit": {"rich_text": _rt(dades.get("resum_agendatgn") or "")},
        "Dubtes": {"rich_text": _rt(dades.get("dubtes") or "")},
        "Notes revisió": {"rich_text": _rt(notes)},
        "Font": {"select": {"name": font}},
        "Canal origen": {"select": {"name": "Web"}},
        "Tipus entrada": {"select": {"name": "Web scraper"}},
        "Model IA": {"select": {"name": "Gemini 2.5 Flash"}},
        "Estat revisió": {"select": {"name": "Pendent revisar"}},
        "Estat automatització": {"select": {"name": "OK"}},
        "Confiança IA": {"select": {"name": dades.get("confianca_ia") or "Baixa"}},
        "Crear activitat": {"checkbox": False},
        "URL font": {"url": url},
    }

    # Data amb rang si hi ha data_fi
    if data_iso:
        date_val = {"start": data_iso}
        fi = dades.get("data_fi_iso")
        if fi and fi > data_iso:
            date_val["end"] = fi
        # Si tenim hora clara (HH:MM), fem datetime
        m = re.match(r"^(\d{1,2}):(\d{2})", hora)
        if m and "end" not in date_val:
            date_val["start"] = f"{data_iso}T{int(m.group(1)):02d}:{m.group(2)}:00"
        props["Data detectada"] = {"date": date_val}

    # Categoria: només si coincideix amb una opció vàlida del select
    categories_valides = {
        "Música", "Teatre", "Exposició", "Cinema", "Patrimoni", "Literatura",
        "Familiar", "Taller", "Gastronomia", "Mercat", "Conferència", "Altres",
        "Dansa", "Art", "Festa popular",
    }
    cat = dades.get("categoria") or ""
    if cat in categories_valides:
        props["Categoria suggerida"] = {"select": {"name": cat}}

    if imatge_url:
        props["URL Drive imatge"] = {"url": imatge_url}

    _post("/pages", {"parent": {"database_id": DB_INBOX}, "properties": props})


# ----------------------------------------------------------------------------
# Log a FONTS WEB
# ----------------------------------------------------------------------------
def actualitza_font(font_nom, estat, resultat):
    data = _post(f"/databases/{DB_FONTS}/query", {
        "filter": {"property": "Nom font", "title": {"equals": font_nom}},
        "page_size": 1,
    })
    results = data.get("results", [])
    if not results:
        print(f"AVÍS: no s'ha trobat la font '{font_nom}' a FONTS WEB.")
        return
    page_id = results[0]["id"]
    _patch(f"/pages/{page_id}", {"properties": {
        "Última revisió": {"date": {"start": dt.datetime.now().isoformat(timespec="seconds")}},
        "Últim resultat": {"rich_text": _rt(resultat)},
        "Estat font": {"select": {"name": estat}},
    }})
