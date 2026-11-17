"""Dibuixa el carrusel de 2 slides (1080x1350) amb la marca d'AgendaTGN.

Slide 1: portada groga amb el titular. Slide 2: fons negre amb el ganxo, les dades i la crida a Primera Fila.
Disseny tipogràfic propi: no fa servir fotos dels mitjans.
"""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent.parent / "assets"
GROC, NEGRE, BLANC, GRIS = "#FFDC00", "#000000", "#FFFFFF", "#BDBDBD"
W, H, PAD = 1080, 1350, 80


def _f(nom, mida):
    return ImageFont.truetype(str(ASSETS / nom), mida)


def anton(m):
    return _f("Anton-Regular.ttf", m)


def inter(m, bold=True):
    return _f("Inter-Bold.ttf" if bold else "Inter-SemiBold.ttf", m)


def _wrap(d, text, font, ample):
    linies, cur = [], ""
    for p in text.split():
        prova = (cur + " " + p).strip()
        if d.textlength(prova, font=font) <= ample:
            cur = prova
        else:
            if cur:
                linies.append(cur)
            cur = p
    if cur:
        linies.append(cur)
    return linies


def _encaixa(d, text, fabrica, mides, ample, alt_max, max_linies, interlinia):
    for m in mides:
        f = fabrica(m)
        lin = _wrap(d, text, f, ample)
        lh = int(m * interlinia)
        if len(lin) <= max_linies and lh * len(lin) <= alt_max and \
                all(d.textlength(x, font=f) <= ample for x in lin):
            return f, lin, lh
    f = fabrica(mides[-1])
    lin = _wrap(d, text, f, ample)[:max_linies]
    return f, lin, int(mides[-1] * interlinia)


def _etiqueta(d, xy, text, fons, color, mida=30):
    f = inter(mida)
    x, y = xy
    w = d.textlength(text, font=f)
    d.rounded_rectangle((x, y, x + w + 44, y + mida + 30), radius=8, fill=fons)
    d.text((x + 22, y + 13), text, font=f, fill=color)
    return y + mida + 30


def _logo(img, mida, xy):
    try:
        lg = Image.open(ASSETS / "logo_cercle.png").convert("RGBA").resize((mida, mida), Image.LANCZOS)
        img.paste(lg, xy, lg)
    except OSError:
        pass


def _png(img):
    b = BytesIO()
    img.save(b, "PNG", optimize=True)
    return b.getvalue()


def slide_portada(titular, categoria, mitja):
    img = Image.new("RGB", (W, H), GROC)
    d = ImageDraw.Draw(img)
    _etiqueta(d, (PAD, PAD), f"NOTÍCIA · {categoria.upper()}" if categoria else "NOTÍCIA CULTURAL", NEGRE, GROC)
    _logo(img, 120, (W - PAD - 120, PAD - 20))
    zona_top, zona_bot = 260, 1090
    f, lin, lh = _encaixa(d, titular.upper(), anton, list(range(170, 69, -6)), W - 2 * PAD,
                          zona_bot - zona_top, 6, 1.12)
    y = zona_top + (zona_bot - zona_top - lh * len(lin)) // 2
    for x in lin:
        d.text((PAD, y), x, font=f, fill=NEGRE)
        y += lh
    d.rectangle((PAD, H - PAD - 90, W - PAD, H - PAD - 84), fill=NEGRE)
    d.text((PAD, H - PAD - 30), f"Font: {mitja}"[:44], font=inter(30, False), fill=NEGRE, anchor="ls")
    d.text((W - PAD, H - PAD - 30), "LLISCA  →", font=inter(32), fill=NEGRE, anchor="rs")
    return _png(img)


def slide_ganxo(ganxo, dades=None):
    img = Image.new("RGB", (W, H), NEGRE)
    d = ImageDraw.Draw(img)
    _etiqueta(d, (PAD, PAD), "EL QUE HAS DE SABER", GROC, NEGRE)
    zona_top, zona_bot = 230, 860
    f, lin, lh = _encaixa(d, ganxo, inter, list(range(64, 35, -2)), W - 2 * PAD,
                          zona_bot - zona_top, 9, 1.22)
    y = zona_top
    for x in lin:
        d.text((PAD, y), x, font=f, fill=BLANC)
        y += lh
    # dades (quan, on...) només si les diu la notícia
    y = max(y + 40, 900)
    for etiqueta, valor in (dades or []):
        if not valor:
            continue
        d.text((PAD, y), etiqueta.upper(), font=inter(26), fill=GROC)
        fv, lv, lhv = _encaixa(d, valor, lambda m: inter(m, False), [34, 30, 28], W - 2 * PAD - 170, 90, 2, 1.2)
        yy = y - 4
        for x in lv:
            d.text((PAD + 170, yy), x, font=fv, fill=BLANC)
            yy += lhv
        y = max(y + 56, yy + 12)
    # crida a Primera Fila
    caixa_top = H - PAD - 150
    d.rounded_rectangle((PAD, caixa_top, W - PAD, H - PAD), radius=14, fill=GROC)
    d.text((PAD + 36, caixa_top + 30), "MÉS PLANS CADA DIJOUS", font=anton(52), fill=NEGRE)
    d.text((PAD + 36, caixa_top + 100), "Primera Fila · link a la bio", font=inter(30, False), fill=NEGRE)
    _logo(img, 100, (W - PAD - 125, caixa_top + 25))
    return _png(img)


if __name__ == "__main__":
    # Prova de disseny amb text d'exemple
    a = slide_portada("Titular d'exemple amb la plaça del Rei i 4 paraules", "Museus", "Mitjà d'exemple")
    b = slide_ganxo("Text d'exemple de la segona slide: dues o tres frases que expliquen l'essencial "
                    "de la notícia i per què interessa a la gent de Tarragona.",
                    [("Quan", "Dia d'exemple"), ("On", "Lloc d'exemple, Tarragona")])
    Path("/tmp/slide1.png").write_bytes(a)
    Path("/tmp/slide2.png").write_bytes(b)
    print("fet")
