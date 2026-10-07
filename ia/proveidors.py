"""Adaptadors dels proveïdors d'IA amb visió. Tots reben la mateixa imatge i el
mateix prompt i retornen el dict JSON tal com el dona el model.

Errors:
- ErrorTemporal: 429, 5xx, timeout o connexió -> val la pena reintentar.
- ErrorPermanent: clau absent, 400/401/403/404 -> passar al següent proveïdor.
- ErrorFormat: la resposta no és JSON -> es pot reintentar un cop.
"""

import base64
import json
import os

import requests

from .esquema import ESQUEMA_CARTELL

TIMEOUT = 90


class ErrorProveidor(Exception):
    pass


class ErrorTemporal(ErrorProveidor):
    pass


class ErrorPermanent(ErrorProveidor):
    pass


class ErrorFormat(ErrorProveidor):
    pass


def _post(url, headers, payload):
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    except (requests.ConnectionError, requests.Timeout) as e:
        raise ErrorTemporal(repr(e)) from e
    if r.status_code == 429 or r.status_code >= 500:
        raise ErrorTemporal(f"{r.status_code} {r.text[:200]}")
    if not r.ok:
        raise ErrorPermanent(f"{r.status_code} {r.text[:300]}")
    return r.json()


def _json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    inici, fi = text.find("{"), text.rfind("}")
    if inici < 0 or fi <= inici:
        raise ErrorFormat(f"Resposta sense JSON: {text[:200]!r}")
    try:
        return json.loads(text[inici:fi + 1])
    except json.JSONDecodeError as e:
        raise ErrorFormat(f"JSON invàlid: {e}") from e


def _data_url(image_bytes, mime):
    return f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"


class Proveidor:
    nom = ""          # nom curt per a logs i config (IA_CADENA)
    etiqueta = ""     # valor de la propietat "Model IA" a Notion
    env_clau = ""

    def disponible(self):
        return bool(os.environ.get(self.env_clau, "").strip())

    def extreu(self, image_bytes, mime, prompt):
        raise NotImplementedError


class Mistral(Proveidor):
    nom = "mistral"
    env_clau = "MISTRAL_API_KEY"

    def __init__(self):
        self.model = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
        self.etiqueta = os.environ.get("MISTRAL_ETIQUETA", "Mistral Small 4")

    def extreu(self, image_bytes, mime, prompt):
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": _data_url(image_bytes, mime)},
                ],
            }],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "cartell", "schema": ESQUEMA_CARTELL, "strict": True},
            },
        }
        headers = {"Authorization": f"Bearer {os.environ[self.env_clau]}"}
        resp = _post("https://api.mistral.ai/v1/chat/completions", headers, payload)
        return _json(resp["choices"][0]["message"]["content"])


class Gemini(Proveidor):
    nom = "gemini"
    env_clau = "GEMINI_API_KEY"

    def __init__(self):
        self.model = os.environ.get("GEMINI_MODEL_CARTELLS", "gemini-3.1-flash-lite")
        self.etiqueta = os.environ.get("GEMINI_ETIQUETA", "Gemini 3.1 Flash-Lite")

    def extreu(self, image_bytes, mime, prompt):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "contents": [{"parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime, "data": base64.b64encode(image_bytes).decode()}},
            ]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "responseJsonSchema": ESQUEMA_CARTELL,
            },
        }
        headers = {"x-goog-api-key": os.environ[self.env_clau]}
        resp = _post(url, headers, payload)
        try:
            text = resp["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            # Sense candidats (p. ex. bloquejat per seguretat): no té sentit reintentar
            raise ErrorPermanent(f"Resposta Gemini sense text: {str(resp)[:200]}") from e
        return _json(text)


class Groq(Proveidor):
    nom = "groq"
    env_clau = "GROQ_API_KEY"

    def __init__(self):
        self.model = os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b")
        self.etiqueta = os.environ.get("GROQ_ETIQUETA", "Qwen 3.8 (Groq)")

    def extreu(self, image_bytes, mime, prompt):
        # Groq: mode JSON genèric; l'esquema va dins el prompt i el valida extraccio.py
        prompt_amb_esquema = (
            prompt + "\n\nL'objecte JSON ha de seguir exactament aquest JSON Schema:\n"
            + json.dumps(ESQUEMA_CARTELL, ensure_ascii=False)
        )
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_amb_esquema},
                    {"type": "image_url", "image_url": {"url": _data_url(image_bytes, mime)}},
                ],
            }],
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {os.environ[self.env_clau]}"}
        resp = _post("https://api.groq.com/openai/v1/chat/completions", headers, payload)
        return _json(resp["choices"][0]["message"]["content"])


PROVEIDORS = {p.nom: p for p in (Mistral, Gemini, Groq)}


def cadena():
    """Proveïdors en l'ordre d'IA_CADENA (per defecte mistral,gemini,groq),
    saltant els que no tenen clau configurada."""
    ordre = os.environ.get("IA_CADENA", "mistral,gemini,groq")
    resultat = []
    for nom in [n.strip().lower() for n in ordre.split(",") if n.strip()]:
        cls = PROVEIDORS.get(nom)
        if cls is None:
            continue
        p = cls()
        if p.disponible():
            resultat.append(p)
    return resultat
