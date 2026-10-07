#!/usr/bin/env python3
"""Prova comparativa de models amb cartells reals ja validats.

Agafa les últimes N captures d'INBOX AGENDA que ja s'han revisat a mà
("Validada" o "Convertida en activitat"), passa cada imatge per CADA proveïdor
configurat i compara el resultat amb els valors bons:
  - si la fila té "Activitat creada": els camps de l'activitat (el valor final)
  - si no: els camps d'INBOX tal com han quedat després de revisar-los

Resultat: taula al resum del workflow de GitHub + prova_models.csv.

Variables: NOTION_TOKEN, NOTION_DB_ID, GOOGLE_OAUTH_* (per baixar de Drive),
MISTRAL_API_KEY / GEMINI_API_KEY / GROQ_API_KEY, PROVA_N (per defecte 30),
PROVA_PROVEIDORS (per defecte "mistral,gemini,groq").
"""

import csv
import os
import re
import sys
import time
from datetime import date
from io import BytesIO

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ia import proveidors  # noqa: E402
from ia.esquema import prompt_cartell  # noqa: E402
from ia.validador import (  # noqa: E402
    RespostaInvalida, comprova_esquema, proporcio_paraules, valida,
)

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID = os.environ["NOTION_DB_ID"]
N = int(os.environ.get("PROVA_N", "30"))
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


# ---------------------------------------------------------------------------
# Notion
# ---------------------------------------------------------------------------
def _text(prop):
    if not prop:
        return ""
    t = prop.get("type")
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in prop.get(t, []))
    if t == "date" and prop.get("date"):
        return prop["date"].get("start", "")[:10]
    if t == "url":
        return prop.get("url") or ""
    return ""


def files_validades():
    payload = {
        "filter": {"and": [
            {"property": "URL Drive imatge", "url": {"is_not_empty": True}},
            {"or": [
                {"property": "Estat revisió", "select": {"equals": "Validada"}},
                {"property": "Estat revisió", "select": {"equals": "Convertida en activitat"}},
            ]},
        ]},
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        "page_size": min(N, 100),
    }
    r = requests.post(f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
                      headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()["results"]


def valors_bons(fila):
    p = fila["properties"]
    bons = {
        "titol": _text(p.get("Títol detectat")) or _text(p.get("Nom provisional")),
        "data": _text(p.get("Data detectada")),
        "hora": _text(p.get("Hora detectada")),
        "lloc": _text(p.get("Lloc detectat")),
        "origen": "INBOX",
    }
    rel = (p.get("Activitat creada") or {}).get("relation") or []
    if rel:
        r = requests.get(f"https://api.notion.com/v1/pages/{rel[0]['id']}", headers=HEADERS, timeout=30)
        if r.ok:
            a = r.json()["properties"]
            bons.update({
                "titol": _text(a.get("Name")) or bons["titol"],
                "data": _text(a.get("Data inici")) or bons["data"],
                "hora": _text(a.get("Hora")) or bons["hora"],
                "lloc": _text(a.get("Lloc")) or bons["lloc"],
                "origen": "ACTIVITAT",
            })
    return bons


# ---------------------------------------------------------------------------
# Drive
# ---------------------------------------------------------------------------
def drive_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_OAUTH_REFRESH_TOKEN"],
        client_id=os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds)


def baixa_imatge(service, url):
    from googleapiclient.http import MediaIoBaseDownload

    m = re.search(r"/d/([\w-]+)", url) or re.search(r"[?&]id=([\w-]+)", url)
    if not m:
        return None, None
    file_id = m.group(1)
    meta = service.files().get(fileId=file_id, fields="mimeType").execute()
    buf = BytesIO()
    dl = MediaIoBaseDownload(buf, service.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue(), meta.get("mimeType", "image/jpeg")


# ---------------------------------------------------------------------------
# Puntuació
# ---------------------------------------------------------------------------
def _hora(h):
    m = re.search(r"(\d{1,2})[:.h](\d{2})?", h or "")
    return f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}" if m else ""


def puntua(model, bo):
    return {
        "titol": bool(model.get("titol")) and bool(bo["titol"]) and (
            proporcio_paraules(bo["titol"], model["titol"]) >= 0.6
            or proporcio_paraules(model["titol"], bo["titol"]) >= 0.6),
        "data": bool(bo["data"]) and model.get("data_inici") == bo["data"],
        "hora": bool(bo["hora"]) and _hora(model.get("hora")) == _hora(bo["hora"]),
        "lloc": bool(model.get("lloc")) and bool(bo["lloc"]) and (
            proporcio_paraules(bo["lloc"], model["lloc"]) >= 0.5
            or proporcio_paraules(model["lloc"], bo["lloc"]) >= 0.5),
    }


def main():
    noms = os.environ.get("PROVA_PROVEIDORS", "mistral,gemini,groq")
    cadena = [proveidors.PROVEIDORS[n.strip()]() for n in noms.split(",")
              if n.strip() in proveidors.PROVEIDORS]
    cadena = [p for p in cadena if p.disponible()]
    if not cadena:
        sys.exit("Cap proveïdor amb clau configurada")

    files = files_validades()[:N]
    print(f"{len(files)} cartells validats; proveïdors: {', '.join(p.nom for p in cadena)}")
    service = drive_service()

    camps = ["titol", "data", "hora", "lloc"]
    stats = {p.nom: {"ok": {c: 0 for c in camps}, "aval": {c: 0 for c in camps},
                     "errors": 0, "temps": [], "alta": 0, "alta_correcta": 0}
             for p in cadena}
    linies_csv = []

    for i, fila in enumerate(files, 1):
        bo = valors_bons(fila)
        url = _text(fila["properties"].get("URL Drive imatge"))
        try:
            img, mime = baixa_imatge(service, url)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}] no s'ha pogut baixar la imatge: {e!r}")
            continue
        if not img:
            continue
        avui = date.fromisoformat(fila["created_time"][:10])  # el dia que va entrar
        prompt = prompt_cartell(avui.isoformat())

        for p in cadena:
            t0 = time.monotonic()
            try:
                dades = comprova_esquema(p.extreu(img, mime, prompt))
                netes, problemes, confianca, estat = valida(dades, avui=avui)
            except (proveidors.ErrorProveidor, RespostaInvalida) as e:
                stats[p.nom]["errors"] += 1
                linies_csv.append([i, p.nom, "ERROR", str(e)[:200]])
                print(f"[{i}] {p.nom}: ERROR {e}")
                time.sleep(2)
                continue
            seg = time.monotonic() - t0
            s = stats[p.nom]
            s["temps"].append(seg)
            punts = puntua(netes, bo)
            for c in camps:
                if bo[c if c != "data" else "data"]:
                    s["aval"][c] += 1
                    s["ok"][c] += punts[c]
            if confianca == "Alta":
                s["alta"] += 1
                s["alta_correcta"] += all(punts[c] for c in camps if bo[c])
            linies_csv.append([i, p.nom, confianca, estat, bo["origen"],
                               bo["titol"], netes.get("titol"), bo["data"], netes.get("data_inici"),
                               bo["hora"], netes.get("hora"), bo["lloc"], netes.get("lloc"),
                               f"{seg:.1f}"])
            print(f"[{i}] {p.nom}: {seg:.1f}s · {confianca} · "
                  + " ".join(f"{c}={'✓' if punts[c] else '✗'}" for c in camps))
            time.sleep(1.5)  # respectar els límits dels plans gratuïts

    with open("prova_models.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#", "proveidor", "confianca", "estat", "origen_bo", "titol_bo", "titol_model",
                    "data_bona", "data_model", "hora_bona", "hora_model", "lloc_bo", "lloc_model", "segons"])
        w.writerows(linies_csv)

    def pct(a, b):
        return f"{100 * a / b:.0f}%" if b else "—"

    taula = ["| Proveïdor | Títol | Data | Hora | Lloc | Errors | Temps mitjà | «Alta» que eren correctes |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for p in cadena:
        s = stats[p.nom]
        temps = f"{sum(s['temps']) / len(s['temps']):.1f}s" if s["temps"] else "—"
        taula.append(
            f"| {p.etiqueta} | " + " | ".join(pct(s["ok"][c], s["aval"][c]) for c in camps)
            + f" | {s['errors']} | {temps} | {pct(s['alta_correcta'], s['alta'])} ({s['alta']}) |")
    resum = (f"## Prova de models · {len(files)} cartells validats\n\n" + "\n".join(taula)
             + "\n\nEl percentatge de cada camp es calcula sobre els cartells que tenen aquell camp omplert.\n")
    print(resum)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(resum)


if __name__ == "__main__":
    main()
