"""Prova ràpida: fa una crida a cada proveïdor d'IA configurat i diu si respon."""
import os

from . import ia

for nom, (_url, env_clau, model_def, env_model) in ia.PROVEIDORS.items():
    if not os.environ.get(env_clau, "").strip():
        print(f"{nom}: sense clau ({env_clau})")
        continue
    model = os.environ.get(env_model) or model_def
    try:
        d, qui = ia._crida(nom, "Respon NOMÉS amb JSON.", 'Torna {"ok": true, "frase": "una frase curta en català sobre Tarragona"}',
                           max_tokens=200)
        print(f"{nom}: OK · {qui} · {d}")
    except Exception as e:  # noqa: BLE001
        print(f"{nom}: FALLA · {model} · {e}")
