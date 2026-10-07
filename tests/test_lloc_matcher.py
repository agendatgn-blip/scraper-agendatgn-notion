"""Proves de lloc_matcher sense xarxa: python -m unittest tests.test_lloc_matcher

Fan servir una còpia de 📍 LLOCS (tests/llocs_fixture.json) i textos reals del camp "Lloc".
"""

import json
import os
import sys
import unittest

ARREL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ARREL)

import lloc_matcher as M  # noqa: E402

with open(os.path.join(ARREL, "tests", "llocs_fixture.json"), encoding="utf-8") as f:
    LLOCS = json.load(f)


def matcher():
    return M.LlocMatcher(llocs=LLOCS, dry_run=True, geocodifica=False, log=lambda *a: None)


class TestNormalitzacio(unittest.TestCase):
    def test_normalitza(self):
        self.assertEqual(M.normalitza("Vil·la Romana dels Munts"), "villa romana dels munts")
        self.assertEqual(M.normalitza("Mèdol – Centre d’Arts"), "medol centre d arts")
        self.assertEqual(M.normalitza("Carrer August n°23"), "carrer august n 23")

    def test_clau_treu_tarragona_i_prefixos(self):
        self.assertEqual(M.clau("CaixaForum Tarragona"), "caixaforum")
        self.assertEqual(M.clau("Teatre Tarragona"), "teatre tarragona")   # sense "Tarragona" no diria res
        self.assertEqual(M.clau("Sala Plana de Casa Canals"), "casa canals")
        self.assertEqual(M.clau("Vestíbul Teatre Tarragona"), "teatre tarragona")


class TestCoincidencies(unittest.TestCase):
    ESPERATS = {
        # àlies del codi
        "Vestíbul Teatre Tarragona": "Teatre Tarragona",
        "Antiga Presó de Tarragona": "Antic Centre Penitenciari (Antiga Presó)",
        "Antic Centre Penitenciari de Tarragona": "Antic Centre Penitenciari (Antiga Presó)",
        "MAMT": "MAMT · Museu d'Art Modern",
        "Museu d'Art Modern": "MAMT · Museu d'Art Modern",
        "Sala Plana de Casa Canals": "Mèdol Cultura Contemporània",
        "Mèdol – Centre d’Arts Contemporànies de Tarragona": "Mèdol Cultura Contemporània",
        "Capsa": "Capsa de Música (Tabacalera)",
        "Capsa de Música - Espai Tabacalera": "Capsa de Música (Tabacalera)",
        "Stone rock'n'roll bar": "Stone Bar",
        "Stone Rock & Roll Bar, Tarragona": "Stone Bar",
        "La Jartá – Port Esportiu Tarragona": "Restaurant La Jartá",
        "LA JARTÁ, PORT ESPORTIU TARRAGONA": "Restaurant La Jartá",
        "12 Topos": "Bar 12 Topos",
        "URV Campus de Catalunya": "Campus URV",
        "Palau Firal i de Congressos de Tarragona · C. Arquitecte Rovira, 2": "Palau Firal",
        "Centre Cultural Antic Ajuntament": "Antic Ajuntament",
        "Pla de la Seu i voltants": "Pla de la Seu",
        "Conjunto romano de Centcelles": "Conjunt romà de Centcelles",
        "Villa romana de Els Munts": "Vil·la romana dels Munts",
        # excepció: la pedrera no és el centre d'art
        "Cantera de El Mèdol": "Pedrera del Mèdol",
        "Pedrera del Mèdol": "Pedrera del Mèdol",
        # exacte / conté / adreça / difús
        "Teatre Tarragona": "Teatre Tarragona",
        "Sala Zero, Tarragona": "Sala Zero",
        "SALA ZERO, SANT MAGI 12 - TARRAGONA": "Sala Zero",
        "Antiga Audiència - Centre Cultural El Pallol": "Antiga Audiència",
        "Espai Jove La Palmera, Tarragona": "Espai Jove La Palmera",
        "Parc de la Ciutat - Quinta de Sant Rafael": "Parc de la Ciutat (Quinta de Sant Rafael)",
        "Plaça de la Font (carrer Quinze, 10, Bonavista)": "Plaça de la Font (Bonavista)",
        "Port Esportiu Tarragona, Passeig Rafael Casanova": "Port Esportiu de Tarragona",
        "Selvático": "Restaurant Selvático",
        "SON'S Cubanos, Carrer de Lleida 17, 43001 Tarragona": "Restaurante Latino - Son's Cubanos",
        "La Bodegueta del Pagès, Rambla Vella 45, Tarragona": "Bodegueta del Pagès",
        "Limboo Beach Club & Restaurant": "Limboo Beach Club",
        "Carrer August n°23, Tarragona": "La Gata Insubmisa",
        "Biblioteca Pública de Torreforta Pepita Ferrer": "Biblioteca de Torreforta Pepita Ferrer",
        "Centre Cívic Municipal de Sant Pere i Sant Pau": "Centre Cívic de Sant Pere i Sant Pau",
        "Casal Sageta de Foc": "Casal Popular Sageta de Foc",
        "Plaça del Fòrum": "Plaza del Forum",
        "Rambla Nova, davant del Teatre Tarragona": "Teatre Tarragona",
    }

    def test_esperats(self):
        m = matcher()
        for text, nom in self.ESPERATS.items():
            with self.subTest(text=text):
                l, regla = m.troba(text)
                self.assertIsNotNone(l, f"«{text}» no ha trobat res ({regla})")
                self.assertEqual(l["nom"], nom, f"«{text}» → {l['nom']} ({regla})")

    def test_medol_centre_no_es_pedrera(self):
        l, _ = matcher().troba("Mèdol – Centre d’Arts Contemporànies de Tarragona")
        self.assertNotEqual(l["nom"], "Pedrera del Mèdol")


class TestDescartats(unittest.TestCase):
    def test_no_enllaca(self):
        for text in ["", "pendent de revisar", "Tarragona", "Barri del Pilar, Tarragona",
                     "Barri El Pilar i Eixample, Tarragona", "MNAT i Teatre de Tàrraco",
                     "El Serrallo, Tarragona",
                     "La Gata Insubmisa, C/ d’August 23; CP La Sageta de Foc, C/ Sant Domènec 18",
                     "Plaça Verdaguer – Rambla Nova – Passeig de les Palmeres"]:
            with self.subTest(text=text):
                self.assertIsNotNone(M.motiu_descart(text))
                lid, info = matcher().troba_o_crea(text)
                self.assertIsNone(lid)

    def test_i_dins_d_un_nom_no_es_dos_llocs(self):
        for text in ["Centre Cívic Municipal de Sant Pere i Sant Pau", "Palau Firal i de Congressos",
                     "Pla de la Seu i voltants"]:
            self.assertIsNone(M.motiu_descart(text), text)


class TestCreacio(unittest.TestCase):
    def test_crea_lloc_nou_un_sol_cop(self):
        m = matcher()
        lid1, info1 = m.troba_o_crea("Refugi 1 del Moll de Costa")
        lid2, info2 = m.troba_o_crea("Refugi 1, Sala 1, Moll de Costa del Port de Tarragona")
        self.assertTrue(info1.startswith("nou"))
        self.assertEqual(lid1, lid2)
        self.assertEqual(len(m.creats), 1)

    def test_camps_del_lloc_nou(self):
        self.assertEqual(M.nom_net("Brasería Cabrera, C/ Tres 35, Bonavista, Tarragona"), "Brasería Cabrera")
        self.assertEqual(M.adreca_del_text("Brasería Cabrera, C/ Tres 35, Bonavista, Tarragona"), "C/ Tres 35, Bonavista")
        self.assertEqual(M.nom_net("Capella de Sant Magí de Tarragona"), "Capella de Sant Magí")
        self.assertEqual(M.tipus_espai("Capella de Sant Magí"), "Patrimoni")
        self.assertEqual(M.tipus_espai("Brasería Cabrera"), "Bar / restaurant")
        self.assertEqual(M.tipus_espai("Teatre Metropol"), "Teatre / auditori")
        self.assertEqual(M.tipus_espai("Platja Llarga"), "Altres")


if __name__ == "__main__":
    unittest.main()
