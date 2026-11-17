"""NOTÍCIES CULTURALS TGN · 1 · Captura.

Llegeix les fonts, descarta sense IA el que no és cultura i les repetides, la IA puntua la resta
i crea a Notion les bones amb l'estat «Nova». A la primera captura del matí envia el top 5 per Telegram.
Execució: python -m noticies.captura
"""
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import feedparser
import requests

from .comu import UA, ara_local, neteja_html, norm, notion_create, notion_query, rich, tg_text, title, txt
from .config import (CATEGORIES, CULTURA, EXCLOURE, FEEDS, HORES_ENRERE, MAX_NOTICIES, NOTION_URL,
                     PAGINES, PUNTUACIO_MINIMA, TEMPS_MAX_CAPTURA)
from .ia import SenseIA, json_ia

INICI = time.time()
ARA = datetime.now(timezone.utc)

SISTEMA = """Ets l'editor de notícies culturals d'@agendatgn, l'agenda cultural no oficial de Tarragona.
Valores notícies per publicar-les a Instagram per a gent de Tarragona i rodalia (Camp de Tarragona).
Només interessa la CULTURA: concerts, festivals, teatre, dansa, cinema, museus, exposicions, patrimoni,
llibres, festes populars i tradicionals, espais culturals que obren o tanquen, programacions, entrades a la venda.
NO interessa: política, partits, eleccions, plens, successos, accidents, judicis, esports, economia general,
obituaris (excepte si és una figura cultural local), ni notícies d'altres territoris sense relació amb Tarragona.
Respon NOMÉS amb un objecte JSON."""

USUARI = """Valora aquesta notícia i respon amb aquest JSON:
{{"cultural": true/false, "tarragona": true/false, "categoria": una de {cats},
 "puntuacio": enter 0-5 (interès per a Instagram: útil, proper, sorprenent, amb data o novetat; 0 si no és cultura de Tarragona),
 "resum": "dues frases en català, reescrites, sense inventar res"}}

MITJÀ: {mitja}
TITULAR: {titol}
EXTRACTE: {extracte}"""


def _te(text, paraules, prefix):
    for p in paraules:
        p = norm(p)
        if not p:
            continue
        patro = r"\b" + re.escape(p) + (r"" if prefix else r"\b")
        if re.search(patro, text):
            return True
    return False


def passa_filtre(titol, extracte, es_cultural):
    t = norm(f"{titol} {extracte}")
    cultura = _te(t, CULTURA, prefix=True)
    if _te(t, EXCLOURE, prefix=False) and not cultura:
        return False
    return cultura or es_cultural


def _feed(url, mitja, es_cultural):
    try:
        raw = requests.get(url, timeout=25, headers=UA).content
        feed = feedparser.parse(raw)
    except Exception as e:  # noqa: BLE001
        print("Font fallada:", mitja, url[:80], e)
        return []
    out = []
    for e in feed.entries:
        titol, link = (e.get("title") or "").strip(), e.get("link") or ""
        if not titol or not link:
            continue
        font = mitja
        if "news.google.com" in link:
            m = re.match(r"^(.*) - ([^-]+)$", titol)
            if m:
                titol, font = m.group(1).strip(), m.group(2).strip()
        t = e.get("published_parsed") or e.get("updated_parsed")
        data = datetime(*t[:6], tzinfo=timezone.utc) if t else ARA
        if ARA - data > timedelta(hours=HORES_ENRERE):
            continue
        out.append(dict(titol=titol, link=link, mitja=mitja, font=font, data=data,
                        extracte=neteja_html(e.get("summary", ""))[:600], es_cultural=es_cultural))
    print(f"  {mitja}: {len(out)} recents")
    return out


def _html_llistat(url):
    """HTML del llistat: primer directe; si falla i hi ha Firecrawl, amb Firecrawl."""
    import os
    try:
        r = requests.get(url, timeout=25, headers=UA)
        if r.ok and len(r.text) > 2000:
            return r.text, "directe"
    except requests.RequestException:
        pass
    clau = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if not clau:
        return "", ""
    try:
        r = requests.post("https://api.firecrawl.dev/v1/scrape", timeout=60,
                          headers={"Authorization": f"Bearer {clau}"},
                          json={"url": url, "formats": ["html"], "onlyMainContent": True})
        if r.ok:
            return (r.json().get("data") or {}).get("html", ""), "firecrawl"
        print("  Firecrawl:", r.status_code, r.text[:150])
    except requests.RequestException as e:
        print("  Firecrawl:", e)
    return "", ""


def _pagina(url, tros, mitja):
    html, via = _html_llistat(url)
    if not html:
        print(f"  {mitja}: no s'ha pogut llegir {url}")
        return []
    out, vistos = [], set()
    for href, cos in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.S | re.I):
        link = urljoin(url, href)
        titol = neteja_html(cos)
        if tros not in link or link.rstrip("/") == url.rstrip("/") or len(titol) < 25 or link in vistos:
            continue
        vistos.add(link)
        out.append(dict(titol=titol, link=link, mitja=mitja, font=mitja, data=ARA, extracte="",
                        es_cultural=True, sense_data=True))
    print(f"  {mitja} ({via}): {len(out)} enllaços")
    return out[:10]


def main():
    print("== Captura de notícies culturals ==")
    recents = notion_query({"page_size": 100, "filter": {"timestamp": "created_time", "created_time": {
        "on_or_after": (ARA - timedelta(days=30)).isoformat()}}})
    ja_links = {txt(p, "Enllaç") for p in recents}
    ja_titols = {norm(txt(p, "Títol")) for p in recents}
    print(f"{len(recents)} notícies dels últims 30 dies a Notion")

    candidates = []
    for url, mitja, es_cultural in FEEDS:
        candidates += _feed(url, mitja, es_cultural)
    for url, tros, mitja in PAGINES:
        candidates += _pagina(url, tros, mitja)

    noves, vistos = [], set()
    for n in candidates:
        clau = norm(n["titol"])
        if clau in vistos or clau in ja_titols or n["link"] in ja_links:
            continue
        vistos.add(clau)
        if not passa_filtre(n["titol"], n["extracte"], n["es_cultural"]):
            continue
        noves.append(n)
    noves.sort(key=lambda n: (n.get("sense_data", False), -n["data"].timestamp()))
    print(f"{len(noves)} candidates després del filtre sense IA")
    if len(noves) > MAX_NOTICIES:
        print(f"Només en valoro {MAX_NOTICIES}")
        noves = noves[:MAX_NOTICIES]

    creades = 0
    for i, n in enumerate(noves, 1):
        if time.time() - INICI > TEMPS_MAX_CAPTURA:
            print("Temps màxim superat; la resta, a la pròxima captura.")
            break
        print(f"[{i}/{len(noves)}] {n['mitja']} · {n['titol'][:90]}")
        try:
            ia, model = json_ia(SISTEMA, USUARI.format(cats=CATEGORIES, **n), max_tokens=500)
        except SenseIA as e:
            print("Cap IA disponible, plego:", e)
            tg_text(f"⚠️ Notícies culturals: cap IA respon ({str(e)[:200]}). Valorades {i - 1}/{len(noves)}, creades {creades}.")
            break
        punts = int(ia.get("puntuacio") or 0)
        if not ia.get("cultural") or not ia.get("tarragona") or punts < PUNTUACIO_MINIMA:
            print(f"   descartada ({punts})")
            continue
        props = {
            "Títol": title(n["titol"]),
            "Enllaç": {"url": n["link"]},
            "Mitjà": {"select": {"name": n["mitja"]}},
            "Resum": rich(ia.get("resum")),
            "Puntuació": {"number": punts},
            "Estat": {"select": {"name": "Nova"}},
            "Model IA": rich(model),
        }
        if not n.get("sense_data"):
            props["Data"] = {"date": {"start": n["data"].isoformat()}}
        if n["font"] != n["mitja"]:
            props["Notes"] = rich(f"Mitjà original: {n['font']}")
        if ia.get("categoria") in CATEGORIES:
            props["Categoria"] = {"select": {"name": ia["categoria"]}}
        try:
            notion_create(props)
            creades += 1
            print(f"   ✓ a Notion ({punts}/5)")
        except RuntimeError as e:
            print("   Notion:", e)
    print(f"{creades} notícies noves a Notion")

    if ara_local().hour < 11:
        avis_mati()


def avis_mati():
    des_de = (ARA - timedelta(hours=30)).isoformat()
    r = notion_query({"page_size": 5, "filter": {"and": [
        {"property": "Estat", "select": {"equals": "Nova"}},
        {"timestamp": "created_time", "created_time": {"on_or_after": des_de}}]},
        "sorts": [{"property": "Puntuació", "direction": "descending"}]}, maxim=5)
    if not r:
        tg_text("📰 Notícies culturals: avui no n'ha entrat cap de nova.")
        return
    linies = [f"{i}. {txt(p, 'Títol')}\n   {txt(p, 'Mitjà')} · {'⭐' * int(txt(p, 'Puntuació') or 0)}"
              for i, p in enumerate(r[:5], 1)]
    tg_text("📰 Notícies culturals · top del dia\n\n" + "\n\n".join(linies) +
            f"\n\nMarca «Escollida» les que vulguis publicar:\n{NOTION_URL}")


if __name__ == "__main__":
    main()
