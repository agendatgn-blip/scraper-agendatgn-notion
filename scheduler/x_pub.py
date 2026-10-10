"""
X (Twitter) · publicació per a @agendatgn
=========================================
- Puja la imatge amb l'endpoint NOU de X (v2: POST /2/media/upload).
  L'antic (v1.1, el que feia servir tweepy.API.media_upload) torna
  "403 Your account is not permitted to access this feature" des del 9/10/2026.
- Si la imatge falla, publica igualment el text (no es perd el post).
- Mai llança excepcions: torna l'id del tuit o None, i ho explica al log.

Variables d'entorn: TWITTER_API_KEY, TWITTER_API_SECRET,
                    TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET
"""
import os
from io import BytesIO

import requests

UPLOAD_URL = "https://api.x.com/2/media/upload"
MAX_BYTES = 4_500_000  # X accepta fins a 5 MB per imatge


def _claus():
    return [os.environ.get(x) for x in ("TWITTER_API_KEY", "TWITTER_API_SECRET",
                                       "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET")]


def configurat():
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


def publicar(text, image_bytes=None, reply_to=None):
    """Publica un tuit (amb imatge si es pot). Torna l'id o None. Mai peta."""
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
