"""Validació sense IA de la resposta del model i càlcul de la confiança final
i de l'"Estat revisió" de 📥 INBOX AGENDA.

Regla d'or: el validador mai posa "Validada". Només ajuda a prioritzar la
revisió humana.
"""

import re
import unicodedata
from datetime import date, timedelta

from .esquema import CATEGORIES, CONFIANCES, ESQUEMA_CARTELL

ORDRE_CONFIANCA = {"Baixa": 0, "Mitjana": 1, "Alta": 2}

MESOS = {
    1: ["gener", "enero", "gen", "ene", "jan"],
    2: ["febrer", "febrero", "feb"],
    3: ["marc", "marzo", "mar"],
    4: ["abril", "abr"],
    5: ["maig", "mayo", "may"],
    6: ["juny", "junio", "jun"],
    7: ["juliol", "julio", "jul"],
    8: ["agost", "agosto", "ago"],
    9: ["setembre", "septiembre", "setiembre", "set", "sep"],
    10: ["octubre", "oct"],
    11: ["novembre", "noviembre", "nov"],
    12: ["desembre", "diciembre", "des", "dic"],
}

PARAULES_BUIDES = {
    "el", "la", "els", "les", "de", "del", "dels", "i", "y", "a", "al", "en", "amb",
    "con", "per", "por", "un", "una", "los", "las", "the", "d", "l",
}


class RespostaInvalida(Exception):
    """La resposta no compleix l'esquema (es tracta com un error de format)."""


# ---------------------------------------------------------------------------
# Utilitats de text
# ---------------------------------------------------------------------------
def normalitza_text(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("·", "").replace("'", " ").replace("’", " ")
    text = re.sub(r"[^a-z0-9:/.\-\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _paraules(text):
    return [p for p in re.split(r"[\s:/.\-]+", normalitza_text(text))
            if len(p) > 2 and p not in PARAULES_BUIDES]


def proporcio_paraules(frase, text):
    """Quina part de les paraules de `frase` apareix a `text` (0-1)."""
    paraules = _paraules(frase)
    if not paraules:
        return 1.0
    conjunt = set(_paraules(text))
    return sum(1 for p in paraules if p in conjunt) / len(paraules)


def data_apareix(iso, text):
    """True si el dia i el mes de la data surten al text (número o nom del mes)."""
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return False
    t = normalitza_text(text)
    if not re.search(rf"(?<!\d)0?{d.day}(?!\d)", t):
        return False
    if re.search(rf"(?<!\d)0?{d.day}\s*[/.\-]\s*0?{d.month}(?!\d)", t):
        return True
    paraules = set(re.findall(r"[a-z]+", t))
    return any(m in paraules for m in MESOS[d.month])


# ---------------------------------------------------------------------------
# 1. Esquema
# ---------------------------------------------------------------------------
def comprova_esquema(dades):
    """Comprovació mínima de l'esquema (sense dependències externes).
    Omple amb valors per defecte el que és opcional i llança RespostaInvalida
    si falta l'essencial."""
    if not isinstance(dades, dict):
        raise RespostaInvalida("La resposta no és un objecte JSON")

    if not isinstance(dades.get("text_visible"), str):
        raise RespostaInvalida("Falta text_visible")

    net = {}
    props = ESQUEMA_CARTELL["properties"]
    for camp, definicio in props.items():
        valor = dades.get(camp)
        tipus = definicio.get("type")
        if tipus == ["string", "null"]:
            if valor is not None and not isinstance(valor, str):
                valor = str(valor)
            net[camp] = (valor or "").strip() or None
        elif tipus == "string":
            net[camp] = valor.strip() if isinstance(valor, str) else ""
        elif tipus == "boolean":
            net[camp] = bool(valor)
        elif tipus == "array":
            net[camp] = [str(x).strip() for x in valor if str(x).strip()] if isinstance(valor, list) else []
        elif tipus == "object":
            net[camp] = valor if isinstance(valor, dict) else None
    return net


# ---------------------------------------------------------------------------
# 2. Validació de contingut
# ---------------------------------------------------------------------------
def _seguent_aniversari(d, avui):
    """La propera vegada que cau aquest dia/mes a partir d'ahir."""
    for any_ in (avui.year, avui.year + 1):
        try:
            candidat = d.replace(year=any_)
        except ValueError:  # 29 de febrer
            continue
        if candidat >= avui - timedelta(days=1):
            return candidat
    return d


def valida(dades, avui=None, duplicat=False):
    """Retorna (dades_netes, problemes, confianca_final, estat_revisio).

    `dades` ha de venir de comprova_esquema(). `duplicat` el calcula qui crida
    (consulta a Notion)."""
    avui = avui or date.today()
    d = dict(dades)
    problemes = []           # es mostren a "Notes revisió"
    revisar_data = False
    revisar_lloc = False
    confianca = "Alta"

    def baixa_a(nivell):
        nonlocal confianca
        if ORDRE_CONFIANCA[nivell] < ORDRE_CONFIANCA[confianca]:
            confianca = nivell

    text = d.get("text_visible") or ""
    if len(text.strip()) < 15:
        problemes.append("Gairebé no s'ha llegit text a la imatge")
        baixa_a("Baixa")

    # --- Títol
    if not d.get("titol"):
        problemes.append("Sense títol")
        baixa_a("Baixa")
    elif proporcio_paraules(d["titol"], text) < 0.6:
        problemes.append("El títol no surt literalment al cartell (pot ser interpretat)")
        baixa_a("Mitjana")

    # --- Data
    inici = fi = None
    if not d.get("data_inici"):
        problemes.append("Sense data")
        revisar_data = True
        baixa_a("Baixa")
    else:
        try:
            inici = date.fromisoformat(d["data_inici"])
        except ValueError:
            problemes.append(f"Data no vàlida: {d['data_inici']}")
            d["data_inici"] = None
            revisar_data = True
            baixa_a("Baixa")

    if inici and not d.get("any_explicit"):
        corregida = _seguent_aniversari(inici, avui)
        if corregida != inici:
            desplacament = corregida.year - inici.year
            inici = corregida
            d["data_inici"] = inici.isoformat()
            if d.get("data_fi"):
                try:
                    f = date.fromisoformat(d["data_fi"])
                    d["data_fi"] = f.replace(year=f.year + desplacament).isoformat()
                except ValueError:
                    pass

    if inici:
        if inici < avui - timedelta(days=1):
            problemes.append(f"La data {inici.isoformat()} ja ha passat")
            revisar_data = True
            baixa_a("Baixa")
        elif inici > avui + timedelta(days=548):
            problemes.append(f"La data {inici.isoformat()} és a més de 18 mesos")
            revisar_data = True
            baixa_a("Baixa")
        elif not data_apareix(d["data_inici"], text):
            problemes.append("La data no surt clarament al text del cartell")
            revisar_data = True
            baixa_a("Mitjana")

    if d.get("data_fi"):
        try:
            fi = date.fromisoformat(d["data_fi"])
            if inici and fi < inici:
                problemes.append("La data final és anterior a l'inicial")
                d["data_fi"] = None
                revisar_data = True
                baixa_a("Mitjana")
            elif inici and fi == inici:
                d["data_fi"] = None
        except ValueError:
            d["data_fi"] = None

    # --- Hora
    if d.get("hora"):
        hores = [h.strip() for h in re.split(r"\s*(?:/|,|;|\bi\b|\by\b)\s*", d["hora"]) if h.strip()]
        valides = []
        for h in hores:
            m = re.fullmatch(r"(\d{1,2})[:.h](\d{2})?h?", h.replace(" ", ""))
            if m and int(m.group(1)) < 24 and int(m.group(2) or 0) < 60:
                valides.append(f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}")
        if valides:
            d["hora"] = " / ".join(valides)
        else:
            problemes.append(f"Hora amb format estrany: {d['hora']}")
            baixa_a("Mitjana")
    else:
        problemes.append("Sense hora")
        baixa_a("Mitjana")

    # --- Lloc
    if not d.get("lloc"):
        problemes.append("Sense lloc")
        revisar_lloc = True
        baixa_a("Mitjana")
    elif proporcio_paraules(d["lloc"], text) < 0.5:
        problemes.append("El lloc no surt literalment al cartell")
        revisar_lloc = True
        baixa_a("Mitjana")

    # --- Categoria
    if d.get("categoria") not in CATEGORIES:
        problemes.append(f"Categoria fora de llista ({d.get('categoria')!r}) → Altres")
        d["categoria"] = "Altres"
        baixa_a("Mitjana")

    # --- Confiança final = la més baixa entre model i validador
    model = d.get("confianca") if d.get("confianca") in CONFIANCES else "Baixa"
    final = model if ORDRE_CONFIANCA[model] < ORDRE_CONFIANCA[confianca] else confianca
    d["confianca"] = final

    # --- Estat revisió (mai "Validada")
    if duplicat:
        estat = "Duplicada"
    elif revisar_data:
        estat = "Revisar data"
    elif revisar_lloc:
        estat = "Revisar lloc"
    else:
        estat = "Pendent revisar"

    return d, problemes, final, estat


def notes_revisio(problemes, dubtes, confianca, model_etiqueta):
    linies = []
    if confianca == "Alta" and not problemes:
        linies.append("✅ Confiança alta: dades clares i trobades al cartell")
    for p in problemes:
        linies.append(f"⚠️ {p}")
    for dub in dubtes or []:
        linies.append(f"❓ {dub}")
    linies.append(f"🤖 {model_etiqueta}")
    return "\n".join(linies)
