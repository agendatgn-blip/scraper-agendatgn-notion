"""
Llegeix de Notion tot el que necessita el PDF de Primera Fila.
"""
import base64
import os
import re
import time
from datetime import date

import requests

API = "https://api.notion.com/v1"
DS_EDICIONS = "8f487a83-0a99-4385-80c6-a1da86a17d8a"
DS_ACTIVITATS = "3705d017-2af5-8001-a94f-000b2226712d"
DS_LLOCS = "bc7d9e22-f18d-4f06-bb83-4bee33e0cd32"


class Notion:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Notion-Version": "2025-09-03",
                               "Content-Type": "application/json"})

    def _req(self, method, path, **kw):
        for _ in range(5):
            r = self.s.request(method, API + path, timeout=40, **kw)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2)))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"Notion {r.status_code}: {r.text[:300]}")
            return r.json()
        raise RuntimeError("Notion: massa intents")

    def query(self, ds, filtre=None, sorts=None):
        cos, out = {"page_size": 100}, []
        if filtre:
            cos["filter"] = filtre
        if sorts:
            cos["sorts"] = sorts
        while True:
            d = self._req("POST", f"/data_sources/{ds}/query", json=cos)
            out += d["results"]
            if not d.get("has_more"):
                return out
            cos["start_cursor"] = d["next_cursor"]

    def page(self, pid):
        return self._req("GET", f"/pages/{pid}")

    def update(self, pid, props):
        return self._req("PATCH", f"/pages/{pid}", json={"properties": props})


# ---------------------------------------------------------------- propietats
def P(p, *noms):
    """Valor de la primera propietat que existeixi i tingui valor."""
    for nom in noms:
        v = p["properties"].get(nom)
        if not v:
            continue
        t = v["type"]
        if t in ("title", "rich_text"):
            val = "".join(x["plain_text"] for x in v[t]).strip()
        elif t == "number":
            val = v["number"]
        elif t == "checkbox":
            val = v["checkbox"]
        elif t == "select":
            val = v["select"]["name"] if v["select"] else None
        elif t == "multi_select":
            val = [x["name"] for x in v["multi_select"]]
        elif t == "date":
            val = v["date"]
        elif t == "url":
            val = v["url"]
        elif t == "relation":
            val = [x["id"] for x in v["relation"]]
        elif t == "files":
            val = [f.get("file", {}).get("url") or f.get("external", {}).get("url") for f in v["files"]]
            val = [u for u in val if u]
        else:
            val = None
        if val not in (None, "", []):
            return val
    return None


def titol(p):
    for v in p["properties"].values():
        if v["type"] == "title":
            return "".join(x["plain_text"] for x in v["title"]).strip()
    return ""


def data_de(d, clau="start"):
    if not d or not d.get(clau):
        return None
    return date.fromisoformat(d[clau][:10])


_CACHE_IMG = {}


def imatge_data_uri(url):
    """Descarrega una imatge i la torna com a data: URI (les URL de Notion caduquen)."""
    if not url:
        return None
    if url in _CACHE_IMG:
        return _CACHE_IMG[url]
    try:
        r = requests.get(url, timeout=40)
        r.raise_for_status()
        tipus = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
        if not tipus.startswith("image/"):
            tipus = "image/jpeg"
        uri = f"data:{tipus};base64," + base64.b64encode(r.content).decode()
    except Exception as e:  # noqa: BLE001
        print(f"  -> Avís: no he pogut baixar una imatge ({e})")
        uri = None
    _CACHE_IMG[url] = uri
    return uri


def preu_text(p):
    t = P(p, "Preu (text)")
    if t:
        return t
    n = P(p, "Preu")
    if n is None:
        return ""
    try:
        return "Gratuït" if float(n) == 0 else f"{float(n):g} €"
    except (TypeError, ValueError):
        return str(n)


def hora_curta(h):
    m = re.search(r"(\d{1,2})[:.h](\d{2})?", h or "")
    if not m:
        return ""
    hh, mm = int(m.group(1)), int(m.group(2) or 0)
    if hh in (0, 24) and mm == 0:
        return "00 h"
    return f"{hh} h" if mm == 0 else f"{hh}.{mm:02d} h"


def minuts(h):
    m = re.search(r"(\d{1,2})[:.h](\d{2})?", h or "")
    if not m:
        return 99 * 60
    hh = int(m.group(1))
    return ((hh + 24) if hh < 6 else hh) * 60 + int(m.group(2) or 0)


# ---------------------------------------------------------------- edició completa
def carregar_edicio(n, edicio_id=None, estat="Maquetant"):
    if edicio_id:
        ed = n.page(edicio_id)
    else:
        eds = n.query(DS_EDICIONS, {"property": "Estat", "select": {"equals": estat}})
        if not eds:
            return None
        ed = eds[0]

    setmana = P(ed, "Setmana") or {}
    ini, fi = data_de(setmana), data_de(setmana, "end")
    dades = {
        "id": ed["id"], "nom": titol(ed) or "Primera Fila",
        "numero": P(ed, "Número edició") or "",
        "ini": ini, "fi": fi or ini,
        "portada": P(ed, "Portada") or [],
        "editorial": P(ed, "Editorial / intro") or "",
        "subscriptors": P(ed, "Subscriptors"), "seguidors": P(ed, "Seguidors IG"),
        "amagar": set(P(ed, "Amagar seccions") or []),
    }
    # Si aquesta edició no té les xifres, agafem les de l'última edició que en tingui
    if dades["subscriptors"] is None or dades["seguidors"] is None:
        for altra in n.query(DS_EDICIONS, sorts=[{"timestamp": "last_edited_time", "direction": "descending"}]):
            if dades["subscriptors"] is None and P(altra, "Subscriptors") is not None:
                dades["subscriptors"] = P(altra, "Subscriptors")
            if dades["seguidors"] is None and P(altra, "Seguidors IG") is not None:
                dades["seguidors"] = P(altra, "Seguidors IG")

    # Llocs (per al nom i el número de mapa)
    llocs = {p["id"]: p for p in n.query(DS_LLOCS)}
    dades["llocs_tots"] = llocs

    # Activitats vinculades a l'edició
    acts = []
    for p in n.query(DS_ACTIVITATS, {"property": "Edició Primera Fila", "relation": {"contains": ed["id"]}}):
        rel = P(p, "Lloc (fitxa)") or []
        lloc_nom = titol(llocs[rel[0]]) if rel and rel[0] in llocs else (P(p, "Lloc") or "")
        acts.append({
            "id": p["id"], "nom": titol(p),
            "dia": data_de(P(p, "Data inici")), "fi": data_de(P(p, "Data final")) or data_de(P(p, "Data inici")),
            "hora": P(p, "Hora") or "", "lloc": lloc_nom, "municipi": P(p, "Municipi") or "",
            "cat": P(p, "Etiqueta PDF", "Categoria") or "", "categoria": P(p, "Categoria") or "",
            "preu": preu_text(p), "descripcio": P(p, "Descripció") or "",
            "destacada": bool(P(p, "Destacada")), "festa": P(p, "Festa / barri") or "",
            "imatges": P(p, "Imatge") or [], "reserva": P(p, "URL reserva") or "",
        })
    dades["activitats"] = acts

    # Article
    art = P(ed, "Article") or []
    if art:
        a = n.page(art[0])
        dades["article"] = {"titol": titol(a), "entradeta": P(a, "Entradeta") or "", "text": P(a, "Text") or "",
                            "cita": P(a, "Cita destacada") or "", "imatge": (P(a, "Imatge") or [None])[0],
                            "peu": P(a, "Peu d'imatge") or "", "signatura": P(a, "Signatura") or "L'equip d'AgendaTGN"}

    # Negoci recomanat
    neg = P(ed, "Negoci recomanat") or []
    if neg:
        b = n.page(neg[0])
        dades["negoci"] = {
            "nom": titol(b), "sector": P(b, "Sector recomanat", "Categoria") or "",
            "tipus": P(b, "Tipus recomanació") or "", "foto": (P(b, "Foto") or [None])[0],
            "historia": P(b, "Història") or "", "cita": P(b, "Cita propietari") or "", "qui": P(b, "Qui parla") or "",
            "perque": P(b, "Per què hi anem") or "", "demanar": P(b, "Què demanar") or "",
            "adreca": P(b, "Adreça") or "", "horari": P(b, "Horari") or "", "instagram": P(b, "Instagram") or "",
            "preu": P(b, "Preu mitjà") or "",
        }

    # Ofertes i contraportada
    ofertes, contra = [], None
    for oid in P(ed, "Ofertes vinculades") or []:
        o = n.page(oid)
        item = {"nom": titol(o), "linia": P(o, "Text curt PDF") or "", "condicions": P(o, "Condicions") or "",
                "enllac": P(o, "Enllaç", "Enllac", "URL", "Link") or "", "tipus": P(o, "Tipus") or "",
                "imatge": (P(o, "Imatge principal", "Imatge") or [None])[0],
                "arxiu": (P(o, "Arxiu contraportada") or [None])[0]}
        if (P(o, "Format PDF") or "").startswith("Contraportada") and contra is None:
            contra = item
        else:
            ofertes.append(item)
    dades["ofertes"] = ofertes[:10]
    dades["contraportada"] = contra

    # Índex de museus i espais
    dades["museus"] = [{"nom": titol(p), "tipus": P(p, "Tipus d'espai") or "Altres",
                        "adreca": P(p, "Adreça") or "", "horari": P(p, "Horari") or ""}
                       for p in llocs.values() if P(p, "Surt a l'índex de museus")]
    return dades
