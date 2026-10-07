"""Recorre la cadena de proveïdors amb reintents i retorna dades validades."""

import sys
import time
from dataclasses import dataclass, field
from datetime import date

from . import proveidors
from .esquema import prompt_cartell
from .validador import RespostaInvalida, comprova_esquema, valida

ESPERES_TEMPORALS = [3, 10]   # 2 reintents per proveïdor amb 429/5xx/timeout
REINTENTS_FORMAT = 1          # 1 reintent si el JSON no compleix l'esquema


class TotsElsProveidorsHanFallat(Exception):
    pass


@dataclass
class ResultatCartell:
    dades: dict                     # camps nets i validats
    problemes: list                 # avisos del validador
    confianca: str                  # Alta / Mitjana / Baixa (final)
    estat_revisio: str              # valor per a "Estat revisió"
    model_etiqueta: str             # valor per a "Model IA"
    intents: list = field(default_factory=list)  # registre per als logs


def _log(msg):
    print(f"[ia] {msg}", file=sys.stderr)


def extreu_cartell(image_bytes, mime="image/jpeg", avui=None, es_duplicat=None, cadena=None):
    """Llegeix un cartell amb el primer proveïdor que respongui bé.

    es_duplicat: funció opcional (dades) -> bool per marcar duplicats.
    cadena: llista de proveïdors (per a proves); per defecte proveidors.cadena().
    """
    avui = avui or date.today()
    prompt = prompt_cartell(avui.isoformat())
    cadena = cadena if cadena is not None else proveidors.cadena()
    if not cadena:
        raise TotsElsProveidorsHanFallat(
            "Cap proveïdor configurat (falten MISTRAL_API_KEY / GEMINI_API_KEY / GROQ_API_KEY)")

    intents = []
    for p in cadena:
        esperes = list(ESPERES_TEMPORALS)
        errors_format = 0
        while True:
            t0 = time.monotonic()
            try:
                crua = p.extreu(image_bytes, mime, prompt)
                dades = comprova_esquema(crua)
            except proveidors.ErrorTemporal as e:
                intents.append(f"{p.nom}: temporal ({e})")
                if esperes:
                    espera = esperes.pop(0)
                    _log(f"{p.nom} no respon ({e}); reintent en {espera}s")
                    time.sleep(espera)
                    continue
                break
            except (proveidors.ErrorFormat, RespostaInvalida) as e:
                intents.append(f"{p.nom}: format ({e})")
                errors_format += 1
                if errors_format <= REINTENTS_FORMAT:
                    _log(f"{p.nom} ha tornat un JSON incorrecte ({e}); es reintenta")
                    continue
                break
            except proveidors.ErrorPermanent as e:
                intents.append(f"{p.nom}: error ({e})")
                _log(f"{p.nom} error permanent: {e}")
                break

            segons = time.monotonic() - t0
            intents.append(f"{p.nom}: ok en {segons:.1f}s")
            _log(f"{p.nom} ({p.model}) ha respost en {segons:.1f}s")
            netes, problemes, confianca, estat = valida(dades, avui=avui)
            if es_duplicat:
                try:
                    if es_duplicat(netes):
                        estat = "Duplicada"
                        problemes.append("Possible duplicat: ja hi ha una entrada amb el mateix títol i data")
                except Exception as e:  # noqa: BLE001 — la comprovació mai ha de tombar el flux
                    _log(f"No s'ha pogut comprovar duplicats: {e!r}")
            return ResultatCartell(netes, problemes, confianca, estat, p.etiqueta, intents)

    raise TotsElsProveidorsHanFallat("; ".join(intents))
