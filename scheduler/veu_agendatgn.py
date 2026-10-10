"""
VEU D'AGENDATGN
===============
El to de tots els posts automàtics (individuals i resums) surt d'aquí.

✏️  Per ajustar-lo, edita a GitHub (llapis ✏️):
  - guia_to.md         -> la guia d'estil completa
  - FRASES_PROHIBIDES  -> expressions que no han de sortir mai
  - CTAS               -> crides a l'acció (s'alternen i no es repeteixen)
"""

import json
import os
import random
import re

import requests

MODEL = "openai/gpt-oss-120b"   # gratuït a Groq
PROBABILITAT_CTA = 0.65         # ~65% dels posts porten CTA
DS_REGISTRE = "d61de192-b46e-4b69-9db1-67f731f5ef9a"
GUIA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guia_to.md")

FRASES_PROHIBIDES = [
    "no et perdis", "no t'ho perdis", "no te'l perdis", "no te la perdis", "no t'ho pots perdre",
    "imprescindible", "experiència única", "experiència inoblidable", "s'omple de",
    "jornada plena de", "per a tots els gustos", "plans per a tothom", "descobreix", "gaudeix",
    "submergeix-te", "viu una experiència", "marca-ho al calendari", "pren nota", "t'ho perdràs",
    "preparat per", "a punt per", "combinació perfecta", "proposta ideal", "sens dubte",
    "i molt més", "el millor de", "oportunitat única", "per a tots els públics",
    "posa en valor", "iniciativa que busca", "cita que promet", "vetllada màgica",
    "ambient únic", "inoblidable", "subscriu-te ara", "no et quedis fora", "uneix-te ja",
    "fes clic", "accedeix en exclusiva", "forma part de la nostra comunitat",
    "última oportunitat", "no esperis més", "avui et proposem", "agendatgn.cat", "http",
]

CTAS = [
    "L'agenda sencera la passem per Primera Fila, al canal de WhatsApp. Link a la bio.",
    "Vols l'agenda completa? Primera Fila és al canal de WhatsApp. Link a la bio.",
    "Primera Fila + agenda no oficial de Tarragona → canal de WhatsApp, link a la bio.",
    "Per tenir-ho tot ordenat: Primera Fila, al canal de WhatsApp.",
    "L'agenda d'aquesta setmana la tens a Primera Fila. Link a la bio.",
    "Si vols tenir l'agenda a mà, la passem pel canal de WhatsApp.",
    "Primera Fila ja és al canal de WhatsApp.",
    "Agenda no oficial de Tarragona + Primera Fila → link a la bio.",
    "Tot això i la resta de l'agenda, a Primera Fila.",
    "L'agenda sencera, al canal de WhatsApp.",
]


def _guia():
    try:
        with open(GUIA_PATH, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return "Escriu en català, to local i directe, sense frases promocionals ni dades inventades."


# ---------------------------------------------------------------- sempre en català
# Paraules que només són castellà (no existeixen en català). Serveixen per detectar
# si la IA ha escrit en castellà perquè les dades originals ho eren.
_MARQUES_CASTELLA = re.compile(
    r"\b(y|con|los|las|para|pero|muy|este|esta|estos|estas|sus|desde|hasta|también|"
    r"como|donde|cuando|hay|será|sobre todo|nuevo|nueva|año|años|niños|entrada libre|"
    r"gratuito|gratuita|concierto|exposición|espectáculo|fiesta)\b|ción\b|ciones\b|ñ",
    re.I)


def sembla_castella(text, minim=2):
    """True si el text té pinta de ser en castellà."""
    return len(_MARQUES_CASTELLA.findall(text or "")) >= minim


def en_catala(textos, groq_api_key):
    """Tradueix al català una llista de noms/títols d'activitat (els que ja ho són
    tornen igual). Una sola crida a la IA per a tota la llista. Si falla, torna els
    originals: mai atura la publicació."""
    textos = [t or "" for t in textos]
    if not any(t.strip() for t in textos) or not groq_api_key:
        return textos
    try:
        from groq import Groq
        client = Groq(api_key=groq_api_key)
        instruccio = (
            "Tradueix al català aquests noms d'activitats culturals. Regles:\n"
            "- Si un nom ja és en català, torna'l exactament igual.\n"
            "- Tradueix les paraules genèriques (concierto→concert, exposición→exposició, "
            "taller, fiesta→festa, ruta, visita guiada, jornadas→jornades, etc.).\n"
            "- NO tradueixis noms propis: persones, grups, companyies, marques, espais, "
            "ni el títol concret d'una obra (llibre, pel·lícula, cançó, espectacle) si va entre cometes "
            "o és clarament un títol.\n"
            "- Mantén majúscules, cometes, emojis i signes com a l'original. No afegeixis res.\n"
            "Respon NOMÉS amb un JSON: una llista de strings, en el mateix ordre i la mateixa quantitat.\n\n"
            + json.dumps(textos, ensure_ascii=False))
        r = client.chat.completions.create(model=MODEL, max_tokens=1500, reasoning_effort="low",
                                           messages=[{"role": "user", "content": instruccio}])
        cru = (r.choices[0].message.content or "").strip()
        cru = re.sub(r"^```(?:json)?|```$", "", cru).strip()
        sortida = json.loads(cru)
        if not isinstance(sortida, list) or len(sortida) != len(textos):
            raise ValueError("resposta amb mida diferent")
        out = []
        for orig, nou in zip(textos, sortida):
            nou = str(nou or "").strip()
            # si la traducció és buida o massa diferent de llargada, ens quedem l'original
            ok = nou and "\n" not in nou and len(nou) <= max(2 * len(orig), len(orig) + 20)
            out.append(nou if ok else orig)
        return out
    except Exception as e:  # noqa: BLE001
        print(f"  -> Avís: no s'han pogut traduir els noms al català ({e})")
        return textos


def _prohibida(text):
    t = text.lower().replace("’", "'")
    return next((f for f in FRASES_PROHIBIDES if f in t), None)


# ---------------------------------------------------------------- memòria de publicacions
def _notion_h():
    return {"Authorization": f"Bearer {os.environ.get('NOTION_TOKEN')}",
            "Notion-Version": "2025-09-03", "Content-Type": "application/json"}


def recents(n=10):
    """Textos de les últimes publicacions (del 🧾 REGISTRE RESUMS)."""
    try:
        r = requests.post(f"https://api.notion.com/v1/data_sources/{DS_REGISTRE}/query",
                          headers=_notion_h(), timeout=30,
                          json={"page_size": n, "sorts": [{"timestamp": "created_time", "direction": "descending"}]})
        r.raise_for_status()
        out = []
        for p in r.json()["results"]:
            t = "".join(x["plain_text"] for x in p["properties"]["Text"]["rich_text"]).strip()
            if t:
                out.append(t)
        return out
    except Exception as e:  # noqa: BLE001
        print(f"  -> Avís: no s'han pogut llegir les publicacions recents ({e})")
        return []


def registrar_post(text, tipus="Post individual", dia=None, clau=None):
    """Desa el text publicat perquè la IA no el repeteixi."""
    try:
        props = {
            "Clau": {"title": [{"text": {"content": clau or f"post-{tipus.lower().replace(' ', '-')}"}}]},
            "Tipus": {"select": {"name": tipus}},
            "Text": {"rich_text": [{"text": {"content": text[:1900]}}]},
        }
        if dia:
            props["Data"] = {"date": {"start": dia}}
        requests.post("https://api.notion.com/v1/pages", headers=_notion_h(), timeout=30,
                      json={"parent": {"data_source_id": DS_REGISTRE}, "properties": props}).raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"  -> Avís: no s'ha pogut registrar el post ({e})")


def triar_cta(textos_recents, forcar=False):
    """Torna una CTA (~65% de les vegades) que no s'hagi fet servir recentment, o None."""
    if not forcar and random.random() > PROBABILITAT_CTA:
        return None
    usades = " ".join(textos_recents[:6])
    lliures = [c for c in CTAS if c not in usades] or CTAS
    return random.choice(lliures)


# ---------------------------------------------------------------- escriure amb IA
def escriure(instruccio, max_chars, groq_api_key, textos_recents=None, intents=3):
    """Demana un text a la IA amb la veu d'AgendaTGN. Torna None si no ho aconsegueix."""
    try:
        from groq import Groq
        client = Groq(api_key=groq_api_key)
    except Exception as e:  # noqa: BLE001
        print(f"  -> Avís IA (no disponible): {e}")
        return None
    sistema = _guia()
    if textos_recents:
        sistema += ("\n\nPUBLICACIONS RECENTS (no en repeteixis l'inici, l'estructura, les bromes ni les frases):\n" +
                    "\n---\n".join(t[:400] for t in textos_recents[:10]))
    missatges = [{"role": "system", "content": sistema},
                 {"role": "user", "content": instruccio + f"\n\nLlargada màxima: {max_chars} caràcters."}]
    for _ in range(intents):
        try:
            r = client.chat.completions.create(model=MODEL, messages=missatges,
                                               max_tokens=600, reasoning_effort="low")
            text = (r.choices[0].message.content or "").strip().strip('"«»').strip()
        except Exception as e:  # noqa: BLE001
            print(f"  -> Avís IA: {e}")
            continue
        text = re.sub(r"\n{3,}", "\n\n", text)
        if not text:
            continue
        if sembla_castella(text):
            missatges += [{"role": "assistant", "content": text},
                          {"role": "user", "content": "Això és en castellà. Escriu-ho en català "
                           "(tradueix-ho tot menys els noms propis)."}]
            continue
        mala = _prohibida(text)
        if mala:
            missatges += [{"role": "assistant", "content": text},
                          {"role": "user", "content": f"Reescriu-lo sense «{mala}» i sense cap fórmula promocional."}]
            continue
        if len(text) > max_chars:
            missatges += [{"role": "assistant", "content": text},
                          {"role": "user", "content": f"És massa llarg. Deixa'l en menys de {max_chars} caràcters."}]
            continue
        return text
    return None
