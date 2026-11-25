#!/usr/bin/env python3
"""
AgendaTGN - Stories "RECOMANATS AVUI" per a Instagram
=====================================================
Les stories editables les fa cada dia a les 8:00 una tasca programada de Claude
a Canva (a partir de la PLANTILLA · Recomanats avui). Quan acaba, deixa una fila
al REGISTRE RESUMS amb la clau "stories-canva-AAAA-MM-DD" i els enllaços de Canva.

Aquest script (cada passada del Publish Scheduler, 8:00-12:00):
  1. Si troba aquesta fila, t'envia l'avís per Telegram amb els enllaços de Canva.
  2. Si a les 9:30 encara no hi és (Canva ha fallat) i avui hi ha destacades,
     fa les stories en PNG (negre, blanc i groc #FFDC00, Anton + Inter, logo,
     màx. 3 activitats per story) i te les envia com a pla B.
Només avisa un cop al dia (clau "stories-ig-AAAA-MM-DD"). Sense destacades, res.

Ús:
  python scheduler/stories_ig.py                       # automàtic (8:00-12:00, un cop al dia)
  python scheduler/stories_ig.py --forcar              # ara mateix, encara que ja s'hagi fet
  python scheduler/stories_ig.py --data 2026-10-24 --forcar
  python scheduler/stories_ig.py --local carpeta/      # només desa els PNG (no envia ni registra)

A més (25/11/2026), cada dia envia una STORY PER ACTIVITAT recomanada, amb el
mateix disseny que la imatge dels posts d'X però en vertical (clau "stories-act-AAAA-MM-DD").
"""
import argparse
import os
import re
import sys
import unicodedata
from datetime import date, datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont

TZ = ZoneInfo("Europe/Madrid")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DS_ACTIVITATS = os.environ.get("NOTION_ACTIVITATS_DB_ID")
DS_LLOCS = "bc7d9e22-f18d-4f06-bb83-4bee33e0cd32"
DS_REGISTRE = "d61de192-b46e-4b69-9db1-67f731f5ef9a"
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID")

HORA_INICI = 8      # a partir de les 8:00
HORA_LIMIT = 12     # passades més tard ja no les fan (GitHub endarrerit)
HORA_ACTIVITATS = 7  # stories per activitat: a partir de les 7:00 (workflow propi a les 7)
MAX_PER_STORY = 3
PLA_B_HORA = (9, 30)  # si a aquesta hora no hi ha les de Canva, s'envien els PNG

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
F_ANTON = os.path.join(ASSETS, "Anton-Regular.ttf")
F_INTER_B = os.path.join(ASSETS, "Inter-Bold.ttf")
F_INTER_SB = os.path.join(ASSETS, "Inter-SemiBold.ttf")
LOGO = os.path.join(ASSETS, "logo_cercle.png")

W, H = 1080, 1920
GROC, NEGRE, BLANC = (255, 220, 0), (0, 0, 0), (255, 255, 255)
MARGE = 60

DIES = ["DILLUNS", "DIMARTS", "DIMECRES", "DIJOUS", "DIVENDRES", "DISSABTE", "DIUMENGE"]
MESOS = ["GENER", "FEBRER", "MARÇ", "ABRIL", "MAIG", "JUNY", "JULIOL",
         "AGOST", "SETEMBRE", "OCTUBRE", "NOVEMBRE", "DESEMBRE"]


# ---------------------------------------------------------------- Notion
def _h():
    return {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2025-09-03",
            "Content-Type": "application/json"}


def query(ds, filtre=None):
    url, cos, out = f"https://api.notion.com/v1/data_sources/{ds}/query", {"page_size": 100}, []
    if filtre:
        cos["filter"] = filtre
    while True:
        r = requests.post(url, headers=_h(), json=cos, timeout=30)
        r.raise_for_status()
        d = r.json()
        out += d["results"]
        if not d.get("has_more"):
            return out
        cos["start_cursor"] = d["next_cursor"]


def prop(p, nom):
    v = p["properties"].get(nom)
    if not v:
        return None
    t = v["type"]
    if t in ("title", "rich_text"):
        return "".join(x["plain_text"] for x in v[t]).strip() or None
    if t == "checkbox":
        return v["checkbox"]
    if t == "select":
        return v["select"]["name"] if v["select"] else None
    if t == "date":
        return v["date"]
    if t == "relation":
        return [x["id"] for x in v["relation"]]
    if t == "number":
        return v["number"]
    return None


def ja_fet(clau):
    return bool(query(DS_REGISTRE, {"property": "Clau", "title": {"equals": clau}}))


def registrar(clau, dia, n_acts, n_stories, text):
    requests.post("https://api.notion.com/v1/pages", headers=_h(), timeout=30, json={
        "parent": {"data_source_id": DS_REGISTRE},
        "properties": {
            "Clau": {"title": [{"text": {"content": clau}}]},
            "Tipus": {"select": {"name": "Stories IG"}},
            "Data": {"date": {"start": dia.isoformat()}},
            "Activitats": {"number": n_acts},
            "Parts X": {"number": n_stories},
            "Text": {"rich_text": [{"text": {"content": text[:1900]}}]},
        }}).raise_for_status()


# ---------------------------------------------------------------- dades
def norm(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", " ", t).split()


def preu_curt(text, num):
    """Criteri AgendaTGN: si no consta preu, és gratuït."""
    if text:
        return text
    try:
        return "Gratuït" if not num else f"{float(num):g} €"
    except (TypeError, ValueError):
        return "Gratuït"


def minuts(h):
    m = re.search(r"(\d{1,2})[:.h](\d{2})?", h or "")
    if not m:
        return 99 * 60
    hh = int(m.group(1))
    return ((hh + 24) if hh < 6 else hh) * 60 + int(m.group(2) or 0)


def hora_neta(h):
    """'De 18:30 h a 21:00 h' -> '18:30 - 21:00'; text no horari -> 'Hora per confirmar'."""
    hores = re.findall(r"(\d{1,2})[:.h](\d{2})", h or "")
    if not hores:
        return "Hora per confirmar" if h and "pendent" in h.lower() else (h or "").strip()
    hh = [f"{int(a):02d}:{b}" for a, b in hores[:2]]
    if hh == ["00:00", "23:59"]:
        return "Tot el dia"
    return " - ".join(hh) if len(hores) > 1 and "/" not in h else " / ".join(hh)


def lloc_curt(lloc):
    lloc = (lloc or "").strip()
    if lloc.lower().startswith("pendent"):
        return "Lloc per confirmar"
    return re.split(r",|\s-\s", lloc)[0].strip()


def nom_net(n):
    n = re.sub(r"\s+-\s+", " · ", n or "(sense nom)")
    n = n.replace('"', "«", 1).replace('"', "»", 1) if n.count('"') >= 2 else n
    return n.strip()


def es_duplicat(a, b):
    """Mateixa activitat entrada dos cops (noms gairebé iguals)."""
    x, y = set(norm(a["nom"])), set(norm(b["nom"]))
    if not x or not y:
        return False
    comuns = len(x & y) / min(len(x), len(y))
    return comuns >= 0.8 or (comuns >= 0.5 and a["min"] == b["min"])


def url_imatge(p):
    """URL del primer fitxer del camp 'Imatge' (enllaços de Drive i tarragona.cat
    convertits a descàrrega directa, com al Publish Scheduler)."""
    v = p["properties"].get("Imatge") or {}
    fitxers = v.get("files") or []
    if not fitxers:
        return None
    f = fitxers[0]
    url = (f.get("external") or f.get("file") or {}).get("url")
    m = re.search(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:[^#]*&)?id=)([\w-]{20,})", url or "")
    if m:
        return f"https://drive.usercontent.google.com/download?id={m.group(1)}&export=view"
    m = re.match(r"(https?://(?:www\.)?tarragona\.cat/.+?)/imatge/?$", url or "")
    return f"{m.group(1)}/@@images/imatge/large" if m else url


def destacades(dia):
    pages = query(DS_ACTIVITATS, {"and": [
        {"property": "Destacada", "checkbox": {"equals": True}},
        {"property": "Aprovada publicació", "checkbox": {"equals": True}},
        {"property": "Data inici", "date": {"equals": dia.isoformat()}},
    ]})
    llocs = {}
    if any(prop(p, "Lloc (fitxa)") for p in pages):
        llocs = {p["id"]: prop(p, "Nom") for p in query(DS_LLOCS)}
    acts = []
    for p in pages:
        rel = prop(p, "Lloc (fitxa)") or []
        lloc = (llocs.get(rel[0]) if rel else None) or prop(p, "Lloc") or ""
        hora = prop(p, "Hora") or ""
        acts.append({
            "nom": nom_net(prop(p, "Name")),
            "hora": hora_neta(hora),
            "min": minuts(hora),
            "lloc": lloc_curt(lloc),
            "preu": preu_curt(prop(p, "Preu (text)"), prop(p, "Preu")),
            "categoria": prop(p, "Categoria") or "",
            "imatge": url_imatge(p),
        })
    acts.sort(key=lambda a: (a["min"], a["nom"]))
    nets = []
    for a in acts:
        if not any(es_duplicat(a, b) for b in nets):
            nets.append(a)
    return nets


# ---------------------------------------------------------------- disseny
def font(path, mida):
    return ImageFont.truetype(path, mida)


def ajusta(draw, text, path, mida, ample, max_linies):
    """Parteix en línies; si no hi cap, redueix la mida."""
    while mida > 30:
        f = font(path, mida)
        linies, actual = [], ""
        for paraula in text.split():
            prova = f"{actual} {paraula}".strip()
            if draw.textlength(prova, font=f) <= ample:
                actual = prova
            else:
                if actual:
                    linies.append(actual)
                actual = paraula
        linies.append(actual)
        if len(linies) <= max_linies and all(draw.textlength(l, font=f) <= ample for l in linies):
            return f, linies
        mida -= 4
    return font(path, 30), [text]


def alt_linia(f, factor=1.05):
    a, d = f.getmetrics()
    return int((a + d) * factor)


def mesura_bloc(draw, a, escala):
    ample = W - 2 * MARGE
    fn, ln = ajusta(draw, a["nom"].upper(), F_ANTON, int(84 * escala), ample, 3)
    fi, li = ajusta(draw, f"{a['hora']} · {a['lloc']}", F_INTER_B, int(44 * escala), ample, 2)
    fp = font(F_INTER_SB, int(38 * escala))
    h = len(ln) * alt_linia(fn, 0.86) + 14 + len(li) * alt_linia(fi) + 8 + alt_linia(fp)
    return h, (fn, ln, fi, li, fp)


def fer_story(dia, acts, i, n):
    img = Image.new("RGB", (W, H), NEGRE)
    d = ImageDraw.Draw(img)

    # Capçalera: logo + RECOMANATS AVUI
    logo = Image.open(LOGO).convert("RGBA").resize((150, 150), Image.LANCZOS)
    img.paste(logo, (MARGE - 10, 40), logo)
    ft = font(F_ANTON, 104)
    d.text((MARGE + 170, 115), "RECOMANATS AVUI", font=ft, fill=BLANC, anchor="lm")

    # Franja groga amb el dia
    y0, y1 = 225, 395
    d.rectangle((MARGE - 20, y0, W - MARGE + 20, y1), fill=GROC)
    dia_txt = f"{DIES[dia.weekday()]} {dia.day} {MESOS[dia.month - 1]}"
    fd, _ = ajusta(d, dia_txt, F_ANTON, 120, W - 2 * MARGE - (110 if n > 1 else 0), 1)
    cx = (W - (90 if n > 1 else 0)) // 2
    d.text((cx, (y0 + y1) // 2), dia_txt, font=fd, fill=NEGRE, anchor="mm")
    if n > 1:
        d.text((W - MARGE, (y0 + y1) // 2), f"{i}/{n}", font=font(F_INTER_B, 48),
               fill=NEGRE, anchor="rm")

    # Activitats (màx. 3): s'ajusten a l'espai disponible
    top, fons = y1 + 60, 1740
    escala = 1.0
    while True:
        blocs = [mesura_bloc(d, a, escala) for a in acts]
        total = sum(b[0] for b in blocs) + 110 * (len(blocs) - 1)
        if total <= fons - top or escala < 0.6:
            break
        escala -= 0.05
    sep = 110 if len(acts) > 1 else 0
    y = top + max(0, (fons - top - total) // 3)
    for k, (a, (alt, (fn, ln, fi, li, fp))) in enumerate(zip(acts, blocs)):
        for l in ln:
            d.text((MARGE, y), l, font=fn, fill=BLANC)
            y += alt_linia(fn, 0.86)
        y += 14
        for l in li:
            d.text((MARGE, y), l, font=fi, fill=GROC)
            y += alt_linia(fi)
        y += 8
        d.text((MARGE, y), a["preu"], font=fp, fill=BLANC)
        y += alt_linia(fp)
        if k < len(acts) - 1:
            ym = y + sep // 2
            d.line((MARGE, ym, W - MARGE, ym), fill=BLANC, width=3)
            y += sep

    # Peu groc
    d.rectangle((0, 1780, W, H), fill=GROC)
    d.text((W // 2, 1850), "TOTA L'AGENDA A @AGENDATGN", font=font(F_ANTON, 76),
           fill=NEGRE, anchor="mm")

    out = BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()



# ------------------------------------------------- story per activitat (estil X)
# Mateix disseny que la imatge dels posts d'X (etiqueta groga de categoria,
# títol en blanc, data en franja groga, logo), però en vertical 1080x1920.
ETIQUETA = {
    "Música": "MÚSICA", "Teatre": "TEATRE", "Exposició": "EXPOSICIONS", "Cinema": "CINEMA",
    "Patrimoni": "PATRIMONI", "Literatura": "LITERATURA", "Familiar": "ACTIVITATS FAMILIARS",
    "Taller": "TALLERS", "Gastronomia": "GASTRONOMIA", "Mercat": "MERCATS",
    "Conferència": "CONFERÈNCIES", "Dansa": "DANSA", "Art": "ART", "Festa popular": "FESTA POPULAR",
}
# Colors de fons que es van alternant (story 1 rosa, 2 blau, 3 negre, 4 rosa...)
COLORS_STORY = [(110, 28, 72), (20, 42, 104), (24, 24, 24)]
DIES_CURTS = ["DL", "DT", "DC", "DJ", "DV", "DS", "DG"]
MESOS_CURTS = ["GEN", "FEB", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OCT", "NOV", "DES"]


def baixa_imatge(url):
    if not url:
        return None
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return Image.open(BytesIO(r.content)).convert("RGB")
    except Exception as e:  # noqa: BLE001
        print(f"  -> Avís: no s'ha pogut baixar la imatge ({e!r}); fons de marca.")
        return None


def story_activitat(dia, a, k=0):
    """Story 1080x1920 d'una activitat recomanada.
    Fons: la mateixa imatge, ampliada, desenfocada i enfosquida. A sobre, el cartell
    sencer (sense retallar) a l'espai lliure de dalt; a sota, etiqueta, títol, data,
    lloc i preu. El text queda fora de les zones que tapa Instagram (dalt i baix)."""
    from PIL import ImageFilter
    foto = baixa_imatge(a.get("imatge"))
    # Fons de color que va alternant (rosa, blau, negre) perquè no siguin totes iguals
    color = COLORS_STORY[k % len(COLORS_STORY)]
    clar = Image.new("RGB", (W, H), color)
    fosc_c = Image.new("RGB", (W, H), tuple(int(v * 0.55) for v in color))
    fons = Image.composite(fosc_c, clar, Image.linear_gradient("L").resize((W, H)))
    c = fons.convert("RGBA")
    d = ImageDraw.Draw(c)
    ample = W - 2 * MARGE

    # 1) Maquetació del text, de baix cap amunt (només mesures)
    peu_y = H - 230                       # per sobre de la barra de resposta d'Instagram
    lloc = f"{a['lloc']} · {a['preu']}" if a.get("lloc") else a["preu"]
    fl, ll = ajusta(d, lloc, F_INTER_B, 44, ample, 2)
    y_lloc = peu_y - 40 - len(ll) * alt_linia(fl)
    hora = a["hora"] if a["hora"] and a["hora"][0].isdigit() else ""
    data_txt = f"{DIES_CURTS[dia.weekday()]} {dia.day} {MESOS_CURTS[dia.month - 1]}"
    data_txt += f" · {hora} H" if hora else ""
    fd = font(F_ANTON, 58)
    y_data = y_lloc - 36 - 92
    ft, lt = ajusta(d, a["nom"].upper(), F_ANTON, 124, ample, 3)
    y_titol = y_data - 34 - len(lt) * alt_linia(ft, 0.92)
    etiqueta = ETIQUETA.get(a.get("categoria"), "")
    y_etiq = y_titol - 86 if etiqueta else y_titol
    text_top = y_etiq - 20

    # 2) Cartell sencer a l'espai lliure de dalt
    zona_top = 230
    zona_h = max(300, text_top - 50 - zona_top)
    if foto:
        cart = foto.copy()
        cart.thumbnail((ample, zona_h), Image.LANCZOS)
        if cart.width < ample * 0.6 and cart.height < zona_h * 0.6:   # imatges petites: amplia
            k = min(ample / cart.width, zona_h / cart.height)
            cart = cart.resize((int(cart.width * k), int(cart.height * k)), Image.LANCZOS)
        x = (W - cart.width) // 2
        y = zona_top + (zona_h - cart.height) // 2
        ombra = Image.new("RGBA", (cart.width + 60, cart.height + 60), (0, 0, 0, 0))
        ImageDraw.Draw(ombra).rectangle((30, 30, cart.width + 30, cart.height + 30), fill=(0, 0, 0, 160))
        c.alpha_composite(ombra.filter(ImageFilter.GaussianBlur(16)), (x - 30, y - 18))
        c.paste(cart, (x, y))
    elif os.path.exists(LOGO):
        m = min(620, zona_h)
        logo = Image.open(LOGO).convert("RGBA").resize((m, m), Image.LANCZOS)
        logo.putalpha(logo.getchannel("A").point(lambda v: v * 0.18))
        c.alpha_composite(logo, ((W - m) // 2, zona_top + (zona_h - m) // 2))

    # 3) Degradat negre des de just sobre el text fins a baix
    grad = Image.new("L", (1, H))
    ini = max(0, text_top - 40)
    for yy in range(H):
        t = min(1.0, max(0.0, (yy - ini) / 200))
        grad.putpixel((0, yy), int(235 * t))
    fosc = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    fosc.putalpha(grad.resize((W, H)))
    c = Image.alpha_composite(c, fosc)
    d = ImageDraw.Draw(c)

    # 4) Capçalera: RECOMANAT AVUI + logo
    if os.path.exists(LOGO):
        logo = Image.open(LOGO).convert("RGBA").resize((130, 130), Image.LANCZOS)
        c.alpha_composite(logo, (W - 130 - MARGE + 10, 50))
    fr = font(F_ANTON, 58)
    tw = d.textlength("RECOMANAT AVUI", font=fr)
    d.rectangle((MARGE, 80, MARGE + tw + 40, 160), fill=GROC)
    d.text((MARGE + 20, 120), "RECOMANAT AVUI", font=fr, fill=NEGRE, anchor="lm")

    # 5) Text
    if etiqueta:
        fe = font(F_ANTON, 46)
        tw = d.textlength(etiqueta, font=fe)
        d.rectangle((MARGE, y_etiq, MARGE + tw + 36, y_etiq + 66), fill=BLANC)
        d.text((MARGE + 18, y_etiq + 33), etiqueta, font=fe, fill=NEGRE, anchor="lm")
    y = y_titol
    for l in lt:
        d.text((MARGE, y), l, font=ft, fill=BLANC)
        y += alt_linia(ft, 0.92)
    tw = d.textlength(data_txt, font=fd)
    d.rectangle((MARGE, y_data, MARGE + tw + 48, y_data + 92), fill=GROC)
    d.text((MARGE + 24, y_data + 46), data_txt, font=fd, fill=NEGRE, anchor="lm")
    y = y_lloc
    for l in ll:
        d.text((MARGE, y), l, font=fl, fill=BLANC)
        y += alt_linia(fl)
    d.line((MARGE, peu_y, W - MARGE, peu_y), fill=GROC, width=3)
    d.text((MARGE, peu_y + 40), "TOTA L'AGENDA A @AGENDATGN", font=font(F_INTER_B, 34),
           fill=BLANC, anchor="lm")

    out = BytesIO()
    c.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()


# ---------------------------------------------------------------- Telegram
def enviar_telegram(imatges, missatge, prefix="recomanats", captions=None):
    if not (TG_TOKEN and TG_CHAT):
        print("Avís: falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID. No s'envia res.")
        return
    api = f"https://api.telegram.org/bot{TG_TOKEN}"
    # Com a document: Telegram no comprimeix la imatge (qualitat per a Instagram)
    for k, png in enumerate(imatges, 1):
        requests.post(f"{api}/sendDocument", timeout=120,
                      data={"chat_id": TG_CHAT,
                            "caption": (captions[k - 1] if captions else f"Story {k}/{len(imatges)}")},
                      files={"document": (f"{prefix}_{k}.png", png, "image/png")}
                      ).raise_for_status()
    requests.post(f"{api}/sendMessage", timeout=30,
                  json={"chat_id": TG_CHAT, "text": missatge}).raise_for_status()


# ---------------------------------------------------------------- main
def stories_activitats(dia, ara, args):
    """Una story per cada activitat recomanada (Destacada) del dia, enviada per
    Telegram. Un cop al dia (clau "stories-act-AAAA-MM-DD"). Les fa el workflow
    "Stories per activitat" a partir de les 7:00; si GitHub s'endarrereix, les
    passades del Publish Scheduler les recuperen fins a les 12:00."""
    clau = f"stories-act-{dia.isoformat()}"
    if not (args.forcar or args.local):
        if not (HORA_ACTIVITATS <= ara.hour < HORA_LIMIT):
            return
        if ja_fet(clau):
            print(f"{clau}: ja enviades.")
            return
    acts = destacades(dia)
    if not acts:
        print(f"Stories per activitat: cap destacada per a {dia}.")
        return
    imatges = [story_activitat(dia, a, k) for k, a in enumerate(acts)]
    if args.local:
        os.makedirs(args.local, exist_ok=True)
        for k, png in enumerate(imatges, 1):
            with open(os.path.join(args.local, f"activitat_{dia}_{k}.png"), "wb") as fh:
                fh.write(png)
        print(f"Desades {len(imatges)} stories per activitat a {args.local}")
        return
    llista = "\n".join(f"• {a['nom']} · {a['hora']} · {a['lloc']}" for a in acts)
    enviar_telegram(imatges, f"📲 Stories per activitat ({len(imatges)} recomanades d'avui).\n\n{llista}",
                    prefix="activitat", captions=[a["nom"][:1000] for a in acts])
    registrar(clau, dia, len(acts), len(imatges), "Stories per activitat\n" + llista)
    print(f"Stories per activitat: {len(imatges)} PNG enviades.")


def fila_canva(clau_canva):
    files = query(DS_REGISTRE, {"property": "Clau", "title": {"equals": clau_canva}})
    if not files:
        return None
    p = files[0]["properties"].get("Text", {}).get("rich_text", [])
    return "".join(x["plain_text"] for x in p).strip() or "(sense enllaços)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", help="AAAA-MM-DD (per defecte, avui)")
    ap.add_argument("--forcar", action="store_true", help="fer els PNG ara, encara que ja s'hagi avisat o fora d'hora")
    ap.add_argument("--local", help="carpeta on desar els PNG (no envia ni registra)")
    ap.add_argument("--nomes-activitats", action="store_true",
                    help="només les stories per activitat (workflow de les 7:00)")
    args = ap.parse_args()

    ara = datetime.now(TZ)
    dia = date.fromisoformat(args.data) if args.data else ara.date()
    clau = f"stories-ig-{dia.isoformat()}"
    pla_b = args.forcar or args.local

    try:
        stories_activitats(dia, ara, args)
    except Exception as e:  # noqa: BLE001 (no atura les de RECOMANATS AVUI)
        print(f"  -> ERROR stories per activitat: {e!r}")
    if args.nomes_activitats:
        return

    if not pla_b:
        if not (HORA_INICI <= ara.hour < HORA_LIMIT):
            print(f"Stories IG: fora d'hora ({ara:%H:%M}).")
            return
        if ja_fet(clau):
            print(f"{clau}: ja avisat.")
            return
        links = fila_canva(f"stories-canva-{dia.isoformat()}")
        if links:
            missatge = ("✅ Ja tens les stories RECOMANATS AVUI fetes a Canva. "
                        "Repassa-les i publica-les a Instagram:\n\n" + links)
            enviar_telegram([], missatge)
            registrar(clau, dia, 0, 0, "Avís Canva enviat\n" + links)
            print("Stories IG: avís de Canva enviat.")
            return
        if (ara.hour, ara.minute) < PLA_B_HORA:
            print("Stories IG: encara no hi ha les de Canva; s'espera.")
            return

    acts = destacades(dia)
    if not acts:
        print(f"Stories IG: cap destacada per a {dia}.")
        return

    # Màxim 3 per story, repartides de manera equilibrada (4 -> 2+2, 5 -> 3+2)
    n = -(-len(acts) // MAX_PER_STORY)
    mida, resta = divmod(len(acts), n)
    grups, i = [], 0
    for k in range(n):
        j = i + mida + (1 if k < resta else 0)
        grups.append(acts[i:j])
        i = j
    imatges = [fer_story(dia, g, i, len(grups)) for i, g in enumerate(grups, 1)]
    llista = "\n".join(f"• {a['nom']} · {a['hora']} · {a['lloc']} · {a['preu']}" for a in acts)
    print(llista)

    if args.local:
        os.makedirs(args.local, exist_ok=True)
        for k, png in enumerate(imatges, 1):
            with open(os.path.join(args.local, f"recomanats_{dia}_{k}.png"), "wb") as fh:
                fh.write(png)
        print(f"Desades {len(imatges)} stories a {args.local}")
        return

    avis = "" if args.forcar else "⚠️ Les de Canva no s'han fet avui. Aquí tens el pla B en PNG.\n\n"
    missatge = (f"{avis}✅ Stories RECOMANATS AVUI "
                f"({len(imatges)} {'story' if len(imatges) == 1 else 'stories'}, "
                f"{len(acts)} activitats).\n\n{llista}")
    enviar_telegram(imatges, missatge)
    registrar(clau, dia, len(acts), len(imatges), llista)
    print(f"Stories IG: {len(imatges)} PNG enviades.")


if __name__ == "__main__":
    main()
