"""
Facebook · token de Pàgina a partir del token de l'usuari del sistema
=====================================================================
El secret FACEBOOK_PAGE_TOKEN pot ser:
  - el token de l'usuari del sistema "bot-publicacio" (Meta Business, no caduca
    i no es trenca si es canvia la contrasenya), o
  - directament un token de Pàgina (com abans).
Si és el del sistema, aquí es demana el token de la Pàgina a Graph API.
Mai peta: si no es pot, torna el token original.
"""
import requests


def token_pagina(page_id, token, version="v26.0"):
    if not (page_id and token):
        return token
    try:
        r = requests.get(f"https://graph.facebook.com/{version}/{page_id}",
                         params={"fields": "access_token", "access_token": token}, timeout=20)
        t = r.json().get("access_token") if r.ok else None
        if not t:
            print(f"  -> Avís Facebook: no s'ha obtingut el token de Pàgina ({r.status_code}); "
                  "es fa servir el del secret tal qual.")
        return t or token
    except Exception as e:  # noqa: BLE001
        print(f"  -> Avís Facebook: error obtenint el token de Pàgina ({e!r}).")
        return token
