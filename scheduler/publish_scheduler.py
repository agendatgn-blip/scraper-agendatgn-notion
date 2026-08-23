#!/usr/bin/env python3
"""
AgendaTGN - Publish Scheduler
==============================
Cada dia (via GitHub Actions cron), aquest script:

1. Consulta la base de dades Notion "Activitats".
2. Per cada activitat amb "Aprovada publicació" = True:
   - Publicació "Avançament" (5 dies abans):
       - Si avui == Data inici - 5 dies  -> es dispara.
       - Si l'activitat es va aprovar amb MENYS de 5 dies d'antelació
         (és a dir, ja hem passat la data "-5 dies" i encara no s'ha
         publicat l'avançament) -> es dispara IGUALMENT avui mateix.
   - Publicació "Dia" (el dia de l'esdeveniment):
       - Si avui == Data inici -> es dispara.
3. Genera el text amb Gemini (variant segons avançament/dia).
4. Publica a X (Twitter) i, si el checkbox "Facebook" és cert i les
   credencials de Facebook estan configurades, també a la Pàgina de
   Facebook via Graph API.
5. Marca a Notion "Publicat Avançament" / "Publicat Dia" = True perquè
   no es dupliqui si l'script torna a córrer el mateix dia.

Variables d'entorn necessàries (GitHub Actions Secrets):
  NOTION_TOKEN            - Integration token de Notion amb accés a la BD
  NOTION_ACTIVITATS_DB_ID - ID de la data source "Activitats"
  GEMINI_API_KEY          - Clau de Google AI Studio
  TWITTER_API_KEY
  TWITTER_API_SECRET
  TWITTER_ACCESS_TOKEN
  TWITTER_ACCESS_SECRET
  FACEBOOK_PAGE_ID        - (opcional, fase 2)
  FACEBOOK_PAGE_TOKEN     - (opcional, fase 2)

Dependències (requirements.txt):
  requests
  google-generativeai
  tweepy
"""

import os
import sys
import json
from datetime import datetime, date, timedelta

import requests

# ---------------------------------------------------------------------------
# Configuració
# ---------------------------------------------------------------------------

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DB_ID = os.environ.get("NOTION_ACTIVITATS_DB_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

TWITTER_API_KEY = os.environ.get("TWITTER_API_KEY")
TWITTER_API_SECRET = os.environ.get("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.environ.get("TWITTER_ACCESS_SECRET")

FACEBOOK_PAGE_ID = os.environ.get("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_TOKEN = os.environ.get("FACEBOOK_PAGE_TOKEN")

NOTION_VERSION = "2025-09-03"
NOTION_API = "https://api.notion.com/v1"

DAYS_BEFORE = 5

REQUIRED_ENV = ["NOTION_TOKEN", "NOTION_ACTIVITATS_DB_ID", "GEMINI_API_KEY"]


def check_env():
    missing = [v for v in REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        print(f"ERROR: falten variables d'entorn: {', '.join(missing)}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Notion helpers
# ---------------------------------------------------------------------------

def notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def query_approved_activities():
    """Retorna totes les activitats amb 'Aprovada publicació' = true."""
    url = f"{NOTION_API}/data_sources/{NOTION_DB_ID}/query"
    payload = {
        "filter": {
            "property": "Aprovada publicació",
            "checkbox": {"equals": True},
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
        return ""
    t = prop.get("type")
    if t == "rich_text":
        return "".join(x.get("plain_text", "") for x in prop["rich_text"])
    if t == "title":
        return "".join(x.get("plain_text", "") for x in prop["title"])
    if t == "select":
        return prop["select"]["name"] if prop["select"] else ""
    if t == "number":
        return prop["number"]
    if t == "checkbox":
        return prop["checkbox"]
    if t == "date":
        return prop["date"]["start"] if prop["date"] else None
    return None


def mark_published(page_id, field_name):
    url = f"{NOTION_API}/pages/{page_id}"
    payload = {"properties": {field_name: {"checkbox": True}}}
    resp = requests.patch(url, headers=notion_headers(), json=payload, timeout=30)
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Generació de text amb Gemini
# ---------------------------------------------------------------------------

def generate_text(activity, mode):
    """mode = 'avancament' | 'dia'"""
    from google import genai

    client = genai.Client(api_key=GEMINI_API_KEY)

    nom = activity["nom"]
    lloc = activity["lloc"]
    hora = activity["hora"]
    descripcio = activity["descripcio"]
    preu = activity["preu"]

    if mode == "avancament":
        instruccio = (
            f"Escriu un tuit curt (màxim 260 caràcters) en català anunciant "
            f"que d'aquí a {DAYS_BEFORE} dies (o properament) tindrà lloc "
            f"l'activitat cultural '{nom}' a Tarragona. To genuí, atractiu, "
            f"sense hashtags excessius (màxim 2)."
        )
    else:
        instruccio = (
            f"Escriu un tuit curt (màxim 260 caràcters) en català anunciant "
            f"que AVUI és el dia de l'activitat cultural '{nom}' a Tarragona. "
            f"Crea sensació d'urgència/oportunitat. Màxim 2 hashtags."
        )

    context = (
        f"Dades de l'activitat:\n"
        f"- Nom: {nom}\n"
        f"- Lloc: {lloc}\n"
        f"- Hora: {hora}\n"
        f"- Preu: {preu}\n"
        f"- Descripció: {descripcio}\n\n{instruccio}\n\n"
        f"Respon NOMÉS amb el text del tuit, sense cometes ni explicacions."
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash", contents=context
    )
    return response.text.strip()


# ---------------------------------------------------------------------------
# Publicació a X (Twitter)
# ---------------------------------------------------------------------------

def post_to_twitter(text):
    import tweepy

    client = tweepy.Client(
        consumer_key=TWITTER_API_KEY,
        consumer_secret=TWITTER_API_SECRET,
        access_token=TWITTER_ACCESS_TOKEN,
        access_token_secret=TWITTER_ACCESS_SECRET,
    )
    client.create_tweet(text=text)
    print(f"  -> Publicat a X: {text[:60]}...")


def post_to_facebook(text):
    if not (FACEBOOK_PAGE_ID and FACEBOOK_PAGE_TOKEN):
        print("  -> Facebook no configurat encara (fase 2), s'omet.")
        return
    url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/feed"
    resp = requests.post(
        url,
        data={"message": text, "access_token": FACEBOOK_PAGE_TOKEN},
        timeout=30,
    )
    if resp.status_code >= 300:
        print(f"  -> ERROR Facebook: {resp.text}")
    else:
        print(f"  -> Publicat a Facebook: {text[:60]}...")


# ---------------------------------------------------------------------------
# Lògica principal
# ---------------------------------------------------------------------------

def process_activity(page):
    props = page["properties"]
    page_id = page["id"]

    nom = get_prop_text(props, "Name") or "(sense nom)"
    data_inici_raw = get_prop_text(props, "Data inici")
    if not data_inici_raw:
        return

    data_inici = datetime.fromisoformat(data_inici_raw.split("T")[0]).date()
    avui = date.today()
    data_avancament = data_inici - timedelta(days=DAYS_BEFORE)

    activity = {
        "nom": nom,
        "lloc": get_prop_text(props, "Lloc") or "",
        "hora": get_prop_text(props, "Hora") or "",
        "descripcio": get_prop_text(props, "Descripció") or "",
        "preu": get_prop_text(props, "Preu"),
    }

    publicat_avancament = get_prop_text(props, "Publicat Avançament")
    publicat_dia = get_prop_text(props, "Publicat Dia")
    vol_facebook = get_prop_text(props, "Facebook")

    # --- Publicació "Avançament" ---
    # Es dispara si avui és exactament la data -5, o si ja hem passat
    # aquesta data (aprovació tardana) i encara no s'ha publicat,
    # sempre que l'esdeveniment encara no hagi passat.
    if not publicat_avancament and avui <= data_inici:
        if avui >= data_avancament:
            print(f"[{nom}] Generant publicació d'avançament...")
            text = generate_text(activity, "avancament")
            post_to_twitter(text)
            if vol_facebook:
                post_to_facebook(text)
            mark_published(page_id, "Publicat Avançament")

    # --- Publicació "Dia" ---
    if not publicat_dia and avui == data_inici:
        print(f"[{nom}] Generant publicació del dia...")
        text = generate_text(activity, "dia")
        post_to_twitter(text)
        if vol_facebook:
            post_to_facebook(text)
        mark_published(page_id, "Publicat Dia")


def main():
    check_env()
    print(f"Executant scheduler — {date.today().isoformat()}")
    activities = query_approved_activities()
    print(f"Activitats aprovades trobades: {len(activities)}")
    for page in activities:
        try:
            process_activity(page)
        except Exception as e:
            name = get_prop_text(page["properties"], "Name")
            print(f"ERROR processant '{name}': {e}")
    print("Fet.")


if __name__ == "__main__":
    main()
