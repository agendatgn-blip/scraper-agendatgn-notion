"""Nota del ganxo (0-100) per als titulars, en català.

Adaptació dels cinc criteris de hookscore.py de l'Instagram Agent Skill
(github.com/Jakeschincariol/instagram-agent-skill, llicència MIT): llargada que es llegeix
en menys de 3 segons, alguna cosa concreta (xifra o nom), alguna cosa en joc, el més
important al principi i parlar a qui llegeix. Serveix per comparar titulars entre ells,
no per predir visualitzacions.
"""
import re

NUMEROS = {"dos", "dues", "tres", "quatre", "cinc", "sis", "set", "vuit", "nou", "deu", "onze",
           "dotze", "vint", "trenta", "quaranta", "cinquanta", "cent", "mil", "milers", "centenars",
           "primer", "primera", "segon", "segona", "tercer", "tercera", "mig", "doble"}
EN_JOC = {"ningú", "mai", "torna", "tornen", "reobre", "obre", "tanca", "tanquen", "adeu", "nou", "nova",
          "nous", "noves", "estrena", "primer", "primera", "últim", "última", "gratis", "gratuït", "gratuïta",
          "només", "secret", "sense", "encara", "ja", "per fi", "canvia", "rècord", "exhaurit", "exhaurides",
          "arriba", "arriben", "torna", "desapareix", "perill", "salva", "premi", "històric", "història"}
TU = {"tu", "et", "t", "teu", "teva", "vas", "pots", "has", "saps", "vols", "trobaràs", "tens", "fes"}

PARAULA = re.compile(r"[\wÀ-ÿ·'’-]+", re.UNICODE)


def _paraules(t):
    return PARAULA.findall(t or "")


def criteris(titular):
    w = _paraules(titular)
    n = len(w)
    baixes = [x.lower().strip("'’") for x in w]
    # 1 · llargada
    if 4 <= n <= 8:
        llarg = 100
    elif n < 4:
        llarg = 55
    else:
        llarg = max(0, 100 - 15 * (n - 8))
    # 2 · concreció: xifra o nom propi (majúscula que no és la primera paraula)
    xifra = bool(re.search(r"\d", titular)) or any(x in NUMEROS for x in baixes)
    nom = any(x[:1].isupper() for x in w[1:]) or (titular.isupper() and n > 0)
    concret = min(100, (60 if xifra else 0) + (50 if nom else 0)) or 15
    # 3 · en joc
    text_b = " ".join(baixes)
    joc = 100 if any(x in baixes or (" " in x and x in text_b) for x in EN_JOC) else 20
    # 4 · el més important al principi
    primeres = baixes[:3]
    davant = 100 if (any(x in EN_JOC or x in NUMEROS or x.isdigit() for x in primeres)
                     or any(y[:1].isupper() for y in w[1:3])) else 40
    # 5 · parla a qui llegeix
    tu = 100 if any(x in TU for x in baixes) else 50
    return {"llargada": llarg, "concreció": concret, "en joc": joc, "davant": davant, "a tu": tu}


def nota(titular):
    c = criteris(titular)
    return round(0.25 * c["llargada"] + 0.25 * c["concreció"] + 0.25 * c["en joc"]
                 + 0.15 * c["davant"] + 0.10 * c["a tu"])


def millor(opcions):
    """Torna (titular, nota) de la millor opció."""
    puntuats = [(o, nota(o)) for o in opcions if o and o.strip()]
    if not puntuats:
        return "", 0
    return max(puntuats, key=lambda x: x[1])


if __name__ == "__main__":
    for t in ["El MNAT torna a la plaça del Rei el 4 de desembre",
              "Notícia sobre una exposició que s'inaugura aviat a la ciutat de Tarragona amb molts artistes",
              "Tallers Oberts: 2 caps de setmana per entrar als estudis"]:
        print(nota(t), criteris(t), t)
