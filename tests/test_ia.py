"""Proves del mòdul ia/ sense xarxa: python -m unittest discover tests"""

import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ia import extraccio, proveidors  # noqa: E402
from ia.validador import comprova_esquema, data_apareix, valida  # noqa: E402

AVUI = date(2026, 10, 7)

BO = {
    "text_visible": "CONCERT DE TARDOR\nCor de Tarragona\nDissabte 17 d'octubre · 19:00 h\n"
                    "Teatre Tarragona\nEntrada gratuïta",
    "titol": "Concert de tardor",
    "data_inici": "2026-10-17",
    "data_fi": None,
    "any_explicit": False,
    "hora": "19:00",
    "lloc": "Teatre Tarragona",
    "organitzador": "Cor de Tarragona",
    "preu": "Gratuït",
    "programa": None,
    "categoria": "Música",
    "resum_web": "Concert del Cor de Tarragona.",
    "dubtes": [],
    "confianca": "Alta",
    "requadre_cartell": {"x_min": 0, "y_min": 0, "x_max": 1000, "y_max": 1000},
}


def bo(**canvis):
    d = dict(BO)
    d.update(canvis)
    return comprova_esquema(d)


class TestValidador(unittest.TestCase):
    def test_cartell_clar_es_alta(self):
        d, problemes, conf, estat = valida(bo(), avui=AVUI)
        self.assertEqual(conf, "Alta", problemes)
        self.assertEqual(estat, "Pendent revisar")
        self.assertEqual(problemes, [])

    def test_mai_validada(self):
        for canvis in ({}, {"data_inici": None}, {"lloc": None}):
            _, _, _, estat = valida(bo(**canvis), avui=AVUI)
            self.assertNotEqual(estat, "Validada")

    def test_sense_data(self):
        _, _, conf, estat = valida(bo(data_inici=None), avui=AVUI)
        self.assertEqual((conf, estat), ("Baixa", "Revisar data"))

    def test_data_inventada(self):
        # el 25/10 no surt al text
        _, problemes, conf, estat = valida(bo(data_inici="2026-10-25"), avui=AVUI)
        self.assertEqual(estat, "Revisar data")
        self.assertEqual(conf, "Mitjana")

    def test_any_implicit_passa_a_l_any_seguent(self):
        text = "FIRA DE GENER\n10 de gener\nPlaça de la Font 11:00"
        d, _, _, _ = valida(bo(text_visible=text, titol="Fira de gener", data_inici="2026-01-10",
                               lloc="Plaça de la Font", hora="11:00"), avui=AVUI)
        self.assertEqual(d["data_inici"], "2027-01-10")

    def test_any_explicit_passat_es_revisa(self):
        _, _, conf, estat = valida(bo(data_inici="2025-10-17", any_explicit=True), avui=AVUI)
        self.assertEqual((conf, estat), ("Baixa", "Revisar data"))

    def test_lloc_no_surt(self):
        _, _, conf, estat = valida(bo(lloc="Auditori Josep Carreras"), avui=AVUI)
        self.assertEqual((conf, estat), ("Mitjana", "Revisar lloc"))

    def test_categoria_fora_de_llista(self):
        d, _, conf, _ = valida(bo(categoria="Concerts"), avui=AVUI)
        self.assertEqual(d["categoria"], "Altres")
        self.assertEqual(conf, "Mitjana")

    def test_hores_multiples(self):
        d, _, _, _ = valida(bo(hora="18 h i 20.30h"), avui=AVUI)
        self.assertEqual(d["hora"], "18:00 / 20:30")

    def test_confianca_model_baixa_mana(self):
        _, _, conf, _ = valida(bo(confianca="Baixa"), avui=AVUI)
        self.assertEqual(conf, "Baixa")

    def test_data_fi_igual_inici_es_buida(self):
        d, _, _, _ = valida(bo(data_fi="2026-10-17"), avui=AVUI)
        self.assertIsNone(d["data_fi"])

    def test_data_apareix(self):
        self.assertTrue(data_apareix("2026-10-17", "Dissabte 17 d'octubre"))
        self.assertTrue(data_apareix("2026-10-17", "17/10/2026"))
        self.assertTrue(data_apareix("2026-03-05", "5 de marzo"))
        self.assertTrue(data_apareix("2026-03-05", "5 de març"))
        self.assertFalse(data_apareix("2026-10-17", "Dissabte 18 d'octubre"))
        self.assertFalse(data_apareix("2026-10-17", "17 de novembre"))

    def test_esquema_incomplet(self):
        from ia.validador import RespostaInvalida
        with self.assertRaises(RespostaInvalida):
            comprova_esquema({"titol": "x"})
        d = comprova_esquema({"text_visible": "hola", "dubtes": "no és llista"})
        self.assertEqual(d["dubtes"], [])
        self.assertIsNone(d["titol"])


class Fals(proveidors.Proveidor):
    def __init__(self, nom, respostes):
        self.nom = nom
        self.etiqueta = nom.upper()
        self.model = nom
        self.respostes = list(respostes)
        self.crides = 0

    def extreu(self, image_bytes, mime, prompt):
        self.crides += 1
        r = self.respostes.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@mock.patch.object(extraccio.time, "sleep", lambda s: None)
class TestCadena(unittest.TestCase):
    def test_primer_ok(self):
        a = Fals("a", [dict(BO)])
        b = Fals("b", [dict(BO)])
        r = extraccio.extreu_cartell(b"x", avui=AVUI, cadena=[a, b])
        self.assertEqual(r.model_etiqueta, "A")
        self.assertEqual(b.crides, 0)

    def test_temporal_i_despres_ok(self):
        a = Fals("a", [proveidors.ErrorTemporal("503"), dict(BO)])
        r = extraccio.extreu_cartell(b"x", avui=AVUI, cadena=[a])
        self.assertEqual(a.crides, 2)
        self.assertEqual(r.confianca, "Alta")

    def test_saturat_passa_al_seguent(self):
        a = Fals("a", [proveidors.ErrorTemporal("429")] * 3)
        b = Fals("b", [dict(BO)])
        r = extraccio.extreu_cartell(b"x", avui=AVUI, cadena=[a, b])
        self.assertEqual(a.crides, 3)  # 1 + 2 reintents
        self.assertEqual(r.model_etiqueta, "B")

    def test_permanent_no_reintenta(self):
        a = Fals("a", [proveidors.ErrorPermanent("401")])
        b = Fals("b", [dict(BO)])
        r = extraccio.extreu_cartell(b"x", avui=AVUI, cadena=[a, b])
        self.assertEqual(a.crides, 1)
        self.assertEqual(r.model_etiqueta, "B")

    def test_format_reintenta_un_cop(self):
        a = Fals("a", [{"x": 1}, {"y": 2}])
        b = Fals("b", [dict(BO)])
        r = extraccio.extreu_cartell(b"x", avui=AVUI, cadena=[a, b])
        self.assertEqual(a.crides, 2)
        self.assertEqual(r.model_etiqueta, "B")

    def test_tots_fallen(self):
        a = Fals("a", [proveidors.ErrorPermanent("401")])
        b = Fals("b", [proveidors.ErrorTemporal("503")] * 3)
        with self.assertRaises(extraccio.TotsElsProveidorsHanFallat):
            extraccio.extreu_cartell(b"x", avui=AVUI, cadena=[a, b])

    def test_sense_proveidors(self):
        with self.assertRaises(extraccio.TotsElsProveidorsHanFallat):
            extraccio.extreu_cartell(b"x", avui=AVUI, cadena=[])

    def test_duplicat(self):
        a = Fals("a", [dict(BO)])
        r = extraccio.extreu_cartell(b"x", avui=AVUI, cadena=[a], es_duplicat=lambda d: True)
        self.assertEqual(r.estat_revisio, "Duplicada")

    def test_error_al_comprovar_duplicat_no_tomba(self):
        def peta(d):
            raise RuntimeError("notion caigut")
        a = Fals("a", [dict(BO)])
        r = extraccio.extreu_cartell(b"x", avui=AVUI, cadena=[a], es_duplicat=peta)
        self.assertEqual(r.estat_revisio, "Pendent revisar")


class TestConfigCadena(unittest.TestCase):
    def test_ordre_i_claus(self):
        env = {"IA_CADENA": "groq,mistral,gemini", "MISTRAL_API_KEY": "k", "GROQ_API_KEY": "k"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual([p.nom for p in proveidors.cadena()], ["groq", "mistral"])


class TestPayloadsProveidors(unittest.TestCase):
    """Comprova el format exacte de les peticions sense cridar la xarxa."""

    def _resp(self, cos):
        r = mock.Mock(status_code=200, ok=True)
        r.json.return_value = cos
        return r

    def test_mistral(self):
        import json
        cos = {"choices": [{"message": {"content": json.dumps(BO)}}]}
        with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "k"}), \
                mock.patch.object(proveidors.requests, "post", return_value=self._resp(cos)) as post:
            d = proveidors.Mistral().extreu(b"img", "image/jpeg", "p")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        self.assertTrue(payload["messages"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(d["titol"], BO["titol"])

    def test_gemini(self):
        import json
        cos = {"candidates": [{"content": {"parts": [{"text": json.dumps(BO)}]}}]}
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}), \
                mock.patch.object(proveidors.requests, "post", return_value=self._resp(cos)) as post:
            proveidors.Gemini().extreu(b"img", "image/png", "p")
        self.assertIn("gemini-3.1-flash-lite", post.call_args.args[0])
        self.assertIn("responseJsonSchema", post.call_args.kwargs["json"]["generationConfig"])

    def test_429_es_temporal(self):
        r = mock.Mock(status_code=429, ok=False, text="quota")
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "k"}), \
                mock.patch.object(proveidors.requests, "post", return_value=r):
            with self.assertRaises(proveidors.ErrorTemporal):
                proveidors.Groq().extreu(b"img", "image/jpeg", "p")


if __name__ == "__main__":
    unittest.main()
