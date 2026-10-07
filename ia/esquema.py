"""Esquema JSON i prompt únics per a tots els proveïdors."""

CATEGORIES = [
    "Música", "Teatre", "Exposició", "Cinema", "Patrimoni", "Literatura",
    "Familiar", "Taller", "Gastronomia", "Mercat", "Conferència", "Altres",
    "Dansa", "Art", "Festa popular",
]

CONFIANCES = ["Alta", "Mitjana", "Baixa"]


def _nullable_str(desc):
    return {"type": ["string", "null"], "description": desc}


# JSON Schema estricte (compatible amb Mistral/OpenAI "strict": totes les
# propietats requerides i additionalProperties=false; els opcionals són null).
ESQUEMA_CARTELL = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "text_visible": {
            "type": "string",
            "description": "Transcripció literal de TOT el text que es veu al cartell, en l'ordre de lectura, sense corregir ni traduir.",
        },
        "titol": _nullable_str("Nom de l'activitat"),
        "data_inici": _nullable_str("Data de l'activitat, YYYY-MM-DD"),
        "data_fi": _nullable_str("Últim dia si és un rang, YYYY-MM-DD; null si és un sol dia"),
        "any_explicit": {
            "type": "boolean",
            "description": "true només si l'any surt escrit al cartell",
        },
        "hora": _nullable_str("Hora d'inici HH:MM; si n'hi ha diverses, separades per ' / '"),
        "lloc": _nullable_str("Nom de l'espai o adreça, tal com surt"),
        "organitzador": _nullable_str("Entitat organitzadora"),
        "preu": _nullable_str("Preu tal com surt ('Gratuït', '8 €')"),
        "programa": _nullable_str("Festival, cicle o festa major del qual forma part"),
        "categoria": {"type": "string", "enum": CATEGORIES},
        "resum_web": {
            "type": "string",
            "description": "2-3 frases neutres en català per a la fitxa web, només amb informació del cartell",
        },
        "dubtes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ambigüitats o dades que caldria confirmar (buit si no n'hi ha)",
        },
        "confianca": {"type": "string", "enum": CONFIANCES},
        "requadre_cartell": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "x_min": {"type": "integer"},
                "y_min": {"type": "integer"},
                "x_max": {"type": "integer"},
                "y_max": {"type": "integer"},
            },
            "required": ["x_min", "y_min", "x_max", "y_max"],
        },
    },
    "required": [
        "text_visible", "titol", "data_inici", "data_fi", "any_explicit", "hora",
        "lloc", "organitzador", "preu", "programa", "categoria", "resum_web",
        "dubtes", "confianca", "requadre_cartell",
    ],
}


def prompt_cartell(avui_iso):
    return f"""Ets l'assistent de l'Agenda Cultural de Tarragona (AgendaTGN).
Reps una captura o foto d'un cartell d'una activitat cultural (pot ser d'Instagram,
WhatsApp, una web o un cartell al carrer). Avui és {avui_iso}.

Fes DUES COSES SEPARADES:
1. "text_visible": copia literalment TOT el text que es veu al cartell, línia a línia,
   sense corregir, traduir ni resumir. Ignora la interfície de l'app (barra d'estat,
   botons d'Instagram, comentaris).
2. La resta de camps: interpreta el cartell i omple'ls.

REGLES:
- No inventis res. Si una dada no surt al cartell, posa null.
- data_inici / data_fi en format YYYY-MM-DD. Si el cartell no diu l'any, tria l'any
  de la propera vegada que arribi aquella data a partir d'avui i posa any_explicit=false.
- Distingeix la data de l'activitat d'altres dates (venda d'entrades, inscripcions).
  Si hi ha dubte, explica-ho a "dubtes".
- hora en format HH:MM (24 h).
- categoria: EXACTAMENT una de: {", ".join(CATEGORIES)}.
- resum_web en català encara que el cartell sigui en castellà.
- confianca: Alta = títol, data, hora i lloc clars; Mitjana = falta o és dubtós algun
  camp important; Baixa = imatge confusa, poc text o no és un cartell d'activitat.
- requadre_cartell: requadre del cartell en si (sense interfície al voltant), amb
  coordenades 0-1000 sobre la imatge sencera. Si la imatge ja és només el cartell:
  0,0,1000,1000.

Respon NOMÉS amb l'objecte JSON."""
