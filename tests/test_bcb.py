"""Unit tests for Brazil Central Bank (BCB) Actor."""

import unittest

from src.main import (
    fetch_bank_interest_rates,
    fetch_focus_expectations,
    fetch_ptax_fx,
    fetch_sgs_series,
    run_query,
)


class TestBcbActor(unittest.TestCase):
    def test_sgs_series_normalization_and_change(self) -> None:
        sample = [
            {"data": "10/11/2026", "valor": "13.25"},
            {"data": "11/11/2026", "valor": "13.75"},
        ]

        def fake_fetcher(url: str, _timeout: int) -> list[dict]:
            self.assertIn("bcdata.sgs.432/dados/ultimos/2", url)
            return sample

        rows = fetch_sgs_series(sgs_code=432, last_n=2, fetcher=fake_fetcher)
        self.assertEqual(len(rows), 2)
        # Most recent returned first
        self.assertEqual(rows[0]["referenceDate"], "2026-11-11")
        self.assertEqual(rows[0]["valuePrimary"], 13.75)
        self.assertEqual(rows[0]["valueSecondary"], 13.25)
        self.assertEqual(rows[0]["spreadBpsOrChange"], 0.5)
        self.assertGreater(rows[0]["changePct"], 3.7)
        self.assertEqual(rows[1]["referenceDate"], "2026-11-10")
        self.assertEqual(rows[1]["spreadBpsOrChange"], 0.0)

    def test_focus_expectations_filter_and_parsing(self) -> None:
        sample = {
            "value": [
                {
                    "Indicador": "IPCA",
                    "IndicadorDetalhe": None,
                    "Data": "2026-11-13",
                    "DataReferencia": "2026",
                    "Media": 4.62,
                    "Mediana": 4.60,
                    "DesvioPadrao": 0.19,
                    "Minimo": 4.10,
                    "Maximo": 5.20,
                    "numeroRespondentes": 141,
                },
                {
                    "Indicador": "Selic",
                    "IndicadorDetalhe": None,
                    "Data": "2026-11-13",
                    "DataReferencia": "2026",
                    "Media": 13.68,
                    "Mediana": 13.75,
                    "DesvioPadrao": 0.16,
                    "Minimo": 13.25,
                    "Maximo": 13.75,
                    "numeroRespondentes": 144,
                },
            ]
        }
        rows = fetch_focus_expectations(indicator="selic", max_results=10, fetcher=lambda _u, _t: sample)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["indicator"], "Selic")
        self.assertEqual(rows[0]["valuePrimary"], 13.75)
        self.assertEqual(rows[0]["respondents"], 144)

    def test_bank_interest_rates_filter(self) -> None:
        sample = {
            "value": [
                {
                    "Mes": "Out-2026",
                    "Modalidade": "Financiamento imobiliário com taxas de mercado - Prefixado",
                    "Posicao": 1,
                    "InstituicaoFinanceira": "CAIXA ECONOMICA FEDERAL",
                    "TaxaJurosAoMes": 0.87,
                    "TaxaJurosAoAno": 10.94,
                    "cnpj8": "00360305",
                    "anoMes": "2026-10",
                },
                {
                    "Mes": "Out-2026",
                    "Modalidade": "Cartão de crédito - Rotativo total",
                    "Posicao": 2,
                    "InstituicaoFinanceira": "BANCO INTER S.A.",
                    "TaxaJurosAoMes": 11.2,
                    "TaxaJurosAoAno": 257.4,
                    "cnpj8": "00416968",
                    "anoMes": "2026-10",
                },
            ]
        }
        rows = fetch_bank_interest_rates(query="caixa", max_results=10, fetcher=lambda _u, _t: sample)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["institution"], "CAIXA ECONOMICA FEDERAL")
        self.assertEqual(rows[0]["valuePrimary"], 10.94)
        self.assertEqual(rows[0]["valueSecondary"], 0.87)

    def test_ptax_fx_spread_calculation_and_router(self) -> None:
        sample = {
            "value": [
                {
                    "paridadeCompra": 1.0,
                    "paridadeVenda": 1.0,
                    "cotacaoCompra": 5.8000,
                    "cotacaoVenda": 5.8029,
                    "dataHoraCotacao": "2026-11-18 13:08:44.271245",
                    "tipoBoletim": "Fechamento",
                }
            ]
        }
        rows = run_query(
            {
                "mode": "ptax_fx",
                "currency": "USD",
                "startDate": "2026-11-10",
                "endDate": "2026-11-18",
            },
            fetcher=lambda url, _t: (
                self.assertIn("11-10-2026", url),
                self.assertIn("11-18-2026", url),
                sample,
            )[-1],
        )
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["spreadAbs"], 0.0029, places=6)
        self.assertAlmostEqual(rows[0]["spreadBpsOrChange"], 5.0, places=2)
        self.assertEqual(rows[0]["bulletinType"], "Fechamento")


if __name__ == "__main__":
    unittest.main()
