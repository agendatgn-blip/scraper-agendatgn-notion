"""Comprovació ràpida: hi ha alguna edició en estat "Maquetant"? (per no instal·lar res si no cal)"""
import os
import requests

DS_EDICIONS = "8f487a83-0a99-4385-80c6-a1da86a17d8a"
r = requests.post(f"https://api.notion.com/v1/data_sources/{DS_EDICIONS}/query", timeout=30,
                  headers={"Authorization": f"Bearer {os.environ['NOTION_TOKEN']}", "Notion-Version": "2025-09-03"},
                  json={"filter": {"property": "Estat", "select": {"equals": "Maquetant"}}, "page_size": 1})
r.raise_for_status()
feina = bool(r.json()["results"])
print("Edició per maquetar:", "sí" if feina else "no")
with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
    f.write(f"feina={'true' if feina else 'false'}\n")
