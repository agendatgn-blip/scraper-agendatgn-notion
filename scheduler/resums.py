#!/usr/bin/env python3
"""
AgendaTGN - Resums de destacats
===============================
1. DESTACATS DE LA SETMANA  (dimecres 20:00): activitats amb "Destacada", de dijous a diumenge.
2. DESTACATS DEL CAP DE SETMANA (divendres 8:00): activitats amb "Destacada", de divendres a diumenge.

A X es publica com a fil (1/2, 2/3…) si no hi cap en un tuit. A la Pàgina de
Facebook, en un sol post. I s'envia a Telegram per copiar-lo al grup.
Les dades (nom, lloc, hora) surten de Notion tal qual; la IA només escriu
la frase d'entrada amb la veu d'AgendaTGN (veu_agendatgn.py).
Els posts individuals de cada activitat els continua fent publish_scheduler.py.

Ús:
  python scheduler/resums.py                                   # automàtic segons el dia i l'hora
  python scheduler/resums.py --mode setmana --previsualitzar
  python scheduler/resums.py --mode cap_de_setmana --data 2026-10-09 --previsualitzar
"""
import argparse
import os
import random
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

import veu_agendatgn as veu
from publish_scheduler import (
    generate_template_image, post_to_facebook, send_to_telegram_for_group,
    DIES_SETMANA_CA,
)

TZ = ZoneInfo("Europe/Madrid")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DS_ACTIVITATS = os.environ.get("NOTION_ACTIVITATS_DB_ID")
DS_LLOCS = "bc7d9e22-f18d-4f06-bb83-4bee33e0cd32"
DS_REGISTRE = "d61de192-b46e-4b69-9db1-67f731f5ef9a"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

HORA_SETMANA = 20       # dimecres 20:00
HORA_CAP_SETMANA = 8    # divendres 8:00
LLOCS_EXCLOSOS = ["tarraco arena", "palau firal", "palau de congressos"]

MESOS_CA = ["gener", "febrer", "març", "abril", "maig", "juny", "juliol",
            "agost", "setembre", "octubre", "novembre", "desembre"]

CATEGORIES = [  # ordre i emoji de cada categoria
    ("Música", "🎵"), ("Teatre", "🎭"), ("Dansa", "💃"), ("Cinema", "🎬"),
    ("Festa popular", "🎉"), ("Familiar", "🧸"), ("Exposició", "🖼️"), ("Art", "🎨"),
    ("Literatura", "📚"), ("Conferència", "🎤"), ("Taller", "✂️"), ("Patrimoni", "🏛️"),
    ("Gastronomia", "🍷"), ("Mercat", "🛍️"), ("Altres", "✨"),
]
EMOJI = dict(CATEGORIES)
ORDRE = {c: i for i, (c, _) in enumerate(CATEGORIES)}
LIMIT_X = 270   # marge sota els 280 de X


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


def ja_publicat(clau):
    return bool(query(DS_REGISTRE, {"property": "Clau", "title": {"equals": clau}}))


def registrar(clau, tipus, dia, n_acts, n_parts, text):
    requests.post("https://api.notion.com/v1/pages", headers=_h(), timeout=30, json={
        "parent": {"data_source_id": DS_REGISTRE},
        "properties": {
            "Clau": {"title": [{"text": {"content": clau}}]},
            "Tipus": {"select": {"name": tipus}},
            "Data": {"date": {"start": dia.isoformat()}},
            "Activitats": {"number": n_acts},
            "Parts X": {"number": n_parts},
            "Text": {"rich_text": [{"text": {"content": text[:1900]}}]},
        }}).raise_for_status()


# ---------------------------------------------------------------- dades
def norm(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def activitats_entre(ini, fi, nomes_destacades=False):
    filtres = [
        {"property": "Aprovada publicació", "checkbox": {"equals": True}},
        {"property": "Data inici", "date": {"on_or_after": ini.isoformat()}},
        {"property": "Data inici", "date": {"before": (fi + timedelta(days=1)).isoformat()}},
    ]
    if nomes_destacades:
        filtres.append({"property": "Destacada", "checkbox": {"equals": True}})
    return query(DS_ACTIVITATS, {"and": filtres})


def preparar(pages, llocs, excloure_grans):
    acts = []
    for p in pages:
        rel = prop(p, "Lloc (fitxa)") or []
        lloc = (llocs.get(rel[0]) if rel else None) or prop(p, "Lloc") or ""
        if excloure_grans:
            if prop(p, "Gran esdeveniment"):
                continue
            if any(x in norm(lloc) for x in LLOCS_EXCLOSOS):
                continue
        d = (prop(p, "Data inici") or {}).get("start") or ""
        acts.append({
            "nom": prop(p, "Name") or "(sense nom)",
            "cat": prop(p, "Categoria") if prop(p, "Categoria") in EMOJI else "Altres",
            "lloc": lloc,
            "hora": prop(p, "Hora") or "",
            "municipi": prop(p, "Municipi") or "",
            "dia": date.fromisoformat(d[:10]) if d else None,
            "preu": preu_curt(prop(p, "Preu (text)"), prop(p, "Preu")),
        })
    return acts


def preu_curt(text, num):
    """Criteri AgendaTGN: si no consta preu, és gratuït."""
    if text:
        return text
    try:
        return "Gratuït" if not num else f"{float(num):g} €"
    except (TypeError, ValueError):
        return "Gratuït"


def hora_curta(h):
    m = re.search(r"(\d{1,2})[:.h](\d{2})?", h or "")
    if not m:
        return ""
    hh, mm = int(m.group(1)), int(m.group(2) or 0)
    if hh in (0, 24) and mm == 0:
        return "mitjanit"
    return f"{hh} h" if mm == 0 else f"{hh}.{mm:02d} h"


def minuts(h):
    m = re.search(r"(\d{1,2})[:.h](\d{2})?", h or "")
    if not m:
        return 99 * 60
    hh = int(m.group(1))
    return ((hh + 24) if hh < 6 else hh) * 60 + int(m.group(2) or 0)


def linia(a):
    """Format fitxa (com els posts individuals), dues línies per activitat:
       🎭 Nom de l'acte
       18 h · Espai (Municipi, si no és Tarragona) · Preu"""
    lloc = a["lloc"]
    mun = a.get("municipi", "").strip()
    if mun and "tarragona" not in mun.lower() and mun.lower() not in lloc.lower():
        lloc = f"{lloc} ({mun})" if lloc else mun
    detall = " · ".join(x for x in [hora_curta(a["hora"]), lloc, a.get("preu", "")] if x)
    return f"{EMOJI.get(a['cat'], '✨')} {a['nom']}" + (f"\n{detall}" if detall else "")


def rang_dates(ini, fi):
    """9-12 d'octubre / 30 d'octubre - 2 de novembre."""
    def de(m):
        mes = MESOS_CA[m - 1]
        return f"d'{mes}" if mes[0] in "aeiou" else f"de {mes}"
    if ini.month == fi.month:
        return f"{ini.day}-{fi.day} {de(fi.month)}"
    return f"{ini.day} {de(ini.month)} - {fi.day} {de(fi.month)}"


def nom_dia(d):
    return f"{DIES_SETMANA_CA[d.weekday()]} {d.day}"


# ---------------------------------------------------------------- X: llargada i fils
def x_len(text):
    """Llargada aproximada segons X (emojis i símbols compten doble)."""
    return sum(2 if ord(c) > 0x2FFF else 1 for c in text)


def fer_fil(intro, blocs, limit=LIMIT_X, mesura=None):
    """blocs = [(capçalera, [línies])]. Torna la llista de parts numerades."""
    mesura = mesura or x_len
    tuits, actual = [], intro
    reserva = 7  # espai per a " (1/3)"

    def cap_hi(t):
        return mesura(t) <= limit - reserva

    for cap, linies in blocs:
        bloc = cap + "\n" + "\n".join(linies)
        if cap_hi(actual + "\n\n" + bloc):
            actual += "\n\n" + bloc
            continue
        # no hi cap sencer: comencem tuit nou i, si cal, partim el bloc
        tuits.append(actual)
        actual = cap
        for l in linies:
            if cap_hi(actual + "\n" + l):
                actual += "\n" + l
            else:
                tuits.append(actual)
                actual = f"{cap} (cont.)\n{l}"
    tuits.append(actual)
    tuits = [t.strip() for t in tuits if t.strip()]
    if len(tuits) > 1:
        tuits = [f"{t} ({i}/{len(tuits)})" for i, t in enumerate(tuits, 1)]
    return tuits


def publicar_fil_x(tuits, imatge):
    """Publica el fil a X amb l'API v2 (x_pub). La imatge només al primer tuit."""
    import x_pub
    anterior = None
    for i, t in enumerate(tuits):
        anterior = x_pub.publicar(t, image_bytes=imatge if i == 0 else None, reply_to=anterior)
        if not anterior:
            raise RuntimeError(f"X: fil aturat a la part {i + 1}")
        print(f"  -> X {i + 1}/{len(tuits)} publicat")


def previsualitzar(tuits, fb, fil_threads=None):
    """Envia a Telegram el que es publicaria, sense publicar res."""
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    text = "🔎 PREVISUALITZACIÓ (no s'ha publicat res)\n\n— X —\n\n" + \
           "\n\n———\n\n".join(tuits) + "\n\n— FACEBOOK —\n\n" + fb
    if fil_threads:
        text += "\n\n— THREADS —\n\n" + "\n\n———\n\n".join(fil_threads)
    print(text)
    if tok and chat:
        for i in range(0, len(text), 4000):
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": chat, "text": text[i:i + 4000]}, timeout=30)


# ---------------------------------------------------------------- resums
def resum_destacats(ini, fi, tipus, prev, forcar):
    """tipus = 'setmana' (dj-dg) | 'cap_de_setmana' (dv-dg)"""
    setmana = tipus == "setmana"
    clau = f"{'destacats' if setmana else 'capsetmana'}-{ini.isoformat()}"
    nom_registre = "Destacats setmana" if setmana else "Destacats cap de setmana"
    if not prev and not forcar and ja_publicat(clau):
        print(f"{clau}: ja publicat.")
        return
    llocs = {p["id"]: prop(p, "Nom") for p in query(DS_LLOCS)}
    acts = preparar(activitats_entre(ini, fi, nomes_destacades=True), llocs, excloure_grans=False)
    if not acts:
        print(f"Cap activitat destacada entre {ini} i {fi}.")
        return
    acts.sort(key=lambda a: (a["dia"] or fi, minuts(a["hora"])))
    blocs = []
    d = ini
    while d <= fi:
        del_dia = [a for a in acts if a["dia"] == d]
        if del_dia:
            blocs.append(("📅 " + nom_dia(d).upper(), [linia(a) for a in del_dia]))
        d += timedelta(days=1)

    periode = "aquesta setmana" if setmana else "aquest cap de setmana"
    recents = veu.recents(10)
    resum_plans = "; ".join(f"{a['nom']} ({nom_dia(a['dia']) if a['dia'] else ''})" for a in acts[:8])
    context = (f"Presentem els plans destacats de {periode} a Tarragona "
               f"(de {nom_dia(ini)} a {nom_dia(fi)} de {MESOS_CA[fi.month - 1]}): {resum_plans}.")
    intro = veu.escriure(context + f" Escriu NOMÉS una frase d'entrada curta i informativa per presentar "
                         f"els destacats de {periode}; el títol i la llista d'activitats ja hi són. "
                         "Sense emojis, enllaços ni crida a l'acció.",
                         120, GROQ_API_KEY, textos_recents=recents) \
        or random.choice(["Els destacats d'aquesta setmana:", "Això és el que destaquem aquesta setmana:",
                          "Setmana amb coses. Els destacats:"] if setmana else
                         ["Cap de setmana a Tarragona. El que destaquem:", "Si aquest cap de setmana vols sortir, tens això:",
                          "Destacats del cap de setmana:"])
    capcalera = (f"DESTACATS DE LA SETMANA | {rang_dates(ini, fi)}" if setmana
                 else f"DESTACATS DEL CAP DE SETMANA | {rang_dates(ini, fi)}")
    intro = f"{capcalera}\n\n{intro}"
    cta = veu.triar_cta(recents)

    def amb_cta(parts, limit, mesura):
        if cta and mesura(parts[-1] + "\n\n" + cta) <= limit:
            # la CTA va a l'última part, abans de la numeració
            m = re.match(r"(.*?)( \(\d+/\d+\))?$", parts[-1], re.S)
            parts[-1] = m.group(1) + "\n\n" + cta + (m.group(2) or "")
        return parts

    tuits = amb_cta(fer_fil(intro, blocs), LIMIT_X, x_len)
    fil_threads = amb_cta(fer_fil(intro, blocs, limit=490, mesura=len), 490, len)
    fb = intro + "\n\n" + "\n\n".join(c + "\n" + "\n".join(ls) for c, ls in blocs) + \
        (f"\n\n{cta}" if cta else "")
    titol = (f"Destacats · {ini.day}-{fi.day} {MESOS_CA[fi.month - 1]}" if setmana
             else f"Cap de setmana · {ini.day}-{fi.day} {MESOS_CA[fi.month - 1]}")
    publicar(nom_registre, clau, ini, acts, tuits, fb, titol, "Destacats", prev, fil_threads)


def publicar(tipus, clau, dia, acts, tuits, fb, titol, etiqueta, prev, fil_threads=None):
    print(f"\n{tipus} · {len(acts)} activitats · {len(tuits)} tuit(s)")
    if prev:
        previsualitzar(tuits, fb, fil_threads)
        return
    imatge = generate_template_image(titol, etiqueta)
    try:
        publicar_fil_x(tuits, imatge)
    except Exception as e:  # noqa: BLE001 (un error a X no atura Threads ni Facebook)
        print(f"  -> ERROR X: {e}")
    try:
        import threads_pub
        if fil_threads and threads_pub.configurat():
            threads_pub.publicar_fil(fil_threads)
    except Exception as e:  # noqa: BLE001
        print(f"  -> Avís Threads: {e}")
    post_to_facebook(fb, image_bytes=imatge)
    send_to_telegram_for_group(fb, image_bytes=imatge)
    registrar(clau, tipus, dia, len(acts), len(tuits), "\n\n".join(tuits))
    print("Fet.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["auto", "setmana", "cap_de_setmana"], default="auto")
    ap.add_argument("--data", help="AAAA-MM-DD d'un dia d'aquella setmana (per defecte, avui)")
    ap.add_argument("--previsualitzar", action="store_true",
                    help="No publica: t'ho envia per Telegram per revisar-ho")
    ap.add_argument("--forcar", action="store_true", help="Ignora l'hora i el registre de duplicats")
    a = ap.parse_args()

    for v in ["NOTION_TOKEN", "NOTION_ACTIVITATS_DB_ID", "GROQ_API_KEY"]:
        if not os.environ.get(v):
            sys.exit(f"Falta la variable {v}")

    ara = datetime.now(TZ)
    dia = date.fromisoformat(a.data) if a.data else ara.date()
    mode = a.mode
    if mode == "auto":
        # GitHub executa a dues hores UTC (estiu/hivern); només actuem a l'hora local bona
        if dia.weekday() == 2 and HORA_SETMANA <= ara.hour < HORA_SETMANA + 2:
            mode = "setmana"
        elif dia.weekday() == 4 and HORA_CAP_SETMANA <= ara.hour < HORA_CAP_SETMANA + 2:
            mode = "cap_de_setmana"
        else:
            print(f"{ara:%A %H:%M}: no toca cap resum.")
            return
    # dates a partir del dilluns de la setmana del dia indicat
    dilluns = dia - timedelta(days=dia.weekday())
    if mode == "setmana":
        resum_destacats(dilluns + timedelta(days=3), dilluns + timedelta(days=6), "setmana", a.previsualitzar, a.forcar)
    else:
        resum_destacats(dilluns + timedelta(days=4), dilluns + timedelta(days=6), "cap_de_setmana", a.previsualitzar, a.forcar)


if __name__ == "__main__":
    main()
