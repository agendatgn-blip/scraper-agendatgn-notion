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
  GROQ_API_KEY            - Clau de console.groq.com
  TWITTER_API_KEY
  TWITTER_API_SECRET
  TWITTER_ACCESS_TOKEN
  TWITTER_ACCESS_SECRET
  FACEBOOK_PAGE_ID        - (opcional, fase 2)
  FACEBOOK_PAGE_TOKEN     - (opcional, fase 2)

Dependències (requirements.txt):
  requests
  groq
  tweepy
  Pillow
"""

import os
import sys
import json
from datetime import datetime, date, timedelta
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Configuració
# ---------------------------------------------------------------------------

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DB_ID = os.environ.get("NOTION_ACTIVITATS_DB_ID")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

TWITTER_API_KEY = os.environ.get("TWITTER_API_KEY")
TWITTER_API_SECRET = os.environ.get("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.environ.get("TWITTER_ACCESS_SECRET")

FACEBOOK_PAGE_ID = os.environ.get("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_TOKEN = os.environ.get("FACEBOOK_PAGE_TOKEN")

NOTION_VERSION = "2025-09-03"
NOTION_API = "https://api.notion.com/v1"

DAYS_BEFORE = 5

# ---------------------------------------------------------------------------
# Disseny de la imatge (plantilla de marca + retolat dinàmic)
# ---------------------------------------------------------------------------
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
TEMPLATE_PATH = os.path.join(ASSETS_DIR, "base_template.png")
FONT_PATH = os.path.join(ASSETS_DIR, "Anton-Regular.ttf")
CANVAS_SIZE = (1600, 900)
BRAND_YELLOW = (255, 220, 0)

CATEGORY_COLORS = {
    "Música": (230, 57, 70),
    "Teatre": (106, 27, 154),
    "Exposició": (21, 101, 192),
    "Cinema": (78, 52, 46),
    "Patrimoni": (96, 96, 96),
    "Literatura": (230, 126, 34),
    "Familiar": (216, 27, 96),
    "Taller": (204, 153, 0),
    "Gastronomia": (56, 142, 60),
    "Mercat": (56, 142, 60),
    "Conferència": (69, 90, 100),
    "Altres": (33, 33, 33),
    "Dansa": (173, 20, 87),
    "Art": (25, 118, 210),
    "Festa popular": (216, 67, 21),
}

REQUIRED_ENV = ["NOTION_TOKEN", "NOTION_ACTIVITATS_DB_ID", "GROQ_API_KEY"]


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
# Imatge: obtenir la de Notion, encaixar-la, o generar la plantilla de marca
# ---------------------------------------------------------------------------

def get_notion_image_url(props):
    """Retorna la URL del primer fitxer del camp 'Imatge' de Notion, si n'hi ha."""
    prop = props.get("Imatge")
    if not prop or prop.get("type") != "files" or not prop.get("files"):
        return None
    f = prop["files"][0]
    if f.get("type") == "external":
        return f["external"]["url"]
    if f.get("type") == "file":
        return f["file"]["url"]
    return None


def fit_image_contain(image_bytes, canvas_size=CANVAS_SIZE, bg_color=BRAND_YELLOW):
    """Encaixa la imatge sencera (sense retallar res) centrada dins del
    format 1600x900, omplint l'espai sobrant amb el groc de marca."""
    img = Image.open(BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    canvas = Image.new("RGB", canvas_size, bg_color)
    fitted = img.copy()
    fitted.thumbnail(canvas_size, Image.LANCZOS)
    x = (canvas_size[0] - fitted.width) // 2
    y = (canvas_size[1] - fitted.height) // 2
    canvas.paste(fitted, (x, y))
    out = BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def _wrap_text(draw, text, font, max_width):
    """Parteix el text en línies que caben dins max_width, amb aquest font."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def generate_template_image(nom, categoria):
    """Genera la imatge de marca genèrica amb el nom de l'activitat i la
    categoria retolats a sobre de la plantilla base."""
    img = Image.open(TEMPLATE_PATH).convert("RGB")
    draw = ImageDraw.Draw(img)

    # --- Etiqueta de categoria ---
    if categoria:
        color = CATEGORY_COLORS.get(categoria, (33, 33, 33))
        tag_font = ImageFont.truetype(FONT_PATH, 34)
        pad_x, pad_y = 24, 12
        text_w = draw.textlength(categoria.upper(), font=tag_font)
        tag_x, tag_y = 60, 250
        draw.rounded_rectangle(
            [tag_x, tag_y, tag_x + text_w + pad_x * 2, tag_y + 34 + pad_y * 2],
            radius=8,
            fill=color,
        )
        draw.text(
            (tag_x + pad_x, tag_y + pad_y - 2),
            categoria.upper(),
            font=tag_font,
            fill=(255, 255, 255),
        )

    # --- Títol de l'activitat (mida adaptativa segons llargada) ---
    max_width = 1480
    title = (nom or "").upper()
    font_size = 110
    lines = []
    while font_size > 44:
        title_font = ImageFont.truetype(FONT_PATH, font_size)
        lines = _wrap_text(draw, title, title_font, max_width)
        line_height = font_size * 1.15
        total_height = line_height * len(lines)
        if len(lines) <= 3 and total_height <= 380:
            break
        font_size -= 6
    title_font = ImageFont.truetype(FONT_PATH, font_size)
    line_height = font_size * 1.15

    start_y = 360
    for i, line in enumerate(lines):
        draw.text((60, start_y + i * line_height), line, font=title_font, fill=(20, 20, 20))

    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def get_activity_image_bytes(props, nom, categoria):
    """Retorna els bytes de la imatge final a publicar: la pròpia de
    l'activitat (encaixada sobre fons de marca) si n'hi ha, o la plantilla
    genèrica generada amb el títol i la categoria si no."""
    notion_url = get_notion_image_url(props)
    if notion_url:
        try:
            resp = requests.get(notion_url, timeout=30)
            resp.raise_for_status()
            return fit_image_contain(resp.content)
        except Exception as e:  # noqa: BLE001
            print(f"  -> Avís: no s'ha pogut baixar la imatge de Notion ({e}), es fa servir la plantilla genèrica.")
    return generate_template_image(nom, categoria)


# ---------------------------------------------------------------------------
# Generació de text amb Groq
# ---------------------------------------------------------------------------

def generate_text(activity, mode):
    """mode = 'avancament' | 'dia'"""
    from groq import Groq

    client = Groq(api_key=GROQ_API_KEY)

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

    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[{"role": "user", "content": context}],
        max_tokens=200,
        reasoning_effort="low",
    )
    resultat = (response.choices[0].message.content or "").strip()
    if not resultat:
        # Xarxa de seguretat: si el model no retorna text (per exemple,
        # tot el contingut ha anat al "raonament"), fem servir un text
        # simple generat directament a partir de les dades, per no perdre
        # la publicació.
        if mode == "avancament":
            resultat = f"📅 D'aquí a {DAYS_BEFORE} dies: {nom}, a {lloc}. No t'ho perdis!"
        else:
            resultat = f"📅 AVUI: {nom}, a {lloc} ({hora}). T'hi esperem!"
    return resultat


# ---------------------------------------------------------------------------
# Publicació a X (Twitter)
# ---------------------------------------------------------------------------

def post_to_twitter(text, image_bytes=None):
    import tweepy

    client = tweepy.Client(
        consumer_key=TWITTER_API_KEY,
        consumer_secret=TWITTER_API_SECRET,
        access_token=TWITTER_ACCESS_TOKEN,
        access_token_secret=TWITTER_ACCESS_SECRET,
    )
    try:
        media_ids = None
        if image_bytes:
            auth = tweepy.OAuth1UserHandler(
                TWITTER_API_KEY, TWITTER_API_SECRET,
                TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET,
            )
            api_v1 = tweepy.API(auth)
            media = api_v1.media_upload(filename="imatge.png", file=BytesIO(image_bytes))
            media_ids = [media.media_id]

        client.create_tweet(text=text, media_ids=media_ids)
        print(f"  -> Publicat a X: {text[:60]}...")
    except Exception as e:
        print(f"  -> ERROR detallat de X: {repr(e)}")
        raise


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
    categoria = get_prop_text(props, "Categoria") or ""

    publicat_avancament = get_prop_text(props, "Publicat Avançament")
    publicat_dia = get_prop_text(props, "Publicat Dia")
    vol_facebook = get_prop_text(props, "Facebook")

    cal_publicar = (not publicat_avancament and avui <= data_inici and avui >= data_avancament) or (
        not publicat_dia and avui == data_inici
    )
    image_bytes = get_activity_image_bytes(props, nom, categoria) if cal_publicar else None

    # --- Publicació "Avançament" ---
    # Es dispara si avui és exactament la data -5, o si ja hem passat
    # aquesta data (aprovació tardana) i encara no s'ha publicat,
    # sempre que l'esdeveniment encara no hagi passat.
    if not publicat_avancament and avui <= data_inici:
        if avui >= data_avancament:
            print(f"[{nom}] Generant publicació d'avançament...")
            text = generate_text(activity, "avancament")
            post_to_twitter(text, image_bytes=image_bytes)
            if vol_facebook:
                post_to_facebook(text)
            mark_published(page_id, "Publicat Avançament")

    # --- Publicació "Dia" ---
    if not publicat_dia and avui == data_inici:
        print(f"[{nom}] Generant publicació del dia...")
        text = generate_text(activity, "dia")
        post_to_twitter(text, image_bytes=image_bytes)
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
