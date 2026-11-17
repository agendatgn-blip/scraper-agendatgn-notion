"""IA de text amb cadena de proveïdors gratuïts: Groq -> Mistral -> NVIDIA.

Errors (regles de robustesa):
- 429 per minut: espera un cop i reintenta. 429 diari: aquest proveïdor queda fora per a tota l'execució.
- 5xx o timeout: un reintent curt i després el següent proveïdor.
- 400/401/403/404 (model o clau dolents): el proveïdor queda fora a la primera.
Cap proveïdor configurat amb clau buida s'intenta.
"""
import json
import os
import time

import requests

TIMEOUT = 60


class SenseIA(Exception):
    """Cap proveïdor ha pogut respondre."""


PROVEIDORS = {
    # nom: (url, variable de la clau, model per defecte, variable del model)
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY",
             "openai/gpt-oss-20b", "NOTICIES_GROQ_MODEL"),
    "mistral": ("https://api.mistral.ai/v1/chat/completions", "MISTRAL_API_KEY",
                "mistral-small-latest", "NOTICIES_MISTRAL_MODEL"),
    "nvidia": ("https://integrate.api.nvidia.com/v1/chat/completions", "NVIDIA_API_KEY",
               "meta/llama-3.3-70b-instruct", "NOTICIES_NVIDIA_MODEL"),
}
_FORA = set()   # proveïdors descartats en aquesta execució


def _json(text):
    text = (text or "").strip()
    i, f = text.find("{"), text.rfind("}")
    if i < 0 or f <= i:
        raise ValueError(f"sense JSON: {text[:150]!r}")
    return json.loads(text[i:f + 1])


def _crida(nom, sistema, usuari, model=None, max_tokens=900):
    url, env_clau, model_def, env_model = PROVEIDORS[nom]
    model = model or os.environ.get(env_model) or model_def
    body = {"model": model, "temperature": 0.4, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuari}]}
    if nom == "groq" and "gpt-oss" in model:
        body["reasoning_effort"] = "low"
    h = {"Authorization": f"Bearer {os.environ[env_clau]}", "Content-Type": "application/json"}
    for intent in range(3):
        try:
            r = requests.post(url, headers=h, json=body, timeout=TIMEOUT)
        except (requests.Timeout, requests.ConnectionError) as e:
            if intent == 0:
                time.sleep(5)
                continue
            raise RuntimeError(f"{nom}: sense connexió ({e.__class__.__name__})")
        if r.status_code == 429:
            t = r.text.lower()
            diari = any(k in t for k in ("per day", "perday", "daily", "(tpd)", "(rpd)", "requests per day", "tokens per day"))
            if diari:
                _FORA.add(nom)
                raise RuntimeError(f"{nom}: quota diària esgotada")
            if intent == 2:
                raise RuntimeError(f"{nom}: massa peticions per minut")
            espera = min(max(int(float(r.headers.get("retry-after", "15") or 15)), 10), 30)
            print(f"  {nom} 429 per minut, espero {espera} s")
            time.sleep(espera)
            continue
        if r.status_code >= 500:
            if intent == 0:
                time.sleep(5)
                continue
            raise RuntimeError(f"{nom}: error {r.status_code}")
        if 400 <= r.status_code < 500:
            _FORA.add(nom)
            raise RuntimeError(f"{nom}: {r.status_code} {r.text[:200]}")
        contingut = r.json()["choices"][0]["message"]["content"]
        return _json(contingut), f"{nom} · {model}"
    raise RuntimeError(f"{nom}: no respon")


def json_ia(sistema, usuari, primer_model=None, max_tokens=900):
    """Torna (dict, 'proveïdor · model'). Prova la cadena fins que un respon. Llança SenseIA si cap."""
    errors = []
    for nom in ("groq", "mistral", "nvidia"):
        if nom in _FORA or not os.environ.get(PROVEIDORS[nom][1], "").strip():
            continue
        try:
            return _crida(nom, sistema, usuari, model=primer_model if nom == "groq" else None,
                          max_tokens=max_tokens)
        except (RuntimeError, ValueError, KeyError, IndexError, TypeError) as e:
            print("  IA:", e)
            errors.append(str(e)[:120])
    raise SenseIA("; ".join(errors) or "cap proveïdor configurat")


def queda_ia():
    return any(n not in _FORA and os.environ.get(PROVEIDORS[n][1], "").strip() for n in PROVEIDORS)
