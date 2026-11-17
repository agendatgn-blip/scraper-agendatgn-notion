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

# Models de NVIDIA disponibles amb aquesta clau (per triar-ne un que funcioni)
if os.environ.get("NVIDIA_API_KEY"):
    import requests
    r = requests.get("https://integrate.api.nvidia.com/v1/models",
                     headers={"Authorization": f"Bearer {os.environ['NVIDIA_API_KEY']}"}, timeout=30)
    ids = sorted(m["id"] for m in r.json().get("data", [])) if r.ok else []
    interessants = [i for i in ids if any(k in i.lower() for k in ("llama", "mistral", "qwen", "nemotron", "gemma", "deepseek", "gpt-oss", "kimi"))]
    print(f"NVIDIA: {len(ids)} models. Candidats:")
    for i in interessants:
        print("  ", i)
