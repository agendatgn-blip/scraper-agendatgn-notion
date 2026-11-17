"""Peces compartides: Notion, Telegram, Google Drive i utilitats."""
import os
import re
import time
import unicodedata
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import requests

from .config import NOTION_DB

TZ = ZoneInfo("Europe/Madrid")
UA = {"User-Agent": "Mozilla/5.0 (AgendaTGN noticies bot)"}

NOTION_H = {
    "Authorization": f"Bearer {os.environ.get('NOTION_TOKEN', '')}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def ara_local():
    return datetime.now(TZ)


# ---------------------------------------------------------------- Notion
def notion_query(body, maxim=300):
    out, cursor = [], None
    while True:
        b = dict(body)
        if cursor:
            b["start_cursor"] = cursor
        r = requests.post(f"https://api.notion.com/v1/databases/{NOTION_DB}/query",
                          headers=NOTION_H, json=b, timeout=30)
        if r.status_code == 404:
            msg = ("⚠️ Notícies culturals: la integració de GitHub no veu la base «📰 Notícies culturals TGN». "
                   "A Notion: obre la base → ··· → Connexions → afegeix la mateixa connexió que fa servir l'INBOX.")
            tg_text(msg)
            raise SystemExit(msg)
        r.raise_for_status()
        d = r.json()
        out += d["results"]
        if not d.get("has_more") or len(out) >= maxim:
            return out
        cursor = d["next_cursor"]


def notion_create(props):
    r = requests.post("https://api.notion.com/v1/pages", headers=NOTION_H,
                      json={"parent": {"database_id": NOTION_DB}, "properties": props}, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Notion {r.status_code}: {r.text[:300]}")
    time.sleep(0.4)
    return r.json()


def notion_update(page_id, props):
    r = requests.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=NOTION_H,
                       json={"properties": props}, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Notion {r.status_code}: {r.text[:300]}")


def txt(page, name):
    p = page["properties"].get(name, {})
    t = p.get("type")
    if t in ("title", "rich_text"):
        return "".join(x["plain_text"] for x in p[t])
    if t == "select":
        return (p["select"] or {}).get("name", "")
    if t == "url":
        return p["url"] or ""
    if t == "number":
        return p["number"]
    if t == "date":
        return (p["date"] or {}).get("start", "")
    return ""


def rich(s):
    s = str(s or "")
    return {"rich_text": [{"text": {"content": s[i:i + 1900]}} for i in range(0, min(len(s), 5700), 1900)]}


def title(s):
    return {"title": [{"text": {"content": str(s or "")[:200]}}]}


# ---------------------------------------------------------------- Telegram
def _tg(method, **kw):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("(sense Telegram)", str(kw.get("data", {}).get("text", ""))[:200])
        return
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/{method}", timeout=60, **kw)
        if not r.ok:
            print("Telegram error:", r.text[:300])
    except requests.RequestException as e:
        print("Telegram error:", e)


def tg_text(text):
    _tg("sendMessage", data={"chat_id": os.environ.get("TELEGRAM_CHAT_ID"), "text": text[:4000],
                             "disable_web_page_preview": True})


def tg_album(imatges, caption=""):
    """imatges: llista de bytes PNG. Envia-les com un sol àlbum (el carrusel)."""
    import json
    media, files = [], {}
    for i, b in enumerate(imatges):
        files[f"f{i}"] = (f"slide{i + 1}.png", b, "image/png")
        item = {"type": "photo", "media": f"attach://f{i}"}
        if i == 0 and caption:
            item["caption"] = caption[:1000]
        media.append(item)
    _tg("sendMediaGroup", data={"chat_id": os.environ.get("TELEGRAM_CHAT_ID"), "media": json.dumps(media)},
        files=files)


# ---------------------------------------------------------------- Google Drive
def drive_upload(png_bytes, nom):
    """Puja la imatge a la carpeta de Drive d'AgendaTGN i en torna l'enllaç. None si no hi ha credencials."""
    folder = os.environ.get("DRIVE_FOLDER_ID")
    if not (folder and os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN")):
        return None
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload
        creds = Credentials(token=None, refresh_token=os.environ["GOOGLE_OAUTH_REFRESH_TOKEN"],
                            client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID"),
                            client_secret=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"),
                            token_uri="https://oauth2.googleapis.com/token",
                            scopes=["https://www.googleapis.com/auth/drive"])
        srv = build("drive", "v3", credentials=creds, cache_discovery=False)
        media = MediaIoBaseUpload(BytesIO(png_bytes), mimetype="image/png", resumable=False)
        f = srv.files().create(body={"name": nom, "parents": [folder]}, media_body=media,
                               fields="id, webViewLink").execute()
        srv.permissions().create(fileId=f["id"], body={"role": "reader", "type": "anyone"}).execute()
        return f["webViewLink"]
    except Exception as e:  # noqa: BLE001
        print("Drive no disponible:", repr(e)[:200])
        return None


# ---------------------------------------------------------------- text
def norm(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", t)).strip()


def neteja_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"&nbsp;|&#160;", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def article_text(url, max_chars=4000):
    """Text de la notícia original (paràgrafs <p>). Buit si no es pot."""
    if not url or "news.google.com" in url:
        return ""
    try:
        html = requests.get(url, timeout=20, headers=UA).text
    except requests.RequestException:
        return ""
    ps = re.findall(r"<p[^>]*>(.*?)</p>", html, flags=re.S | re.I)
    clean = [neteja_html(p) for p in ps]
    return " ".join(p for p in clean if len(p) > 60)[:max_chars]
