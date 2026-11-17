# 📰 Notícies culturals TGN

Recull notícies culturals de Tarragona, et proposa les millors i et deixa fet el carrusel de 2 slides.

| Pas | Quan | Què fa |
|---|---|---|
| Captura (`captura.py`) | 7, 13 i 19 h | Llegeix les fonts de `config.py`, descarta el que no és cultura, la IA puntua i crea les bones a Notion («Nova»). La del matí envia el top 5 per Telegram |
| Tu | quan vulguis | A Notion marques «Escollida» les que vols publicar |
| Producció (`produccio.py`) | cada 15 min, dins el Publish Scheduler | Escriu 3 titulars i tria el de més nota de ganxo, fa les 2 slides, passa a «Per aprovar» i t'ho envia per Telegram |

- **Afegir una font:** una línia a `FEEDS` o `PAGINES` de `config.py`.
- **IA:** Groq → Mistral → NVIDIA (si hi ha `NVIDIA_API_KEY`). Models canviables amb les variables `NOTICIES_GROQ_MODEL` i `NOTICIES_MODEL_ESCRIURE`.
- **Webs sense RSS:** es llegeixen directament; si falla i hi ha `FIRECRAWL_API_KEY`, amb Firecrawl.
- **Veu:** la mateixa guia de to dels posts d'X (`scheduler/guia_to.md`).
- **Nota del ganxo:** `ganxo.py`, adaptat de l'Instagram Agent Skill (MIT).
