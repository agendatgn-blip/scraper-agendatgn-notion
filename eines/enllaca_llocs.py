#!/usr/bin/env python3
"""Pas de reparació: enllaça "Lloc (fitxa)" de les activitats que no en tenen.

Recorre les Activitats amb "Data inici" ≥ avui i "Lloc (fitxa)" buit i, a partir
del text de "Lloc", les enllaça amb la seva fitxa de 📍 LLOCS (o en crea una de nova
si és un lloc concret que encara no hi és). Només escriu "Lloc (fitxa)": no toca cap
altre camp de les activitats ni dels llocs existents, i no esborra res.

    python eines/enllaca_llocs.py            # ho fa
    python eines/enllaca_llocs.py --dry-run  # només llista què faria (no escriu res)

Variables: NOTION_TOKEN (i opcionalment NOTION_ACTIVITATS_DB_ID).
"""

import os
import sys
import datetime as dt

import requests

ARREL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ARREL)

from lloc_matcher import LlocMatcher, NOTION_API, NOTION_VERSION  # noqa: E402

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DS_ACTIVITATS = os.environ.get("NOTION_ACTIVITATS_DB_ID") or "3705d017-2af5-8001-a94f-000b2226712d"
H = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": NOTION_VERSION, "Content-Type": "application/json"}


def text(props, nom):
    p = props.get(nom) or {}
    t = p.get("type")
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in p.get(t, [])).strip()
    return ""


def activitats_sense_lloc():
    avui = dt.date.today().isoformat()
    cos = {"page_size": 100, "filter": {"and": [
        {"property": "Data inici", "date": {"on_or_after": avui}},
        {"property": "Lloc (fitxa)", "relation": {"is_empty": True}},
    ]}}
    out = []
    while True:
        r = requests.post(f"{NOTION_API}/data_sources/{DS_ACTIVITATS}/query", headers=H, json=cos, timeout=30)
        r.raise_for_status()
        d = r.json()
        out += d.get("results", [])
        if not d.get("has_more"):
            return out
        cos["start_cursor"] = d["next_cursor"]


def main():
    dry = "--dry-run" in sys.argv
    print(f"Enllaçar llocs — {dt.date.today().isoformat()}" + ("  [DRY-RUN: no s'escriu res]" if dry else ""))
    m = LlocMatcher(NOTION_TOKEN, dry_run=dry)
    print(f"Fitxes a 📍 LLOCS: {len(m.llocs)}")
    acts = activitats_sense_lloc()
    print(f"Activitats futures sense 'Lloc (fitxa)': {len(acts)}\n")

    enllacades, errors = [], 0
    for p in acts:
        props = p["properties"]
        nom, lloc = text(props, "Name") or "(sense nom)", text(props, "Lloc")
        lid, info = m.troba_o_crea(lloc)
        print(f"- {nom[:60]} | «{lloc}» → {info}")
        if not lid:
            continue
        if not dry:
            r = requests.patch(f"{NOTION_API}/pages/{p['id']}", headers=H, timeout=30,
                               json={"properties": {"Lloc (fitxa)": {"relation": [{"id": lid}]}}})
            if not r.ok:
                errors += 1
                print(f"  ERROR enllaçant: {r.status_code} {r.text[:300]}")
                continue
        enllacades.append((nom, lloc, info))

    amb = [c for c in m.creats if c.get("coords")]
    sense = [c for c in m.creats if not c.get("coords")]
    verb = "s'enllaçarien" if dry else "enllaçades"
    linies = [
        f"Activitats {verb}: {len(enllacades)} de {len(acts)}",
        f"Llocs nous{' (simulats)' if dry else ''}: {len(m.creats)} — {len(amb)} amb coordenades, {len(sense)} sense",
        *[f"  · {c['nom']} ({c['tipus']}){' — ' + c['adreca'] if c.get('adreca') else ''}"
          f" — {'amb coordenades' if c.get('coords') else 'SENSE coordenades'}" for c in m.creats],
        f"Sense enllaçar: {len(m.descartats)}",
        *[f"  · «{t}»: {motiu}" for t, motiu in m.descartats],
        f"Errors: {errors}",
    ]
    print("\n" + "\n".join(linies))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(f"### Enllaçar llocs{' (dry-run)' if dry else ''}\n\n```\n" + "\n".join(linies) + "\n```\n")


if __name__ == "__main__":
    main()
