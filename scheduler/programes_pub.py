"""Publicació agrupada dels 🎪 Programes (festivals, cicles, festes de barri...).

Decisió del 23/11/2026:
- Les activitats d'un programa marcat «Agrupar en publicacions» NO tenen post
  individual, excepte les marcades «Destacada».
- En lloc d'això, el programa té un post propi a X, Threads i Facebook:
  un avançament 5 dies abans del primer dia i un recordatori el primer dia.
- El post porta la llista d'actes (les activitats aprovades del programa).

Es crida des de publish_scheduler.main(); fa servir les seves funcions
(Notion, imatges, publicació) per no duplicar codi.
"""
import os
from datetime import datetime, timedelta

import requests

PROGRAMES_DS_ID = os.environ.get("NOTION_PROGRAMES_DS_ID") or "7adf4d3a-6ed6-483b-ade4-be5286ebc087"

TIPUS_ETIQUETA = {
    "Festival": "FESTIVAL", "Cicle": "CICLE", "Festa de barri": "FESTA DE BARRI",
    "Festa major": "FESTA MAJOR", "Jornades": "JORNADES", "Fira": "FIRA",
}
DIES_CURTS = ["dl", "dt", "dc", "dj", "dv", "ds", "dg"]


def carrega_agrupats(ps):
    """Programes amb «Agrupar en publicacions» marcat."""
    url = f"{ps.NOTION_API}/data_sources/{PROGRAMES_DS_ID}/query"
    payload = {"filter": {"property": "Agrupar en publicacions", "checkbox": {"equals": True}}}
    out = []
    while True:
        r = requests.post(url, headers=ps.notion_headers(), json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("results", []))
        if not data.get("has_more"):
            return out
        payload["start_cursor"] = data["next_cursor"]


def programes_de_activitat(page):
    rel = (page["properties"].get("Programa") or {}).get("relation", [])
    return {x["id"] for x in rel}


def finestres(programes):
    """{programa_id: (inici, fi)} dels programes que tenen «Dates» omplertes.
    Només aquests agrupen: un cicle llarg sense dates (p. ex. un cicle de tot l'any)
    continua amb posts individuals, perquè un sol post no el pot cobrir."""
    out = {}
    for prog in programes:
        d = (prog["properties"].get("Dates") or {}).get("date") or {}
        if d.get("start"):
            ini = datetime.fromisoformat(d["start"][:10]).date()
            fi = datetime.fromisoformat(d["end"][:10]).date() if d.get("end") else ini
            out[prog["id"]] = (ini, fi)
    return out


def dins_programa(ps, page, fin):
    """True si l'activitat cau dins les dates d'algun programa agrupat."""
    d = _data(ps, page["properties"])
    if not d:
        return False
    return any(fin[pid][0] <= d <= fin[pid][1] for pid in programes_de_activitat(page) if pid in fin)


def _data(ps, props, camp="Data inici"):
    raw = ps.get_prop_text(props, camp)
    return datetime.fromisoformat(raw.split("T")[0]).date() if raw else None


def _actes(ps, prog_id, activitats):
    """Activitats aprovades del programa, ordenades per data i hora."""
    actes = []
    for page in activitats:
        if prog_id not in programes_de_activitat(page):
            continue
        props = page["properties"]
        d = _data(ps, props)
        if not d:
            continue
        actes.append({
            "data": d,
            "hora": ps.get_prop_text(props, "Hora") or "",
            "nom": ps.get_prop_text(props, "Name") or "",
            "lloc": ps.get_prop_text(props, "Lloc") or "",
            "props": props,
        })
    actes.sort(key=lambda a: (a["data"], ps._hora_ordre(a["hora"])))
    return actes


def _rang(ps, d1, d2):
    if not d2 or d2 == d1:
        return ps.data_llarga(d1)
    if d1.month == d2.month:
        return f"del {d1.day} al {ps.data_llarga(d2)}"
    return f"del {ps.data_llarga(d1)} al {ps.data_llarga(d2)}"


def _linia_acte(ps, a, amb_lloc=True):
    hora = ps._hora_txt(a["hora"])
    parts = [f"{DIES_CURTS[a['data'].weekday()]} {a['data'].day}"]
    if hora:
        parts.append(hora)
    parts.append(a["nom"])
    if amb_lloc and a["lloc"]:
        parts.append(a["lloc"])
    return "▪️ " + " · ".join(parts)


def compon(ps, prog, actes, inici, fi, mode, limit=None, mida=len):
    """TIPUS | 🎉 Nom / descripció / 📅 dates / llista d'actes (tantes com hi càpiguen)."""
    props = prog["properties"]
    nom = (ps.get_prop_text(props, "Nom") or "").strip()
    tipus = ps.get_prop_text(props, "Tipus") or ""
    etiqueta = TIPUS_ETIQUETA.get(tipus, "PROGRAMA")
    desc = (ps.get_prop_text(props, "Descripció") or "").strip()
    primera = desc.split(". ")[0].rstrip(".") + "." if desc else ""
    quan = ("Comença avui · " if mode == "dia" else "") + _rang(ps, inici, fi)
    n = len(actes)

    def munta(text_desc, n_actes, amb_lloc):
        parts = [f"{etiqueta} | 🎉 {nom}"]
        if text_desc:
            parts.append(text_desc)
        parts.append(f"📅 {quan}")
        if n_actes:
            llista = "\n".join(_linia_acte(ps, a, amb_lloc) for a in actes[:n_actes])
            if n > n_actes:
                llista += f"\n… i {n - n_actes} actes més"
            parts.append(llista)
        return "\n\n".join(parts)

    if limit is None:
        return munta(desc, min(n, 15), True)
    # Prioritat: que hi càpiguen com més actes millor; després, la descripció i els llocs
    combinacions = [(desc, True), (primera, True), (desc, False), (primera, False), ("", True), ("", False)]
    for k in range(min(n, 15), -1, -1):
        for text_desc, amb_lloc in combinacions:
            out = munta(text_desc, k, amb_lloc)
            if mida(out) <= limit:
                return out
    return munta("", 0, False)


def _imatge(ps, prog, actes, inici):
    """Imatge del programa; si no en té, la del primer acte que en tingui; si no, la plantilla."""
    props = prog["properties"]
    nom = ps.get_prop_text(props, "Nom") or ""
    etiqueta = ps.etiqueta_data(inici)
    if ps.get_notion_image_url(props):
        return ps.get_activity_image_bytes(props, nom, "Festa popular", etiqueta)
    for a in actes:
        if ps.get_notion_image_url(a["props"]):
            return ps.get_activity_image_bytes(a["props"], nom, "Festa popular", etiqueta)
    return ps.get_activity_image_bytes({}, nom, "Festa popular", etiqueta)


def publica_programes(ps, programes, activitats, ara):
    """Publica els posts de programa que toquin avui. Només a partir de l'hora dels posts del dia."""
    if ara < ps._a_les(ara, ps.HORA_POSTS_DIA) and not ps._publicar_tot_ara():
        return
    import threads_pub
    import veu_agendatgn as veu
    avui = ara.date()
    for prog in programes:
        props = prog["properties"]
        nom = ps.get_prop_text(props, "Nom") or "(programa)"
        actes = _actes(ps, prog["id"], activitats)
        # Aprovat si el programa ho està o si té alguna activitat aprovada
        if not (ps.get_prop_text(props, "Aprovada publicació") or actes):
            continue
        dates = props.get("Dates", {}).get("date") or {}
        if not dates.get("start"):
            continue   # sense dates no s'agrupa (vegeu finestres())
        inici = datetime.fromisoformat(dates["start"][:10]).date()
        fi = datetime.fromisoformat(dates["end"][:10]).date() if dates.get("end") else inici
        actes = [a for a in actes if inici <= a["data"] <= fi]
        modes = []
        if not ps.get_prop_text(props, "Publicat Dia") and avui == inici:
            modes.append("dia")
        if (not ps.get_prop_text(props, "Publicat Avançament")
                and inici - timedelta(days=ps.DAYS_BEFORE) <= avui < inici):
            modes.append("avancament")
        for mode in modes:
            print(f"[🎪 {nom}] Post de programa ({mode}) amb {len(actes)} actes...")
            imatge = _imatge(ps, prog, actes, inici)
            ok = {}
            try:
                ok["X"] = ps.post_to_twitter(compon(ps, prog, actes, inici, fi, mode, 280, ps._x_len),
                                             image_bytes=imatge)
            except Exception as e:  # noqa: BLE001
                print(f" -> ERROR X: {e!r}")
                ok["X"] = False
            try:
                if threads_pub.configurat():
                    ok["Threads"] = bool(threads_pub.publicar_post(
                        compon(ps, prog, actes, inici, fi, mode, threads_pub.LIMIT)))
            except Exception as e:  # noqa: BLE001
                print(f" -> Avís Threads: {e}")
                ok["Threads"] = False
            llarg = compon(ps, prog, actes, inici, fi, mode)
            if ps.FACEBOOK_PAGE_ID and ps.FACEBOOK_PAGE_TOKEN:
                try:
                    ok["Facebook"] = ps.post_to_facebook(llarg, image_bytes=imatge)
                except Exception as e:  # noqa: BLE001
                    print(f" -> ERROR Facebook: {e!r}")
                    ok["Facebook"] = False
            print("    Resultat: " + ", ".join(f"{k} {'OK' if v else 'ERROR'}" for k, v in ok.items()))
            if any(ok.values()):
                ps.mark_published(prog["id"], "Publicat Dia" if mode == "dia" else "Publicat Avançament")
                veu.registrar_post(llarg, "Post individual", avui.isoformat(), f"programa-{prog['id']}-{mode}")
