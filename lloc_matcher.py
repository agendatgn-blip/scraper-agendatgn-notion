# -*- coding: utf-8 -*-
"""
Enllaça el text del camp "Lloc" d'una activitat amb la seva fitxa de 📍 LLOCS.

    m = LlocMatcher(NOTION_TOKEN)          # llegeix 📍 LLOCS un sol cop
    lloc_id, info = m.troba_o_crea("Vestíbul Teatre Tarragona")

Ordre de cerca (després dels àlies fixos):
  a) nom normalitzat exacte
  b) un nom conté l'altre
  c) l'adreça del text coincideix amb la "Adreça" d'un lloc (carrer + número)
  d) similitud difusa (token_set_ratio ≥ 90, amb difflib; sense dependències)
Si no en troba cap i el text és un lloc concret, en crea una fitxa nova a 📍 LLOCS
(geocodificada amb Nominatim/OpenStreetMap si pot) marcada per revisar.

No s'enllaça ni es crea res si el text és buit, "pendent de revisar", només
"Tarragona", un barri sencer o més d'un lloc alhora.
"""

import re
import time
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import quote_plus

import requests

DS_LLOCS = "bc7d9e22-f18d-4f06-bb83-4bee33e0cd32"
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "AgendaTGN-bot/1.0 (+https://instagram.com/agendatgn; enllaç de llocs)"
# Tarragona i voltants (Constantí, Altafulla, la Canonja, Vila-seca...): lon_min, lat_max, lon_max, lat_min
VIEWBOX = "0.95,41.30,1.45,41.03"
LLINDAR_DIFUS = 90

# --------------------------------------------------------------------------- àlies
# text (normalitzat) → nom exacte de la fitxa a 📍 LLOCS. Ampliable.
ALIES = {
    "vestibul teatre tarragona": "Teatre Tarragona",
    "antiga preso": "Antic Centre Penitenciari (Antiga Presó)",
    "antic centre penitenciari": "Antic Centre Penitenciari (Antiga Presó)",
    "mamt": "MAMT · Museu d'Art Modern",
    "museu d art modern": "MAMT · Museu d'Art Modern",
    "sala plana de casa canals": "Mèdol Cultura Contemporània",
    "medol centre d arts contemporanies": "Mèdol Cultura Contemporània",
    "casa canals": "Mèdol Cultura Contemporània",
    "capsa": "Capsa de Música (Tabacalera)",
    "capsa de musica": "Capsa de Música (Tabacalera)",
    "stone rock n roll bar": "Stone Bar",
    "stone rock roll bar": "Stone Bar",
    "stone rock and roll bar": "Stone Bar",
    "la jarta": "Restaurant La Jartá",
    "12 topos": "Bar 12 Topos",
    "urv campus de catalunya": "Campus URV",
    "palau firal i de congressos": "Palau Firal",
    "centre cultural antic ajuntament": "Antic Ajuntament",
    "pla de la seu i voltants": "Pla de la Seu",
    "conjunto romano de centcelles": "Conjunt romà de Centcelles",
    "villa romana de els munts": "Vil·la romana dels Munts",
    # excepció: la pedrera NO és el Mèdol centre d'art
    "cantera de el medol": "Pedrera del Mèdol",
    "cantera del medol": "Pedrera del Mèdol",
    "pedrera del medol": "Pedrera del Mèdol",
    "pedrera de el medol": "Pedrera del Mèdol",
}
# S'avaluen abans que els àlies normals
_PEDRERA = re.compile(r"\b(cantera|pedrera)\b.*\bmedol\b")

# Barris sencers: no són un lloc concret per al mapa
BARRIS = {
    "el serrallo", "serrallo", "bonavista", "torreforta", "campclar", "sant pere i sant pau",
    "sant salvador", "part alta", "la part alta", "eixample", "el pilar", "la floresta",
    "el llorer", "riu clar", "la granja", "icomar",
}

# Paraules que, soles, no identifiquen cap lloc
GENERIQUES = {
    "de", "del", "dels", "la", "el", "les", "els", "l", "d", "i", "a", "en", "s",
    "sala", "teatre", "espai", "centre", "civic", "municipal", "museu", "bar", "restaurant",
    "restaurante", "placa", "plaza", "parc", "carrer", "c", "passeig", "pg", "rambla", "cultural",
    "jove", "art", "galeria", "llibreria", "biblioteca", "publica", "tarragona", "tgn", "auditori",
    "casa", "casal", "local", "club", "cafe", "hotel", "via", "avinguda", "av",
}
_STOP = {"de", "del", "dels", "la", "el", "les", "els", "l", "d", "i", "a", "en", "s"}
# Paraules que inicien un nom de lloc (per detectar "X i Y" = dos llocs)
_INICI_LLOC = {
    "teatre", "museu", "sala", "mnat", "mamt", "placa", "plaza", "parc", "centre", "auditori",
    "espai", "biblioteca", "esglesia", "castell", "passeig", "rambla", "carrer", "caixaforum",
    "palau", "antiga", "antic", "casa", "galeria", "llibreria", "bar", "restaurant", "amfiteatre",
    "circ", "catedral", "capella", "biblioteca", "port", "platja", "moll",
}
_PREFIXOS = [r"^vestibul (del |de l )?", r"^sala \w+ (de|del|de la|de l) ", r"^les golfes (de|del) ",
             r"^golfes (de|del) "]
_PARAULES_CARRER = {"c", "carrer", "placa", "pca", "pl", "plaza", "rambla", "avinguda", "av", "avda",
                    "passeig", "pg", "via", "baixada", "travessera", "ronda", "moll", "cami", "calle"}


# --------------------------------------------------------------------------- normalització
def normalitza(t):
    """Minúscules, sense accents ni puntuació, l·l → ll."""
    t = (t or "").lower()
    t = t.replace("l·l", "ll").replace("l.l", "ll").replace("ŀl", "ll")
    t = re.sub(r"[^\w\s]", " ", t)          # puntuació i símbols (°, ’, &...) → espai
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _sense_ciutat(n):
    """Treu "tarragona"/"tgn" si el que queda encara identifica el lloc."""
    t = re.sub(r"\b(de |a )?(tarragona|tgn)\b", " ", n)
    t = re.sub(r"\b43\d{3}\b", " ", t)          # codi postal
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\b(de|del|a)$", "", t).strip()
    return t if _significatives(t) else n


def _sense_prefix(n):
    for p in _PREFIXOS:
        n2 = re.sub(p, "", n)
        if n2 != n and (_significatives(n2) or len(n2.split()) >= 2):
            return n2
    return n


def _paraules(n):
    return [w for w in n.split() if w not in _STOP]


def _significatives(n):
    return {w for w in n.split() if w not in GENERIQUES}


def clau(text):
    """Clau de comparació d'un fragment de text."""
    return _sense_ciutat(_sense_prefix(normalitza(text)))


def _fragments(text):
    """Fragments candidats del text original: [base, segments separats per guions].
    La base és el text abans de la primera coma, '·', '(' o ';' (el que ve després sol ser l'adreça)."""
    t = (text or "").strip()
    base = re.split(r",|·|\(|;|\s\|\s", t)[0].strip(" '\"")
    segs = [s.strip(" '\"") for s in re.split(r"\s[-–—]\s", base) if s.strip()]
    out = [base] + (segs if len(segs) > 1 else [])
    return [f for f in out if f]


def _resta(text):
    """El que ve després de la base (adreça, barri...)."""
    t = (text or "").strip()
    m = re.search(r",|·|\(", t)
    return t[m.end():].strip(" )") if m else ""


# --------------------------------------------------------------------------- adreces
def _adreca_clau(t):
    """('august', '23') a partir de 'C/ d'August, 23' o 'Carrer August n°23'."""
    n = normalitza(t)
    num = re.search(r"\b(\d{1,4})\b", n)
    paraules = [w for w in n.split() if not w.isdigit() and w not in _PARAULES_CARRER
                and w not in _STOP and w not in {"n", "no", "num", "sn", "tarragona"}]
    return (" ".join(paraules[:4]), num.group(1) if num else None)


def _sembla_adreca(t):
    n = normalitza(t)
    if not n:
        return False
    primera = n.split()[0]
    return primera in _PARAULES_CARRER or bool(re.search(r"\b\d{1,4}\b", n) and len(n.split()) <= 6)


# --------------------------------------------------------------------------- difús
def _ratio(a, b):
    return SequenceMatcher(None, a, b).ratio() * 100


def token_set_ratio(a, b):
    """Equivalent a rapidfuzz/fuzzywuzzy token_set_ratio (sense articles ni preposicions)."""
    sa, sb = set(_paraules(a)), set(_paraules(b))
    if not sa or not sb:
        return 0
    inter = " ".join(sorted(sa & sb))
    d1 = " ".join(sorted(sa - sb))
    d2 = " ".join(sorted(sb - sa))
    t1 = (inter + " " + d1).strip()
    t2 = (inter + " " + d2).strip()
    return max(_ratio(inter, t1) if inter else 0, _ratio(inter, t2) if inter else 0, _ratio(t1, t2))


# --------------------------------------------------------------------------- regles de descart
def motiu_descart(text):
    """Torna el motiu pel qual NO s'ha d'enllaçar (o None si és enllaçable)."""
    n = normalitza(text)
    if not n:
        return "buit"
    if "pendent" in n:
        return "pendent de revisar"
    if n in {"tarragona", "tgn", "tarragona tarragona"}:
        return "només Tarragona"
    if re.search(r"\bbarri\b", n):
        return "barri sencer"
    base = _sense_ciutat(normalitza(_fragments(text)[0])) if _fragments(text) else n
    if base in BARRIS:
        return "barri sencer"
    if ";" in text or re.search(r"\brecorregut\b", n):
        return "més d'un lloc / recorregut"
    if len(re.split(r"\s[-–—]\s", text)) >= 3:
        return "més d'un lloc / recorregut"
    # "X i Y" amb Y que comença com un nom de lloc (p. ex. "MNAT i Teatre de Tàrraco")
    for m in re.finditer(r"\si\s", text):
        esquerra, dreta = text[:m.start()].strip(), text[m.end():].strip()
        primera = normalitza(dreta).split()[:1]
        if esquerra and primera and primera[0] in _INICI_LLOC and dreta[:1].isupper():
            return "més d'un lloc"
    return None


# --------------------------------------------------------------------------- tipus d'espai
def tipus_espai(nom):
    n = normalitza(nom)
    regles = [
        (r"\bmuseu|\bmnat\b|\bmamt\b", "Museu"),
        (r"\bteatre|\bauditori|\bteatret\b", "Teatre / auditori"),
        (r"\bsala (de )?concerts|\bmusica\b|\bsala zero\b", "Sala de concerts"),
        (r"\bbar\b|\brestaurant|\bcerveseria|\bcafe\b|\bbraseria|\bbodega|\btaverna|\bpub\b|\bvermuteria", "Bar / restaurant"),
        (r"\bllibreria|\blibreria", "Llibreria"),
        (r"\bgaleria|\bart\b", "Galeria / art"),
        (r"\bcentre civic|\bespai jove|\bbiblioteca|\bcasal\b|\boficina jove|\bpunt de lectura|\blocal\b", "Espai jove / cívic"),
        (r"\besglesia|\bcapella|\bcatedral|\bromana?\b|\bcastell|\bmuralla|\bpretori|\bamfiteatre|\bcirc\b|\bvilla\b|\bpedrera|\bconjunt", "Patrimoni"),
    ]
    for patro, tipus in regles:
        if re.search(patro, n):
            return tipus
    return "Altres"


def nom_net(text):
    """Nom per a una fitxa nova: el primer fragment, sense 'Tarragona' ni prefixos d'espai."""
    base = _fragments(text)[0] if _fragments(text) else (text or "")
    base = re.sub(r"(?i)\s*[,\-–]?\s*\b(de\s+)?(tarragona|tgn)\b\s*$", "", base).strip(" ,-–")
    base = re.sub(r"(?i)^vest[ií]bul\s+(del\s+|de\s+l')?", "", base).strip()
    if base.isupper():
        base = base.title()
    return base[:1].upper() + base[1:] if base else base


def adreca_del_text(text):
    resta = _resta(text)
    if not resta:
        return ""
    trossos = [s.strip() for s in re.split(r",|·", resta) if s.strip()]
    trossos = [s for s in trossos if normalitza(s) not in {"tarragona", "tgn"} and not re.fullmatch(r"43\d{3}.*", s)]
    adreca = ", ".join(trossos)
    return adreca if adreca and _sembla_adreca(trossos[0]) else ""


# --------------------------------------------------------------------------- matcher
class LlocMatcher:
    def __init__(self, token=None, llocs=None, dry_run=False, log=print, geocodifica=True):
        """llocs: llista opcional [{id, nom, adreca}] (per a proves sense Notion)."""
        self.token = token
        self.dry_run = dry_run
        self.log = log
        self.geocodifica = geocodifica
        self._darrera_geo = 0.0
        self.creats = []          # fitxes creades en aquesta execució
        self.descartats = []      # (text, motiu)
        self.llocs = []
        for l in (llocs if llocs is not None else self._carrega()):
            self._afegeix(l)

    # ---- Notion
    def _h(self):
        return {"Authorization": f"Bearer {self.token}", "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json"}

    def _carrega(self):
        out, cos = [], {"page_size": 100}
        while True:
            r = requests.post(f"{NOTION_API}/data_sources/{DS_LLOCS}/query", headers=self._h(), json=cos, timeout=30)
            r.raise_for_status()
            d = r.json()
            for p in d.get("results", []):
                pr = p.get("properties", {})
                nom = "".join(x.get("plain_text", "") for x in (pr.get("Nom") or {}).get("title", []))
                adr = "".join(x.get("plain_text", "") for x in (pr.get("Adreça") or {}).get("rich_text", []))
                out.append({"id": p["id"], "nom": nom, "adreca": adr})
            if not d.get("has_more"):
                return out
            cos["start_cursor"] = d["next_cursor"]

    def _afegeix(self, l):
        nom = l["nom"]
        sense_parens = re.sub(r"\(.*?\)", " ", nom)
        l = dict(l)
        l["claus"] = {clau(nom), clau(sense_parens)} - {""}
        l["adreca_clau"] = _adreca_clau(l.get("adreca") or "") if l.get("adreca") else None
        self.llocs.append(l)

    def _per_nom(self, nom):
        n = normalitza(nom)
        return next((l for l in self.llocs if normalitza(l["nom"]) == n), None)

    # ---- cerca
    def troba(self, text):
        """Torna (lloc, regla) o (None, motiu)."""
        motiu = motiu_descart(text)
        if motiu:
            return None, motiu
        complet = clau(text)
        frags = [clau(f) for f in _fragments(text)]
        frags = [f for f in frags if f]
        crus = [normalitza(f) for f in _fragments(text)] + [normalitza(text)]   # sense treure "Tarragona"

        # 0) àlies (la pedrera primer)
        if _PEDRERA.search(normalitza(text)):
            l = self._per_nom("Pedrera del Mèdol")
            if l:
                return l, "àlies"
        for f in frags + crus + [complet]:
            for alies, nom in sorted(ALIES.items(), key=lambda kv: -len(kv[0])):
                if f == alies or re.search(rf"\b{re.escape(alies)}\b", f):
                    l = self._per_nom(nom)
                    if l:
                        return l, "àlies"
        # a) exacte
        for f in frags:
            for l in self.llocs:
                if f in l["claus"]:
                    return l, "exacte"
        # b) un nom conté l'altre (només amb paraules que identifiquin; el més llarg guanya)
        candidats = []
        for f in frags + [complet] + crus[-1:]:
            if len(f) < 4:
                continue
            for l in self.llocs:
                for c in l["claus"]:
                    if len(c) < 4 or not (_significatives(c) or len(c.split()) >= 2):
                        continue
                    # el nom del lloc dins del text; o el text (que identifiqui) dins del nom
                    if re.search(rf"\b{re.escape(c)}\b", f) or (
                            _significatives(f) and re.search(rf"\b{re.escape(f)}\b", c)):
                        candidats.append((len(c), l))
            if candidats:
                return max(candidats, key=lambda x: x[0])[1], "conté"
        # c) adreça
        adreces = [_resta(text)] + [x for x in _fragments(text) if _sembla_adreca(x)]
        for a in adreces:
            carrer, num = _adreca_clau(a) if a else ("", None)
            if not carrer or not num:
                continue
            for l in self.llocs:
                if l["adreca_clau"] and l["adreca_clau"][1] == num and l["adreca_clau"][0] and (
                        l["adreca_clau"][0] == carrer or l["adreca_clau"][0] in carrer or carrer in l["adreca_clau"][0]):
                    return l, "adreça"
        # d) difús
        millor, punts = None, 0
        for f in frags:
            for l in self.llocs:
                for c in l["claus"]:
                    if not (_significatives(c) & _significatives(f)):
                        continue
                    s = token_set_ratio(f, c)
                    if s > punts:
                        millor, punts = l, s
        if millor and punts >= LLINDAR_DIFUS:
            return millor, f"difús ({punts:.0f})"
        return None, "sense coincidència"

    def troba_o_crea(self, text):
        """Torna (lloc_id o None, descripció de què ha passat)."""
        l, regla = self.troba(text)
        if l:
            return l["id"], f"{regla} → {l['nom']}"
        if regla != "sense coincidència":
            self.descartats.append((text, regla))
            self.log(f"  [sense enllaçar] «{text}»: {regla}")
            return None, f"descartat ({regla})"
        nou = self._crea(text)
        return (nou["id"] if nou else None), (f"nou → {nou['nom']}" if nou else "no s'ha pogut crear")

    # ---- creació
    def _geo(self, nom, adreca):
        if not self.geocodifica:
            return None
        consultes = ([f"{adreca}, Tarragona"] if adreca else []) + [f"{nom}, Tarragona", nom]
        for q in consultes:
            espera = 1.1 - (time.time() - self._darrera_geo)
            if espera > 0:
                time.sleep(espera)
            self._darrera_geo = time.time()
            try:
                r = requests.get(NOMINATIM, params={"q": q, "format": "json", "limit": 1, "countrycodes": "es",
                                                    "viewbox": VIEWBOX, "bounded": 1},
                                 headers={"User-Agent": USER_AGENT, "Accept-Language": "ca"}, timeout=20)
                if r.ok and r.json():
                    d = r.json()[0]
                    return float(d["lat"]), float(d["lon"])
            except Exception as e:  # noqa: BLE001
                self.log(f"  Avís Nominatim ({q}): {e}")
        return None

    def _crea(self, text):
        nom = nom_net(text)
        if not nom or not _significatives(normalitza(nom)) and len(normalitza(nom)) < 4:
            self.descartats.append((text, "nom massa genèric"))
            return None
        # Ja existeix (també les creades en aquesta execució)?
        ja = self._per_nom(nom)
        if ja:
            return ja
        adreca = adreca_del_text(text)
        coords = self._geo(nom, adreca)
        tipus = tipus_espai(nom)
        props = {
            "Nom": {"title": [{"text": {"content": nom[:200]}}]},
            "Tipus d'espai": {"select": {"name": tipus}},
            "Google Maps": {"url": f"https://www.google.com/maps/search/?api=1&query={quote_plus(nom + ' Tarragona')}"},
        }
        if adreca:
            props["Adreça"] = {"rich_text": [{"text": {"content": adreca[:200]}}]}
        if coords:
            props["Latitud"] = {"number": round(coords[0], 6)}
            props["Longitud"] = {"number": round(coords[1], 6)}
            props["Precisió"] = {"select": {"name": "Aproximada (OSM)"}}
            props["Revisar"] = {"rich_text": [{"text": {"content": "Creat automàticament: comprova la ubicació"}}]}
        else:
            props["Precisió"] = {"select": {"name": "Pendent"}}
            props["Revisar"] = {"rich_text": [{"text": {"content": "Creat automàticament: falten coordenades"}}]}

        if self.dry_run or not self.token:
            nou = {"id": f"(nou:{nom})", "nom": nom, "adreca": adreca}
        else:
            r = requests.post(f"{NOTION_API}/pages", headers=self._h(), timeout=30,
                              json={"parent": {"data_source_id": DS_LLOCS}, "properties": props})
            if not r.ok:
                self.log(f"  ERROR creant el lloc «{nom}»: {r.status_code} {r.text[:300]}")
                return None
            nou = {"id": r.json()["id"], "nom": nom, "adreca": adreca}
        nou["coords"] = coords
        nou["tipus"] = tipus
        self._afegeix(nou)
        self.creats.append(nou)
        self.log(f"  [lloc nou{' (simulat)' if self.dry_run else ''}] {nom} · {tipus}"
                 f"{' · ' + adreca if adreca else ''} · {'amb coordenades' if coords else 'SENSE coordenades'}")
        return nou
