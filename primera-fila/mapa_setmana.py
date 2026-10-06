#!/usr/bin/env python3
"""
MAPA DE LA SETMANA · Primera Fila (AgendaTGN)

Llegeix de Notion l'edició que està en estat "Maquetant", agafa NOMÉS les
activitats vinculades a aquella edició, busca el lloc de cadascuna a 📍 LLOCS
i dibuixa el mapa amb aquests llocs, numerats per ordre d'aparició al PDF
(dijous → diumenge, per hora).

Ús:
    python mapa_setmana.py                 # edició en estat "Maquetant"
    python mapa_setmana.py --edicio URL    # una edició concreta (URL o id de Notion)

Cal la variable d'entorn NOTION_TOKEN (la clau de la integració de Notion).

Resultat a  sortida/<nom-edicio>/ :
    mapa_general.png / .svg     -> només els llocs de la setmana
    mapa_zoom.png / .svg        -> zoom de la zona amb més llocs (si cal)
    llocs_setmana.json          -> números, llocs i activitats (el farà servir el generador del PDF)
    informe.txt                 -> què ha anat bé i què cal revisar
"""
import argparse
import difflib
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests

from mapa_propi import descarregar, dibuixar, bbox_amb_proporcio, dist_km

# ---------- CONFIGURACIÓ ----------
DS_EDICIONS = "8f487a83-0a99-4385-80c6-a1da86a17d8a"
DS_ACTIVITATS = "3705d017-2af5-8001-a94f-000b2226712d"
DS_LLOCS = "bc7d9e22-f18d-4f06-bb83-4bee33e0cd32"
ESTAT_A_GENERAR = "Maquetant"

GEN_W, GEN_H = 706, 560        # mapa general (pàgina del PDF)
ZOOM_W, ZOOM_H = 706, 900      # mapa zoom (pàgina sencera)
RADI_MAX_KM = 2.3              # més lluny del centre -> "fora del mapa"
MIDA_MIN_M = 1200              # el mapa general mai fa menys d'1,2 km d'ample
RADI_ZOOM_M = 320
MIN_LLOCS_ZOOM = 6             # només fem zoom si hi ha prou llocs amuntegats

API = "https://api.notion.com/v1"


# ---------- NOTION ----------
class Notion:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2025-09-03",
            "Content-Type": "application/json",
        })

    def _req(self, method, path, **kw):
        for intent in range(5):
            r = self.s.request(method, API + path, timeout=30, **kw)
            if r.status_code == 429:  # massa peticions: esperem
                time.sleep(float(r.headers.get("Retry-After", 2)))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"Notion {r.status_code}: {r.text[:300]}")
            return r.json()
        raise RuntimeError("Notion: massa intents")

    def query(self, data_source, filtre=None, sorts=None):
        cos, files = {"page_size": 100}, []
        if filtre:
            cos["filter"] = filtre
        if sorts:
            cos["sorts"] = sorts
        while True:
            d = self._req("POST", f"/data_sources/{data_source}/query", json=cos)
            files += d["results"]
            if not d.get("has_more"):
                return files
            cos["start_cursor"] = d["next_cursor"]

    def page(self, page_id):
        return self._req("GET", f"/pages/{page_id}")


def prop(p, nom):
    """Valor senzill d'una propietat de Notion."""
    v = p["properties"].get(nom)
    if not v:
        return None
    t = v["type"]
    if t in ("title", "rich_text"):
        return "".join(x["plain_text"] for x in v[t]).strip() or None
    if t == "number":
        return v["number"]
    if t == "date":
        return v["date"]
    if t == "relation":
        return [x["id"] for x in v["relation"]]
    if t == "select":
        return v["select"]["name"] if v["select"] else None
    if t == "url":
        return v["url"]
    if t == "checkbox":
        return v["checkbox"]
    return None


def id_de(text):
    """Extreu l'id d'una URL o text de Notion."""
    m = re.findall(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])", text) or \
        [x.replace("-", "") for x in re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text)]
    if not m:
        raise SystemExit(f"No trobo cap id de Notion a: {text}")
    return m[-1]


def normalitza(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\b(sala|bar|restaurant|rest|llibreria|teatre|the|el|la|les|els|l|cafe)\b", " ", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def hora_ordenable(h):
    m = re.search(r"(\d{1,2})[:.h](\d{2})?", h or "")
    if not m:
        return 99 * 60
    hh, mm = int(m.group(1)), int(m.group(2) or 0)
    if hh < 6:  # 00:00, 01:00 -> nit, va al final del dia
        hh += 24
    return hh * 60 + mm


# ---------- LÒGICA ----------
def triar_edicio(n, arg):
    if arg:
        p = n.page(id_de(arg))
        return p
    eds = n.query(DS_EDICIONS, {"property": "Estat", "select": {"equals": ESTAT_A_GENERAR}},
                  [{"property": "Data publicació", "direction": "descending"}])
    if not eds:
        raise SystemExit(f'Cap edició en estat "{ESTAT_A_GENERAR}". Posa l\'Estat a {ESTAT_A_GENERAR} o fes servir --edicio.')
    if len(eds) > 1:
        print(f'Atenció: hi ha {len(eds)} edicions en "{ESTAT_A_GENERAR}"; agafo la de data més recent.')
    return eds[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edicio", help="URL o id de l'edició (opcional)")
    ap.add_argument("--sortida", default="sortida")
    a = ap.parse_args()

    token = os.environ.get("NOTION_TOKEN")
    if not token:
        raise SystemExit("Falta la variable NOTION_TOKEN.")
    n = Notion(token)

    ed = triar_edicio(n, a.edicio)
    nom_ed = prop(ed, "Nom edició") or "edicio"
    print(f"Edició: {nom_ed}")

    # 1. Activitats d'aquesta edició
    acts = n.query(DS_ACTIVITATS, {"property": "Edició Primera Fila", "relation": {"contains": ed["id"]}})
    print(f"{len(acts)} activitats vinculades.")

    def clau(p):
        d = (prop(p, "Data inici") or {}).get("start") or "9999"
        return (d[:10], hora_ordenable(prop(p, "Hora")), prop(p, "Name") or "")
    acts.sort(key=clau)

    # 2. Tots els llocs (una sola consulta)
    llocs = {p["id"]: p for p in n.query(DS_LLOCS)}
    per_nom = {normalitza(prop(p, "Nom")): pid for pid, p in llocs.items()}

    # 3. Lloc de cada activitat + numeració per ordre d'aparició
    numeracio, ordre, act_num = {}, [], {}
    sense_lloc, deduits, sense_coord = [], [], []
    for p in acts:
        nom_act = prop(p, "Name") or "(sense nom)"
        rel = prop(p, "Lloc (fitxa)") or []
        lid = rel[0] if rel else None
        if not lid:  # pla B: el text del camp "Lloc"
            text = normalitza(prop(p, "Lloc"))
            if text:
                cand = difflib.get_close_matches(text, list(per_nom), n=1, cutoff=0.82)
                if not cand:
                    cand = [k for k in per_nom if k and (k in text or text in k) and len(k) > 3][:1]
                if cand:
                    lid = per_nom[cand[0]]
                    deduits.append(f'{nom_act}  →  «{prop(p, "Lloc")}» = {prop(llocs[lid], "Nom")}')
        if not lid or lid not in llocs:
            sense_lloc.append(f'{nom_act}  (Lloc: «{prop(p, "Lloc") or "buit"}»)')
            continue
        L = llocs[lid]
        if prop(L, "Latitud") is None or prop(L, "Longitud") is None:
            if prop(L, "Nom") not in sense_coord:
                sense_coord.append(prop(L, "Nom"))
            continue
        if lid not in numeracio:
            numeracio[lid] = len(ordre) + 1
            ordre.append(lid)
        act_num[p["id"]] = numeracio[lid]

    punts = [{
        "num": numeracio[lid], "id": lid, "nom": prop(llocs[lid], "Nom"),
        "adreca": prop(llocs[lid], "Adreça"), "instagram": prop(llocs[lid], "Instagram"),
        "lat": prop(llocs[lid], "Latitud"), "lon": prop(llocs[lid], "Longitud"),
        "google_maps": prop(llocs[lid], "Google Maps"),
    } for lid in ordre]
    print(f"{len(punts)} llocs diferents amb coordenades.")
    if not punts:
        raise SystemExit("Cap lloc per dibuixar. Revisa que les activitats tinguin 'Lloc (fitxa)'.")

    # 4. Llocs dins / fora del mapa
    lats = sorted(x["lat"] for x in punts); lons = sorted(x["lon"] for x in punts)
    centre = (lats[len(lats) // 2], lons[len(lons) // 2])
    dins = [x for x in punts if dist_km(centre, (x["lat"], x["lon"])) <= RADI_MAX_KM]
    fora = [x for x in punts if x not in dins]

    slug = re.sub(r"[^a-z0-9]+", "-", normalitza(nom_ed) or "edicio").strip("-")
    out = Path(a.sortida) / slug
    out.mkdir(parents=True, exist_ok=True)

    # 5. Mapa general (amb una mida mínima perquè no quedi massa ampliat)
    print("\nMAPA GENERAL")
    bbox = bbox_amb_proporcio(dins, max(180, MIDA_MIN_M / 2 - _ample_m(dins) / 2), GEN_W / GEN_H)
    dibuixar(bbox, descarregar(bbox), dins, str(out / "mapa_general"), mida_pin=22, w=GEN_W, h=GEN_H)

    # 6. Zoom, només si hi ha una zona amb molts llocs junts
    def veins(x):
        return [y for y in dins if dist_km((x["lat"], x["lon"]), (y["lat"], y["lon"])) * 1000 <= RADI_ZOOM_M]
    cluster = max((veins(x) for x in dins), key=len)
    # zoom només si hi ha prou llocs junts i ocupen una zona clarament més petita que el mapa general
    te_zoom = len(cluster) >= MIN_LLOCS_ZOOM and _ample_m(cluster) < 0.5 * max(_ample_m(dins), MIDA_MIN_M)
    if te_zoom:
        print(f"\nMAPA ZOOM ({len(cluster)} llocs junts)")
        bz = bbox_amb_proporcio(cluster, 90, ZOOM_W / ZOOM_H)
        dibuixar(bz, descarregar(bz), cluster, str(out / "mapa_zoom"), mida_pin=30,
                 n_etiquetes=14, w=ZOOM_W, h=ZOOM_H, amb_mar=False)

    # 7. Dades per al generador del PDF
    dades = {
        "edicio": {"id": ed["id"], "nom": nom_ed},
        "llocs": punts,
        "activitat_num": act_num,
        "fora_del_mapa": [x["num"] for x in fora],
        "zoom": {"existeix": te_zoom, "nums": [x["num"] for x in cluster] if te_zoom else []},
        "sense_coordenades": sense_coord,
        "sense_lloc": sense_lloc,
    }
    (out / "llocs_setmana.json").write_text(json.dumps(dades, ensure_ascii=False, indent=2), encoding="utf-8")

    inf = [f"EDICIÓ: {nom_ed}", f"Activitats: {len(acts)}  ·  Llocs al mapa: {len(dins)}  ·  Fora del mapa: {len(fora)}", ""]
    inf += ["NUMERACIÓ"] + [f'  {x["num"]:>2} · {x["nom"]}' for x in punts] + [""]
    if fora:
        inf += ["FORA DEL MAPA"] + [f'  {x["num"]} · {x["nom"]}' for x in fora] + [""]
    if deduits:
        inf += ["LLOC DEDUÏT PEL TEXT (comprova-ho i, si és bo, posa'l a 'Lloc (fitxa)')"] + [f"  {t}" for t in deduits] + [""]
    if sense_lloc:
        inf += ["SENSE LLOC (no surten al mapa: omple 'Lloc (fitxa)')"] + [f"  {t}" for t in sense_lloc] + [""]
    if sense_coord:
        inf += ["LLOCS SENSE COORDENADES (omple Latitud/Longitud a 📍 LLOCS)"] + [f"  {t}" for t in sense_coord] + [""]
    (out / "informe.txt").write_text("\n".join(inf), encoding="utf-8")
    print("\n" + "\n".join(inf))
    print(f"Fet! Tot és a: {out}")


def _ample_m(punts):
    """Ample aproximat (m) que ocupen els punts."""
    lons = [x["lon"] for x in punts]
    lat = sum(x["lat"] for x in punts) / len(punts)
    return (max(lons) - min(lons)) * 111_320 * __import__("math").cos(__import__("math").radians(lat))


if __name__ == "__main__":
    main()
