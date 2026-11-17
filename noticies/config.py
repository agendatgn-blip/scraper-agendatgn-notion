"""NOTÍCIES CULTURALS TGN · configuració.

Per afegir una font: afegeix una línia a FEEDS (RSS) o a PAGINES (webs sense RSS).
Tot es pot tocar des de GitHub amb el llapis ✏️.
"""
import os

# Base de Notion 📰 Notícies culturals TGN
NOTION_DB = os.environ.get("NOTION_NOTICIES_DB_ID") or "41b5d0172af58146a55fd54c546b3b2b"
NOTION_URL = "https://www.notion.so/" + NOTION_DB


def gn(q):
    """Cerca de Google News en català."""
    return f"https://news.google.com/rss/search?q={q}+when:2d&hl=ca&gl=ES&ceid=ES:ca"


# (url, mitjà, és_cultural) -> si és_cultural és False, el filtre de paraules ha de trobar cultura
FEEDS = [
    ("https://www.tarragonaradio.cat/category/cultura/feed/", "Tarragona Ràdio", True),
    ("https://www.diaridetarragona.com/rss/cultura", "Diari de Tarragona", True),
    ("https://www.tarragonaradio.cat/feed/", "Tarragona Ràdio", False),
    ("https://www.tarragonadigital.com/rss", "Tarragona Digital", False),
    (gn("Tarragona+(concert+OR+festival+OR+museu+OR+teatre+OR+exposició)"), "Google News", False),
    (gn("Tarragona+(patrimoni+OR+cultura+OR+cinema+OR+llibre)"), "Google News", False),
]

# Webs sense RSS: (url del llistat, tros que han de tenir els enllaços de notícia, mitjà)
# Primer es llegeixen directament; si falla i hi ha FIRECRAWL_API_KEY, es fa servir Firecrawl.
PAGINES = [
    ("https://www.mnat.cat/noticies/", "/noticies/", "MNAT"),
    ("https://www.tarragona.cat/cultura/noticies", "/cultura/noticies/noticies-20", "Ajuntament de Tarragona"),
    ("https://www.tarragona.cat/patrimoni/noticies", "/patrimoni/noticies/noticies-20", "Ajuntament de Tarragona"),
]

# Límits (robustesa)
MAX_NOTICIES = 20          # màxim que passen per la IA a cada captura
HORES_ENRERE = 36          # només notícies d'aquestes hores
TEMPS_MAX_CAPTURA = 10 * 60  # segons; el workflow talla als 15 min
MAX_PRODUCCIO = 3          # carrusels per execució de producció
PUNTUACIO_MINIMA = 2       # per sota d'això no entra a Notion

CATEGORIES = ["Música", "Teatre", "Exposició", "Museus", "Patrimoni", "Cinema", "Literatura",
              "Festivals", "Festa popular", "Dansa", "Espais", "Altres"]

# Filtre previ sense IA (sense accents ni majúscules). CULTURA: inici de paraula. EXCLOURE: paraula sencera.
# Es descarta si té alguna paraula d'EXCLOURE i cap de CULTURA, o si ve d'una font general i no té cap de CULTURA.
CULTURA = [
    "concert", "festival", "museu", "mnat", "teatre", "exposici", "expo", "patrimoni", "cultura",
    "cultural", "cinema", "pel·lícula", "pelicula", "llibre", "llibreria", "escriptor", "escriptora",
    "poesia", "dansa", "música", "musica", "músic", "banda", "coral", "òpera", "opera", "circ",
    "castell", "colla", "santa tecla", "sant magí", "tarraco viva", "festival rec", "dixie", "art ",
    "artista", "galeria", "fotografia", "festa major", "carnaval", "museo", "teatro", "exposición",
    "libro", "cine", "danza", "biblioteca", "arxiu", "romà", "romana", "amfiteatre", "circ romà",
    "tallers oberts", "estrena", "gira", "entrades", "programació", "premi", "certamen", "jazz",
    "rock", "flamenc", "sala zero", "el cau", "metropol", "teatre tarragona", "caixaforum",
]
EXCLOURE = [
    "erc", "junts", "psc", "pp", "vox", "comuns", "eleccions", "electoral", "ple municipal",
    "regidor", "alcalde", "alcaldessa", "parlament", "govern", "partit", "candidat", "vaga",
    "accident", "mort", "mor", "detingut", "detinguts", "policia", "mossos", "incendi", "robatori",
    "judici", "jutjat", "condemna", "futbol", "nàstic", "nastic", "bàsquet", "handbol", "lliga",
    "elecciones", "detenido", "accidente", "fallece", "huelga", "incendio",
]
