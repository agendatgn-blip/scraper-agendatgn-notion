"""
THREADS · publicació automàtica per a @agendatgn
================================================
- Publica posts de text (i fils) a Threads amb l'API oficial (gratuïta).
- El token de Threads caduca cada 60 dies: aquest mòdul el renova sol
  (com a molt un cop per setmana) i guarda el nou a 🔐 CLAUS AUTOMÀTIQUES de Notion.
  El secret THREADS_TOKEN de GitHub només fa falta la primera vegada.

Variables d'entorn:
  THREADS_TOKEN     - token inicial (60 dies)
  THREADS_USER_ID   - id del perfil de Threads
  NOTION_TOKEN      - per guardar el token renovat
Si falten, Threads s'omet sense trencar res.
"""
import os
import time
from datetime import date, timedelta

import requests

API = "https://graph.threads.net/v1.0"
DS_CLAUS = "79a7def5-cf51-428e-b801-8b10ae87c33a"
NOM_CLAU = "threads_token"
TEMA = "Tarragona"          # tema (topic tag) de cada post
LIMIT = 500                 # caràcters per post a Threads
RENOVAR_CADA_DIES = 7


def _notion_h():
    return {"Authorization": f"Bearer {os.environ.get('NOTION_TOKEN')}",
            "Notion-Version": "2025-09-03", "Content-Type": "application/json"}


def _llegir_clau():
    """Torna (page_id, token, data_actualitzat) de Notion, o (None, None, None)."""
    try:
        r = requests.post(f"https://api.notion.com/v1/data_sources/{DS_CLAUS}/query", headers=_notion_h(),
                          json={"filter": {"property": "Nom", "title": {"equals": NOM_CLAU}}}, timeout=30)
        r.raise_for_status()
        res = r.json()["results"]
        if not res:
            return None, None, None
        p = res[0]["properties"]
        token = "".join(x["plain_text"] for x in p["Valor"]["rich_text"]).strip() or None
        d = (p["Actualitzat"]["date"] or {}).get("start")
        return res[0]["id"], token, (date.fromisoformat(d[:10]) if d else None)
    except Exception as e:  # noqa: BLE001
        print(f"  -> Threads: no he pogut llegir el token de Notion ({e})")
        return None, None, None


def _desar_clau(page_id, token):
    props = {"Nom": {"title": [{"text": {"content": NOM_CLAU}}]},
             "Valor": {"rich_text": [{"text": {"content": token}}]},
             "Actualitzat": {"date": {"start": date.today().isoformat()}}}
    try:
        if page_id:
            requests.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=_notion_h(),
                           json={"properties": props}, timeout=30).raise_for_status()
        else:
            requests.post("https://api.notion.com/v1/pages", headers=_notion_h(), timeout=30,
                          json={"parent": {"data_source_id": DS_CLAUS}, "properties": props}).raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"  -> Threads: no he pogut desar el token a Notion ({e})")


_TOKEN = None


def token():
    """Token vàlid de Threads, renovant-lo si fa més d'una setmana."""
    global _TOKEN
    if _TOKEN:
        return _TOKEN
    page_id, tok, actualitzat = _llegir_clau()
    tok = tok or os.environ.get("THREADS_TOKEN")
    if not tok:
        return None
    if not actualitzat or date.today() - actualitzat >= timedelta(days=RENOVAR_CADA_DIES):
        try:
            r = requests.get("https://graph.threads.net/refresh_access_token",
                             params={"grant_type": "th_refresh_token", "access_token": tok}, timeout=30)
            if r.ok and r.json().get("access_token"):
                tok = r.json()["access_token"]
                _desar_clau(page_id, tok)
                print("  -> Threads: token renovat (60 dies més).")
            else:
                print(f"  -> Threads: no s'ha pogut renovar el token: {r.text[:200]}")
        except Exception as e:  # noqa: BLE001
            print(f"  -> Threads: error renovant el token ({e})")
    _TOKEN = tok
    return tok


def configurat():
    return bool(os.environ.get("THREADS_USER_ID") and (os.environ.get("THREADS_TOKEN") or os.environ.get("NOTION_TOKEN")))


def _publicar(text, reply_to=None):
    uid, tok = os.environ.get("THREADS_USER_ID"), token()
    if not (uid and tok):
        print("  -> Threads no configurat, s'omet.")
        return None
    dades = {"media_type": "TEXT", "text": text[:LIMIT], "access_token": tok}
    if reply_to:
        dades["reply_to_id"] = reply_to
    if TEMA:
        dades["topic_tag"] = TEMA
    r = requests.post(f"{API}/{uid}/threads", data=dades, timeout=30)
    if not r.ok and TEMA:  # si el tema dona problemes, ho tornem a provar sense
        dades.pop("topic_tag", None)
        r = requests.post(f"{API}/{uid}/threads", data=dades, timeout=30)
    if not r.ok:
        print(f"  -> ERROR Threads (contenidor): {r.text[:300]}")
        return None
    creation_id = r.json()["id"]
    time.sleep(3)
    r = requests.post(f"{API}/{uid}/threads_publish",
                      data={"creation_id": creation_id, "access_token": tok}, timeout=30)
    if not r.ok:
        print(f"  -> ERROR Threads (publicar): {r.text[:300]}")
        return None
    return r.json().get("id")


def publicar_post(text):
    pid = _publicar(text)
    if pid:
        print(f"  -> Publicat a Threads: {text[:60]}...")
    return pid


def publicar_fil(parts):
    anterior = None
    for i, t in enumerate(parts):
        anterior = _publicar(t, reply_to=anterior)
        if not anterior:
            print(f"  -> Threads: fil aturat a la part {i + 1}.")
            return
        print(f"  -> Threads {i + 1}/{len(parts)} publicat")
        time.sleep(2)
