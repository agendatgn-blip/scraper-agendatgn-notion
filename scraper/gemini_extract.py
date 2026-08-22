# -*- coding: utf-8 -*-
"""Extracció estructurada amb Gemini. Regla central: NO INVENTAR DADES."""

import os
import json
import re

from google import genai

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

_client = genai.Client(api_key=GEMINI_API_KEY)

PROMPT = """Analitza el text següent, extret de la fitxa d'un acte de l'agenda \
cultural de l'Ajuntament de Tarragona, i extreu informació per crear una entrada \
a la base de dades 📥 INBOX AGENDA de Notion.

REGLES ESTRICTES:
- No inventis cap dada. Si una dada no apareix clarament al text, escriu exactament "pendent de revisar".
- Aplica-ho a: data, hora, lloc, preu, organitzador, categoria.
- "data" en format dd/mm/aaaa. Si l'acte té un rang de dates, "data" és l'inici i "data_fi" el final (dd/mm/aaaa); si no, "data_fi" ha de ser "".
- "categoria" ha de ser exactament una d'aquestes o "pendent de revisar": Música, Teatre, Exposició, Cinema, Patrimoni, Literatura, Familiar, Taller, Gastronomia, Mercat, Conferència, Dansa, Art, Festa popular, Altres.
- "resum_agendatgn": 1-2 frases neutres i informatives en català basades NOMÉS en el text.
- "dubtes": qualsevol ambigüitat o dada que caldria confirmar. "" si no n'hi ha.
- Criteri de "confianca_ia": Alta = títol, data, hora i lloc clars; Mitjana = falta algun camp important; Baixa = text confús o insuficient.

Retorna NOMÉS JSON vàlid, sense markdown ni cap text fora del JSON, amb aquests camps:
{"titol": "", "data": "", "data_fi": "", "hora": "", "lloc": "", "organitzador": "",
 "preu": "", "categoria": "", "text_visible": "", "resum_agendatgn": "", "dubtes": "",
 "confianca_ia": "Alta | Mitjana | Baixa"}

URL de la fitxa: {URL}

TEXT DE LA FITXA:
{TEXT}
"""


def _neteja_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    inici, fi = text.find("{"), text.rfind("}")
    if inici >= 0 and fi > inici:
        text = text[inici:fi + 1]
    return text


def extreu(text_fitxa, url):
    prompt = PROMPT.replace("{URL}", url).replace("{TEXT}", text_fitxa)
    resposta = _client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    dades = json.loads(_neteja_json(resposta.text))

    # Sanejament defensiu
    if dades.get("confianca_ia") not in ("Alta", "Mitjana", "Baixa"):
        dades["confianca_ia"] = "Baixa"
    for camp in ("titol", "data", "hora", "lloc", "organitzador", "preu"):
        if not (dades.get(camp) or "").strip():
            dades[camp] = "pendent de revisar"

    # data_fi en ISO per a Notion (rangs d'exposicions, cicles...)
    fi = (dades.get("data_fi") or "").strip()
    dades["data_fi_iso"] = None
    if fi and "pendent" not in fi.lower():
        import datetime as dt
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                dades["data_fi_iso"] = dt.datetime.strptime(fi[:10], fmt).date().isoformat()
                break
            except ValueError:
                continue

    dades["text_visible"] = (dades.get("text_visible") or text_fitxa[:1500])
    return dades


# -----------------------------------------------------------------------------
# Extracció de LLISTES d'activitats (fonts genèriques: MNAT, CaixaForum, etc.)
# -----------------------------------------------------------------------------
PROMPT_LLISTA = """Analitza el text següent, extret de la pàgina d'agenda o \
programació d'una web cultural de Tarragona, i extreu la llista d'activitats \
culturals que s'hi anuncien (concerts, exposicions, teatre, tallers, visites, \
xerrades, festivals, activitats familiars...).

REGLES ESTRICTES:
- No inventis cap dada. Si una dada d'una activitat no apareix clarament al text, escriu exactament "pendent de revisar".
- Inclou NOMÉS activitats amb data d'inici entre {AVUI} i {LIMIT} (o exposicions/cicles que estiguin actius dins d'aquest període). Descarta activitats clarament passades.
- No incloguis elements de navegació, notícies sense data d'activitat, ni serveis permanents (horaris del museu, botiga, etc.).
- "data" i "data_fi" en format dd/mm/aaaa ("data_fi" = "" si és un sol dia).
- "categoria": exactament una d'aquestes o "pendent de revisar": Música, Teatre, Exposició, Cinema, Patrimoni, Literatura, Familiar, Taller, Gastronomia, Mercat, Conferència, Dansa, Art, Festa popular, Altres.
- "url_font": si a la LLISTA D'ENLLAÇOS hi ha un enllaç que clarament correspon a l'activitat, posa-hi aquella URL exacta; si no, "".
- "resum_agendatgn": 1 frase neutra en català basada NOMÉS en el text.
- "confianca_ia": Alta = títol, data i lloc clars; Mitjana = falta algun camp important; Baixa = informació confusa.
- Si no hi ha cap activitat vàlida, retorna [].

Retorna NOMÉS un array JSON vàlid, sense markdown ni text fora del JSON. Cada element:
{"titol": "", "data": "", "data_fi": "", "hora": "", "lloc": "", "organitzador": "",
 "preu": "", "categoria": "", "url_font": "", "resum_agendatgn": "", "dubtes": "",
 "confianca_ia": "Alta | Mitjana | Baixa"}

URL de la pàgina: {URL}

TEXT DE LA PÀGINA:
{TEXT}

LLISTA D'ENLLAÇOS DE LA PÀGINA:
{ENLLACOS}
"""


def extreu_llista(text_pagina, enllacos, url, avui):
    import datetime as dt
    limit = avui + dt.timedelta(days=30)
    prompt = (PROMPT_LLISTA
              .replace("{AVUI}", avui.strftime("%d/%m/%Y"))
              .replace("{LIMIT}", limit.strftime("%d/%m/%Y"))
              .replace("{URL}", url)
              .replace("{TEXT}", text_pagina)
              .replace("{ENLLACOS}", enllacos or "(cap)"))
    resposta = _client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    net = _neteja_json_array(resposta.text)
    activitats = json.loads(net)
    if not isinstance(activitats, list):
        return []

    resultat = []
    for act in activitats:
        if not isinstance(act, dict):
            continue
        if act.get("confianca_ia") not in ("Alta", "Mitjana", "Baixa"):
            act["confianca_ia"] = "Baixa"
        for camp in ("titol", "data", "hora", "lloc", "organitzador", "preu"):
            if not (act.get(camp) or "").strip():
                act[camp] = "pendent de revisar"
        if act["titol"] == "pendent de revisar":
            continue  # sense títol no té sentit crear entrada
        # data_fi en ISO
        fi = (act.get("data_fi") or "").strip()
        act["data_fi_iso"] = None
        if fi and "pendent" not in fi.lower():
            import datetime as dt2
            for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    act["data_fi_iso"] = dt2.datetime.strptime(fi[:10], fmt).date().isoformat()
                    break
                except ValueError:
                    continue
        act["text_visible"] = ""
        resultat.append(act)
    return resultat


def _neteja_json_array(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    inici, fi = text.find("["), text.rfind("]")
    if inici >= 0 and fi > inici:
        text = text[inici:fi + 1]
    return text or "[]"
