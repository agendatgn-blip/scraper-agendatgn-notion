"""Capa d'IA de l'AgendaTGN: llegeix cartells amb una cadena de proveïdors
(Mistral → Gemini → Groq), valida el resultat i decideix si cal revisió humana.

Ús:
    from ia import extreu_cartell
    resultat = extreu_cartell(bytes_imatge, "image/jpeg")
"""

from .extraccio import extreu_cartell, ResultatCartell, TotsElsProveidorsHanFallat  # noqa: F401
