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
4. Publica a X (Twitter) i, si el checkbox "Facebook" és cert:
   - a la Pàgina de Facebook (Graph API, amb imatge), i
   - t'envia el mateix post per Telegram per copiar-lo al GRUP de Facebook
     (Meta no permet publicar en grups per API des d'abril de 2024).
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
  FACEBOOK_PAGE_ID        - (opcional) id de la Pàgina
  FACEBOOK_PAGE_TOKEN     - (opcional) token de Pàgina que no caduca
  TELEGRAM_BOT_TOKEN      - (opcional) el mateix bot de les captures
  TELEGRAM_CHAT_ID        - (opcional) el teu id de Telegram

Dependències (requirements.txt):
  requests
  groq
  tweepy
  Pillow
"""

import os
import re
import sys
import json
from datetime import datetime, date, timedelta
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
FACEBOOK_API_VERSION = "v26.0"

# Telegram: t'envia cada post de Facebook perquè el copiïs al GRUP
# (Meta no permet publicar en grups via API des de 2024)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

NOTION_VERSION = "2025-09-03"
NOTION_API = "https://api.notion.com/v1"

DAYS_BEFORE = 5

DIES_SETMANA_CA = [
    "dilluns", "dimarts", "dimecres", "dijous", "divendres", "dissabte", "diumenge",
]

# ---------------------------------------------------------------------------
# Disseny de la imatge (plantilla de marca + retolat dinàmic)
# ---------------------------------------------------------------------------
ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets"
)
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

def url_descarrega(url):
    """Els enllaços de Google Drive (/file/d/ID/view, open?id=ID) porten a la pàgina del
    visor (HTML), no a la imatge. Els convertim a la descàrrega directa del fitxer."""
    m = re.search(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:[^#]*&)?id=)([\w-]{20,})", url or "")
    if m:
        return f"https://drive.usercontent.google.com/download?id={m.group(1)}&export=view"
    # Ajuntament de Tarragona: ".../imatge" és l'original (10-20 MB, el servidor talla la
    # descàrrega). Plone en serveix una versió de 768 px a ".../@@images/imatge/large".
    m = re.match(r"(https?://(?:www\.)?tarragona\.cat/.+?)/imatge/?$", url or "")
    if m:
        return f"{m.group(1)}/@@images/imatge/large"
    return url


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
            resp = requests.get(url_descarrega(notion_url), timeout=30)
            resp.raise_for_status()
            return fit_image_contain(resp.content)
        except Exception as e:  # noqa: BLE001
            print(f"  -> Avís: no s'ha pogut baixar la imatge de Notion ({e}), es fa servir la plantilla genèrica.")
    return generate_template_image(nom, categoria)


# ---------------------------------------------------------------------------
# Generació de text amb Groq
# ---------------------------------------------------------------------------

def _lloc_complet(activity):
    lloc = activity.get("lloc") or ""
    mun = (activity.get("municipi") or "").strip()
    if mun and "tarragona" not in mun.lower() and mun.lower() not in lloc.lower():
        lloc = f"{lloc} ({mun})" if lloc else mun
    return lloc


def generate_text(activity, mode, recents=None):
    """mode = 'avancament' | 'dia'. El to surt de veu_agendatgn.py i guia_to.md.
    Torna (text_x, cta) — la CTA s'afegeix a part perquè no es repeteixi."""
    import veu_agendatgn as veu

    recents = recents or []
    cta = veu.triar_cta(recents)
    nom, hora, data_text = activity["nom"], activity["hora"], activity.get("data_text", "")
    lloc = _lloc_complet(activity)
    dades = (
        "Dades de l'activitat (fes servir NOMÉS aquestes):\n"
        f"- Nom: {nom}\n- Data: {data_text}\n- Hora: {hora}\n- Lloc: {lloc}\n"
        f"- Preu: {activity.get('preu_text') or ''}\n- Descripció: {activity['descripcio']}\n\n"
    )
    if mode == "avancament":
        instruccio = dades + (
            f"Escriu un post per a X que avanci aquesta activitat. Digues la data tal qual («el {data_text}»), "
            "sense comptes enrere. Inclou hora i lloc si hi són. No hi posis cap crida a l'acció ni enllaç."
        )
    else:
        instruccio = dades + (
            "Escriu un post per a X per dir que és AVUI. Inclou hora i lloc si hi són. "
            "No hi posis cap crida a l'acció ni enllaç."
        )
    marge = 270 - (len(cta) + 2 if cta else 0)
    resultat = veu.escriure(instruccio, marge, GROQ_API_KEY, textos_recents=recents)
    if not resultat:
        # Xarxa de seguretat: text simple a partir de les dades
        detall = " · ".join(x for x in [hora, lloc] if x)
        resultat = (f"El {data_text}: {nom}." if mode == "avancament" else f"Avui: {nom}.") + \
            (f"\n{detall}" if detall else "")
    return resultat, cta


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


def facebook_text(text, activity, cta=None):
    """Text de X + una línia pràctica (sense emojis) + CTA opcional. Sense URLs."""
    parts = [activity.get("data_text", "").capitalize(), activity.get("hora", ""),
             _lloc_complet(activity), activity.get("preu_text", "")]
    detall = " · ".join(p for p in parts if p)
    out = text
    ja_hi_es = all((x or "").lower() in text.lower() for x in [activity.get("hora"), _lloc_complet(activity)])
    if detall and not ja_hi_es:
        out += f"\n\n{detall}"
    if cta:
        out += f"\n\n{cta}"
    return out


def post_to_facebook(text, image_bytes=None):
    """Publica a la Pàgina de Facebook. Amb imatge si n'hi ha."""
    if not (FACEBOOK_PAGE_ID and FACEBOOK_PAGE_TOKEN):
        print("  -> Facebook no configurat encara, s'omet.")
        return
    base = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{FACEBOOK_PAGE_ID}"
    if image_bytes:
        resp = requests.post(
            f"{base}/photos",
            data={"caption": text, "published": "true", "access_token": FACEBOOK_PAGE_TOKEN},
            files={"source": ("imatge.png", image_bytes, "image/png")},
            timeout=60,
        )
    else:
        resp = requests.post(
            f"{base}/feed",
            data={"message": text, "access_token": FACEBOOK_PAGE_TOKEN},
            timeout=30,
        )
    if resp.status_code >= 300:
        print(f"  -> ERROR Facebook: {resp.text}")
    else:
        print(f"  -> Publicat a la Pàgina de Facebook: {text[:60]}...")


def send_to_telegram_for_group(text, image_bytes=None):
    """T'envia el post per Telegram, llest per copiar i enganxar al grup de FB."""
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    capcalera = "👥 Per al GRUP de Facebook (copia i enganxa):\n\n"
    try:
        if image_bytes:
            caption = (capcalera + text)[:1024]
            requests.post(
                f"{api}/sendPhoto",
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                files={"photo": ("imatge.png", image_bytes, "image/png")},
                timeout=60,
            ).raise_for_status()
        else:
            requests.post(
                f"{api}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": capcalera + text},
                timeout=30,
            ).raise_for_status()
        print("  -> Enviat a Telegram per al grup de Facebook.")
    except Exception as e:  # noqa: BLE001
        print(f"  -> Avís: no s'ha pogut enviar a Telegram ({e}).")


def publish_everywhere(text, cta, image_bytes, activity, vol_facebook, clau):
    import veu_agendatgn as veu
    text_x = f"{text}\n\n{cta}" if cta and len(text) + len(cta) + 2 <= 280 else text
    post_to_twitter(text_x, image_bytes=image_bytes)
    try:
        import threads_pub
        if threads_pub.configurat():
            threads_pub.publicar_post(facebook_text(text, activity, cta)[:threads_pub.LIMIT])
    except Exception as e:  # noqa: BLE001  (Threads mai ha de trencar X/Facebook)
        print(f"  -> Avís Threads: {e}")
    if vol_facebook:
        fb = facebook_text(text, activity, cta)
        post_to_facebook(fb, image_bytes=image_bytes)
        send_to_telegram_for_group(fb, image_bytes=image_bytes)
    veu.registrar_post(text_x, "Post individual", date.today().isoformat(), clau)


# ---------------------------------------------------------------------------
# Lògica principal
# ---------------------------------------------------------------------------

def _preu_llegible(preu):
    if preu is None or preu == "":
        return ""
    try:
        return "Gratuït" if float(preu) == 0 else f"{float(preu):g} €"
    except (TypeError, ValueError):
        return str(preu)


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
    data_text = f"{DIES_SETMANA_CA[data_inici.weekday()]} dia {data_inici.day}"

    activity = {
        "nom": nom,
        "lloc": get_prop_text(props, "Lloc") or "",
        "municipi": get_prop_text(props, "Municipi") or "",
        "hora": get_prop_text(props, "Hora") or "",
        "descripcio": get_prop_text(props, "Descripció") or "",
        "preu": get_prop_text(props, "Preu"),
        "data_text": data_text,
        "preu_text": get_prop_text(props, "Preu (text)") or _preu_llegible(get_prop_text(props, "Preu")),
    }
    categoria = get_prop_text(props, "Categoria") or ""

    publicat_avancament = get_prop_text(props, "Publicat Avançament")
    publicat_dia = get_prop_text(props, "Publicat Dia")
    vol_facebook = get_prop_text(props, "Facebook")

    # No té sentit publicar "avançament" el mateix dia de l'esdeveniment:
    # el tuit de "dia" ja ho cobreix i sortirien els dos alhora.
    cal_avancament = not publicat_avancament and avui < data_inici and avui >= data_avancament
    cal_dia = not publicat_dia and avui == data_inici

    image_bytes = get_activity_image_bytes(props, nom, categoria) if (cal_avancament or cal_dia) else None

    # --- Publicació "Avançament" ---
    # Es dispara si avui és exactament la data -5, o si ja hem passat
    # aquesta data (aprovació tardana) i encara no s'ha publicat,
    # sempre que encara no sigui el mateix dia de l'esdeveniment.
    if cal_avancament:
        print(f"[{nom}] Generant publicació d'avançament...")
        text, cta = generate_text(activity, "avancament", RECENTS)
        publish_everywhere(text, cta, image_bytes, activity, vol_facebook, f"post-{page_id}-avancament")
        RECENTS.insert(0, text)
        mark_published(page_id, "Publicat Avançament")

    # --- Publicació "Dia" ---
    if cal_dia:
        print(f"[{nom}] Generant publicació del dia...")
        text, cta = generate_text(activity, "dia", RECENTS)
        publish_everywhere(text, cta, image_bytes, activity, vol_facebook, f"post-{page_id}-dia")
        RECENTS.insert(0, text)
        mark_published(page_id, "Publicat Dia")


RECENTS = []


def main():
    check_env()
    import veu_agendatgn as veu
    RECENTS.extend(veu.recents(10))
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
