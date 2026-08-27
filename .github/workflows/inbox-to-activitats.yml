#!/usr/bin/env python3
"""
AgendaTGN - INBOX -> Activitats
==================================
Cada dia (via GitHub Actions cron), aquest script:

1. Consulta 📥 INBOX AGENDA i busca entrades amb "Estat revisió" = "Validada"
   que encara no tinguin cap activitat vinculada ("Activitat creada" buit).
2. Per cada una, crea una fila nova a la base "Activitats" traduint els
   camps detectats (títol, data, hora, lloc, categoria, preu, organitzador,
   descripció i imatge).
3. Enllaça la nova fila des del camp "Activitat creada" de l'entrada
   d'INBOX, i marca "Estat revisió" = "Convertida en activitat" perquè no
   es torni a processar.

La fila nova a Activitats NO queda aprovada per publicar-se — "Aprovada
publicació" es deixa sense marcar a propòsit. Cal revisar-la i aprovar-la
manualment (o des del futur dashboard) abans que el scheduler la publiqui.

Variables d'entorn necessàries (GitHub Actions Secrets):
  NOTION_TOKEN            - Integration token de Notion
  NOTION_DB_ID            - ID de la base INBOX AGENDA (ja existent al repo)
  NOTION_ACTIVITATS_DB_ID - ID de la data source "Activitats" (ja existent)

Dependències (requirements.txt):
  requests
"""

import os
import re
import sys
from datetime import datetime

import requests

# ---------------------------------------------------------------------------
# Configuració
# ---------------------------------------------------------------------------

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
INBOX_DB_ID = os.environ["NOTION_DB_ID"]
ACTIVITATS_DB_ID = os.environ["NOTION_ACTIVITATS_DB_ID"]

NOTION_VERSION = "2025-09-03"
NOTION_API = "https://api.notion.com/v1"

# Categories que no coincideixen exactament de nom entre INBOX i Activitats
# es podrien mapejar aquí. Ara mateix totes coincideixen 1:1.
CATEGORY_MAP = {}

REQUIRED_ENV = ["NOTION_TOKEN", "NOTION_DB_ID", "NOTION_ACTIVITATS_DB_ID"]


def check_env():
    missing = [v for v in REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        print(f"ERROR: falten variables d'entorn: {', '.join(missing)}")
        sys.exit(1)


def notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Notion helpers
# ---------------------------------------------------------------------------

def query_validated_inbox_entries():
    """Retorna les entrades d'INBOX amb 'Estat revisió' = 'Validada' i que
    encara no tenen cap activitat creada vinculada."""
    url = f"{NOTION_API}/data_sources/{INBOX_DB_ID}/query"
    payload = {
        "filter": {
            "and": [
                {"property": "Estat revisió", "select": {"equals": "Validada"}},
                {"property": "Activitat creada", "relation": {"is_empty": True}},
            ]
        }
    }
    results = []
    while True:
        resp = requests.post(url, headers=notion_headers(), json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("results", []))
        if data.get("has_more"):
            payload["start_cursor"] = data["next_cursor"]
        else:
            break
    return results


def get_prop_text(props, name):
    prop = props.get(name)
    if not prop:
        return None
    t = prop.get("type")
    if t == "rich_text":
        text = "".join(x.get("plain_text", "") for x in prop["rich_text"])
        return text or None
    if t == "title":
        text = "".join(x.get("plain_text", "") for x in prop["title"])
        return text or None
    if t == "select":
        return prop["select"]["name"] if prop["select"] else None
    if t == "url":
        return prop.get("url")
    if t == "date":
        return prop["date"]["start"] if prop["date"] else None
    return None


def parse_preu(preu_text):
    """Interpreta el text lliure de 'Preu detectat' (p.ex. '8€', 'Gratuït')
    i en treu un número, si es pot. Si no es pot determinar, retorna None."""
    if not preu_text:
        return None
    text = preu_text.strip().lower()
    if "gratu" in text or "gratis" in text or "free" in text:
        return 0
    match = re.search(r"(\d+[.,]?\d*)", text)
    if match:
        try:
            return float(match.group(1).replace(",", "."))
        except ValueError:
            return None
    return None


def build_activitat_properties(inbox_props):
    titol = (
        get_prop_text(inbox_props, "Títol detectat")
        or get_prop_text(inbox_props, "Nom provisional")
        or "Sense títol"
    )

    properties = {
        "Name": {"title": [{"text": {"content": titol}}]},
    }

    data_detectada = get_prop_text(inbox_props, "Data detectada")
    if data_detectada:
        properties["Data inici"] = {"date": {"start": data_detectada.split("T")[0]}}

    lloc = get_prop_text(inbox_props, "Lloc detectat")
    if lloc:
        properties["Lloc"] = {"rich_text": [{"text": {"content": lloc}}]}

    hora = get_prop_text(inbox_props, "Hora detectada")
    if hora:
        properties["Hora"] = {"rich_text": [{"text": {"content": hora}}]}

    organitzador = get_prop_text(inbox_props, "Organitzador detectat")
    if organitzador:
        properties["Organitzador"] = {"rich_text": [{"text": {"content": organitzador}}]}

    categoria = get_prop_text(inbox_props, "Categoria suggerida")
    if categoria:
        categoria = CATEGORY_MAP.get(categoria, categoria)
        properties["Categoria"] = {"select": {"name": categoria}}

    preu_text = get_prop_text(inbox_props, "Preu detectat")
    preu_num = parse_preu(preu_text)
    if preu_num is not None:
        properties["Preu"] = {"number": preu_num}

    descripcio = get_prop_text(inbox_props, "Resum web")
    if descripcio:
        properties["Descripció"] = {"rich_text": [{"text": {"content": descripcio[:2000]}}]}

    imatge_url = get_prop_text(inbox_props, "URL Drive imatge")
    if imatge_url:
        properties["Imatge"] = {
            "files": [{"name": "imatge.jpg", "external": {"url": imatge_url}}]
        }

    return properties


def create_activitat(properties):
    url = f"{NOTION_API}/pages"
    payload = {
        "parent": {"data_source_id": ACTIVITATS_DB_ID},
        "properties": properties,
    }
    resp = requests.post(url, headers=notion_headers(), json=payload, timeout=30)
    if not resp.ok:
        print("Error creant l'activitat:", resp.status_code, resp.text, file=sys.stderr)
    resp.raise_for_status()
    return resp.json()


def mark_inbox_converted(page_id, activitat_page_id):
    url = f"{NOTION_API}/pages/{page_id}"
    payload = {
        "properties": {
            "Estat revisió": {"select": {"name": "Convertida en activitat"}},
            "Activitat creada": {"relation": [{"id": activitat_page_id}]},
        }
    }
    resp = requests.patch(url, headers=notion_headers(), json=payload, timeout=30)
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Lògica principal
# ---------------------------------------------------------------------------

def main():
    check_env()
    print(f"Executant inbox_to_activitats — {datetime.now().isoformat()}")

    entries = query_validated_inbox_entries()
    print(f"Entrades validades pendents de convertir: {len(entries)}")

    for entry in entries:
        props = entry["properties"]
        titol = get_prop_text(props, "Títol detectat") or get_prop_text(props, "Nom provisional") or "(sense títol)"
        try:
            activitat_props = build_activitat_properties(props)
            nova_activitat = create_activitat(activitat_props)
            mark_inbox_converted(entry["id"], nova_activitat["id"])
            print(f"  -> Convertida: «{titol}»")
        except Exception as e:  # noqa: BLE001
            print(f"  -> ERROR convertint «{titol}»: {e}")

    print("Fet.")


if __name__ == "__main__":
    main()
