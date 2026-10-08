# -*- coding: utf-8 -*-
"""
AgendaTGN · Scraper de l'Agenda de l'Ajuntament de Tarragona
=============================================================
Cada 2 dies (GitHub Actions):
  1. Demana el llistat COMPLET del rang AVUI -> AVUI+30 dies a l'endpoint AJAX
     del cercador (@@portada-events): actes curts, llargs, exposicions i cursos.
     (El cercador HTML només en mostra ~20; la resta va darrere "Consulta'n més".)
  2. Recull les URL dels actes (cada acte té un UID únic a la URL).
  3. Descarta els que ja existeixen a Notion (dedup per UID i per títol+data).
  4. Per cada acte nou, llegeix la fitxa de detall i n'extreu les dades
     directament de l'HTML (sense IA): data, hora, lloc, preu, organitzador,
     imatge, descripció, entrades... Gemini és opcional (IA_AJUNTAMENT=si).
  5. Crea l'entrada a 📥 INBOX AGENDA amb Estat revisió = "Pendent revisar".
  6. Actualitza el log de la font a 🌐 FONTS WEB.

Res no es publica automàticament. Tot queda pendent de revisió humana.
"""

import os
import re
import sys
import json
import time
import datetime as dt
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

import notion_io
import gemini_extract

# ----------------------------------------------------------------------------
# Configuració
# ----------------------------------------------------------------------------
BASE_URL = "https://agenda.tarragona.cat"
SEARCH_ENDPOINT = BASE_URL + "/@@search-events"
FONT_NOM = "Agenda Ajuntament Tarragona"      # ha de coincidir amb l'opció del select "Font" de l'INBOX
DIES_FINESTRA = int(os.environ.get("DIES_FINESTRA", "30"))
MAX_ACTES_PER_RUN = int(os.environ.get("MAX_ACTES_PER_RUN", "150"))
PAUSA_ENTRE_PETICIONS = 1.5   # segons — scraping responsable

HEADERS = {
    "User-Agent": "AgendaTGN-bot/1.0 (+https://instagram.com/agendatgn; seguiment editorial responsable)",
    "Accept-Language": "ca,es;q=0.8",
}

# Endpoint AJAX que fa servir el botó "Consulta'n més" del cercador.
# El cercador (@@search-events) només pinta 8 actes curts + 4 llargs + 4 expos
# + 4 cursos; la resta es carrega per AJAX. Demanant-ho directament amb un
# b_limit alt obtenim TOTS els actes del rang en una sola petició per tipus.
AJAX_ENDPOINT = BASE_URL + "/@@portada-events"
TIPUS_LLISTES = ["curt", "llarg", "expo", "curs"]   # ordre de prioritat
B_LIMIT = 2000
# IA només per reescriure el resum (opcional). La resta de dades surten de la fitxa.
USA_IA = os.environ.get("IA_AJUNTAMENT", "no").lower() in ("si", "sí", "1", "true", "yes")
INCLOU_CURSOS = os.environ.get("INCLOU_CURSOS", "si").lower() in ("si", "sí", "1", "true", "yes")

MESOS = {"gen": 1, "febr": 2, "feb": 2, "març": 3, "mar": 3, "abr": 4, "maig": 5,
         "juny": 6, "jun": 6, "jul": 7, "ag": 8, "ago": 8, "set": 9, "oct": 10,
         "nov": 11, "des": 12, "dic": 12}

# Formats de data per al pla B (cercador HTML clàssic)
FORMATS_DATA = ["%Y-%m-%d", "%d/%m/%Y"]


def log(msg):
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ----------------------------------------------------------------------------
# 1. Cerca: llistat complet via AJAX
# ----------------------------------------------------------------------------
def _uid_de(href):
    return parse_qs(urlparse(href).query).get("UID", [None])[0]


def _es_enllac_acte(href):
    """Només fitxes de l'agenda (exclou els enllaços de compartir a FB/X/WA)."""
    p = urlparse(href)
    return p.netloc.endswith("agenda.tarragona.cat") and "/agenda/" in p.path and "UID=" in href


def _txt_despres_etiqueta(node):
    """'On: Espai Jove Kesse' -> 'Espai Jove Kesse'."""
    if not node:
        return ""
    t = node.get_text(" ", strip=True)
    return re.sub(r"^[^:]{1,20}:\s*", "", t).strip()


def _dia_mes_a_data(txt, referencia):
    """'22 juny' -> date, deduint l'any (a prop de la data de referència)."""
    m = re.match(r"(\d{1,2})\s+([a-zç]+)", (txt or "").strip().lower())
    if not m:
        return None
    mes = MESOS.get(m.group(2)) or MESOS.get(m.group(2)[:3])
    if not mes:
        return None
    any_ = referencia.year
    try:
        d = dt.date(any_, mes, int(m.group(1)))
    except ValueError:
        return None
    # Si queda a més de 6 mesos de distància, és de l'any anterior/següent
    if (d - referencia).days > 183:
        d = d.replace(year=any_ - 1)
    elif (referencia - d).days > 183:
        d = d.replace(year=any_ + 1)
    return d


def parse_llistat(html, tipus, avui):
    """Parseja el HTML del llistat AJAX. Retorna [ {uid, url, titol, data, ...} ]."""
    soup = BeautifulSoup(html, "html.parser")
    zona = soup.select_one(f".reload-zone-{tipus}") or soup
    actes = []
    for art in zona.find_all("article"):
        a = art.select_one(".event-title a[href]") or next(
            (x for x in art.find_all("a", href=True) if _es_enllac_acte(urljoin(BASE_URL, x["href"]))), None)
        if not a:
            continue
        url = urljoin(BASE_URL, a["href"]).split("#")[0]
        uid = _uid_de(url)
        if not uid or not _es_enllac_acte(url):
            continue

        info = {"uid": uid, "url": url, "tipus": tipus,
                "titol": a.get_text(" ", strip=True),
                "lloc": _txt_despres_etiqueta(art.select_one(".event-location")),
                "cicle": _txt_despres_etiqueta(art.select_one(".event-cicle")),
                "categoria_web": (art.select_one(".event-categoria").get_text(" ", strip=True)
                                  if art.select_one(".event-categoria") else ""),
                "data": None, "data_fi": None, "hora": ""}

        # Data concreta ("Quan: 06/10/2026")
        quan = _txt_despres_etiqueta(art.select_one(".event-date"))
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", quan)
        if m:
            info["data"] = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))

        # Hores (actes curts) o rang de dates (llargs, expos, cursos)
        hores = art.select(".eventItem__time__hour span")
        if hores:
            info["hora"] = "-".join(h.get_text(strip=True) for h in hores if h.get_text(strip=True))
        rang = [s.get_text(strip=True) for s in art.select(".eventItem__time__date span")]
        if rang:
            ini = _dia_mes_a_data(rang[0], avui)
            fi = _dia_mes_a_data(rang[-1], avui) if len(rang) > 1 else None
            if ini and fi and fi < ini:
                fi = fi.replace(year=fi.year + 1)
            info["data"] = info["data"] or ini
            info["data_fi"] = fi
        actes.append(info)
    return actes


def _llista_tipus(session, tipus, data_inici, data_fi):
    params = {
        "template": "search-events.pt", "event_type": tipus,
        "b_start": 0, "b_size": B_LIMIT, "b_limit": B_LIMIT,
        "category": "", "cicle": "", "ubicacio": "All",
        "start_date": data_inici.isoformat(), "end_date": data_fi.isoformat(),
        "expo": "true" if tipus == "expo" else "false",
        "curs": "true" if tipus == "curs" else "false",
    }
    r = session.get(AJAX_ENDPOINT, params=params, timeout=90)
    r.raise_for_status()
    return parse_llistat(r.text, tipus, data_inici)


def _cerca_html_clasic(session, data_inici, data_fi):
    """Pla B: cercador HTML (només primera tanda) i portada."""
    for fmt in FORMATS_DATA:
        params = {"start_date": data_inici.strftime(fmt), "end_date": data_fi.strftime(fmt),
                  "category": "", "cicle": "", "ubicacio": "All", "searchableText": ""}
        try:
            r = session.get(SEARCH_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()
        except requests.RequestException as e:
            log(f"  Pla B: error de xarxa ({fmt}): {e}")
            continue
        actes = []
        for tipus in TIPUS_LLISTES:
            actes += parse_llistat(r.text, tipus, data_inici)
        if actes:
            return actes
        time.sleep(PAUSA_ENTRE_PETICIONS)
    return []


def cerca_actes(data_inici, data_fi):
    """Retorna ({uid: info}, mètode). info inclou url + dades bàsiques del llistat."""
    session = requests.Session()
    session.headers.update(HEADERS)
    actes, errors = {}, []

    tipus_a_llegir = [t for t in TIPUS_LLISTES if INCLOU_CURSOS or t != "curs"]
    for tipus in tipus_a_llegir:
        try:
            llista = _llista_tipus(session, tipus, data_inici, data_fi)
        except requests.RequestException as e:
            errors.append(tipus)
            log(f"  Error AJAX ({tipus}): {e}")
            continue
        nous = 0
        for info in llista:
            if info["uid"] not in actes:      # 1a aparició = data més propera
                actes[info["uid"]] = info
                nous += 1
        log(f"  Llista '{tipus}': {len(llista)} files, {nous} actes únics nous")
        time.sleep(PAUSA_ENTRE_PETICIONS)

    if actes:
        metode = "AJAX @@portada-events" + (f" (errors: {', '.join(errors)})" if errors else "")
        return actes, metode

    log("  L'AJAX no ha retornat actes. Pla B: cercador HTML clàssic.")
    llista = _cerca_html_clasic(session, data_inici, data_fi)
    actes = {}
    for info in llista:
        actes.setdefault(info["uid"], info)
    return actes, "cercador HTML (fallback — REVISAR ESTRUCTURA AJAX)"


# ----------------------------------------------------------------------------
# 2. Fitxa de detall d'un acte
# ----------------------------------------------------------------------------
def _seccions_lateral(article):
    """{'Preu': (text, [(text_enllac, url)]), ...} a partir dels h3 del lateral."""
    seccions = {}
    for h3 in article.select("h3.asideEvent__title"):
        etiqueta = h3.get_text(" ", strip=True).rstrip(":").strip()
        textos, enllacos, items = [], [], []
        for sib in h3.find_next_siblings():
            if sib.name == "h3":
                break
            t = sib.get_text(" ", strip=True)
            if t:
                textos.append(t)
            items += [li.get_text(" ", strip=True) for li in sib.find_all("li")]
            for a in sib.find_all("a", href=True):
                enllacos.append((a.get_text(" ", strip=True), urljoin(BASE_URL, a["href"])))
        seccions[etiqueta] = (" · ".join(textos), enllacos, items)
    return seccions


def _data_hora_fitxa(txt):
    """'Inici: 07-10-2026, 20:00 Fi: 09-10-2026, 21:00' -> (date_ini, hora, date_fi)."""
    trobades = re.findall(r"(\d{2})-(\d{2})-(\d{4})(?:,\s*(\d{1,2}:\d{2}))?", txt or "")
    if not trobades:
        return None, "", None
    d, m, a, h = trobades[0]
    ini = dt.date(int(a), int(m), int(d))
    fi = None
    if len(trobades) > 1:
        d2, m2, a2, _ = trobades[-1]
        fi = dt.date(int(a2), int(m2), int(d2))
        if fi <= ini:
            fi = None
    return ini, h or "", fi


def llegeix_fitxa(url):
    """Llegeix la fitxa d'un acte i en treu les dades estructurades (sense IA)."""
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    art = soup.select_one("article.esdeveniment") or soup.find(id="content") or soup.body
    for tag in art(["script", "style", "iframe"]):
        tag.decompose()

    sec = _seccions_lateral(art)
    get = lambda k: sec.get(k, ("", [], []))

    # Descripció (columna principal)
    cos = art.select_one(".asideEvent .text") or art.select_one(".asideEvent")
    descripcio = cos.get_text("\n", strip=True) if cos else ""
    enllacos_desc = []
    if cos:
        for a in cos.find_all("a", href=True):
            enllacos_desc.append((a.get_text(" ", strip=True), urljoin(BASE_URL, a["href"])))

    # Imatge: la gran del cos; si no, og:image
    imatge = None
    img = art.select_one("figure img[src]")
    if img:
        imatge = urljoin(BASE_URL, img["src"])
    else:
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            imatge = og["content"]

    ini, hora, fi = _data_hora_fitxa(get("Quan")[0])
    entrades_txt, entrades_links, _ = get("Venda d'entrades / Inscripcions")
    titol_tag = art.find("h2")
    return {
        "titol": titol_tag.get_text(" ", strip=True) if titol_tag else "",
        "data": ini, "data_fi": fi, "hora": hora,
        "lloc": get("Localització")[0],
        "preu": get("Preu")[0],
        "organitzador": get("Organitzat per")[0],
        "collabora": get("Hi col·labora")[0],
        "programacio": get("Programació")[0],
        "que": get("Què")[2],
        "entrades_text": entrades_txt,
        "entrades_links": [u for _, u in entrades_links],
        "enllacos_desc": enllacos_desc,
        "descripcio": descripcio,
        "imatge": imatge,
        "text_pla": (art.get_text("\n", strip=True) if art else "")[:8000],
    }


def enllac_entrades_fitxa(fitxa):
    """Enllaç de compra/inscripció de la fitxa: el del bloc 'Venda d'entrades /
    Inscripcions' i, si no n'hi ha, un de la descripció que sigui d'una plataforma de venda."""
    for u in fitxa.get("entrades_links") or []:
        if u.startswith("http"):
            return u
    import imatges
    for text, u in fitxa.get("enllacos_desc") or []:
        if imatges._DOMINIS_ENTRADES.search(u) or imatges._TEXT_ENTRADES.search(text or ""):
            return u
    return None


# ----------------------------------------------------------------------------
# 3. Utilitats de dates i dedup
# ----------------------------------------------------------------------------
def normalitza_titol(t):
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def parse_data_iso(valor):
    """Converteix una data de Gemini (dd/mm/aaaa o ISO) a ISO. None si no es pot."""
    if not valor or "pendent" in valor.lower():
        return None
    valor = valor.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(valor[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ----------------------------------------------------------------------------
# Programa principal
# ----------------------------------------------------------------------------
CATEGORIES_WEB = {   # categoria de l'Ajuntament -> select "Categoria suggerida"
    "Música": "Música", "Teatre": "Teatre", "Exposicions": "Exposició", "Cinema": "Cinema",
    "Patrimoni i història": "Patrimoni", "Lletres": "Literatura",
    "Activitats familiars": "Familiar", "Cursos i tallers": "Taller",
    "Gastronomia": "Gastronomia", "Fires i mercats": "Mercat",
    "Xerrades i congressos": "Conferència", "Dansa": "Dansa", "Art": "Art",
    "Cultura popular i festes": "Festa popular",
}


def dades_del_llistat(info):
    """Dades mínimes a partir del llistat (quan Gemini no està disponible)."""
    pendent = "pendent de revisar"
    return {
        "titol": info.get("titol") or pendent,
        "data": info["data"].strftime("%d/%m/%Y") if info.get("data") else pendent,
        "data_fi_iso": info["data_fi"].isoformat() if info.get("data_fi") else None,
        "hora": info.get("hora") or pendent,
        "lloc": info.get("lloc") or pendent,
        "organitzador": pendent, "preu": pendent,
        "categoria": CATEGORIES_WEB.get(info.get("categoria_web", ""), "pendent de revisar"),
        "resum_agendatgn": "",
        "confianca_ia": "Baixa",
    }


def _es_quota(e):
    t = str(e).lower()
    return any(k in t for k in ("429", "resource_exhausted", "quota", "rate limit"))


def processa_ajuntament(mode_test):
    avui = dt.date.today()
    fi = avui + dt.timedelta(days=DIES_FINESTRA)
    log(f"=== Font: {FONT_NOM} · Finestra: {avui.isoformat()} -> {fi.isoformat()}")

    # --- Cerca ---
    actes, metode = cerca_actes(avui, fi)
    log(f"Mètode: {metode} · Actes candidats: {len(actes)}")

    if not actes:
        notion_io.actualitza_font(
            FONT_NOM, estat="Error",
            resultat=f"Run {avui.isoformat()}: 0 actes trobats ({metode}). Revisar la web.",
        )
        return

    # --- Dedup contra Notion ---
    existents = notion_io.entrades_existents(FONT_NOM)
    uids_existents = existents["uids"]
    claus_existents = existents["titol_data"]
    log(f"Entrades ja existents a INBOX d'aquesta font: {len(uids_existents)} UIDs")

    nous = [info for uid, info in actes.items() if uid not in uids_existents]
    # Prioritat: actes curts > llargs > expos > cursos, i dins de cada tipus, data més propera
    ordre_tipus = {t: i for i, t in enumerate(TIPUS_LLISTES)}
    nous.sort(key=lambda x: (ordre_tipus.get(x["tipus"], 9), x.get("data") or fi))
    log(f"Actes nous (per UID): {len(nous)} · en processarem fins a {MAX_ACTES_PER_RUN}")

    if mode_test:
        log("MODE TEST: no s'escriurà res a Notion. Llista d'actes nous:")
        for info in nous[:MAX_ACTES_PER_RUN]:
            log(f"  NOU [{info['tipus']}] {info.get('data')} · {info['titol']} · {info.get('lloc')}")
        return

    # --- Processament ---
    creats, duplicats_tou, errors, sense_fitxa, amb_ia = 0, 0, 0, 0, 0
    gemini_ok = USA_IA
    for info in nous[:MAX_ACTES_PER_RUN]:
        url = info["url"]
        time.sleep(PAUSA_ENTRE_PETICIONS)
        try:
            dades = dades_del_llistat(info)
            dades["model_ia"] = None
            extres = []

            # 1. Fitxa de detall (dades estructurades, sense IA)
            fitxa = None
            try:
                fitxa = llegeix_fitxa(url)
            except Exception as e:
                sense_fitxa += 1
                log(f"  Avís: no s'ha pogut llegir la fitxa {url}: {e} -> dades del llistat")

            if fitxa:
                if fitxa["titol"]:
                    dades["titol"] = fitxa["titol"]
                if fitxa["data"]:
                    dades["data"] = fitxa["data"].strftime("%d/%m/%Y")
                if fitxa["data_fi"]:
                    dades["data_fi_iso"] = fitxa["data_fi"].isoformat()
                for camp in ("hora", "lloc", "preu", "organitzador"):
                    if fitxa.get(camp):
                        dades[camp] = fitxa[camp]
                for q in fitxa["que"]:
                    if q in CATEGORIES_WEB:
                        dades["categoria"] = CATEGORIES_WEB[q]
                        break
                dades["resum_agendatgn"] = fitxa["descripcio"]
                dades["imatge"] = fitxa["imatge"]
                dades["confianca_ia"] = "Alta"
                dades["programa"] = fitxa["programacio"] or info.get("cicle") or ""
                entrades_url = enllac_entrades_fitxa(fitxa)
                if entrades_url:
                    dades["url_entrades"] = entrades_url
                if fitxa["entrades_links"] or fitxa["entrades_text"]:
                    extres.append("Entrades/Inscripcions: " + " ".join(
                        [fitxa["entrades_text"]] + fitxa["entrades_links"]).strip())
                mes_info = [u for t, u in fitxa["enllacos_desc"] if "tarragona.cat" not in u]
                if mes_info:
                    extres.append("Enllaços: " + " ".join(mes_info[:3]))
                if fitxa["collabora"]:
                    extres.append(f"Hi col·labora: {fitxa['collabora']}")
                if len(fitxa["que"]) > 1:
                    extres.append("Categories web: " + ", ".join(fitxa["que"]))

                # 2. (Opcional) resum curt amb IA
                if gemini_ok:
                    try:
                        ia = gemini_extract.extreu(fitxa["text_pla"], url)
                        if ia.get("resum_agendatgn"):
                            dades["resum_agendatgn"] = ia["resum_agendatgn"]
                            dades["model_ia"] = "Gemini"
                            amb_ia += 1
                    except Exception as e:
                        if _es_quota(e):
                            gemini_ok = False
                            log("  Quota de Gemini esgotada: continuem sense IA.")
                        else:
                            log(f"  Avís Gemini amb {url}: {e}")
            else:
                dades["programa"] = info.get("cicle") or ""

            data_iso = parse_data_iso(dades.get("data"))
            clau = (normalitza_titol(dades.get("titol")), data_iso or "")
            notes = f"Nova (run automàtic {avui.isoformat()})."
            if not fitxa:
                notes += " Creada només amb dades del llistat: revisar fitxa."
            if clau in claus_existents:
                notes = ("Possible duplicat — pendent de revisar "
                         f"(coincideix títol+data amb una entrada existent). Run {avui.isoformat()}.")
                duplicats_tou += 1
            if extres:
                notes += "\n" + "\n".join(extres)

            notion_io.crea_entrada_inbox(
                dades=dades, url=url, data_iso=data_iso,
                imatge_url=dades.get("imatge"), font=FONT_NOM, notes=notes,
            )
            claus_existents.add(clau)
            creats += 1
            log(f"  CREAT: {dades.get('titol') or url}")
        except Exception as e:
            errors += 1
            log(f"  ERROR amb {url}: {e}")

    # --- Log de la font ---
    pendents = max(0, len(nous) - MAX_ACTES_PER_RUN)
    resum = (f"Run {avui.isoformat()}: {len(actes)} actes al cercador, "
             f"{len(nous)} nous, {creats} entrades creades ({sense_fitxa} sense fitxa, {amb_ia} amb resum IA), "
             f"{duplicats_tou} possibles duplicats, {errors} errors, "
             f"{pendents} pendents pel proper run. Mètode: {metode}.")
    estat = "OK" if errors == 0 and "fallback" not in metode else "Revisar estructura"
    notion_io.actualitza_font(FONT_NOM, estat=estat, resultat=resum)
    log(resum)


def processa_fonts_generiques(mode_test):
    """Resta de fonts actives de 🌐 FONTS WEB (MNAT, CaixaForum, Turisme...)."""
    import generic_source
    try:
        fonts = notion_io.fonts_actives()
    except Exception as e:
        log(f"ERROR llegint FONTS WEB: {e}")
        return
    for font in fonts:
        if font["nom"] == FONT_NOM:
            continue  # l'Ajuntament té el seu mòdul propi (cercador amb UID)
        try:
            generic_source.processa_font(font, mode_test=mode_test)
        except Exception as e:
            log(f"ERROR inesperat amb la font {font['nom']}: {e}")
        time.sleep(PAUSA_ENTRE_PETICIONS)


def main():
    mode_test = "--test" in sys.argv
    if mode_test:
        log("MODE TEST activat: no s'escriurà res a Notion.")

    # 1. Agenda Ajuntament (mòdul dedicat: cercador amb dates + UID únic)
    try:
        processa_ajuntament(mode_test)
    except Exception as e:
        log(f"ERROR inesperat amb {FONT_NOM}: {e}")

    # 2. Resta de fonts actives de 🌐 FONTS WEB (mòdul genèric amb Gemini)
    processa_fonts_generiques(mode_test)

    log("Run completat.")


if __name__ == "__main__":
    main()
