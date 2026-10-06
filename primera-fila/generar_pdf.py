#!/usr/bin/env python3
"""
GENERADOR DEL PDF DE PRIMERA FILA
=================================
1. Busca a Notion l'edició en estat "Maquetant" (o la que li diguis amb --edicio).
2. Dibuixa el mapa de la setmana (mapa_setmana.py) i numera els llocs.
3. Munta totes les pàgines amb el disseny de Primera Fila i en fa un PDF A4.
4. El puja a Google Drive, t'envia el PDF per Telegram i posa l'edició en "Revisió"
   amb el "Link descàrrega" omplert.

Ús:
  python generar_pdf.py                    # edició en "Maquetant"
  python generar_pdf.py --edicio URL       # una edició concreta
  python generar_pdf.py --local            # només genera el PDF (no puja ni toca Notion)
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import requests

import notion_dades as nd
import plantilles as T

AQUI = Path(__file__).resolve().parent
WHATSAPP = "https://whatsapp.com/channel/0029VaDHGB6Elagyhppwfz2x"
MAX_PER_PAGINA = 7

GRUPS_MUSEUS = [
    ("MUSEUS I CENTRES D'ART", {"Museu", "Galeria / art"}),
    ("PATRIMONI", {"Patrimoni"}),
    ("ESPAIS CULTURALS I SALES", {"Teatre / auditori", "Sala de concerts", "Espai jove / cívic", "Llibreria", "Altres", "Bar / restaurant"}),
]


def num_txt(x):
    return f"{int(x):,}".replace(",", ".") if x else ""


def repartir(llista, maxim):
    """Parteix en pàgines equilibrades (10 -> 5+5, 9 -> 5+4...)."""
    if len(llista) <= maxim:
        return [llista]
    n = math.ceil(len(llista) / maxim)
    mida = math.ceil(len(llista) / n)
    return [llista[i:i + mida] for i in range(0, len(llista), mida)]


def mapa(edicio_id, sortida):
    """Executa mapa_setmana.py i torna (dades_json, carpeta) o (None, None)."""
    try:
        subprocess.run([sys.executable, str(AQUI / "mapa_setmana.py"), "--edicio", edicio_id, "--sortida", str(sortida)],
                       check=True, cwd=AQUI)
    except Exception as e:  # noqa: BLE001
        print(f"Avís: el mapa no s'ha pogut generar ({e}). El PDF sortirà sense mapa.")
        return None, None
    fitxers = sorted(Path(sortida).glob("*/llocs_setmana.json"), key=lambda p: p.stat().st_mtime)
    if not fitxers:
        return None, None
    return json.loads(fitxers[-1].read_text(encoding="utf-8")), fitxers[-1].parent


def png_uri(path):
    import base64
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def muntar(ed, mapa_dades, mapa_dir):
    ctx = {"dates": T.dates_txt(ed["ini"], ed["fi"]), "whatsapp": WHATSAPP,
           "subs_txt": num_txt(ed["subscriptors"]), "seg_txt": num_txt(ed["seguidors"]), "n_dia": {}}
    nums = (mapa_dades or {}).get("activitat_num", {})
    pagines = []

    # Imatges
    ed["portada_uri"] = nd.imatge_data_uri(ed["portada"][0]) if ed["portada"] else None
    for a in ed["activitats"]:
        a["img"] = nd.imatge_data_uri(a["imatges"][0]) if a["imatges"] else None
        a["hora_curta"] = nd.hora_curta(a["hora"])

    # 1-2 · Portada i canal
    pagines.append(T.portada(ctx, ed))
    amagar = ed.get("amagar", set())
    if amagar:
        print("Seccions amagades:", ", ".join(sorted(amagar)))
    if "Canal WhatsApp" not in amagar:
        pagines.append(T.canal(ctx))

    # 3 · Article
    if ed.get("article") and "Article" not in amagar:
        art = ed["article"]
        art["imatge_uri"] = nd.imatge_data_uri(art["imatge"]) if art["imatge"] else None
        pagines.append(T.article(ctx, art))

    # Classificar activitats
    # si s'amaguen Exposicions o Festes, aquestes activitats van a la pàgina del seu dia
    expos = [] if "Exposicions" in amagar else [a for a in ed["activitats"] if "exposici" in (a["categoria"] or "").lower()]
    festes = [] if "Festes" in amagar else [a for a in ed["activitats"] if a["festa"] and a not in expos]
    dies = [a for a in ed["activitats"] if a not in expos and a not in festes and a["dia"]]

    # 4 · Pàgines de dia (dijous -> diumenge)
    for dia in sorted({a["dia"] for a in dies}):
        del_dia = sorted([a for a in dies if a["dia"] == dia], key=lambda a: nd.minuts(a["hora"]))
        dest = next((a for a in del_dia if a["destacada"]), None)
        if dest:
            del_dia.remove(dest)
            del_dia.insert(0, dest)
        ctx["n_dia"][dia] = len(del_dia)
        for i, tros in enumerate(repartir(del_dia, MAX_PER_PAGINA)):
            pagines.append(T.pagina_dia(ctx, dia, tros, continuacio=i > 0, nums=nums))

    # 5 · Festes als barris (2 per pàgina)
    if festes:
        barris = []
        for nom in sorted({a["festa"] for a in festes}):
            acts = sorted([a for a in festes if a["festa"] == nom], key=lambda a: (a["dia"] or ed["fi"], nd.minuts(a["hora"])))
            dies_b = []
            for d in sorted({a["dia"] for a in acts if a["dia"]}):
                dies_b.append((T.DIES[d.weekday()], [(a["hora_curta"] or "·", a["nom"]) for a in acts if a["dia"] == d]))
            dd = [a["dia"] for a in acts if a["dia"]]
            barris.append({"nom": nom, "dies": dies_b[:3], "img": next((a["img"] for a in acts if a["img"]), None),
                           "dates": f"{min(dd).day}—{max(dd).day} {T.MESOS[max(dd).month - 1].upper()}" if dd else ""})
        for tros in [barris[i:i + 2] for i in range(0, len(barris), 2)]:
            pagines.append(T.pagina_festes(ctx, tros))

    # 6 · Exposicions
    if expos:
        def fila(a):
            if ed["ini"] and a["dia"] and a["dia"] >= ed["ini"]:
                quan = f"Des del {a['dia'].day} de {T.MESOS[a['dia'].month - 1]}"
            elif a["fi"]:
                quan = f"Fins al {a['fi'].day} de {T.MESOS[a['fi'].month - 1]}"
            else:
                quan = ""
            return {"nom": a["nom"], "lloc": a["lloc"], "quan": quan, "preu": a["preu"], "img": a["img"]}
        nov = [a for a in expos if ed["ini"] and a["dia"] and a["dia"] >= ed["ini"]]
        ult = [a for a in expos if a not in nov and a["fi"] and ed["fi"] and a["fi"] <= ed["fi"] + timedelta(days=7)]
        cur = [a for a in expos if a not in nov and a not in ult]
        files = [("NOVETATS", nov), ("EN CURS", cur), ("ÚLTIMS DIES", ult)]
        plans = [(g, [fila(a) for a in l]) for g, l in files]
        # com a molt 7 files per pàgina
        pag, compte = [], 0
        for g, l in plans:
            for x in l:
                if compte == 7:
                    pagines.append(T.pagina_expos(ctx, pag))
                    pag, compte = [], 0
                if not pag or pag[-1][0] != g:
                    pag.append((g, []))
                pag[-1][1].append(x)
                compte += 1
        if pag:
            pagines.append(T.pagina_expos(ctx, pag))

    # 7 · Museus i espais
    if ed["museus"] and "Museus" not in amagar:
        grups = []
        for nom, tipus in GRUPS_MUSEUS:
            items = sorted([m for m in ed["museus"] if m["tipus"] in tipus], key=lambda m: m["nom"])
            if items:
                grups.append((nom, items[:12]))
        if grups:
            pagines.append(T.pagina_museus(ctx, grups))

    # 8 · Negoci recomanat
    if ed.get("negoci") and "Negoci" not in amagar:
        b = ed["negoci"]
        b["foto_uri"] = nd.imatge_data_uri(b["foto"]) if b["foto"] else None
        pagines.append(T.pagina_negoci(ctx, b))

    # 9 · Ofertes (5 per pàgina, màxim 10)
    if ed["ofertes"] and "Ofertes" not in amagar:
        for o in ed["ofertes"]:
            o["img"] = nd.imatge_data_uri(o["imatge"]) if o["imatge"] else None
        trossos = [ed["ofertes"][i:i + 5] for i in range(0, len(ed["ofertes"]), 5)]
        for i, tros in enumerate(trossos, 1):
            pagines.append(T.pagina_ofertes(ctx, tros, i, len(trossos)))

    # 10 · Comunitat
    if "Comunitat" not in amagar:
        pagines.append(T.pagina_comunitat(ctx))

    # 11 · Mapa, zoom i llocs
    if mapa_dades and mapa_dir and (mapa_dir / "mapa_general.png").exists():
        llocs = mapa_dades["llocs"]
        fora = [x for x in llocs if x["num"] in mapa_dades.get("fora_del_mapa", [])]
        te_zoom = mapa_dades.get("zoom", {}).get("existeix") and (mapa_dir / "mapa_zoom.png").exists()
        if "Mapa" not in amagar:
            pagines.append(T.pagina_mapa(ctx, png_uri(mapa_dir / "mapa_general.png"), fora, te_zoom, len(llocs)))
            if te_zoom:
                pagines.append(T.pagina_zoom(ctx, png_uri(mapa_dir / "mapa_zoom.png")))
        for tros in [llocs[i:i + 16] for i in range(0, len(llocs), 16)]:
            if "Llocs" not in amagar:
                pagines.append(T.pagina_llocs(ctx, tros))

    # 12 · Contraportada
    if ed.get("contraportada") and "Contraportada" not in amagar:
        c = ed["contraportada"]
        c["arxiu_uri"] = nd.imatge_data_uri(c["arxiu"] or c["imatge"]) if (c["arxiu"] or c["imatge"]) else None
        pagines.append(T.contraportada(ctx, c))

    return T.document(pagines), len(pagines)


def a_pdf(html, sortida_pdf):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        nav = p.chromium.launch()
        pg = nav.new_page()
        pg.set_content(html, wait_until="networkidle", timeout=120_000)
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(1500)
        pg.pdf(path=str(sortida_pdf), format="A4", print_background=True, prefer_css_page_size=True)
        nav.close()


def pujar_drive(path, nom):
    cid, sec, ref = (os.environ.get(k) for k in ["GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN"])
    carpeta = os.environ.get("DRIVE_PDF_FOLDER_ID") or os.environ.get("DRIVE_FOLDER_ID")
    if not (cid and sec and ref):
        print("Drive no configurat: el PDF no es puja.")
        return None
    tok = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "client_id": cid, "client_secret": sec, "refresh_token": ref, "grant_type": "refresh_token"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    meta = {"name": nom, "mimeType": "application/pdf"}
    if carpeta:
        meta["parents"] = [carpeta]
    r = requests.post("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,webViewLink",
                      headers=h, timeout=300, files={
                          "metadata": ("metadata", json.dumps(meta), "application/json"),
                          "file": (nom, Path(path).read_bytes(), "application/pdf")})
    r.raise_for_status()
    f = r.json()
    requests.post(f"https://www.googleapis.com/drive/v3/files/{f['id']}/permissions", headers=h, timeout=30,
                  json={"role": "reader", "type": "anyone"})
    return f["webViewLink"]


def avisar_telegram(path, text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return
    try:
        with open(path, "rb") as f:
            requests.post(f"https://api.telegram.org/bot{tok}/sendDocument", timeout=120,
                          data={"chat_id": chat, "caption": text[:1000]}, files={"document": (Path(path).name, f, "application/pdf")})
    except Exception as e:  # noqa: BLE001
        print(f"Avís Telegram: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edicio", help="URL o id de l'edició")
    ap.add_argument("--local", action="store_true", help="Només genera el PDF, sense pujar-lo ni tocar Notion")
    ap.add_argument("--sense-mapa", action="store_true")
    ap.add_argument("--sortida", default="sortida")
    a = ap.parse_args()

    token = os.environ.get("NOTION_TOKEN")
    if not token:
        sys.exit("Falta NOTION_TOKEN")
    n = nd.Notion(token)
    edicio_id = None
    if a.edicio:
        m = re.findall(r"[0-9a-f]{32}", a.edicio.replace("-", ""))
        edicio_id = m[-1] if m else a.edicio
    ed = nd.carregar_edicio(n, edicio_id)
    if not ed:
        print('Cap edició en estat "Maquetant". No hi ha res a fer.')
        return
    print(f"Edició: {ed['nom']} · {len(ed['activitats'])} activitats")

    sortida = AQUI / a.sortida
    sortida.mkdir(exist_ok=True)
    sense = a.sense_mapa or {"Mapa", "Llocs"} <= ed.get("amagar", set())
    dades_mapa, dir_mapa = (None, None) if sense else mapa(ed["id"], sortida)

    html, n_pag = muntar(ed, dades_mapa, dir_mapa)
    slug = re.sub(r"[^a-z0-9]+", "-", ed["nom"].lower()).strip("-") or "primera-fila"
    (sortida / f"{slug}.html").write_text(html, encoding="utf-8")
    pdf = sortida / f"Primera-Fila-{slug}.pdf"
    a_pdf(html, pdf)
    print(f"PDF: {pdf} ({n_pag} pàgines)")

    if a.local:
        return
    link = None
    try:
        link = pujar_drive(pdf, pdf.name)
        print(f"Drive: {link}")
    except Exception as e:  # noqa: BLE001
        print(f"Avís Drive: {e}")
    props = {"PDF maquetat": {"checkbox": True}, "Estat": {"select": {"name": "Revisió"}}}
    if link:
        props["Link descàrrega"] = {"url": link}
    n.update(ed["id"], props)
    avisar_telegram(pdf, f"📰 {ed['nom']}: PDF llest per revisar ({n_pag} pàgines)." + (f"\n{link}" if link else ""))
    print("Fet! L'edició ja és a 'Revisió'.")


if __name__ == "__main__":
    main()
