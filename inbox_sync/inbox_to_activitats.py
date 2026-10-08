#!/usr/bin/env python3
"""
AgendaTGN - INBOX -> Activitats
==================================
Cada dia (via GitHub Actions cron), aquest script:

1. Consulta 📥 INBOX AGENDA i busca entrades amb "Estat revisió" = "Validada"
   que encara no tinguin cap activitat vinculada ("Activitat creada" buit).
2. Per cada una, crea una fila nova a la base "Activitats" traduint els
   camps detectats (títol, dates, hora, lloc, categoria, preu, organitzador,
   descripció i imatge) i l'enllaça amb el seu 🎪 Programa (festival, cicle,
   festa de barri...) a partir de "Programa detectat". Si el programa no
   existeix, el crea sense agrupar i marcat "Creat automàticament".
3. Enllaça la nova fila des del camp "Activitat creada" de l'entrada
   d'INBOX, i marca "Estat revisió" = "Convertida en activitat" perquè no
   es torni a processar.

La fila nova a Activitats NO queda aprovada per publicar-se — "Aprovada
publicació" es deixa sense marcar a propòsit. Cal revisar-la i aprovar-la
manualment (o des del futur dashboard) abans que el scheduler la publiqui.

Variables d'entorn necessàries (GitHub Actions Secrets):
  NOTION_TOKEN                 - Integration token de Notion
  NOTION_INBOX_DATASOURCE_ID   - ID de la data source d'INBOX AGENDA (nou)
  NOTION_ACTIVITATS_DB_ID      - ID de la data source "Activitats" (ja existent)

Dependències (requirements.txt):
  requests
"""

import os
import re
import sys
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import entrades_llocs  # noqa: E402  (enllaços d'entrades per lloc, a l'arrel del repo)

# ---------------------------------------------------------------------------
# Configuració
# ---------------------------------------------------------------------------

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
INBOX_DB_ID = os.environ["NOTION_INBOX_DATASOURCE_ID"]
ACTIVITATS_DB_ID = os.environ["NOTION_ACTIVITATS_DB_ID"]

# 🎪 Programes (festivals, cicles, festes de barri...). Es pot sobreescriure per secret.
PROGRAMES_DS_ID = os.environ.get("NOTION_PROGRAMES_DS_ID") or "7adf4d3a-6ed6-483b-ade4-be5286ebc087"

NOTION_VERSION = "2025-09-03"
NOTION_API = "https://api.notion.com/v1"

# Categories que no coincideixen exactament de nom entre INBOX i Activitats
# es podrien mapejar aquí. Ara mateix totes coincideixen 1:1.
CATEGORY_MAP = {}

REQUIRED_ENV = ["NOTION_TOKEN", "NOTION_INBOX_DATASOURCE_ID", "NOTION_ACTIVITATS_DB_ID"]


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


def get_date_end(props, name):
    prop = props.get(name) or {}
    d = prop.get("date") or {}
    return d.get("end")


# ---------------------------------------------------------------------------
# 🎪 Programes
# ---------------------------------------------------------------------------

def _norm(t):
    t = (t or "").lower()
    for a, b in (("à", "a"), ("á", "a"), ("è", "e"), ("é", "e"), ("í", "i"), ("ï", "i"),
                 ("ò", "o"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ç", "c"), ("·", "")):
        t = t.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "", t)


def load_programes():
    """{nom_normalitzat: page_id} amb el Nom i tots els Àlies de cada programa."""
    url = f"{NOTION_API}/data_sources/{PROGRAMES_DS_ID}/query"
    payload, index = {"page_size": 100}, {}
    while True:
        resp = requests.post(url, headers=notion_headers(), json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for page in data.get("results", []):
            props = page["properties"]
            noms = [get_prop_text(props, "Nom") or ""]
            noms += (get_prop_text(props, "Àlies") or "").split(",")
            for nom in noms:
                if _norm(nom):
                    index[_norm(nom)] = page["id"]
        if data.get("has_more"):
            payload["start_cursor"] = data["next_cursor"]
        else:
            break
    return index


def create_programa(nom):
    payload = {
        "parent": {"data_source_id": PROGRAMES_DS_ID},
        "properties": {
            "Nom": {"title": [{"text": {"content": nom[:200]}}]},
            "Creat automàticament": {"checkbox": True},
            "Agrupar en publicacions": {"checkbox": False},
        },
    }
    resp = requests.post(f"{NOTION_API}/pages", headers=notion_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]


def programes_de(text, index):
    """'Tarragona Sona Flamenc, Arts escèniques TGN Cultura' -> [page_id, ...].
    Els programes que no existeixen es creen (sense agrupar) perquè els revisis."""
    ids = []
    for nom in (text or "").split(","):
        nom = nom.strip()
        if not _norm(nom):
            continue
        pid = index.get(_norm(nom))
        if not pid:
            pid = create_programa(nom)
            index[_norm(nom)] = pid
            print(f"     · Programa nou creat per revisar: «{nom}»")
        if pid not in ids:
            ids.append(pid)
    return ids


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


def build_activitat_properties(inbox_props, programes_index=None, llocs_entrades=None):
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
        data_fi = get_date_end(inbox_props, "Data detectada")
        if data_fi and data_fi.split("T")[0] > data_detectada.split("T")[0]:
            properties["Data final"] = {"date": {"start": data_fi.split("T")[0]}}
            properties["Tipus durada"] = {"select": {"name": "Diversos dies"}}

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
    sense_preu = not preu_text or "pendent" in preu_text.lower()
    if preu_num is None and sense_preu:
        preu_num = 0   # criteri AgendaTGN: si no consta preu, és gratuït (es pot corregir a mà)
    if preu_num is not None:
        properties["Preu"] = {"number": preu_num}
    if preu_text and "pendent" not in preu_text.lower():
        properties["Preu (text)"] = {"rich_text": [{"text": {"content": preu_text[:200]}}]}

    programa = get_prop_text(inbox_props, "Programa detectat")
    if programa and programes_index is not None:
        ids = programes_de(programa, programes_index)
        if ids:
            properties["Programa"] = {"relation": [{"id": i} for i in ids]}

    descripcio = get_prop_text(inbox_props, "Resum web")
    if descripcio:
        properties["Descripció"] = {"rich_text": [{"text": {"content": descripcio[:2000]}}]}

    # Enllaç d'entrades: el propi; si és de pagament i no en té, el del lloc
    # (📍 LLOCS → URL entrades) o, si ve de l'agenda de l'Ajuntament, el general de l'Ajuntament.
    entrades_url = entrades_llocs.resol(
        url_propi=get_prop_text(inbox_props, "URL entrades") or "",
        preu_text=preu_text or "", preu_num=preu_num,
        lloc_text=get_prop_text(inbox_props, "Lloc detectat") or "",
        de_ajuntament=get_prop_text(inbox_props, "Font") == "Agenda Ajuntament Tarragona",
        llocs=llocs_entrades)
    if entrades_url:
        properties["URL reserva"] = {"url": entrades_url}

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

    try:
        programes_index = load_programes()
        print(f"Programes coneguts (noms + àlies): {len(programes_index)}")
    except Exception as e:  # noqa: BLE001
        programes_index = None
        print(f"AVÍS: no s'han pogut llegir els 🎪 Programes ({e}). Es continua sense enllaçar-los.")

    llocs_entrades = entrades_llocs.carrega(NOTION_TOKEN)
    print(f"Llocs amb enllaç d'entrades: {len(llocs_entrades)}")

    for entry in entries:
        props = entry["properties"]
        titol = get_prop_text(props, "Títol detectat") or get_prop_text(props, "Nom provisional") or "(sense títol)"
        try:
            activitat_props = build_activitat_properties(props, programes_index, llocs_entrades)
            nova_activitat = create_activitat(activitat_props)
            mark_inbox_converted(entry["id"], nova_activitat["id"])
            print(f"  -> Convertida: «{titol}»")
        except Exception as e:  # noqa: BLE001
            print(f"  -> ERROR convertint «{titol}»: {e}")

    print("Fet.")


if __name__ == "__main__":
    main()
