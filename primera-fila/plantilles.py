"""
Plantilles HTML de Primera Fila (estil fanzine/riso: crema, blau, rosa, groc).
Cada funció torna l'HTML d'una pàgina A4.
"""
import base64
import os
from html import escape as e

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
MESOS = ["gener", "febrer", "març", "abril", "maig", "juny", "juliol", "agost",
         "setembre", "octubre", "novembre", "desembre"]
DIES = ["DILLUNS", "DIMARTS", "DIMECRES", "DIJOUS", "DIVENDRES", "DISSABTE", "DIUMENGE"]

CSS = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
:root { --blau:#1F4FC1; --rosa:#FF3EA5; --groc:#FFD60A; --crema:#F2ECDF; --tinta:#1A2F66; --magenta:#B8126B; }
html, body { margin:0; padding:0; background:var(--crema); }
.pg { width:210mm; height:297mm; padding:40px 44px 30px; background:var(--crema); color:var(--blau);
      font-family:'Archivo',sans-serif; display:flex; flex-direction:column; gap:14px; overflow:hidden;
      position:relative; page-break-after:always; break-after:page; }
.pg.full { padding:0; }
.bowl { font-family:'Bowlby One',sans-serif; font-weight:400; }
.mono { font-family:'Space Mono',monospace; font-weight:700; }
.cats { text-align:center; font-weight:800; font-size:12px; letter-spacing:.14em; flex-shrink:0; }
.hdr { display:flex; align-items:center; gap:16px; height:118px; flex-shrink:0; }
.hdr .bar { width:14px; height:118px; background:var(--rosa); flex-shrink:0; }
.hdr .tit { flex-grow:1; display:flex; flex-direction:column; gap:8px; min-width:0; }
.hdr .big { font-family:'Bowlby One',sans-serif; font-size:76px; line-height:.95; text-shadow:4px 4px 0 var(--rosa); white-space:nowrap; }
.chip { align-self:flex-start; background:var(--groc); color:var(--blau); font-size:13px; font-weight:800; padding:4px 10px; }
.stamp { width:118px; height:118px; border-radius:50%; background:var(--rosa); color:var(--crema); display:flex; flex-direction:column;
         align-items:center; justify-content:center; transform:rotate(-9deg); flex-shrink:0; text-align:center; }
.stamp b { font-family:'Bowlby One',sans-serif; font-weight:400; font-size:52px; line-height:.9; }
.stamp small { font-family:'Space Mono',monospace; font-weight:700; font-size:11px; letter-spacing:.12em; }
.foot { margin-top:auto; display:flex; justify-content:space-between; font-family:'Space Mono',monospace; font-size:11px;
        font-weight:700; border-top:3px solid var(--blau); padding-top:8px; flex-shrink:0; }
.row { display:flex; gap:14px; flex-shrink:0; }
.card { position:relative; flex:1 1 0; min-width:0; display:flex; border:2px dashed var(--blau); }
.card.feat { border:3px solid var(--blau); }
.card.v { flex-direction:column; }
.media { background:var(--blau); overflow:hidden; flex-shrink:0; }
.card.feat .media { background:var(--rosa); }
.media img { width:100%; height:100%; object-fit:cover; display:block; filter:grayscale(1) contrast(1.2) brightness(1.05); mix-blend-mode:screen; }
.media.buit { background:repeating-linear-gradient(45deg,#1F4FC1 0 10px,#5A80D9 10px 20px); }
.info { flex-grow:1; min-width:0; padding:10px 12px 11px; display:flex; flex-direction:column; gap:6px; }
.card.h .info { padding:16px 18px; gap:8px; }
.chips { display:flex; gap:6px; align-items:center; flex-wrap:wrap; }
.hora { background:var(--groc); font-family:'Bowlby One',sans-serif; padding:1px 8px; line-height:1.25; }
.cat { border:2px solid var(--rosa); color:var(--magenta); font-size:10.5px; font-weight:800; letter-spacing:.08em;
       padding:2px 7px; text-transform:uppercase; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:100%; }
.pin { width:22px; height:22px; border-radius:50%; background:var(--groc); border:2px solid var(--blau); font-weight:800;
       font-size:11px; display:inline-flex; align-items:center; justify-content:center; flex-shrink:0; }
.ttl { font-weight:800; line-height:1.12; text-transform:uppercase; }
.feat .ttl, .hero .ttl { font-family:'Bowlby One',sans-serif; font-weight:400; }
.blurb { font-size:13px; font-weight:500; line-height:1.45; color:var(--tinta); }
.venue { font-size:11.5px; font-weight:700; }
.preu { align-self:flex-start; padding:3px 8px; font-weight:800; text-transform:uppercase; letter-spacing:.06em; font-size:10.5px; }
.preu.free { background:var(--blau); color:var(--crema); }
.preu.paid { border:2px solid var(--blau); padding:1px 8px; }
.stick { position:absolute; top:-14px; right:12px; background:var(--rosa); color:var(--crema); font-family:'Bowlby One',sans-serif;
         font-size:14px; padding:4px 10px; transform:rotate(6deg); }
.sp { flex-grow:1; }
a { color:inherit; text-decoration:none; }
.sec { font-family:'Bowlby One',sans-serif; font-size:17px; color:var(--crema); background:var(--blau); align-self:flex-start; padding:3px 12px; }
.hatch-b { background:repeating-linear-gradient(45deg,#1F4FC1 0 10px,#5A80D9 10px 20px); }
.hatch-p { background:repeating-linear-gradient(45deg,#FF3EA5 0 12px,#F7A3CF 12px 24px); }
.cta { display:flex; align-items:center; justify-content:space-between; gap:16px; background:var(--groc); border:3px solid var(--blau);
       padding:14px 20px; color:var(--blau); flex-shrink:0; }
.cta .bt { background:var(--rosa); color:#1A1033; font-family:'Bowlby One',sans-serif; font-size:16px; padding:8px 12px; transform:rotate(4deg); white-space:nowrap; }
"""

FONTS = ('<link href="https://fonts.googleapis.com/css2?family=Bowlby+One&family=Anton&'
         'family=Archivo:wght@500;700;800&family=Space+Mono:wght@700&display=swap" rel="stylesheet">')


def asset_uri(nom):
    with open(os.path.join(ASSETS, nom), "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


def nom_dia(d):
    return f"{DIES[d.weekday()]} {d.day}"


def dates_txt(ini, fi):
    if not ini:
        return ""
    if fi and fi.month != ini.month:
        return f"DEL {ini.day} DE {MESOS[ini.month - 1].upper()} AL {fi.day} DE {MESOS[fi.month - 1].upper()}"
    return f"DEL {ini.day} AL {(fi or ini).day} DE {MESOS[ini.month - 1].upper()}"


def peu(ctx):
    return (f'<div class="foot"><span>PRIMERA FILA // @AGENDATGN</span>'
            f'<span>SETMANA {e(ctx["dates"])} · {{{{PAG}}}}</span></div>')


def capcalera(gran, chip, s1, s2, mida=76):
    return (f'<div class="hdr"><div class="bar"></div><div class="tit">'
            f'<span class="big" style="font-size:{mida}px">{e(gran)}</span><span class="chip">{e(chip)}</span></div>'
            f'<div class="stamp"><b style="font-size:{44 if len(s1) > 2 else 52}px">{e(s1)}</b><small>{e(s2)}</small></div></div>')


def media(img, h=None, w=None):
    estil = (f"height:{h}px;" if h else "") + (f"width:{w}px;" if w else "")
    if img:
        return f'<div class="media" style="{estil}"><img src="{img}"></div>'
    return f'<div class="media buit" style="{estil}"></div>'


# ---------------------------------------------------------------- 1 · portada
def portada(ctx, ed):
    img = ed.get("portada_uri")
    foto = (f'<img src="{img}" style="width:100%;height:100%;object-fit:cover;display:block">' if img
            else '<div class="hatch-p" style="width:100%;height:100%"></div>')
    return f"""<section class="pg" style="padding:34px 44px 30px;align-items:center;gap:10px">
<span style="font-family:'Anton',sans-serif;font-size:124px;line-height:1;text-shadow:5px 5px 0 var(--rosa);white-space:nowrap">PRIMERA FILA</span>
<span style="font-weight:800;font-size:13px;letter-spacing:.34em">EL NEWSLETTER DE L'AGENDA NO OFICIAL DE TARRAGONA</span>
<div style="display:flex;justify-content:space-between;align-items:center;width:706px;background:var(--blau);color:var(--crema);padding:8px 16px;margin-top:6px">
<span class="bowl" style="font-size:22px">{e(ctx["dates"])}</span><span class="mono" style="font-size:13px;letter-spacing:.12em">{e(ed["numero"].upper())}</span></div>
<div style="width:706px;height:660px;margin-top:10px;border:4px solid var(--blau);box-shadow:12px 12px 0 var(--rosa);overflow:hidden;flex-shrink:0">{foto}</div>
<span style="font-family:'Anton',sans-serif;font-size:50px;line-height:1.05;padding-top:22px;white-space:nowrap">DIJOUS DIVENDRES CAP DE SETMANA</span>
<span style="background:var(--groc);font-weight:800;font-size:16px;letter-spacing:.3em;padding:6px 14px">ESTIMA LA CULTURA · ESTIMA TARRAGONA</span>
</section>"""


# ---------------------------------------------------------------- 2 · canal
def canal(ctx):
    return f"""<section class="pg" style="gap:16px">
<div style="position:relative;height:128px;background:var(--blau);overflow:hidden;flex-shrink:0">
<img src="{asset_uri('rosassa.jpg')}" style="width:100%;height:128px;object-fit:cover;display:block;filter:grayscale(1) contrast(1.2);mix-blend-mode:screen">
<div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%) rotate(-1.5deg);background:var(--groc);border:3px solid var(--blau);padding:8px 20px;white-space:nowrap">
<span class="bowl" style="font-size:26px">L'AGENDA NO OFICIAL DE TARRAGONA</span></div></div>
<div style="display:flex;flex-direction:column;gap:8px">
<span class="bowl" style="font-size:30px;line-height:1.1;text-shadow:3px 3px 0 var(--rosa)">CADA DIJOUS, ENDINSA'T EN LA TARRAGONA REAL:</span>
<span style="font-weight:800;font-size:18px;line-height:1.35;color:var(--tinta)">la que ningú t'explica, la que no surt ni als diaris ni a les apps.</span></div>
<div style="display:flex;gap:34px;align-items:center;height:470px;flex-shrink:0;padding:0 6px">
<div style="width:360px;height:420px;border:4px solid var(--blau);box-shadow:12px 12px 0 var(--rosa);transform:rotate(-2deg);flex-shrink:0;overflow:hidden">
<img src="{asset_uri('nena.jpg')}" style="width:100%;height:100%;object-fit:cover;display:block"></div>
<div style="flex-grow:1;display:flex;flex-direction:column;gap:18px">
<span class="bowl" style="align-self:flex-start;background:var(--blau);color:var(--crema);font-size:34px;padding:8px 16px;transform:rotate(2deg)">SENSE APPS</span>
<span class="bowl" style="align-self:flex-start;background:var(--blau);color:var(--crema);font-size:34px;padding:8px 16px;transform:rotate(-2deg)">NI REGISTRES</span>
{f'<span style="font-weight:800;font-size:16px;line-height:1.45;color:var(--tinta)">{ctx["subs_txt"]} persones ja reben Primera Fila cada dijous, directament al mòbil.</span>' if ctx.get("subs_txt") else ""}
</div></div>
<div class="cats" style="border-top:3px solid var(--blau);border-bottom:3px solid var(--blau);padding:7px 0">ESPECTACLES / EXPOS / VERMUTS / CONCERTS / TARDEIGS / TEATRE / CINEMA</div>
<a class="cta" href="{ctx['whatsapp']}"><span class="bowl" style="font-size:25px;line-height:1.1">SUBSCRIU-TE GRATUÏTAMENT AL NOSTRE CANAL DE WHATSAPP</span><span class="bt">CLICA AQUÍ →</span></a>
{peu(ctx)}</section>"""


# ---------------------------------------------------------------- 3 · article
def article(ctx, a):
    img = a.get("imatge_uri")
    paras = "".join(f"<p style='margin:0 0 10px'>{e(x.strip())}</p>" for x in a["text"].split("\n") if x.strip())
    return f"""<section class="pg">
{capcalera("ARTICLE", "La crònica de la setmana", "3′", "LECTURA")}
<span class="bowl" style="font-size:40px;line-height:1.05">{e(a["titol"].upper())}</span>
<span style="font-weight:800;font-size:18px;line-height:1.45;color:var(--tinta);border-bottom:3px solid var(--blau);padding-bottom:14px">{e(a["entradeta"])}</span>
<div style="display:flex;gap:22px;height:290px;flex-shrink:0">
<div style="width:400px;height:290px;border:3px solid var(--blau);flex-shrink:0;overflow:hidden" class="media{'' if img else ' buit'}">{f'<img src="{img}">' if img else ''}</div>
<div style="flex-grow:1;display:flex;flex-direction:column;justify-content:center;gap:12px">
{f'<span class="bowl" style="font-size:24px;line-height:1.15;color:var(--magenta)">«{e(a["cita"])}»</span>' if a["cita"] else ""}
<span class="mono" style="font-size:12px">— {e(a["signatura"].upper())}</span>
{f'<span style="font-size:11px;font-weight:700">{e(a["peu"])}</span>' if a["peu"] else ""}</div></div>
<div style="column-count:2;column-gap:28px;font-size:14.5px;font-weight:500;line-height:1.6;color:var(--tinta);overflow:hidden;flex-grow:1">{paras}</div>
{peu(ctx)}</section>"""


# ---------------------------------------------------------------- dies (motor adaptable)
PLANS_D = {1: [1], 2: [1, 1], 3: [1, 2], 4: [1, 3], 5: [1, 2, 2], 6: [1, 3, 2], 7: [1, 3, 3]}
PLANS_N = {1: [1], 2: [1, 1], 3: [1, 1, 1], 4: [2, 2], 5: [3, 2], 6: [3, 3], 7: [3, 2, 2]}
ALT_D = {1: [856], 2: [421, 421], 3: [440, 402], 4: [380, 462], 5: [260, 284, 284], 6: [260, 284, 284], 7: [240, 294, 294]}
ALT_N = {1: [856], 2: [421, 421], 3: [276, 276, 276], 4: [421, 421], 5: [421, 421], 6: [421, 421], 7: [276, 276, 276]}


def _targeta(a, h, n_fila, destacada, num):
    horiz = n_fila == 1 and h <= 500
    hero = n_fila == 1 and h > 500
    ts = 38 if hero else (30 if h >= 380 else 22) if horiz else (18 if n_fila == 2 else 14)
    hora = a["hora_curta"]
    pin = f'<span class="pin">{num}</span>' if num else ""
    preu = ""
    if a["preu"]:
        preu = f'<span class="preu {"free" if a["preu"] == "Gratuït" else "paid"}">{e(a["preu"])}</span>'
    blurb = (f'<span class="blurb">{e(a["descripcio"][:220])}</span>'
             if a["descripcio"] and (hero or (horiz and h >= 240)) else "")
    lloc = a["lloc"] + (f' ({a["municipi"]})' if a["municipi"] and "tarragona" not in a["municipi"].lower() else "")
    hora_html = f'<span class="hora" style="font-size:{20 if (hero or horiz) else 16}px">{e(hora)}</span>' if hora else ""
    cat_html = f'<span class="cat">{e(a["cat"])}</span>' if a["cat"] else ""
    info = (f'<div class="info"><div class="chips">{pin}{hora_html}{cat_html}</div>'
            f'<span class="ttl" style="font-size:{ts}px">{e(a["nom"])}</span>{blurb}<div class="sp"></div>'
            f'<span class="venue">{e(lloc)}</span>{preu}</div>')
    stick = '<span class="stick">GRATIS!</span>' if destacada and a["preu"] == "Gratuït" else ""
    cls = "card " + ("feat " if destacada else "") + ("h" if horiz else "v") + (" hero" if hero else "")
    if horiz:
        return f'<div class="{cls}">{media(a["img"], w=420 if h >= 380 else 340)}{info}{stick}</div>'
    info_h = 230 if hero else (150 if n_fila == 2 else 158)
    return f'<div class="{cls}">{media(a["img"], h=h - info_h)}{info}{stick}</div>'


def pagina_dia(ctx, dia, acts, continuacio, nums):
    n = len(acts)
    dest = (not continuacio) and acts[0]["destacada"]
    plan, alts = (PLANS_D if dest else PLANS_N)[n], (ALT_D if dest else ALT_N)[n]
    files, k = [], 0
    for len_fila, h in zip(plan, alts):
        cards = "".join(_targeta(a, h, len_fila, dest and k + j == 0, nums.get(a["id"]))
                        for j, a in enumerate(acts[k:k + len_fila]))
        files.append(f'<div class="row" style="height:{h}px">{cards}</div>')
        k += len_fila
    chip = ("Continuació · més plans d'aquest dia" if continuacio
            else f"{ctx['n_dia'][dia]} activitats d'oci i cultura")
    return f"""<section class="pg">
<div class="cats">ESPECTACLES / EXPOS / VERMUTS / CONCERTS / TARDEIGS / TEATRE / CINEMA</div>
{capcalera(DIES[dia.weekday()], chip, str(dia.day), MESOS[dia.month - 1].upper())}
{''.join(files)}
{peu(ctx)}</section>"""


# ---------------------------------------------------------------- festes
def pagina_festes(ctx, barris):
    blocs = ""
    for b in barris:
        cols = ""
        for dia, items in b["dies"]:
            files = "".join(
                f'<div style="display:flex;gap:6px;align-items:flex-start"><span class="hora" style="font-size:12px;padding:1px 5px;white-space:nowrap">{e(h)}</span>'
                f'<span style="font-size:12.5px;font-weight:700;line-height:1.3">{e(t)}</span></div>' for h, t in items[:7])
            cols += f'<div style="display:flex;flex-direction:column;gap:8px"><span class="bowl" style="font-size:16px;color:var(--magenta)">{e(dia)}</span>{files}</div>'
        img = b.get("img")
        cartell = (f'<div class="media" style="width:116px"><img src="{img}" style="mix-blend-mode:normal;filter:none"></div>' if img
                   else '<div class="hatch-b" style="width:116px;flex-shrink:0"></div>')
        blocs += f"""<div style="display:flex;flex-direction:column;border:3px solid var(--blau);height:410px;flex-shrink:0">
<div style="display:flex;justify-content:space-between;align-items:center;background:var(--blau);color:var(--crema);padding:8px 16px">
<span class="bowl" style="font-size:22px">{e(b["nom"].upper())}</span><span class="mono" style="font-size:12px">{e(b["dates"])}</span></div>
<div style="display:flex;gap:16px;padding:14px 16px;flex-grow:1;min-height:0">{cartell}
<div style="flex-grow:1;display:grid;grid-template-columns:repeat({max(1, min(3, len(b["dies"])))},minmax(0,1fr));gap:14px;overflow:hidden">{cols}</div></div></div>"""
    return f"""<section class="pg">{capcalera("FESTES", "Programes resumits dels barris en festa", str(len(barris)), "BARRIS")}
{blocs}{peu(ctx)}</section>"""


# ---------------------------------------------------------------- exposicions
def pagina_expos(ctx, grups):
    cos = ""
    for nom, items in grups:
        if not items:
            continue
        cos += f'<span class="sec">{e(nom)}</span>'
        for x in items:
            thumb = (f'<div class="media" style="width:76px;height:76px"><img src="{x["img"]}"></div>' if x["img"]
                     else '<div class="hatch-b" style="width:76px;height:76px;flex-shrink:0"></div>')
            cos += f"""<div style="display:flex;gap:14px;align-items:center;height:88px;border-bottom:2px dashed var(--blau);flex-shrink:0">{thumb}
<div style="flex-grow:1;min-width:0;display:flex;flex-direction:column;gap:4px"><span class="bowl" style="font-size:18px;line-height:1.1">{e(x["nom"])}</span>
<span style="font-size:12.5px;font-weight:700;color:var(--tinta)">{e(x["lloc"])}</span></div>
<div style="display:flex;flex-direction:column;align-items:flex-end;gap:5px;flex-shrink:0">
<span style="font-size:12px;font-weight:800">{e(x["quan"])}</span>
{f'<span style="font-size:10.5px;font-weight:800;text-transform:uppercase;letter-spacing:.06em">{e(x["preu"])}</span>' if x["preu"] else ""}</div></div>"""
    return f"""<section class="pg">{capcalera("EXPOS", "Índex d'exposicions a Tarragona", "ART", "I MÉS")}
<div style="display:flex;flex-direction:column;gap:6px">{cos}</div>{peu(ctx)}</section>"""


# ---------------------------------------------------------------- museus
def pagina_museus(ctx, grups):
    cos = ""
    for nom, items in grups:
        cel = "".join(f'<div style="display:flex;flex-direction:column;gap:2px;min-height:44px"><span style="font-weight:800;font-size:14px;text-transform:uppercase">{e(x["nom"])}</span>'
                      f'<span style="font-size:12.5px;font-weight:700;color:var(--tinta)">{e(" · ".join(v for v in [x["adreca"], x["horari"]] if v))}</span></div>' for x in items)
        cos += (f'<span class="sec">{e(nom)}</span><div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:28px;'
                f'row-gap:10px;border-top:3px solid var(--blau);padding-top:12px">{cel}</div>')
    return f"""<section class="pg">{capcalera("MUSEUS", "Museus i espais culturals de Tarragona", "TGN", "CULTURA")}
<div style="display:flex;flex-direction:column;gap:10px">{cos}</div>{peu(ctx)}</section>"""


# ---------------------------------------------------------------- negoci
def pagina_negoci(ctx, b):
    foto = (f'<img src="{b["foto_uri"]}" style="width:100%;height:100%;object-fit:cover;display:block">' if b.get("foto_uri")
            else '<div class="hatch-p" style="width:100%;height:100%"></div>')
    demanar = "".join(f'<span style="border:2px dashed var(--blau);font-weight:800;font-size:13px;padding:4px 10px">{e(x.strip())}</span>'
                      for x in b["demanar"].split(",") if x.strip())
    etiqueta = "PATROCINAT" if (b["tipus"] or "").lower().startswith("patro") else ""
    onquan = "".join(f"<span>{e(v)}</span>" for v in [b["adreca"], b["horari"], b["instagram"], b["preu"]] if v)
    return f"""<section class="pg">{capcalera("NEGOCI", "Negoci local recomanat · " + (b["sector"] or "gastronomia o comerç").lower(), "TOP", "LOCAL")}
<div style="position:relative;height:290px;flex-shrink:0;border:3px solid var(--blau);overflow:hidden">{foto}
{f'<span style="position:absolute;top:14px;left:14px;background:var(--groc);font-weight:800;font-size:12px;letter-spacing:.1em;padding:4px 10px">{e(b["sector"].upper())}</span>' if b["sector"] else ""}
{f'<span class="mono" style="position:absolute;bottom:14px;right:14px;background:var(--crema);border:2px solid var(--blau);font-size:11px;padding:3px 8px">{etiqueta}</span>' if etiqueta else ""}</div>
<span class="bowl" style="font-size:44px;line-height:1">{e(b["nom"].upper())}</span>
{f'''<div style="display:flex;gap:18px;background:#fff;border:2px dashed var(--blau);padding:16px 18px;flex-shrink:0">
<span class="bowl" style="font-size:64px;line-height:.8;color:var(--rosa);flex-shrink:0">“</span>
<div style="display:flex;flex-direction:column;gap:8px"><span class="bowl" style="font-size:17px;color:var(--magenta)">LA SEVA HISTÒRIA</span>
<span style="font-size:15px;font-weight:500;line-height:1.6;color:var(--tinta)">{e(b["historia"])}{f" «{e(b['cita'])}»" if b["cita"] else ""}</span>
{f'<span class="mono" style="font-size:12px">— {e(b["qui"])}</span>' if b["qui"] else ""}</div></div>''' if b["historia"] else ""}
<div style="display:flex;gap:26px">
<div style="flex-grow:1;display:flex;flex-direction:column;gap:10px">
{f'<span class="bowl" style="font-size:17px;color:var(--magenta)">PER QUÈ HI ANEM</span><span style="font-size:15px;font-weight:500;line-height:1.6;color:var(--tinta)">{e(b["perque"])}</span>' if b["perque"] else ""}
{f'<span class="bowl" style="font-size:17px;color:var(--magenta)">QUÈ DEMANAR</span><div style="display:flex;gap:8px;flex-wrap:wrap">{demanar}</div>' if demanar else ""}</div>
{f'<div style="width:230px;flex-shrink:0;background:var(--blau);color:var(--crema);padding:16px;display:flex;flex-direction:column;gap:10px;font-size:13px;font-weight:700"><span class="bowl" style="font-size:16px">ON I QUAN</span>{onquan}</div>' if onquan else ""}
</div>{peu(ctx)}</section>"""


# ---------------------------------------------------------------- ofertes
def pagina_ofertes(ctx, ofertes, pag, total):
    cards = ""
    for i, o in enumerate(ofertes):
        img = o.get("img")
        foto = (f'<div style="width:190px;flex-shrink:0;overflow:hidden"><img src="{img}" style="width:100%;height:100%;object-fit:cover;display:block"></div>'
                if img else f'<div class="{"hatch-b" if i % 2 == 0 else "hatch-p"}" style="width:190px;flex-shrink:0"></div>')
        cards += f"""<div style="display:flex;height:158px;border:2px dashed var(--blau);flex-shrink:0">{foto}
<div style="flex-grow:1;min-width:0;padding:12px 16px;display:flex;flex-direction:column;gap:5px">
{f'<span class="cat" style="align-self:flex-start">{e(o["tipus"])}</span>' if o["tipus"] else ""}
<span class="bowl" style="font-size:21px;line-height:1.1">{e(o["nom"].upper())}</span>
{f'<span style="font-weight:800;font-size:14.5px;color:var(--tinta)">{e(o["linia"])}</span>' if o["linia"] else ""}
{f'<span style="font-size:12px;font-weight:500;color:var(--tinta)">{e(o["condicions"][:140])}</span>' if o["condicions"] else ""}</div>
<a href="{e(o["enllac"] or ctx["whatsapp"])}" style="width:150px;flex-shrink:0;background:var(--groc);border-left:2px dashed var(--blau);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;padding:10px;text-align:center">
<span class="bowl" style="font-size:20px;line-height:1">CLICA AQUÍ</span><span style="font-weight:800;font-size:11.5px;line-height:1.25">per gaudir de l'oferta →</span></a></div>"""
    return f"""<section class="pg">{capcalera("OFERTES", "Descomptes exclusius per a la comunitat · Publicitat", f"{pag}/{total}", "PÀGINA")}
<div style="display:flex;flex-direction:column;gap:12px">{cards}</div>{peu(ctx)}</section>"""


# ---------------------------------------------------------------- comunitat
def pagina_comunitat(ctx):
    stats = ""
    if ctx.get("seg_txt"):
        stats += f'<div style="background:var(--blau);color:var(--crema);padding:22px;display:flex;flex-direction:column;gap:6px"><span class="bowl" style="font-size:64px;line-height:1">{ctx["seg_txt"]}</span><span style="font-weight:800;font-size:15px">seguidors a Instagram · @agendatgn</span></div>'
    if ctx.get("subs_txt"):
        stats += f'<div style="background:var(--rosa);color:#1A1033;padding:22px;display:flex;flex-direction:column;gap:6px"><span class="bowl" style="font-size:64px;line-height:1">{ctx["subs_txt"]}</span><span style="font-weight:800;font-size:15px">subscriptors directes a Primera Fila</span></div>'
    return f"""<section class="pg">{capcalera("GRÀCIES", "La comunitat que fa possible AgendaTGN", "TGN", "GRÀCIES")}
<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px">{stats}</div>
<div style="font-size:17px;font-weight:700;line-height:1.5;color:var(--tinta)">Aquest projecte creix gràcies a vosaltres. Gràcies per seguir-nos, llegir-nos i confiar cada setmana en la nostra agenda cultural.</div>
<div style="border:3px dashed var(--blau);height:330px;padding:22px;display:flex;flex-direction:column;gap:10px;flex-shrink:0">
<span class="mono" style="align-self:flex-start;background:var(--groc);font-size:12px;padding:3px 8px">ESPAI PUBLICITARI · MITJA PÀGINA</span>
<span class="bowl" style="font-size:40px;line-height:1.05">EL TEU NEGOCI AQUÍ</span>
<span style="font-size:16px;font-weight:700;line-height:1.5;color:var(--tinta)">Vols anunciar-te al mitjà setmanal amb més subscriptors de Tarragona? Cada dijous arribem directament al mòbil de tota la comunitat.</span>
<div class="sp"></div><a href="mailto:agendatgn@gmail.com" style="align-self:flex-start;background:var(--blau);color:var(--crema);font-weight:800;font-size:15px;padding:10px 16px">Escriu-nos a agendatgn@gmail.com →</a></div>
<a class="cta" href="{ctx['whatsapp']}"><span class="bowl" style="font-size:19px">COMPARTEIX PRIMERA FILA AMB QUI ESTIMIS</span><span style="font-weight:800;font-size:13px">CANAL DE WHATSAPP →</span></a>
{peu(ctx)}</section>"""


# ---------------------------------------------------------------- mapa
def pagina_mapa(ctx, img, fora, te_zoom, total_llocs):
    pins = "".join(f'<div style="display:flex;align-items:center;gap:8px;font-size:12.5px;font-weight:700;color:var(--tinta)">'
                   f'<span class="pin" style="width:30px;height:30px;font-size:13px">{x["num"]}</span><span>{e(x["nom"])}</span></div>' for x in fora)
    return f"""<section class="pg">{capcalera("MAPA", "Els llocs d'aquesta setmana", str(total_llocs), "LLOCS")}
<div style="width:706px;height:560px;border:3px solid var(--blau);overflow:hidden;flex-shrink:0"><img src="{img}" style="width:100%;height:100%;object-fit:cover;display:block"></div>
<div style="display:flex;gap:16px"><div style="flex:1 1 0;display:flex;flex-direction:column;gap:10px">
<span class="bowl" style="font-size:17px;color:var(--magenta)">COM LLEGIR EL MAPA</span>
<div style="display:flex;align-items:center;gap:10px;font-size:13.5px;font-weight:700;color:var(--tinta)"><span class="pin" style="width:30px;height:30px">7</span><span>El número és el mateix que a la targeta de cada activitat i a la llista de llocs.</span></div>
{'<div style="display:flex;align-items:center;gap:10px;font-size:13.5px;font-weight:700;color:var(--tinta)"><span class="bowl" style="width:30px;text-align:center;font-size:20px">→</span><span>La zona amb més llocs la tens ampliada a la pàgina següent.</span></div>' if te_zoom else ""}</div>
{f'<div style="width:250px;flex-shrink:0;border:2px dashed var(--blau);padding:12px 14px;display:flex;flex-direction:column;gap:8px"><span class="bowl" style="font-size:15px">FORA DEL MAPA</span>{pins}</div>' if fora else ""}</div>
{peu(ctx)}</section>"""


def pagina_zoom(ctx, img):
    return f"""<section class="pg"><div style="display:flex;align-items:center;gap:16px;height:64px;flex-shrink:0">
<div style="width:12px;height:64px;background:var(--rosa)"></div><span class="bowl" style="font-size:50px;line-height:1;text-shadow:3px 3px 0 var(--rosa)">ZOOM</span>
<span class="chip" style="align-self:center">La zona amb més plans</span><div class="sp"></div><span class="mono" style="font-size:12px">MAPA 2/2</span></div>
<div style="width:706px;height:900px;border:3px solid var(--blau);overflow:hidden;flex-shrink:0"><img src="{img}" style="width:100%;height:100%;object-fit:cover;display:block"></div>
{peu(ctx)}</section>"""


def pagina_llocs(ctx, llocs):
    cel = "".join(f"""<div style="display:flex;gap:12px;align-items:flex-start;min-height:62px">
<span class="bowl" style="width:40px;height:40px;border-radius:50%;background:var(--blau);color:var(--crema);font-size:17px;display:flex;align-items:center;justify-content:center;flex-shrink:0">{x["num"]}</span>
<div style="display:flex;flex-direction:column;gap:3px;min-width:0"><span style="font-weight:800;font-size:14px;text-transform:uppercase">{e(x["nom"])}</span>
{f'<a href="{e(x["google_maps"])}" style="font-size:12.5px;font-weight:700;color:var(--tinta);text-decoration:underline">{e(x["adreca"] or "Veure a Google Maps")}</a>' if x.get("google_maps") else f'<span style="font-size:12.5px;font-weight:700">{e(x["adreca"] or "")}</span>'}
{f'<span style="font-size:12px;font-weight:700;color:var(--magenta)">{e(x["instagram"])}</span>' if x.get("instagram") else ""}</div></div>""" for x in llocs)
    return f"""<section class="pg">{capcalera("LLOCS", "Clica l'adreça i vas directe a Google Maps", str(len(llocs)), "LLOCS")}
<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:28px;row-gap:12px;border-top:3px solid var(--blau);padding-top:18px">{cel}</div>
{peu(ctx)}</section>"""


# ---------------------------------------------------------------- contraportada
def contraportada(ctx, o):
    img = o.get("arxiu_uri")
    fons = (f'<img src="{img}" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover">' if img
            else '<div class="hatch-b" style="position:absolute;inset:0"></div>')
    return f"""<section class="pg full">{fons}
<a href="{e(o["enllac"] or ctx["whatsapp"])}" style="position:absolute;inset:0"></a>
<span class="mono" style="position:absolute;top:18px;left:18px;background:var(--crema);border:2px solid var(--blau);font-size:11px;letter-spacing:.12em;padding:3px 8px">PUBLICITAT</span>
<div class="mono" style="position:absolute;left:0;right:0;bottom:0;height:30px;background:var(--blau);color:var(--crema);display:flex;align-items:center;justify-content:space-between;padding:0 18px;font-size:11px">
<span>PRIMERA FILA // @AGENDATGN</span><span>SETMANA {e(ctx["dates"])} · {{{{PAG}}}}</span></div></section>"""


def document(pagines):
    cos = ""
    for i, p in enumerate(pagines, 1):
        cos += p.replace("{{PAG}}", str(i))
    return f'<!doctype html><html lang="ca"><head><meta charset="utf-8">{FONTS}<style>{CSS}</style></head><body>{cos}</body></html>'
