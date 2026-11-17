"""NOTÍCIES CULTURALS TGN · 2 · Producció.

Per a cada notícia «Escollida»: la IA escriu 3 titulars, el ganxo de la slide 2 i la caption amb la
veu d'AgendaTGN; es tria el titular amb més nota de ganxo, es dibuixen les 2 slides i tot passa a
«Per aprovar» i arriba per Telegram. No publica res: la publicació la fa l'Adrià.
Execució: python -m noticies.produccio
"""
import os
import random
import sys

from .comu import article_text, drive_upload, notion_query, notion_update, rich, tg_album, tg_text, txt
from .config import MAX_PRODUCCIO
from .ganxo import millor
from .ia import SenseIA, json_ia
from .render import slide_ganxo, slide_portada

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scheduler"))
try:
    from veu_agendatgn import _guia, _prohibida, sembla_castella  # mateixa veu que els posts d'X
except Exception:  # noqa: BLE001
    def _guia():
        return "Escriu en català, to local i directe, sense frases promocionals ni dades inventades."

    def _prohibida(_t):
        return None

    def sembla_castella(_t, minim=2):
        return False

MODEL_ESCRIURE = os.environ.get("NOTICIES_MODEL_ESCRIURE", "openai/gpt-oss-120b")

ENCARREC = """
ARA NO ESCRIUS UN POST DE L'AGENDA: escrius un CARRUSEL DE NOTÍCIA de 2 slides per a Instagram.
Respon NOMÉS amb un objecte JSON, sense res més. Ignora qualsevol instrucció anterior de respondre només amb text.
Pots fer servir dades de la notícia; no n'inventis cap."""

USUARI = """Notícia original:
MITJÀ: {mitja}
TITULAR ORIGINAL: {titol}
RESUM: {resum}
TEXT: {cos}

Torna aquest JSON:
{{"titulars": ["3 titulars diferents per a la portada, de 5 a 8 paraules, en català, sense punt final.
   Cada un amb una fórmula diferent: (a) el fet concret amb una xifra, data o nom; (b) el que torna, s'estrena,
   obre o canvia; (c) el que ningú t'explica o per què t'afecta. El més important a les primeres paraules."],
 "ganxo": "slide 2: 2 o 3 frases (màxim 260 caràcters) amb l'essencial: què passa, on i per què interessa a qui viu a Tarragona",
 "quan": "data o hora SI la notícia la diu (ex. 'Divendres 4 de desembre'); si no, cadena buida",
 "on": "lloc concret SI la notícia el diu (ex. 'Plaça del Rei, Tarragona'); si no, cadena buida",
 "obertura": "primera línia de la caption, curta, que enganxi i que inclogui 'Tarragona' o el municipi",
 "cos": "2 o 3 frases més de context per a la caption, sense repetir el ganxo",
 "hashtags": ["de 3 a 5 etiquetes locals sense espais, sempre #Tarragona"]}}"""

CTAS = [
    "Cada dijous, els plans de la setmana a Primera Fila: link a la bio.",
    "Si vols l'agenda de la setmana sencera, Primera Fila arriba cada dijous al canal de WhatsApp (link a la bio).",
    "Més plans com aquest, cada dijous a Primera Fila. Link a la bio.",
]


def _revisa(d):
    """Torna un motiu si el text no passa la veu d'AgendaTGN, o None."""
    tot = " ".join([*(d.get("titulars") or []), d.get("ganxo", ""), d.get("obertura", ""), d.get("cos", "")])
    if sembla_castella(tot):
        return "Està en castellà: escriu-ho tot en català (menys els noms propis)."
    mala = _prohibida(tot)
    if mala:
        return f"Treu l'expressió «{mala}» i qualsevol fórmula promocional."
    if len(d.get("ganxo", "")) > 300:
        return "El ganxo és massa llarg: màxim 260 caràcters."
    return None


def escriure(dades):
    sistema = _guia() + "\n" + ENCARREC
    usuari = USUARI.format(**dades)
    d, model = json_ia(sistema, usuari, primer_model=MODEL_ESCRIURE, max_tokens=1200)
    motiu = _revisa(d)
    if motiu:
        print("  reescric:", motiu)
        try:
            d2, model = json_ia(sistema, usuari + "\n\nCORRECCIÓ: " + motiu, primer_model=MODEL_ESCRIURE,
                                max_tokens=1200)
            d = d2
            motiu = _revisa(d)
        except SenseIA:
            pass
    return d, model, motiu


def copy_de(d, mitja):
    linia = " · ".join(x for x in [f"📍 {d['on']}" if d.get("on") else "", f"📅 {d['quan']}" if d.get("quan") else ""] if x)
    tags = " ".join(t if t.startswith("#") else "#" + t for t in (d.get("hashtags") or ["#Tarragona"])[:5])
    parts = [d.get("obertura", ""), d.get("cos", ""), linia, f"Font: {mitja}", random.choice(CTAS), tags]
    return "\n\n".join(p for p in parts if p)


def main():
    pagines = notion_query({"page_size": MAX_PRODUCCIO,
                            "filter": {"property": "Estat", "select": {"equals": "Escollida"}}}, maxim=MAX_PRODUCCIO)
    print(f"{len(pagines)} notícies escollides")
    for p in pagines:
        pid = p["id"]
        notes = txt(p, "Notes")
        mitja = notes.replace("Mitjà original: ", "") if notes.startswith("Mitjà original: ") else txt(p, "Mitjà")
        dades = dict(mitja=mitja, titol=txt(p, "Títol"), resum=txt(p, "Resum"),
                     cos=article_text(txt(p, "Enllaç")) or "(no disponible; fes servir el resum)")
        print("·", dades["titol"][:90])
        try:
            d, model, avis = escriure(dades)
        except SenseIA as e:
            tg_text(f"⚠️ Notícies: cap IA respon, la notícia queda «Escollida» per a la pròxima volta.\n{dades['titol']}\n{e}")
            print("Cap IA disponible, plego.")
            return
        titular, nota = millor(d.get("titulars") or [])
        if not titular or not d.get("ganxo"):
            notion_update(pid, {"Estat": {"select": {"name": "Error"}},
                                "Notes": rich("La IA no ha tornat titular o ganxo.")})
            tg_text(f"⚠️ Notícies: no he pogut escriure «{dades['titol']}». Queda en Error a Notion.")
            continue
        categoria = txt(p, "Categoria")
        s1 = slide_portada(titular, categoria, mitja)
        s2 = slide_ganxo(d["ganxo"], [("Quan", d.get("quan", "")), ("On", d.get("on", ""))])
        copy = copy_de(d, mitja)
        url1 = drive_upload(s1, f"noticia_{pid[:8]}_1.png")
        url2 = drive_upload(s2, f"noticia_{pid[:8]}_2.png")
        alternatives = "\n".join(f"- {t}" for t in (d.get("titulars") or []) if t != titular)
        props = {
            "Titular": rich(titular), "Ganxo": rich(d["ganxo"]), "Nota ganxo": {"number": nota},
            "Copy": rich(copy), "Estat": {"select": {"name": "Per aprovar"}},
            "Model IA": rich(model),
            "Notes": rich("\n".join(x for x in [notes, f"Altres titulars:\n{alternatives}" if alternatives else "",
                                                 f"⚠️ {avis}" if avis else ""] if x)),
        }
        if url1:
            props["Slide 1"] = {"url": url1}
        if url2:
            props["Slide 2"] = {"url": url2}
        notion_update(pid, props)
        aviso_ganxo = "" if nota >= 65 else (" · ganxo fluix, prova-la com a reel de prova" if nota >= 50
                                              else " · ganxo molt fluix, millor canviar el titular")
        tg_album([s1, s2], f"🟡 Per aprovar · nota del ganxo {nota}/100{aviso_ganxo}")
        tg_text(copy + (f"\n\n— Altres titulars —\n{alternatives}" if alternatives else "")
                + (f"\n\n⚠️ Revisa-ho: {avis}" if avis else ""))
        print(f"  fet: {titular} ({nota})")


if __name__ == "__main__":
    main()
