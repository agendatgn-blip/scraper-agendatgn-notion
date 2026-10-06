# Primera Fila · generador automàtic del PDF

## Com es fa servir (des de Notion)
1. Crea l'edició a 📰 PRIMERA FILA · EDICIONS i omple: Setmana, Número edició, Portada,
   Article, Negoci recomanat, Ofertes vinculades, Subscriptors i Seguidors IG.
2. Vincula-hi les activitats (columna "Edició Primera Fila" de cada activitat).
3. Posa l'Estat a **Maquetant**.
4. En uns 15 minuts: el PDF t'arriba per Telegram, es puja a Drive, s'omple "Link descàrrega"
   i l'edició passa sola a **Revisió**. Per refer-lo, torna-la a posar a Maquetant.

## Què hi surt (en aquest ordre; les seccions sense dades no surten)
Portada · Canal de WhatsApp · Article · Dies (dijous→diumenge, màx. 7 per pàgina, destacada en gran) ·
Festes als barris (camp "Festa / barri") · Exposicions (categoria Exposició) · Museus i espais
(Llocs amb "Surt a l'índex de museus") · Negoci recomanat · Ofertes (5 per pàgina, màx. 10) ·
Comunitat · Mapa + zoom + llista de llocs de la setmana · Contraportada (oferta amb Format = Contraportada).

## Proves a l'ordinador
pip install -r requirements.txt && python -m playwright install chromium
set NOTION_TOKEN=...   (Windows)   ·   export NOTION_TOKEN=...   (Mac/Linux)
python generar_pdf.py --edicio "URL de l'edició" --local
