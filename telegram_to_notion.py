#!/usr/bin/env python3
"""
AgendaTGN — Bot de pantallazos
--------------------------------
Flux: Telegram (foto) -> Gemini (extreu dades) -> Google Drive (guarda imatge)
      -> Notion (crea entrada a INBOX AGENDA)

Dissenyat per executar-se periòdicament (p. ex. cada 5 minuts via GitHub Actions
cron). Cada execució:
  1. Demana a Telegram els missatges nous (getUpdates)
  2. Per cada foto rebuda: la baixa, l'envia a Gemini per extreure les dades
  3. Puja la imatge original a una carpeta de Google Drive
  4. Crea una pàgina nova a la base de dades INBOX AGENDA de Notion amb les
     dades extretes + l'enllaç de la imatge
  5. Confirma els missatges a Telegram (perquè no es tornin a processar)
  6. Respon al xat de Telegram confirmant que s'ha afegit (o l'error, si cal)

Totes les claus es llegeixen de variables d'entorn — no hi ha res sensible
escrit en aquest fitxer.
"""

import base64
import json
import os
import sys
from datetime import datetime, timezone
from io import BytesIO

import requests

# ---------------------------------------------------------------------------
# Configuració — es llegeix de variables d'entorn (mai escrita aquí)
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID = os.environ["NOTION_DB_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]  # contingut sencer del JSON
DRIVE_FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]  # ID de la carpeta "AgendaTGN - Imatges"

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
GEMINI_MODEL = "gemini-3.6-flash"

CATEGORIES = [
    "Música", "Teatre", "Exposició", "Cinema", "Patrimoni", "Literatura",
    "Familiar", "Taller", "Gastronomia", "Mercat", "Conferència", "Altres",
    "Dansa", "Art", "Festa popular",
]

EXTRACTION_PROMPT = f"""Ets un assistent que llegeix captures de pantalla d'esdeveniments
culturals (xarxes socials, cartells, webs d'agenda) i n'extreu les dades estructurades.

Retorna NOMÉS un JSON vàlid (sense text addicional, sense ```), amb aquests camps:
{{
  "titol": "nom de l'activitat",
  "data_inici": "YYYY-MM-DD o null si no es veu",
  "data_fi": "YYYY-MM-DD o null si és un sol dia",
  "hora": "HH:MM o null si no es veu",
  "lloc": "nom del lloc/espai",
  "categoria": "una EXACTAMENT d'aquesta llista: {", ".join(CATEGORIES)}",
  "resum_x": "frase curta estil tuit (màxim ~200 caràcters) que resumeixi l'activitat de forma atractiva",
  "resum_web": "resum més ampli (2-3 frases) per a una fitxa web",
  "preu": "text tal qual apareix (p.ex. 'Gratuït', '8€') o null",
  "organitzador": "entitat organitzadora si es veu, si no null",
  "text_detectat": "tot el text llegible que es veu a la imatge, transcrit tal qual"
}}

Si algun camp no es pot determinar amb la imatge, posa null. No inventis dades.
La categoria HA de ser exactament una de la llista, sense variacions ni accents diferents."""


def telegram_get_updates(offset=None):
    params = {"timeout": 0}
    if offset is not None:
        params["offset"] = offset
    r = requests.get(f"{TELEGRAM_API}/getUpdates", params=params, timeout=30)
    r.raise_for_status()
    return r.json()["result"]


def telegram_confirm(offset):
    """Truca getUpdates amb l'offset següent per marcar els missatges com llegits."""
    requests.get(f"{TELEGRAM_API}/getUpdates", params={"offset": offset, "timeout": 0}, timeout=30)


def telegram_send_message(chat_id, text):
    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=30,
    )


def telegram_download_photo(file_id):
    r = requests.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id}, timeout=30)
    r.raise_for_status()
    file_path = r.json()["result"]["file_path"]
    file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    img = requests.get(file_url, timeout=30)
    img.raise_for_status()
    return img.content, file_path.split(".")[-1]


def gemini_extract(image_bytes, mime_type="image/jpeg"):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": EXTRACTION_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(image_bytes).decode("utf-8"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json"},
    }
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return _parse_json_response(text)


def _parse_json_response(text):
    """Neteja i interpreta la resposta de Gemini encara que vingui embolicada
    amb ```json ... ```, amb text addicional al voltant, o amb contingut extra
    després del primer objecte JSON vàlid."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Busca el primer objecte JSON complet comptant claus obertes/tancades,
    # ignorant qualsevol text (o segon objecte) que vingui després.
    start = cleaned.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    print("Resposta de Gemini no vàlida com a JSON:", repr(text), file=sys.stderr)
    raise json.JSONDecodeError("No s'ha pogut interpretar la resposta de Gemini", cleaned, 0)


def get_drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds)


def drive_upload(image_bytes, filename, mime_type="image/jpeg"):
    from googleapiclient.http import MediaIoBaseUpload

    service = get_drive_service()
    file_metadata = {"name": filename, "parents": [DRIVE_FOLDER_ID]}
    media = MediaIoBaseUpload(BytesIO(image_bytes), mimetype=mime_type, resumable=False)
    uploaded = service.files().create(
        body=file_metadata, media_body=media, fields="id, webViewLink"
    ).execute()
    # Fa que l'enllaç sigui visible per a qualsevol persona amb l'enllaç (només lectura)
    service.permissions().create(
        fileId=uploaded["id"], body={"role": "reader", "type": "anyone"}
    ).execute()
    return uploaded["webViewLink"]


def notion_create_page(data, image_url, filename=None):
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    titol = data.get("titol") or "Sense títol"

    properties = {
        "Nom provisional": {"title": [{"text": {"value": titol}}]},
        "Titol detectat": {"rich_text": [{"text": {"value": titol}}]},
        "Font": {"select": {"name": "Instagram"}},
        "Model IA": {"select": {"name": "Gemini"}},
        "URL Drive imatge": {"url": image_url},
        "Captura / imatge original": {"url": image_url},
    }

    if data.get("data_inici"):
        date_obj = {"start": data["data_inici"]}
        if data.get("data_fi") and data["data_fi"] != data["data_inici"]:
            date_obj["end"] = data["data_fi"]
        properties["Data detectada"] = {"date": date_obj}

    if data.get("categoria"):
        properties["Categoria suggerida"] = {"select": {"name": data["categoria"]}}

    if data.get("lloc"):
        properties["Lloc detectat"] = {"rich_text": [{"text": {"value": data["lloc"]}}]}

    if data.get("hora"):
        properties["Hora detectada"] = {"rich_text": [{"text": {"value": data["hora"]}}]}

    if data.get("preu"):
        properties["Preu detectat"] = {"rich_text": [{"text": {"value": data["preu"]}}]}

    if data.get("organitzador"):
        properties["Organitzador detectat"] = {"rich_text": [{"text": {"value": data["organitzador"]}}]}

    if data.get("resum_x"):
        properties["Resum X"] = {"rich_text": [{"text": {"value": data["resum_x"]}}]}

    if data.get("resum_web"):
        properties["Resum web"] = {"rich_text": [{"text": {"value": data["resum_web"]}}]}
        properties["Resum suggerit"] = {"rich_text": [{"text": {"value": data["resum_web"]}}]}

    if data.get("text_detectat"):
        # Notion limita el text a 2000 caràcters per bloc de rich_text
        properties["Text detectat"] = {"rich_text": [{"text": {"value": data["text_detectat"][:2000]}}]}

    if filename:
        properties["Nom arxiu / captura"] = {"rich_text": [{"text": {"value": filename}}]}

    payload = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": properties,
    }

    r = requests.post(f"{NOTION_API}/pages", headers=headers, json=payload, timeout=30)
    if not r.ok:
        print("Error Notion:", r.status_code, r.text, file=sys.stderr)
    r.raise_for_status()
    return r.json()


def process_photo_message(message):
    chat_id = message["chat"]["id"]
    photo = message["photo"][-1]  # la resolució més alta
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    try:
        telegram_send_message(chat_id, "📥 Rebut, processant la imatge...")

        img_bytes, ext = telegram_download_photo(photo["file_id"])
        mime = "image/png" if ext.lower() == "png" else "image/jpeg"

        data = gemini_extract(img_bytes, mime_type=mime)

        filename = f"screenshot_{ts}.{ext}"
        image_url = drive_upload(img_bytes, filename, mime_type=mime)

        notion_create_page(data, image_url, filename=filename)

        resum = data.get("titol") or "activitat"
        telegram_send_message(
            chat_id,
            f"✅ Afegit a INBOX AGENDA: «{resum}»\n"
            f"📅 {data.get('data_inici') or '(sense data)'}"
            + (f" · {data.get('hora')}" if data.get("hora") else "")
            + f"\n📍 {data.get('lloc') or '(sense lloc)'}\n"
            f"🏷️ {data.get('categoria') or '(sense categoria)'}\n\n"
            f"Revisa-ho i completa el que falti a Notion.",
        )
    except Exception as e:  # noqa: BLE001
        print("Error processant missatge:", repr(e), file=sys.stderr)
        telegram_send_message(
            chat_id,
            "⚠️ Hi ha hagut un error processant la imatge.\n"
            f"Detall: {type(e).__name__}: {e}\n\n"
            "Torna-ho a provar o avisa perquè es revisi.",
        )


def main():
    updates = telegram_get_updates()
    if not updates:
        print("Sense missatges nous.")
        return

    last_update_id = updates[-1]["update_id"]

    for update in updates:
        message = update.get("message")
        if not message or "photo" not in message:
            continue
        process_photo_message(message)

    # Confirma tots els missatges processats perquè no es tornin a llegir
    telegram_confirm(last_update_id + 1)


if __name__ == "__main__":
    main()
