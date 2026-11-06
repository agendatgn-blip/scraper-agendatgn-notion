"""
X (Twitter) · publicació per a @agendatgn
=========================================
MODE PER DEFECTE (des del 6/11/2026): "cua".
  L'API d'X ja no és gratis (pay-per-use) i es van acabar els crèdits.
  Ara cada tuit es desa a la base de Notion "📤 Cua X" (Estat = Pendent),
  amb la imatge adjunta, i Claude el publica a x.com des de Chrome.
  Els fils es guarden amb el mateix "Fil" i un "Ordre" (1, 2, 3...).

MODE "api" (X_MODE=api): publica directament amb l'API v2 com abans.
- Puja la imatge amb l'endpoint NOU de X (v2: POST /2/media/upload).
- Si la imatge falla, publica igualment el text (no es perd el post).
- Mai llança excepcions: torna l'id del tuit o None, i ho explica al log.

Variables d'entorn: X_MODE (cua | api), NOTION_TOKEN,
                    TWITTER_API_KEY, TWITTER_API_SECRET,
                    TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET (només mode api)
"""
import os
from io import BytesIO

import requests

MODE = (os.environ.get("X_MODE") or "cua").strip().lower()
DS_CUA_X = "7ccafda8-c161-497b-84d2-1e2804064bc4"  # Notion: 📤 Cua X
UPLOAD_URL = "https://api.x.com/2/media/upload"
MAX_BYTES = 4_500_000  # X accepta fins a 5 MB per imatge


def _claus():
    return [os.environ.get(x) for x in ("TWITTER_API_KEY", "TWITTER_API_SECRET",
                                       "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET")]


def configurat():
    if MODE == "cua":
        return bool(os.environ.get("NOTION_TOKEN"))
    return all(_claus())


def _a_jpeg_si_cal(image_bytes):
    """Si la imatge és massa grossa (PNG de foto), la passa a JPEG."""
    if len(image_bytes) <= MAX_BYTES:
        return image_bytes, "image/png"
    from PIL import Image
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    for q in (90, 82, 72):
        out = BytesIO()
        img.save(out, format="JPEG", quality=q, optimize=True)
        if out.tell() <= MAX_BYTES:
            return out.getvalue(), "image/jpeg"
    return out.getvalue(), "image/jpeg"


def pujar_imatge(image_bytes):
    """Puja la imatge a X (API v2). Torna el media_id o None."""
    from requests_oauthlib import OAuth1
    k = _claus()
    dades, mime = _a_jpeg_si_cal(image_bytes)
    nom = "imatge.jpg" if mime == "image/jpeg" else "imatge.png"
    try:
        r = requests.post(
            UPLOAD_URL,
            auth=OAuth1(k[0], k[1], k[2], k[3]),
            files={"media": (nom, dades, mime)},
            data={"media_category": "tweet_image", "media_type": mime},
            timeout=60,
        )
        if not r.ok:
            print(f"  -> X: ERROR pujant la imatge ({r.status_code}): {r.text[:300]}")
            return None
        j = r.json()
        media_id = (j.get("data") or {}).get("id") or j.get("media_id_string")
        if not media_id:
            print(f"  -> X: resposta estranya pujant la imatge: {str(j)[:300]}")
        return media_id
    except Exception as e:  # noqa: BLE001
        print(f"  -> X: error pujant la imatge ({e!r})")
        return None


def publicar_api(text, image_bytes=None, reply_to=None):
    """Publica un tuit amb l'API (amb imatge si es pot). Torna l'id o None. Mai peta."""
    if not configurat():
        print("  -> X no configurat, s'omet.")
        return None
    import tweepy
    k = _claus()
    client = tweepy.Client(consumer_key=k[0], consumer_secret=k[1],
                           access_token=k[2], access_token_secret=k[3])
    media_ids = None
    if image_bytes:
        mid = pujar_imatge(image_bytes)
        if mid:
            media_ids = [mid]
        else:
            print("  -> X: es publica només el text (sense imatge).")
    try:
        r = client.create_tweet(text=text, media_ids=media_ids, in_reply_to_tweet_id=reply_to)
        print(f"  -> Publicat a X{' amb imatge' if media_ids else ''}: {text[:60]}...")
        return r.data["id"]
    except Exception as e:  # noqa: BLE001
        print(f"  -> X: ERROR publicant el tuit: {e!r}")
        return None


# ---------------------------------------------------------------------------
# Mode "cua": desa el tuit a Notion (📤 Cua X) perquè Claude el publiqui
# ---------------------------------------------------------------------------
_FILS = {}  # id fals d'un tuit -> (clau del fil, ordre)


def _notion_h(json_ct=True):
    h = {"Authorization": f"Bearer {os.environ.get('NOTION_TOKEN')}",
         "Notion-Version": "2025-09-03"}
    if json_ct:
        h["Content-Type"] = "application/json"
    return h


def _pujar_a_notion(image_bytes):
    """Puja la imatge a Notion (File Upload API). Torna l'id o None."""
    try:
        dades, mime = _a_jpeg_si_cal(image_bytes)
        nom = "imatge.jpg" if mime == "image/jpeg" else "imatge.png"
        r = requests.post("https://api.notion.com/v1/file_uploads", headers=_notion_h(),
                          json={"filename": nom, "content_type": mime}, timeout=30)
        r.raise_for_status()
        fu = r.json()
        r = requests.post(f"https://api.notion.com/v1/file_uploads/{fu['id']}/send",
                          headers=_notion_h(json_ct=False),
                          files={"file": (nom, dades, mime)}, timeout=60)
        r.raise_for_status()
        return fu["id"]
    except Exception as e:  # noqa: BLE001
        print(f"  -> Cua X: no s'ha pogut pujar la imatge ({e!r}); es desa sense.")
        return None


def publicar_cua(text, image_bytes=None, reply_to=None):
    """Desa el tuit a 📤 Cua X (Pendent). Torna un id fals per encadenar fils."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    if reply_to and reply_to in _FILS:
        fil, ordre = _FILS[reply_to][0], _FILS[reply_to][1] + 1
    else:
        fil, ordre = None, 1
    props = {
        "Nom": {"title": [{"text": {"content": text.split("\n")[0][:90]}}]},
        "Text": {"rich_text": [{"text": {"content": text[:2000]}}]},
        "Estat": {"select": {"name": "Pendent"}},
        "Ordre": {"number": ordre},
        "Data": {"date": {"start": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(timespec="minutes")}},
    }
    if image_bytes:
        fid = _pujar_a_notion(image_bytes)
        if fid:
            props["Imatge"] = {"files": [{"type": "file_upload", "file_upload": {"id": fid},
                                          "name": "imatge"}]}
    try:
        r = requests.post("https://api.notion.com/v1/pages", headers=_notion_h(), timeout=30,
                          json={"parent": {"data_source_id": DS_CUA_X}, "properties": props})
        r.raise_for_status()
        pid = r.json()["id"]
    except Exception as e:  # noqa: BLE001
        print(f"  -> Cua X: ERROR desant el tuit: {e!r}")
        return None
    fil = fil or pid
    try:
        requests.patch(f"https://api.notion.com/v1/pages/{pid}", headers=_notion_h(), timeout=30,
                       json={"properties": {"Fil": {"rich_text": [{"text": {"content": fil}}]}}})
    except Exception:  # noqa: BLE001
        pass
    fals = f"cua:{pid}"
    _FILS[fals] = (fil, ordre)
    print(f"  -> Desat a 📤 Cua X (part {ordre}): {text[:60]}...")
    return fals


def publicar(text, image_bytes=None, reply_to=None):
    """Punt d'entrada únic: cua (per defecte) o API segons X_MODE. Mai peta."""
    if MODE == "api":
        return publicar_api(text, image_bytes=image_bytes, reply_to=reply_to)
    if not configurat():
        print("  -> Cua X: falta NOTION_TOKEN, s'omet.")
        return None
    return publicar_cua(text, image_bytes=image_bytes, reply_to=reply_to)
