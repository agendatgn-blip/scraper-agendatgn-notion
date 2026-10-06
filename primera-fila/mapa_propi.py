#!/usr/bin/env python3
"""
MAPA PROPI · Primera Fila (AgendaTGN)

Genera el mapa de Tarragona amb l'estil de Primera Fila (paper crema, carrers
blaus, mar blau clar, parcs rosa) i hi posa els llocs numerats.

Ús:
    python mapa_propi.py Llocs_Notion_final.csv

Resultat (a la mateixa carpeta):
    mapa_general.svg / mapa_general.png      -> tota la zona
    mapa_part_alta.svg / mapa_part_alta.png  -> zoom de la zona amb més llocs
    mapa_fora.txt                            -> llocs que queden fora del mapa

Cal instal·lar (una sola vegada):
    pip install osmnx matplotlib

Dades: © OpenStreetMap contributors (cal posar-ho en petit al PDF).
"""
import csv
import math
import re
import sys
import warnings

warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import osmnx as ox
import geopandas as gpd
from shapely.geometry import Point, box
from shapely.ops import split, unary_union, linemerge

# ---------- ESTIL PRIMERA FILA ----------
PAPER = "#F2ECDF"
BLAU = "#1F4FC1"
MAR = "#CFDDF3"
PARC = "#F7C9E0"
EDIFICI = "#E7DECC"
GROC = "#FFD60A"
ROSA = "#FF3EA5"

AMPLADA_CARRER = {
    "motorway": 2.6, "trunk": 2.4, "primary": 2.2, "secondary": 1.8,
    "tertiary": 1.4, "residential": 0.8, "unclassified": 0.8,
    "living_street": 0.7, "pedestrian": 0.9, "service": 0.4,
    "footway": 0.35, "path": 0.3, "steps": 0.3, "cycleway": 0.3,
}

# Mida final: pàgina A4 del PDF (706 x 900 px útils) a 300 ppp
PAGINA_W, PAGINA_H = 706, 900
RADI_MAX_KM = 2.3       # llocs més lluny del centre queden fora del mapa general
RADI_ZOOM_M = 320       # radi per detectar la zona densa (Part Alta)
MARGE_M = 180


def llegir_llocs(ruta):
    llocs = []
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                lat, lon = float(r["Latitud"]), float(r["Longitud"])
            except (ValueError, KeyError, TypeError):
                continue
            num = (r.get("Núm") or "").strip()
            if not num:
                continue  # només els llocs numerats del directori
            llocs.append({"num": int(float(num)), "nom": r["Nom"], "lat": lat, "lon": lon})
    return llocs


def dist_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    d = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(d))


def bbox_amb_proporcio(punts, marge_m, ratio):
    """bbox (lon_min, lat_min, lon_max, lat_max) que conté els punts amb la proporció de la pàgina."""
    lats = [p["lat"] for p in punts]
    lons = [p["lon"] for p in punts]
    lat_c = (min(lats) + max(lats)) / 2
    m_lat = 111_320
    m_lon = 111_320 * math.cos(math.radians(lat_c))
    w = (max(lons) - min(lons)) * m_lon + 2 * marge_m
    h = (max(lats) - min(lats)) * m_lat + 2 * marge_m
    if w / h < ratio:
        w = h * ratio
    else:
        h = w / ratio
    lon_c = (min(lons) + max(lons)) / 2
    return (lon_c - w / 2 / m_lon, lat_c - h / 2 / m_lat, lon_c + w / 2 / m_lon, lat_c + h / 2 / m_lat)


def descarregar(bbox):
    print("  · carrers...")
    G = ox.graph_from_bbox(bbox, network_type="all", simplify=True, retain_all=True)
    carrers = ox.graph_to_gdfs(G, nodes=False)

    def feats(tags, nom):
        print(f"  · {nom}...")
        try:
            g = ox.features_from_bbox(bbox, tags)
            return g[g.geometry.notna()]
        except Exception:
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    costa = feats({"natural": "coastline"}, "línia de costa")
    aigua = feats({"natural": ["water", "bay"], "water": True, "landuse": ["basin", "harbour"]}, "aigua i port")
    parcs = feats({"leisure": ["park", "garden", "pitch"], "landuse": ["grass", "recreation_ground"]}, "parcs")
    edificis = feats({"building": True}, "edificis")
    tren = feats({"railway": "rail"}, "via del tren")
    return carrers, costa, aigua, parcs, edificis, tren


def poligon_mar(bbox, costa):
    """Parteix un rectangle una mica més gran que el mapa per la línia de costa i es queda la part del mar."""
    if costa.empty:
        return None
    marc = box(*bbox)
    # A Tarragona el mar queda a baix a la dreta (sud-est) del mapa
    punt_mar = Point(bbox[2] - (bbox[2] - bbox[0]) * 0.03, bbox[1] + (bbox[3] - bbox[1]) * 0.03)
    linies = unary_union([g for g in costa.geometry if g.geom_type in ("LineString", "MultiLineString")])
    if linies.geom_type == "MultiLineString":
        try:
            linies = linemerge(linies)
        except ValueError:
            pass
    try:
        trossos = list(split(marc, linies).geoms)
    except Exception:
        return None
    if len(trossos) < 2:
        return None
    mar = [p for p in trossos if p.contains(punt_mar)]
    return gpd.GeoDataFrame(geometry=mar, crs="EPSG:4326") if mar else None


def etiquetes_carrers(ax, carrers, n, mida):
    """Escriu el nom dels carrers més llargs, seguint la seva direcció."""
    import matplotlib.patheffects as pe
    c = carrers[carrers["name"].notna()].copy()
    c["nom"] = c["name"].apply(lambda v: v[0] if isinstance(v, list) else v)
    c["llarg"] = c.geometry.length
    tipus = c["highway"].apply(lambda h: h[0] if isinstance(h, list) else h)
    c = c[tipus.isin(["primary", "secondary", "tertiary", "residential", "pedestrian", "living_street", "trunk"])]
    per_nom = c.groupby("nom")["llarg"].sum().sort_values(ascending=False)
    for nom in list(per_nom.index)[:n]:
        tros = c[c["nom"] == nom].sort_values("llarg", ascending=False).geometry.iloc[0]
        mig = tros.interpolate(0.5, normalized=True)
        a = tros.interpolate(0.4, normalized=True); b = tros.interpolate(0.6, normalized=True)
        angle = math.degrees(math.atan2(b.y - a.y, b.x - a.x))
        if angle > 90: angle -= 180
        if angle < -90: angle += 180
        ax.text(mig.x, mig.y, nom.upper(), fontsize=mida, fontweight="bold", color=BLAU,
                rotation=angle, rotation_mode="anchor", ha="center", va="center", zorder=6,
                path_effects=[pe.withStroke(linewidth=2.5, foreground=PAPER)])


def repartir(xy, dmin, iteracions=80):
    """Separa els pins que se solapen (retorna posicions de dibuix)."""
    pos = [list(p) for p in xy]
    for _ in range(iteracions):
        mogut = False
        for i in range(len(pos)):
            for j in range(i + 1, len(pos)):
                dx, dy = pos[j][0] - pos[i][0], pos[j][1] - pos[i][1]
                d = math.hypot(dx, dy)
                if d < dmin:
                    if d < 1e-6:
                        dx, dy, d = 1.0, 0.0, 1.0
                    empenta = (dmin - d) / 2
                    ux, uy = dx / d, dy / d
                    pos[i][0] -= ux * empenta; pos[i][1] -= uy * empenta
                    pos[j][0] += ux * empenta; pos[j][1] += uy * empenta
                    mogut = True
        if not mogut:
            break
    return pos


def dibuixar(bbox, capes, llocs, sortida, mida_pin, n_etiquetes=8, w=PAGINA_W, h=PAGINA_H, amb_mar=True):
    carrers, costa, aigua, parcs, edificis, tren = capes
    marc = gpd.GeoDataFrame(geometry=[box(*bbox)], crs="EPSG:4326")
    crs = "EPSG:3857"  # Web Mercator: el rectangle lat/lon queda recte, sense puntes

    def pr(g):
        return g.to_crs(crs) if g is not None and not g.empty else None

    marc_p = pr(marc)
    minx, miny, maxx, maxy = marc_p.total_bounds

    fig = plt.figure(figsize=(w / 100, h / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(minx, maxx); ax.set_ylim(miny, maxy)
    ax.set_aspect("equal"); ax.axis("off")
    fig.patch.set_facecolor(PAPER); ax.set_facecolor(PAPER)

    mar = poligon_mar(bbox, costa) if amb_mar else None
    if mar is not None:
        mar_p = pr(mar)
        geo_mar = unary_union(list(mar_p.geometry))
        gpd.GeoSeries([geo_mar], crs=mar_p.crs).plot(ax=ax, color=MAR, linewidth=0, zorder=1)
    if (a := pr(aigua)) is not None:
        a[a.geom_type.isin(["Polygon", "MultiPolygon"])].plot(ax=ax, color=MAR, linewidth=0, zorder=1)
    if (p := pr(parcs)) is not None:
        p[p.geom_type.isin(["Polygon", "MultiPolygon"])].plot(ax=ax, color=PARC, linewidth=0, zorder=2)
    if (e := pr(edificis)) is not None:
        e[e.geom_type.isin(["Polygon", "MultiPolygon"])].plot(ax=ax, color=EDIFICI, linewidth=0, zorder=3)

    c = pr(carrers)
    tipus = c["highway"].apply(lambda h: h[0] if isinstance(h, list) else h)
    for t, amp in sorted(AMPLADA_CARRER.items(), key=lambda kv: kv[1]):
        sel = c[tipus == t]
        if not sel.empty:
            sel.plot(ax=ax, color=BLAU, linewidth=amp, alpha=0.55 if amp < 1 else 0.9,
                     zorder=4 if amp < 1.5 else 5, capstyle="round")
    if (t := pr(tren)) is not None:
        t.plot(ax=ax, color=BLAU, linewidth=0.7, alpha=0.7, linestyle=(0, (4, 3)), zorder=5)

    etiquetes_carrers(ax, c, n_etiquetes, mida_pin * 0.27)

    # Pins
    pts = gpd.GeoDataFrame(llocs, geometry=[Point(l["lon"], l["lat"]) for l in llocs], crs="EPSG:4326").to_crs(crs)
    xy = [(g.x, g.y) for g in pts.geometry]
    escala = (maxx - minx) / w  # metres per píxel
    pos = repartir(xy, mida_pin * 1.05 * escala)
    for (x0, y0), (x1, y1), l in zip(xy, pos, llocs):
        if math.hypot(x1 - x0, y1 - y0) > 1:
            ax.plot([x0, x1], [y0, y1], color=BLAU, linewidth=0.8, zorder=6)
            ax.scatter([x0], [y0], s=6, color=BLAU, zorder=6)
        ax.scatter([x1], [y1], s=(mida_pin * 0.72) ** 2, color=GROC, edgecolors=BLAU, linewidths=1.4, zorder=7)
        ax.text(x1, y1, str(l["num"]), ha="center", va="center", fontsize=mida_pin * 0.36,
                fontweight="bold", color=BLAU, zorder=8)

    ax.text(maxx - 6 * escala, miny + 6 * escala, "© OpenStreetMap contributors",
            ha="right", va="bottom", fontsize=5, color=BLAU, alpha=0.8, zorder=9)

    fig.savefig(sortida + ".svg", facecolor=PAPER)
    fig.savefig(sortida + ".png", dpi=300, facecolor=PAPER)
    plt.close(fig)
    print(f"  ✓ {sortida}.svg i {sortida}.png")


def main():
    if len(sys.argv) < 2:
        print("Ús: python mapa_propi.py Llocs_Notion_final.csv"); sys.exit(1)
    llocs = llegir_llocs(sys.argv[1])
    print(f"{len(llocs)} llocs numerats amb coordenades.")

    # Centre = mediana; fora els que queden massa lluny (ex. polígon Francolí)
    lats = sorted(l["lat"] for l in llocs); lons = sorted(l["lon"] for l in llocs)
    centre = (lats[len(lats) // 2], lons[len(lons) // 2])
    dins = [l for l in llocs if dist_km(centre, (l["lat"], l["lon"])) <= RADI_MAX_KM]
    fora = [l for l in llocs if l not in dins]
    with open("mapa_fora.txt", "w", encoding="utf-8") as f:
        for l in fora:
            f.write(f'{l["num"]} · {l["nom"]}\n')
    print(f"{len(fora)} llocs queden fora del mapa general (mira mapa_fora.txt).")

    ratio = PAGINA_W / PAGINA_H

    print("\nMAPA GENERAL")
    GEN_W, GEN_H = 706, 560   # més apaïsat: menys mar i muntanya buida
    bbox = bbox_amb_proporcio(dins, MARGE_M, GEN_W / GEN_H)
    capes = descarregar(bbox)
    dibuixar(bbox, capes, dins, "mapa_general", mida_pin=22, w=GEN_W, h=GEN_H)

    # Zoom: el lloc amb més veïns a menys de RADI_ZOOM_M
    def veins(l):
        return [m for m in dins if dist_km((l["lat"], l["lon"]), (m["lat"], m["lon"])) * 1000 <= RADI_ZOOM_M]
    cluster = max((veins(l) for l in dins), key=len)
    if len(cluster) >= 6:
        print(f"\nMAPA ZOOM ({len(cluster)} llocs a la zona més densa)")
        bbox_z = bbox_amb_proporcio(cluster, 90, ratio)
        capes_z = descarregar(bbox_z)
        dibuixar(bbox_z, capes_z, cluster, "mapa_part_alta", mida_pin=30, n_etiquetes=14, amb_mar=False)

    print("\nFet!")


if __name__ == "__main__":
    main()
