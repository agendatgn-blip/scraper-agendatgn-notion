# -*- coding: utf-8 -*-
"""
Busca la imatge principal d'una pàgina d'activitat (sense IA, gratis).

Ordre de preferència:
  1. og:image / twitter:image (la que la mateixa web tria per compartir)
  2. <link rel="image_src">
  3. La primera imatge "gran" del contingut (descartant logos, icones, svg...)

Es comprova que la URL respon com a imatge real abans de donar-la per bona.
Si no es troba res, torna None i l'entrada queda amb "Imatge pendent" marcat
(les xarxes ja fan servir la imatge tipus de marca com a últim recurs).
"""

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "AgendaTGN-bot/1.0 (+https://instagram.com/agendatgn; seguiment editorial responsable)",
    "Accept-Language": "ca,es;q=0.8",
}

# Paraules que gairebé sempre indiquen una imatge que NO és el cartell
_DESCARTA = re.compile(
    r"logo|icon|icona|favicon|sprite|avatar|banner-cookies|placeholder|"
    r"default|no-image|noimage|blank|pixel|spacer|loading|social|share|"
    r"facebook|twitter|instagram|whatsapp|youtube|tiktok|flag|bandera|"
    r"escut|segell|generalitat|ministerio|feder|next-generation",
    re.I,
)
_EXT_OK = re.compile(r"\.(jpe?g|png|webp|gif)(\?|$)", re.I)
MIDA_MINIMA = 8_000          # bytes: per sota, segur que és una icona
AMPLADA_MINIMA = 250         # px, si l'HTML ho declara


def _sembla_dolenta(url):
    if not url or url.startswith("data:"):
        return True
    nom = url.lower().split("?")[0]
    if nom.endswith(".svg") or nom.endswith(".ico"):
        return True
    return bool(_DESCARTA.search(nom.rsplit("/", 1)[-1]))


def es_imatge_valida(url, timeout=15):
    """Comprova que la URL torna una imatge (no una pàgina d'error) i no és minúscula."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
        if not r.ok:
            return False
        tipus = r.headers.get("Content-Type", "").lower()
        if not tipus.startswith("image/") or "svg" in tipus:
            return False
        mida = r.headers.get("Content-Length")
        if mida and mida.isdigit():
            return int(mida) >= MIDA_MINIMA
        # Sense Content-Length: llegim fins al mínim
        llegit = 0
        for tros in r.iter_content(4096):
            llegit += len(tros)
            if llegit >= MIDA_MINIMA:
                return True
        return False
    except requests.RequestException:
        return False
    finally:
        try:
            r.close()
        except Exception:
            pass


def _candidates(soup, base):
    vistos = []

    def afegeix(u):
        if u:
            u = urljoin(base, u.strip())
            if u not in vistos and not _sembla_dolenta(u):
                vistos.append(u)

    # 1. Metadades de compartir
    for attr, val in (("property", "og:image"), ("property", "og:image:url"),
                      ("property", "og:image:secure_url"),
                      ("name", "twitter:image"), ("name", "twitter:image:src")):
        for m in soup.find_all("meta", attrs={attr: val}):
            afegeix(m.get("content"))
    # 2. link image_src
    for l in soup.find_all("link", rel=lambda v: v and "image_src" in v):
        afegeix(l.get("href"))

    # 3. Imatges del contingut (main / article / #content)
    cos = soup.find("article") or soup.find("main") or soup.find(id="content") or soup.body
    if cos:
        for tag in cos(["header", "footer", "nav", "aside"]):
            tag.decompose()
        for img in cos.find_all("img"):
            src = (img.get("data-src") or img.get("data-lazy-src") or img.get("src") or "")
            if not src and img.get("srcset"):
                src = img["srcset"].split(",")[-1].strip().split(" ")[0]
            w = img.get("width") or ""
            if w.isdigit() and int(w) < AMPLADA_MINIMA:
                continue
            if src and (_EXT_OK.search(src) or re.search(r"/(image|imatge|images|imatges|uploads|media)", src, re.I)):
                afegeix(src)
    return vistos


def imatge_de_pagina(url, html=None, max_proves=4):
    """Torna la URL de la imatge principal de la pàgina o None."""
    if not url:
        return None
    try:
        if html is None:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            html = r.text
    except requests.RequestException:
        return None
    soup = BeautifulSoup(html, "html.parser")
    for cand in _candidates(soup, url)[:max_proves]:
        if es_imatge_valida(cand):
            return cand
    return None


# ----------------------------------------------------------------------------
# Enllaç d'entrades / inscripcions
# ----------------------------------------------------------------------------
# Plataformes de venda conegudes: si n'hi ha un enllaç, és gairebé segur el bo
_DOMINIS_ENTRADES = re.compile(
    r"entradium|eventbrite|ticketmaster|janto|koobin|ticketea|atrapalo|codetickets|"
    r"giglon|wegow|dice\.fm|seetickets|tiquetsbcn|enterticket|entradas\.com|"
    r"compralaentrada|taquilla|ticketing|tickets?\.|entrades\.|reserves?\.|"
    r"proticketing|ataquilla|oneboxtds|fever|clicketing",
    re.I,
)
_TEXT_ENTRADES = re.compile(
    r"entrad|ticket|tiquet|compra|comprar|venda|reserv|inscri|taquilla|butaca",
    re.I,
)
_HREF_NO = re.compile(r"^(mailto:|tel:|javascript:|#)|facebook\.com/sharer|twitter\.com/share|"
                      r"api\.whatsapp|wa\.me/|/login|/cistella|/cart", re.I)


def enllac_entrades(html, url):
    """Torna l'enllaç per comprar entrades / inscriure's que surt a la pàgina, o None.
    Prioritza plataformes de venda conegudes; si no, un enllaç amb text tipus 'Entrades'."""
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    cos = soup.find("article") or soup.find("main") or soup.find(id="content") or soup.body
    if not cos:
        return None
    for tag in cos(["header", "footer", "nav"]):
        tag.decompose()
    per_domini, per_text = None, None
    for a in cos.find_all("a", href=True):
        href = a["href"].strip()
        if _HREF_NO.search(href):
            continue
        absolut = urljoin(url, href)
        if absolut.split("#")[0] == url.split("#")[0]:
            continue
        text = " ".join([a.get_text(" ", strip=True), a.get("title") or "", a.get("aria-label") or ""])
        if not per_domini and _DOMINIS_ENTRADES.search(absolut):
            per_domini = absolut
        if not per_text and _TEXT_ENTRADES.search(text):
            per_text = absolut
    return per_domini or per_text


def analitza_pagina(url):
    """Una sola descàrrega: torna (imatge, enllaç d'entrades) de la pàgina de l'activitat."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except requests.RequestException:
        return None, None
    return imatge_de_pagina(url, html=r.text), enllac_entrades(r.text, url)
