#!/usr/bin/env python3
"""
AgendaTGN — Bot de pantallazos
--------------------------------
Flux: Telegram (foto) -> IA (Mistral → Gemini → Groq, mòdul ia/) -> Google Drive (guarda imatge)
      -> Notion (crea entrada a INBOX AGENDA)

Dissenyat per executar-se periòdicament (p. ex. cada 5 minuts via GitHub Actions
cron). Cada execució:
  1. Demana a Telegram els missatges nous (getUpdates)
  2. Per cada foto rebuda: la baixa i l'envia a la cadena d'IA (ia/) per extreure
     i validar les dades
  3. Puja la imatge original a una carpeta de Google Drive
  4. Crea una pàgina nova a la base de dades INBOX AGENDA de Notion amb les
     dades extretes + l'enllaç de la imatge
  5. Confirma els missatges a Telegram (perquè no es tornin a processar)
  6. Respon al xat de Telegram confirmant que s'ha afegit (o l'error, si cal)

Totes les claus es llegeixen de variables d'entorn — no hi ha res sensible
escrit en aquest fitxer.
"""

import hashlib
import os
import sys
import time
from datetime import datetime, timezone
from io import BytesIO

import requests
from PIL import Image

from ia import TotsElsProveidorsHanFallat, extreu_cartell
from ia.validador import notes_revisio

# ---------------------------------------------------------------------------
# Configuració — es llegeix de variables d'entorn (mai escrita aquí)
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID = os.environ["NOTION_DB_ID"]
GOOGLE_OAUTH_CLIENT_ID = os.environ["GOOGLE_OAUTH_CLIENT_ID"]
GOOGLE_OAUTH_CLIENT_SECRET = os.environ["GOOGLE_OAUTH_CLIENT_SECRET"]
GOOGLE_OAUTH_REFRESH_TOKEN = os.environ["GOOGLE_OAUTH_REFRESH_TOKEN"]
DRIVE_FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]  # ID de la carpeta "AgendaTGN - Imatges"

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Si cap proveïdor d'IA respon durant aquestes hores, es crea igualment la fila
# a INBOX (amb la imatge i sense dades) perquè el cartell no es perdi.
HORES_MAX_REINTENT = int(os.environ.get("HORES_MAX_REINTENT", "3"))


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


def crop_to_poster(image_bytes, bbox, mime_type="image/jpeg"):
    """Retalla la imatge al requadre del cartell indicat per la IA.

    bbox ve amb coordenades normalitzades 0-1000. Si el requadre no és vàlid
    (falta, és massa petit, o cobreix pràcticament tota la imatge), es
    retorna la imatge original sense tocar — mai fallem la pujada per un
    retall dubtós.
    """
    if not bbox:
        return image_bytes

    try:
        x_min = int(bbox.get("x_min", 0))
        y_min = int(bbox.get("y_min", 0))
        x_max = int(bbox.get("x_max", 1000))
        y_max = int(bbox.get("y_max", 1000))
    except (TypeError, ValueError):
        return image_bytes

    # Si el requadre és pràcticament tota la imatge, no cal retallar.
    if x_min <= 5 and y_min <= 5 and x_max >= 995 and y_max >= 995:
        return image_bytes

    # Validació bàsica: requadre coherent i amb una mida mínima raonable.
    if not (0 <= x_min < x_max <= 1000 and 0 <= y_min < y_max <= 1000):
        return image_bytes
    if (x_max - x_min) < 100 or (y_max - y_min) < 100:
        return image_bytes

    try:
        img = Image.open(BytesIO(image_bytes))
        w, h = img.size
        left = round(x_min / 1000 * w)
        top = round(y_min / 1000 * h)
        right = round(x_max / 1000 * w)
        bottom = round(y_max / 1000 * h)
        cropped = img.crop((left, top, right, bottom))

        out = BytesIO()
        fmt = "PNG" if mime_type == "image/png" else "JPEG"
        if fmt == "JPEG" and cropped.mode in ("RGBA", "P"):
            cropped = cropped.convert("RGB")
        cropped.save(out, format=fmt, quality=92 if fmt == "JPEG" else None)
        return out.getvalue()
    except Exception as e:  # noqa: BLE001
        print("Avís: no s'ha pogut retallar la imatge, es puja sencera:", repr(e), file=sys.stderr)
        return image_bytes


def get_drive_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=GOOGLE_OAUTH_REFRESH_TOKEN,
        client_id=GOOGLE_OAUTH_CLIENT_ID,
        client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/drive"],
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


def notion_find_by_hash(image_hash):
    """Cerca si ja existeix una entrada amb aquesta mateixa empremta d'imatge
    (evita duplicats quan s'envia per error la mateixa foto dues vegades)."""
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    payload = {
        "filter": {
            "property": "Nom arxiu / captura",
            "rich_text": {"contains": image_hash},
        },
        "page_size": 1,
    }
    r = requests.post(
        f"{NOTION_API}/databases/{NOTION_DB_ID}/query", headers=headers, json=payload, timeout=30
    )
    r.raise_for_status()
    results = r.json().get("results", [])
    return results[0] if results else None


def _notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _rt(text, max_total=2000):
    """rich_text de Notion: trossos de 2.000 caràcters (límit per tros)."""
    text = (text or "")[:max_total]
    return [{"text": {"content": text[i:i + 2000]}} for i in range(0, len(text), 2000)]


def notion_find_duplicate(dades):
    """True si ja hi ha una entrada amb el mateix títol i la mateixa data."""
    titol, data = dades.get("titol"), dades.get("data_inici")
    if not titol or not data:
        return False
    payload = {
        "filter": {"and": [
            {"property": "Data detectada", "date": {"equals": data}},
            {"or": [
                {"property": "Títol detectat", "rich_text": {"equals": titol}},
                {"property": "Nom provisional", "title": {"equals": titol}},
            ]},
        ]},
        "page_size": 1,
    }
    r = requests.post(
        f"{NOTION_API}/databases/{NOTION_DB_ID}/query",
        headers=_notion_headers(), json=payload, timeout=30,
    )
    r.raise_for_status()
    return bool(r.json().get("results"))


def notion_create_page(resultat, image_url, filename=None):
    """Crea la fila a INBOX AGENDA a partir d'un ia.ResultatCartell.
    Els camps sense dada es deixen buits (mai "pendent de revisar")."""
    data = resultat.dades
    titol = data.get("titol") or "Sense títol"

    properties = {
        "Nom provisional": {"title": _rt(titol, 200)},
        "Títol detectat": {"rich_text": _rt(titol, 200)},
        "Font": {"select": {"name": "Instagram"}},
        "Model IA": {"select": {"name": resultat.model_etiqueta}},
        "Tipus entrada": {"select": {"name": "Captura Instagram"}},
        "Estat revisió": {"select": {"name": resultat.estat_revisio}},
        "Confiança IA": {"select": {"name": resultat.confianca}},
        "URL Drive imatge": {"url": image_url},
        "Captura / imatge original": {
            "files": [{"name": filename or "captura.jpg", "external": {"url": image_url}}]
        },
        "Notes revisió": {"rich_text": _rt(notes_revisio(
            resultat.problemes, data.get("dubtes"), resultat.confianca, resultat.model_etiqueta))},
    }

    if data.get("data_inici"):
        date_obj = {"start": data["data_inici"]}
        if data.get("data_fi"):
            date_obj["end"] = data["data_fi"]
        properties["Data detectada"] = {"date": date_obj}

    textos = {
        "categoria": None,  # select, a part
        "lloc": "Lloc detectat",
        "hora": "Hora detectada",
        "preu": "Preu detectat",
        "organitzador": "Organitzador detectat",
        "programa": "Programa detectat",
        "resum_web": "Resum web",
    }
    for camp, prop in textos.items():
        if prop and data.get(camp):
            properties[prop] = {"rich_text": _rt(data[camp], 200 if camp == "programa" else 2000)}

    if data.get("categoria"):
        properties["Categoria suggerida"] = {"select": {"name": data["categoria"]}}

    if data.get("text_visible"):
        properties["Text visible"] = {"rich_text": _rt(data["text_visible"], 8000)}

    if filename:
        properties["Nom arxiu / captura"] = {"rich_text": _rt(filename)}

    payload = {"parent": {"database_id": NOTION_DB_ID}, "properties": properties}
    r = requests.post(f"{NOTION_API}/pages", headers=_notion_headers(), json=payload, timeout=30)
    if not r.ok:
        print("Error Notion:", r.status_code, r.text, file=sys.stderr)
    r.raise_for_status()
    return r.json()


def notion_create_fallback_page(image_url, filename, motiu):
    """Fila mínima quan cap IA ha respost en HORES_MAX_REINTENT hores."""
    properties = {
        "Nom provisional": {"title": _rt("Cartell sense llegir (IA no disponible)")},
        "Font": {"select": {"name": "Instagram"}},
        "Model IA": {"select": {"name": "Manual"}},
        "Tipus entrada": {"select": {"name": "Captura Instagram"}},
        "Estat revisió": {"select": {"name": "Pendent revisar"}},
        "Confiança IA": {"select": {"name": "Baixa"}},
        "URL Drive imatge": {"url": image_url},
        "Captura / imatge original": {"files": [{"name": filename, "external": {"url": image_url}}]},
        "Nom arxiu / captura": {"rich_text": _rt(filename)},
        "Notes revisió": {"rich_text": _rt(
            f"⚠️ Cap proveïdor d'IA ha respost en {HORES_MAX_REINTENT} h. Cal omplir-la a mà.\n{motiu}")},
    }
    payload = {"parent": {"database_id": NOTION_DB_ID}, "properties": properties}
    r = requests.post(f"{NOTION_API}/pages", headers=_notion_headers(), json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def _missatge_resultat(resultat):
    d = resultat.dades
    if resultat.estat_revisio == "Duplicada":
        cap = "♻️ Sembla un duplicat (mateix títol i data). L'he afegit marcat com a «Duplicada»."
    elif resultat.confianca == "Alta":
        cap = "✅ Afegit a INBOX AGENDA · confiança alta"
    elif resultat.estat_revisio == "Revisar data":
        cap = "⚠️ Afegit a INBOX AGENDA · revisa la data"
    elif resultat.estat_revisio == "Revisar lloc":
        cap = "⚠️ Afegit a INBOX AGENDA · revisa el lloc"
    else:
        cap = f"🟡 Afegit a INBOX AGENDA · confiança {resultat.confianca.lower()}"
    return (
        f"{cap}\n«{d.get('titol') or 'Sense títol'}»\n"
        f"📅 {d.get('data_inici') or '(sense data)'}"
        + (f" · {d.get('hora')}" if d.get("hora") else "")
        + f"\n📍 {d.get('lloc') or '(sense lloc)'}\n"
        f"🏷️ {d.get('categoria') or '(sense categoria)'}\n"
        f"🤖 {resultat.model_etiqueta}"
    )


def process_photo_message(message):
    """Retorna False si cal reintentar el missatge al proper cicle."""
    chat_id = message["chat"]["id"]
    if "photo" in message:
        file_id = message["photo"][-1]["file_id"]  # la resolució més alta
    else:
        file_id = message["document"]["file_id"]  # imatge enviada com a fitxer
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    edat_hores = (time.time() - message.get("date", time.time())) / 3600
    primer_intent = edat_hores < 1  # el bot corre cada hora

    try:
        if primer_intent:
            telegram_send_message(chat_id, "📥 Rebut, processant la imatge...")

        img_bytes, ext = telegram_download_photo(file_id)
        mime = "image/png" if ext.lower() == "png" else "image/jpeg"

        image_hash = hashlib.sha256(img_bytes).hexdigest()[:16]
        existing = notion_find_by_hash(image_hash)
        if existing:
            telegram_send_message(
                chat_id,
                "ℹ️ Aquesta imatge ja s'havia processat abans (mateixa captura exacta) — "
                "no s'ha duplicat l'entrada a Notion.",
            )
            return
        filename = f"screenshot_{image_hash}_{ts}.{ext}"

        try:
            resultat = extreu_cartell(img_bytes, mime, es_duplicat=notion_find_duplicate)
        except TotsElsProveidorsHanFallat as e:
            print("Cap proveïdor d'IA disponible:", e, file=sys.stderr)
            if edat_hores >= HORES_MAX_REINTENT:
                image_url = drive_upload(img_bytes, filename, mime_type=mime)
                notion_create_fallback_page(image_url, filename, str(e)[:1500])
                telegram_send_message(
                    chat_id,
                    f"⚠️ Cap servei d'IA ha respost en {HORES_MAX_REINTENT} h. He desat la imatge a "
                    "INBOX AGENDA sense dades perquè no es perdi: cal omplir-la a mà.",
                )
                return
            if primer_intent:
                telegram_send_message(
                    chat_id,
                    "⏳ Els serveis d'IA estan saturats ara mateix. "
                    "No cal que facis res: ho tornaré a provar automàticament al proper cicle.",
                )
            return False

        upload_bytes = crop_to_poster(
            img_bytes, resultat.dades.get("requadre_cartell"), mime_type=mime)
        image_url = drive_upload(upload_bytes, filename, mime_type=mime)

        notion_create_page(resultat, image_url, filename=filename)
        telegram_send_message(chat_id, _missatge_resultat(resultat))
    except Exception as e:  # noqa: BLE001
        print("Error processant missatge:", repr(e), file=sys.stderr)
        telegram_send_message(
            chat_id,
            "⚠️ Hi ha hagut un error processant la imatge.\n"
            f"Detall: {type(e).__name__}: {e}\n\n"
            "Torna-ho a provar o avisa perquè es revisi.",
        )


def is_image_message(message):
    """Accepta fotos normals i també imatges enviades com a fitxer."""
    if "photo" in message:
        return True
    doc = message.get("document") or {}
    return str(doc.get("mime_type", "")).startswith("image/")


def main():
    updates = telegram_get_updates()
    if not updates:
        print("Sense missatges nous.")
        return

    confirm_offset = None
    for update in updates:
        message = update.get("message")
        if message and is_image_message(message):
            if process_photo_message(message) is False:
                # IA no disponible: no confirmem aquest missatge ni els següents,
                # així es tornaran a processar al proper run.
                break
        confirm_offset = update["update_id"] + 1

    if confirm_offset is not None:
        telegram_confirm(confirm_offset)


if __name__ == "__main__":
    main()
