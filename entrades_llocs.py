# -*- coding: utf-8 -*-
"""
Enllaç d'entrades d'una activitat, amb plans B per lloc.

Ordre:
  1. L'enllaç propi de l'activitat (URL reserva / URL entrades), si n'hi ha.
  2. Si l'activitat NO és gratuïta: la "URL entrades" del seu lloc a 📍 LLOCS
     (Teatre Tarragona, Tarraco Arena, Palau Firal, Sala Trono, Sala Zero...).
     El lloc es busca per la relació "Lloc (fitxa)" o, si no n'hi ha, pel text del lloc.
  3. Si l'activitat NO és gratuïta i ve de l'agenda de l'Ajuntament: la web
     general d'entrades de l'Ajuntament.
Les activitats gratuïtes mai porten enllaç genèric (només el propi, si en tenen).

Els enllaços de cada lloc es canvien a Notion (📍 LLOCS → URL entrades), no aquí.
"""

import re
import unicodedata

import requests

DS_LLOCS = "bc7d9e22-f18d-4f06-bb83-4bee33e0cd32"
ENTRADES_AJUNTAMENT = "https://entrades.tarragona.cat/"
_PARAULES_BUIDES = {"sala", "teatre", "de", "del", "la", "el", "l", "i", "espai", "tarragona",
                    # massa comunes per identificar un lloc soles
                    "tarraco", "palau", "centre", "civic", "placa", "auditori", "museu", "nova",
                    "casa", "parc", "carrer", "rambla", "port", "camp", "mart", "magatzem", "congressos"}


def _norm(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def carrega(token):
    """Llegeix 📍 LLOCS i torna [{id, nom, url}] dels llocs que tenen URL entrades."""
    h = {"Authorization": f"Bearer {token}", "Notion-Version": "2025-09-03",
         "Content-Type": "application/json"}
    cos = {"page_size": 100, "filter": {"property": "URL entrades", "url": {"is_not_empty": True}}}
    out = []
    try:
        while True:
            r = requests.post(f"https://api.notion.com/v1/data_sources/{DS_LLOCS}/query",
                              headers=h, json=cos, timeout=30)
            r.raise_for_status()
            d = r.json()
            for p in d.get("results", []):
                pr = p.get("properties", {})
                nom = "".join(x.get("plain_text", "") for x in (pr.get("Nom") or {}).get("title", []))
                url = (pr.get("URL entrades") or {}).get("url")
                if url:
                    out.append({"id": p["id"], "nom": nom, "url": url})
            if not d.get("has_more"):
                break
            cos["start_cursor"] = d["next_cursor"]
    except Exception as e:  # noqa: BLE001  (mai ha de trencar la publicació)
        print(f"  -> Avís: no s'han pogut llegir els enllaços d'entrades dels llocs ({e})")
    return out


def des_de_pagines(pagines, prop):
    """Igual que carrega(), però a partir de pàgines de LLOCS ja descarregades.
    `prop(pagina, nom_propietat)` ha de tornar el valor de la propietat."""
    out = []
    for p in pagines:
        url = prop(p, "URL entrades")
        if url:
            out.append({"id": p["id"], "nom": prop(p, "Nom") or "", "url": url})
    return out


def es_gratuit(preu_text="", preu_num=None):
    t = (preu_text or "").strip().lower()
    if t and "pendent" not in t:
        if any(x in t for x in ("gratu", "gratis", "lliure", "free", "de franc")):
            return True
        return not re.search(r"\d", t) and preu_num in (None, 0)   # p.ex. "Consultar": no sabem → no posar genèric
    if preu_num is not None:
        try:
            return float(preu_num) == 0
        except (TypeError, ValueError):
            return True
    return True   # criteri AgendaTGN: sense preu = gratuït


def lloc_de(llocs, lloc_text="", lloc_ids=()):
    ids = {i.replace("-", "") for i in (lloc_ids or [])}
    for l in llocs:
        if l["id"].replace("-", "") in ids:
            return l
    t = _norm(lloc_text)
    if not t:
        return None
    for l in llocs:
        n = _norm(l["nom"])
        if n and (n in t or t in n):
            return l
    # Coincidència per paraula distintiva (p.ex. "Trono", "Zero", "Arena")
    paraules_t = set(t.split()) - _PARAULES_BUIDES
    for l in llocs:
        clau = set(_norm(l["nom"]).split()) - _PARAULES_BUIDES
        if clau and clau & paraules_t and len(max(clau & paraules_t, key=len)) >= 4:
            return l
    return None


def resol(url_propi="", preu_text="", preu_num=None, lloc_text="", lloc_ids=(),
          de_ajuntament=False, llocs=None):
    """Torna l'enllaç d'entrades a fer servir ("" si no n'hi ha cap)."""
    if url_propi:
        return url_propi
    if es_gratuit(preu_text, preu_num):
        return ""
    l = lloc_de(llocs or [], lloc_text, lloc_ids)
    if l:
        return l["url"]
    if de_ajuntament:
        return ENTRADES_AJUNTAMENT
    return ""
