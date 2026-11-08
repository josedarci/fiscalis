import threading
import time
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import requests
from fastapi.testclient import TestClient

import main


VALID_CNPJ = "11222333000181"
TOKEN = "ct01-secret-token"
VALID_UFS = ["SP", "RJ"]
VALID_VIGENCY = {
    "VigenciaInicio": "2026-01-01",
    "VigenciaFim": "2026-12-31",
}


def valid_request(**overrides):
    payload = {
        "token": TOKEN,
        "cnpj": VALID_CNPJ,
        "codigo": "01012100",
        "gtin": "7891234567890",
        "descricao": "Produto",
        "valor": "100.00",
        "ufs": VALID_UFS,
        "cenario": "nacional",
    }
    payload.update(overrides)
    return payload


def ibpt_result(**overrides):
    result = {
        "Codigo": "01012100",
        "UF": "SP",
        "Nacional": "10",
        "Estadual": "4",
        "Municipal": "1",
        "Importado": "20",
        "Fonte": "IBPT",
        "Versao": "2026.1",
        **VALID_VIGENCY,
    }
    result.update(overrides)
    return result


class Ct01ApiTests(unittest.TestCase):
    def setUp(self):
        self.startup_mock = Mock()
        self.startup = patch.object(
            main.app.router, "on_startup", [self.startup_mock]
        )
        self.startup.start()
        self.addCleanup(self.startup.stop)

        self.ibpt = patch(
            "main.requests.get",
            side_effect=AssertionError("IBPT deve permanecer mockado"),
        )
        self.ibpt_mock = self.ibpt.start()
        self.addCleanup(self.ibpt.stop)

        self.database = patch(
            "main._db_connection",
            side_effect=AssertionError("o banco real não deve ser acessado"),
        )
        self.db_mock = self.database.start()
        self.addCleanup(self.database.stop)

        self.client = TestClient(main.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def allow_ibpt(self, body=None, *, ok=True, side_effect=None):
        if side_effect is not None:
            self.ibpt_mock.side_effect = side_effect
            return None

        def fake_get(url, *, params, timeout):
            response = Mock(ok=ok)
            if body is None:
                response_body = ibpt_result(Codigo=params["codigo"], UF=params["uf"])
            else:
                response_body = dict(body)
                if (
                    response_body.get("Codigo") == "01012100"
                    and response_body.get("UF") == "SP"
                ):
                    response_body["Codigo"] = params["codigo"]
                    response_body["UF"] = params["uf"]
            response.json.return_value = response_body
            return response

        self.ibpt_mock.side_effect = fake_get
        return None

    def allow_database(self, *, rows=None, row=None, record_id=100):
        connection = MagicMock()
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.lastrowid = record_id
        cursor.fetchall.return_value = rows if rows is not None else []
        cursor.fetchone.return_value = row
        connection.cursor.return_value = cursor
        self.db_mock.side_effect = None
        self.db_mock.return_value = connection
        return connection, cursor

    def compare(self, payload=None):
        return self.client.post(
            "/api/comparar-tributos",
            json=valid_request() if payload is None else payload,
        )

    def test_comparison_contract_two_ufs_and_external_params(self):
        self.allow_ibpt()

        response = self.compare(
            valid_request(
                NCM="00123456",
                codigo=None,
                unidadeMedida="KG",
                gtin="7891234567890",
                ex=7,
            )
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            set(body),
            {"comparison_id", "history_status", "cenario", "comparabilidade", "resumo", "resultados"},
        )
        self.assertIsNone(body["comparison_id"])
        self.assertEqual(body["history_status"], "BLOCKED_LICENSE")
        self.assertEqual(body["cenario"], "nacional")
        self.assertEqual(body["comparabilidade"], "COMPARABLE")
        self.assertEqual(set(body["resumo"]), {"menor_uf", "maior_uf"})
        self.assertEqual(
            {item["uf"] for item in body["resultados"]}, set(VALID_UFS)
        )
        self.assertEqual(
            set(body["resultados"][0]),
            {
                "id", "uf", "status", "comparabilidade", "Federal", "Estadual",
                "Municipal", "Importado", "valor_federal", "valor_estadual",
                "valor_municipal", "total_estimado", "percentual_total",
                "Fonte", "Versao", "VigenciaInicio", "VigenciaFim", "erro",
            },
        )
        for item in body["resultados"]:
            self.assertIsNone(item["id"])
            self.assertEqual(item["status"], "SUCCESS")
            self.assertEqual(item["comparabilidade"], "COMPARABLE")
            self.assertEqual(item["VigenciaInicio"], "2026-01-01")
            self.assertEqual(item["VigenciaFim"], "2026-12-31")

        params = [call.kwargs["params"] for call in self.ibpt_mock.call_args_list]
        self.assertEqual(len(params), 2)
        for query in params:
            self.assertEqual(query["codigo"], "00123456")
            self.assertEqual(query["token"], TOKEN)
            self.assertEqual(query["cnpj"], VALID_CNPJ)
            self.assertEqual(query["descricao"], "Produto")
            self.assertEqual(query["unidadeMedida"], "KG")
            self.assertEqual(query["valor"], "100.00")
            self.assertEqual(query["gtin"], "7891234567890")
            self.assertEqual(query["ex"], 7)
        self.assertEqual(
            {tuple(sorted((key, value) for key, value in item.items() if key != "uf"))
             for item in params},
            {tuple(sorted((key, value) for key, value in params[0].items() if key != "uf"))},
        )
        self.assertEqual({query["uf"] for query in params}, set(VALID_UFS))

        self.db_mock.assert_not_called()

        self.ibpt_mock.reset_mock()
        self.db_mock.reset_mock()
        history_connection, history_cursor = self.allow_database(rows=[])
        history = self.client.get("/api/historico")
        self.assertEqual(history.status_code, 200)
        self.assertNotIn(TOKEN, history.text)
        history_sql, history_params = history_cursor.execute.call_args.args
        self.assertNotIn(TOKEN, history_sql)
        self.assertNotIn(TOKEN, repr(history_params))
        self.ibpt_mock.assert_not_called()
        history_connection.close.assert_called_once()

    def test_twenty_seven_ufs_are_returned_with_bounded_concurrency(self):
        lock = threading.Lock()
        active = 0
        observed_max = 0

        def fake_get(url, *, params, timeout):
            nonlocal active, observed_max
            with lock:
                active += 1
                observed_max = max(observed_max, active)
            try:
                time.sleep(0.005)
                response = Mock(ok=True)
                response.json.return_value = ibpt_result(Codigo=params["codigo"], UF=params["uf"])
                return response
            finally:
                with lock:
                    active -= 1

        self.ibpt_mock.side_effect = fake_get
        self.allow_database()
        with patch.dict("os.environ", {"IBPT_COMPARE_CONCURRENCY": "20"}):
            response = self.compare(valid_request(ufs=sorted(main.BRAZILIAN_UFS)))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row["uf"] for row in response.json()["resultados"]},
            set(main.BRAZILIAN_UFS),
        )
        self.assertEqual(len(response.json()["resultados"]), 27)
        self.assertTrue(
            all(row["status"] == "SUCCESS" for row in response.json()["resultados"])
        )
        self.assertLessEqual(observed_max, 5)

    def test_rejects_invalid_uf_count_duplicates_ncm_cnpj_value_and_scenario(self):
        invalid_payloads = [
            valid_request(gtin=""),
            {key: value for key, value in valid_request().items() if key != "gtin"},
            valid_request(ufs=["SP"]),
            valid_request(ufs=sorted(main.BRAZILIAN_UFS) + ["SP"]),
            valid_request(ufs=["SP", "SP"]),
            valid_request(ufs=["SP", "XX"]),
            valid_request(codigo="1234567"),
            valid_request(codigo="12A45678"),
            valid_request(cnpj="11222333000180"),
            valid_request(cnpj="00000000000000"),
            valid_request(valor="0"),
            valid_request(valor="-1"),
            valid_request(valor="NaN"),
            valid_request(valor="Infinity"),
            valid_request(valor="not-a-number"),
            valid_request(cenario="combined"),
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.compare(payload)
                self.assertEqual(response.status_code, 422)
        self.ibpt_mock.assert_not_called()
        self.db_mock.assert_not_called()

    def test_ncm_leading_zeroes_are_preserved(self):
        self.allow_ibpt()
        self.allow_database()

        response = self.compare(
            valid_request(codigo=None, ncm="00123456")
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {call.kwargs["params"]["codigo"] for call in self.ibpt_mock.call_args_list},
            {"00123456"},
        )

    def test_gtin_is_required_nonblank_and_forwarded_unchanged(self):
        self.allow_ibpt()
        payload = valid_request(gtin="  custom identifier  ")
        response = self.compare(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {call.kwargs["params"]["gtin"] for call in self.ibpt_mock.call_args_list},
            {"  custom identifier  "},
        )

    def test_each_scenario_selects_its_own_federal_rate_and_ranking(self):
        def fake_get(url, *, params, timeout):
            response = Mock(ok=True)
            response.json.return_value = ibpt_result(
                Codigo=params["codigo"],
                UF=params["uf"],
                Nacional={"SP": "10", "RJ": "20"}[params["uf"]],
                Importado={"SP": "80", "RJ": "5"}[params["uf"]],
                Estadual={"SP": "4", "RJ": "1"}[params["uf"]],
                Municipal="1",
            )
            return response

        self.ibpt_mock.side_effect = fake_get
        self.allow_database()
        national = self.compare(valid_request(cenario="nacional"))
        self.assertEqual(national.status_code, 200)
        national_body = national.json()
        national_rows = {row["uf"]: row for row in national_body["resultados"]}
        self.assertEqual(national_rows["SP"]["Federal"], "10")
        self.assertEqual(national_rows["SP"]["Importado"], "80")
        self.assertEqual(national_rows["SP"]["valor_federal"], "10.00")
        self.assertEqual(national_rows["SP"]["total_estimado"], "15.00")
        self.assertEqual(national_body["resumo"], {"menor_uf": "SP", "maior_uf": "RJ"})

        self.allow_database()
        imported = self.compare(valid_request(cenario="importado"))
        self.assertEqual(imported.status_code, 200)
        imported_body = imported.json()
        imported_rows = {row["uf"]: row for row in imported_body["resultados"]}
        self.assertEqual(imported_rows["SP"]["Federal"], "80")
        self.assertEqual(imported_rows["SP"]["Importado"], "80")
        self.assertEqual(imported_rows["SP"]["valor_federal"], "80.00")
        self.assertEqual(imported_rows["SP"]["total_estimado"], "85.00")
        self.assertEqual(imported_body["resumo"], {"menor_uf": "RJ", "maior_uf": "SP"})

    def test_zero_rate_is_distinct_from_missing_rate(self):
        self.allow_ibpt(ibpt_result(Nacional="0"))
        self.allow_database()
        zero_response = self.compare()
        self.assertEqual(zero_response.status_code, 200)
        zero_rows = zero_response.json()["resultados"]
        self.assertTrue(all(row["Federal"] == "0" for row in zero_rows))
        self.assertTrue(all(row["valor_federal"] == "0.00" for row in zero_rows))

        self.allow_ibpt(ibpt_result(Estadual=None))
        self.allow_database()
        missing_response = self.compare()
        self.assertEqual(missing_response.status_code, 200)
        self.assertEqual(missing_response.json()["comparabilidade"], "UNVERIFIED")
        self.assertEqual(
            missing_response.json()["resumo"], {"menor_uf": None, "maior_uf": None}
        )
        for row in missing_response.json()["resultados"]:
            self.assertIsNone(row["valor_estadual"])
            self.assertIsNone(row["total_estimado"])
            self.assertIsNone(row["percentual_total"])

    def test_partial_timeout_and_http_error_return_error_rows(self):
        def fake_get(url, *, params, timeout):
            if params["uf"] == "SP":
                raise requests.Timeout("private timeout detail")
            response = Mock(ok=False)
            return response

        self.ibpt_mock.side_effect = fake_get
        self.allow_database()
        response = self.compare()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["comparabilidade"], "UNVERIFIED")
        self.assertEqual(
            {row["uf"]: row["status"] for row in body["resultados"]},
            {"SP": "ERROR", "RJ": "ERROR"},
        )
        self.assertTrue(all(row["comparabilidade"] == "ERROR" for row in body["resultados"]))
        self.assertNotIn("private timeout detail", response.text)

    def test_metadata_mismatch_makes_comparison_incompatible(self):
        mismatch_cases = (
            ("VigenciaInicio", "2026-02-01"),
            ("Versao", "2026.2"),
        )
        for field, second_value in mismatch_cases:
            with self.subTest(field=field):
                def fake_get(url, *, params, timeout):
                    metadata = {field: second_value} if params["uf"] == "RJ" else {}
                    response = Mock(ok=True)
                    response.json.return_value = ibpt_result(
                        Codigo=params["codigo"],
                        UF=params["uf"],
                        **metadata,
                    )
                    return response

                self.ibpt_mock.side_effect = fake_get
                self.allow_database()
                response = self.compare()

                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["comparabilidade"], "INCOMPATIBLE")
                self.assertEqual(
                    body["resumo"], {"menor_uf": None, "maior_uf": None}
                )

    def test_returned_product_identity_is_checked_before_using_rates(self):
        for field in ("Codigo", "UF"):
            with self.subTest(field=field):
                def fake_get(url, *, params, timeout):
                    response = Mock(ok=True)
                    identity = {
                        "Codigo": params["codigo"],
                        "UF": params["uf"],
                    }
                    identity[field] = "99999999" if field == "Codigo" else "XX"
                    response.json.return_value = ibpt_result(**identity)
                    return response

                self.ibpt_mock.side_effect = fake_get
                response = self.compare()
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["comparabilidade"], "UNVERIFIED")
                self.assertEqual(body["resumo"], {"menor_uf": None, "maior_uf": None})
                results = {item["uf"]: item for item in body["resultados"]}
                self.assertEqual(results["SP"]["status"], "ERROR")
                self.assertIsNone(results["SP"]["Federal"])
                self.assertIsNone(results["SP"]["total_estimado"])
                self.assertEqual(results["RJ"]["status"], "SUCCESS")

    def test_missing_returned_identity_keeps_rates_but_prevents_ranking(self):
        def fake_get(url, *, params, timeout):
            response = Mock(ok=True)
            result = ibpt_result(Codigo=params["codigo"], UF=params["uf"])
            if params["uf"] == "RJ":
                result.pop("UF")
            response.json.return_value = result
            return response

        self.ibpt_mock.side_effect = fake_get
        response = self.compare()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["comparabilidade"], "UNVERIFIED")
        self.assertEqual(body["resumo"], {"menor_uf": None, "maior_uf": None})
        rj = next(item for item in body["resultados"] if item["uf"] == "RJ")
        self.assertEqual(rj["status"], "SUCCESS")
        self.assertEqual(rj["Federal"], "10")
        self.assertEqual(rj["total_estimado"], "15.00")

    def test_absent_vigency_is_unverified_and_does_not_rank(self):
        self.allow_ibpt(ibpt_result(VigenciaInicio=None, VigenciaFim=None))
        self.allow_database()

        response = self.compare()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["comparabilidade"], "UNVERIFIED")
        self.assertEqual(body["resumo"], {"menor_uf": None, "maior_uf": None})
        self.assertTrue(
            all(
                row["VigenciaInicio"] is None and row["VigenciaFim"] is None
                for row in body["resultados"]
            )
        )

    def test_comparisons_do_not_access_database_pending_license_terms(self):
        self.allow_ibpt()
        response = self.compare()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["history_status"], "BLOCKED_LICENSE")
        self.db_mock.assert_not_called()
        self.assertTrue(all(row["id"] is None for row in response.json()["resultados"]))

    def test_existing_endpoints_still_work(self):
        self.startup_mock.assert_called_once_with()
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/tabela").status_code, 200)
        self.assertEqual(self.client.get("/comparar").status_code, 200)

        self.allow_ibpt()
        self.allow_database()
        legacy = self.client.post(
            "/api/consultar-imposto",
            json={
                "token": TOKEN,
                "cnpj": VALID_CNPJ,
                "codigo": "01012100",
                "uf": "SP",
                "descricao": "Produto",
                "valor": "100.00",
            },
        )
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(legacy.json()["codigo"], "01012100")
        self.assertEqual(legacy.json()["uf"], "SP")

    def test_history_filters_include_audit_fields_without_external_calls(self):
        row = {
            "id": 8,
            "uf": "SP",
            "codigo_ncm": "01012100",
            "valor_unitario": Decimal("100.00"),
            "audit_scenario": "nacional",
            "audit_source_version": "2026.1",
        }
        connection, cursor = self.allow_database(rows=[row])
        response = self.client.get(
            "/api/historico",
            params={
                "ncm": "01012100",
                "uf": "sp",
                "cenario": "nacional",
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["audit_scenario"], "nacional")
        self.assertEqual(response.json()[0]["audit_source_version"], "2026.1")
        sql, params = cursor.execute.call_args.args
        for field in ("codigo_ncm = %s", "uf = %s", "cenario = %s", "comparison_id IS NULL"):
            self.assertIn(field, sql)
        self.assertIn("comparison_id AS audit_group_id", sql)
        self.assertIn("versao_fonte AS audit_source_version", sql)
        self.assertEqual(
            params,
            (
                "01012100",
                "SP",
                "nacional",
                date(2026, 1, 1),
                date(2026, 2, 1),
                50,
            ),
        )
        self.assertNotIn(TOKEN, response.text)
        self.ibpt_mock.assert_not_called()
        connection.close.assert_called_once()

    def test_detail_and_reproduction_use_persisted_values_only(self):
        stored = {
            "id": 17,
            "uf": "SP",
            "codigo_ncm": "01012100",
            "audit_scenario": "nacional",
            "audit_source_version": "2026.1",
        }
        detail_connection, _ = self.allow_database(row=stored)
        detail = self.client.get("/api/historico/17")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["id"], 17)
        self.assertEqual(detail.json()["audit_scenario"], "nacional")
        detail_sql = detail_connection.cursor.return_value.execute.call_args.args[0]
        self.assertIn("comparison_id AS audit_group_id", detail_sql)
        self.assertIn("cenario AS audit_scenario", detail_sql)
        self.assertNotIn("audit_group_id FROM", detail_sql)
        detail_connection.close.assert_called_once()

        reproduction_row = {
            "id": 17,
            "valor_unitario": Decimal("100.00"),
            "aliquota_nacional": Decimal("10"),
            "aliquota_estadual": Decimal("4"),
            "aliquota_municipal": Decimal("1"),
            "aliquota_importado": Decimal("80"),
            "audit_scenario": "nacional",
            "comparison_id": None,
        }
        reproduce_connection, _ = self.allow_database(row=reproduction_row)
        reproduced = self.client.post("/api/historico/17/reproduzir")

        self.assertEqual(reproduced.status_code, 200)
        self.assertEqual(reproduced.json()["status"], "AVAILABLE")
        self.assertEqual(reproduced.json()["Federal"], "10.00")
        self.assertEqual(reproduced.json()["Estadual"], "4.00")
        self.assertEqual(reproduced.json()["Municipal"], "1.00")
        self.assertEqual(reproduced.json()["total_estimado"], "15.00")
        self.assertEqual(reproduced.json()["cenario"], "nacional")
        replay_calls = reproduce_connection.cursor.return_value.execute.call_args_list
        self.assertIn("SELECT comparison_id", replay_calls[0].args[0])
        self.assertIn("cenario AS audit_scenario", replay_calls[1].args[0])
        reproduce_connection.close.assert_called_once()
        self.ibpt_mock.assert_not_called()

    def test_legacy_record_reproduction_is_unavailable_without_external_call(self):
        connection, _ = self.allow_database(
            row={
                "id": 5,
                "valor_unitario": Decimal("100.00"),
                "aliquota_nacional": Decimal("10"),
                "aliquota_estadual": Decimal("4"),
                "aliquota_municipal": Decimal("1"),
                "aliquota_importado": Decimal("80"),
                "audit_scenario": None,
            }
        )

        response = self.client.post("/api/historico/5/reproduzir")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "UNAVAILABLE")
        self.assertIn("erro", response.json())
        self.ibpt_mock.assert_not_called()
        connection.close.assert_called_once()

    def test_comparison_specific_history_detail_and_replay_fail_closed(self):
        detail_connection, _ = self.allow_database(
            row={"id": 24, "comparison_id": "44b60a94-5be1-4429-a4e3-73057a75a31a"}
        )
        detail = self.client.get("/api/historico/24")
        self.assertEqual(detail.status_code, 451)
        self.assertIn("licença", detail.json()["detail"])
        detail_connection.close.assert_called_once()

        replay_connection, _ = self.allow_database(
            row={
                "id": 24,
                "comparison_id": "44b60a94-5be1-4429-a4e3-73057a75a31a",
                "valor_unitario": Decimal("100"),
                "aliquota_nacional": Decimal("10"),
                "aliquota_estadual": Decimal("4"),
                "aliquota_municipal": Decimal("1"),
                "aliquota_importado": Decimal("80"),
                "audit_scenario": "nacional",
            }
        )
        replay = self.client.post("/api/historico/24/reproduzir")
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["status"], "UNAVAILABLE")
        replay_connection.close.assert_called_once()
        self.ibpt_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
