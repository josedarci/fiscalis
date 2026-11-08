import unittest
from datetime import datetime
from decimal import Decimal
import os
from unittest.mock import MagicMock, Mock, mock_open, patch

import requests
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app as compatibility_app
import main

DB_CONNECTION = main._db_connection


VALID_CNPJ = "11222333000181"
TAX_RESPONSE = {
    "Nacional": "12.30",
    "Estadual": "18",
    "Municipal": "0",
    "Importado": "15.5",
    "Fonte": "IBPT",
}


def valid_request(**overrides):
    payload = {
        "token": "test-token",
        "cnpj": VALID_CNPJ,
        "codigo": "01012100",
        "uf": "SP",
        "descricao": "Produto",
        "valor": "3.25",
    }
    payload.update(overrides)
    return payload


class BackendApiTests(unittest.TestCase):
    def setUp(self):
        self.startup_mock = Mock()
        self.startup_patch = patch.object(
            main.app.router, "on_startup", [self.startup_mock]
        )
        self.startup_patch.start()
        self.addCleanup(self.startup_patch.stop)

        ibpt_patch = patch(
            "main.requests.get",
            side_effect=AssertionError("IBPT deve permanecer mockado"),
        )
        self.ibpt = ibpt_patch.start()
        self.addCleanup(ibpt_patch.stop)

        db_patch = patch(
            "main._db_connection",
            side_effect=AssertionError("o banco real não deve ser acessado"),
        )
        self.db = db_patch.start()
        self.addCleanup(db_patch.stop)

        self.client = TestClient(main.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def allow_ibpt(self, body=TAX_RESPONSE, *, ok=True):
        response = Mock()
        response.ok = ok
        response.json.return_value = body
        self.ibpt.side_effect = None
        self.ibpt.return_value = response
        return response

    def allow_database(self, *, record_id=42, rows=None):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.lastrowid = record_id
        cursor.fetchall.return_value = rows or []
        self.db.side_effect = None
        self.db.return_value = connection
        return connection, cursor

    def post(self, payload=None):
        return self.client.post(
            "/api/consultar-imposto", json=payload or valid_request()
        )

    def test_imports_routes_health_and_compatibility_facade(self):
        self.assertIs(compatibility_app.app, main.app)
        self.assertIs(compatibility_app.ConsultaRequest, main.ConsultaRequest)
        self.assertIs(compatibility_app.ConsultaImpostoRequest, main.ConsultaRequest)
        self.assertIs(compatibility_app.consultar_imposto, main.consultar_imposto)
        self.assertIs(compatibility_app.historico, main.historico)
        self.assertIs(compatibility_app.health_check, main.health_check)
        self.assertIs(compatibility_app.pagina_inicial, main.home)
        self.assertTrue(callable(compatibility_app.validar_configuracao_banco))
        self.assertTrue(callable(compatibility_app.consultar_ibpt))

        paths = {route.path for route in main.app.routes}
        self.assertIn("/health", paths)
        self.assertIn("/api/consultar-imposto", paths)
        self.assertIn("/api/historico", paths)
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        self.startup_mock.assert_called_once_with()
        self.ibpt.assert_not_called()
        self.db.assert_not_called()

    def test_legacy_app_model_uses_environment_credentials_and_ncm_alias(self):
        with patch.dict(
            os.environ,
            {"IBPT_TOKEN": "environment-token", "IBPT_CNPJ": VALID_CNPJ},
        ):
            request = compatibility_app.ConsultaImpostoRequest(
                ncm="01012100",
                uf="sp",
                descricao="Produto",
                valor="3.25",
            )

        self.assertEqual(request.codigo, "01012100")
        self.assertEqual(request.token, "environment-token")
        self.assertEqual(request.cnpj, VALID_CNPJ)

        with patch.dict(os.environ, {"IBPT_TOKEN": "", "IBPT_CNPJ": ""}):
            with self.assertRaises(ValidationError):
                compatibility_app.ConsultaImpostoRequest(
                    ncm="01012100",
                    uf="SP",
                    descricao="Produto",
                    valor="3.25",
                )

    def test_db_connection_supports_legacy_mysql_environment_names(self):
        legacy_env = {
            "DB_HOST": "",
            "DB_PORT": "",
            "DB_NAME": "",
            "DB_USER": "",
            "DB_PASSWORD": "",
            "MYSQL_HOST": "db.local",
            "MYSQL_PORT": "3307",
            "MYSQL_DATABASE": "fiscalis",
            "MYSQL_USER": "app",
            "MYSQL_PASSWORD": "private",
        }
        with patch.dict(os.environ, legacy_env):
            with patch("main.pymysql.connect") as connect:
                DB_CONNECTION()

        self.assertEqual(
            {key: connect.call_args.kwargs[key] for key in (
                "host",
                "port",
                "database",
                "user",
                "password",
            )},
            {
                "host": "db.local",
                "port": 3307,
                "database": "fiscalis",
                "user": "app",
                "password": "private",
            },
        )

    def test_valid_post_persists_and_returns_canonical_response(self):
        self.allow_ibpt()
        connection, cursor = self.allow_database()

        response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "id": 42,
                "codigo": "01012100",
                "uf": "SP",
                "Nacional": "12.30",
                "Estadual": "18",
                "Municipal": "0",
                "Importado": "15.5",
                "Fonte": "IBPT",
            },
        )
        self.assertEqual(self.ibpt.call_args.kwargs["params"]["valor"], "3.25")
        self.assertEqual(self.ibpt.call_args.kwargs["params"]["cnpj"], VALID_CNPJ)
        self.assertEqual(self.ibpt.call_args.kwargs["timeout"], 10)
        cursor.execute.assert_called_once()
        sql, params = cursor.execute.call_args.args
        self.assertIn("INSERT INTO consultas_tributos", sql)
        self.assertEqual(params[0:4], (VALID_CNPJ, "SP", "01012100", "Produto"))
        self.assertEqual(params[4], Decimal("3.25"))
        connection.commit.assert_called_once()
        connection.close.assert_called_once()

    def test_ncm_preserves_leading_zeroes_and_rejects_invalid_values(self):
        self.allow_ibpt()
        self.allow_database()
        response = self.post(valid_request(codigo="00123456"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["codigo"], "00123456")
        self.assertEqual(
            self.ibpt.call_args.kwargs["params"]["codigo"], "00123456"
        )

        for invalid_code in ("1234567", "123456789", "12A45678", 12345678):
            with self.subTest(codigo=invalid_code):
                result = self.post(valid_request(codigo=invalid_code))
                self.assertEqual(result.status_code, 422)
        self.assertEqual(self.ibpt.call_count, 1)

    def test_cnpj_requires_valid_check_digits_and_normalizes_format(self):
        self.allow_ibpt()
        self.allow_database()
        formatted = self.post(valid_request(cnpj="11.222.333/0001-81"))
        self.assertEqual(formatted.status_code, 200)
        self.assertEqual(
            self.ibpt.call_args.kwargs["params"]["cnpj"], VALID_CNPJ
        )

        self.ibpt.reset_mock()
        self.db.reset_mock()
        for invalid_cnpj in ("11222333000180", "00000000000000", "123"):
            with self.subTest(cnpj=invalid_cnpj):
                result = self.post(valid_request(cnpj=invalid_cnpj))
                self.assertEqual(result.status_code, 422)
        self.ibpt.assert_not_called()
        self.db.assert_not_called()

    def test_all_27_brazilian_states_are_accepted(self):
        ufs = (
            "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
            "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
            "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
        )
        self.assertEqual(len(ufs), 27)
        for uf in ufs:
            with self.subTest(uf=uf):
                self.allow_ibpt()
                self.allow_database()
                result = self.post(valid_request(uf=uf.lower()))
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["uf"], uf)
                self.assertEqual(
                    self.ibpt.call_args.kwargs["params"]["uf"], uf
                )
                self.ibpt.reset_mock()
                self.db.reset_mock()

    def test_invalid_uf_and_unsupported_services_are_rejected(self):
        invalid_payloads = (
            valid_request(uf="XX"),
            valid_request(tipo="serviço"),
            valid_request(type="2"),
            valid_request(tipo="unknown"),
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.post(payload)
                self.assertEqual(response.status_code, 422)
                self.ibpt.assert_not_called()
                self.db.assert_not_called()

        service_error = self.post(valid_request(tipo="serviço"))
        self.assertIn("serviços não são suportadas", service_error.json()["detail"][0]["msg"])

    def test_numeric_product_type_codes_and_service_code(self):
        for code in (0, 1):
            with self.subTest(tipo=code):
                self.allow_ibpt()
                self.allow_database()
                response = self.post(valid_request(tipo=code))
                self.assertEqual(response.status_code, 200)
                self.ibpt.reset_mock()
                self.db.reset_mock()

        response = self.post(valid_request(tipo=2))
        self.assertEqual(response.status_code, 422)
        self.assertIn("serviços não são suportadas", response.json()["detail"][0]["msg"])
        self.ibpt.assert_not_called()
        self.db.assert_not_called()

    def test_nonpositive_nonfinite_and_malformed_values_are_rejected(self):
        for value in ("0", "-1", "NaN", "Infinity", "not-a-number"):
            with self.subTest(valor=value):
                response = self.post(valid_request(valor=value))
                self.assertEqual(response.status_code, 422)
        self.ibpt.assert_not_called()
        self.db.assert_not_called()

    def test_optional_fields_default_and_are_forwarded(self):
        self.allow_ibpt()
        self.allow_database()
        payload = valid_request(NCM="00123456")
        payload.pop("codigo")
        response = self.post(payload)
        self.assertEqual(response.status_code, 200)
        params = self.ibpt.call_args.kwargs["params"]
        self.assertEqual(params["codigo"], "00123456")
        self.assertEqual(params["gtin"], "")
        self.assertEqual(params["ex"], 0)
        self.assertEqual(params["unidadeMedida"], "UN")

    def test_zero_is_a_valid_tax_rate_and_all_rates_are_returned(self):
        self.allow_ibpt(
            {
                "Nacional": 0,
                "Estadual": "0",
                "Municipal": "2.50",
                "Importado": "15",
                "Fonte": "Fonte de teste",
            }
        )
        self.allow_database()

        response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [response.json()[key] for key in main.TAX_FIELDS],
            ["0", "0", "2.50", "15"],
        )
        self.assertEqual(response.json()["Fonte"], "Fonte de teste")

    def test_missing_tax_rates_are_rejected_without_persisting(self):
        for body in ({}, {"Nacional": None}, {"Nacional": "", "Fonte": "IBPT"}):
            with self.subTest(body=body):
                self.allow_ibpt(body)
                response = self.post()
                self.assertEqual(response.status_code, 502)
                self.db.assert_not_called()
                self.ibpt.reset_mock()

    def test_malformed_ibpt_responses_are_rejected_without_persisting(self):
        malformed = (
            [],
            "invalid",
            {"Nacional": "not-a-rate"},
            {"Nacional": "NaN"},
            {"Nacional": -1},
        )
        for body in malformed:
            with self.subTest(body=body):
                self.allow_ibpt(body)
                response = self.post()
                self.assertEqual(response.status_code, 502)
                self.db.assert_not_called()
                self.ibpt.reset_mock()

        self.allow_ibpt()
        self.ibpt.return_value.json.side_effect = ValueError("invalid JSON")
        response = self.post()
        self.assertEqual(response.status_code, 502)
        self.db.assert_not_called()

    def test_ibpt_timeout_connection_and_http_errors_are_safe(self):
        cases = (
            (requests.Timeout("sensitive"), 504, "tempo limite"),
            (requests.ConnectionError("sensitive"), 502, "conectar"),
        )
        for error, status, message in cases:
            with self.subTest(error=type(error).__name__):
                self.ibpt.side_effect = error
                response = self.post()
                self.assertEqual(response.status_code, status)
                self.assertIn(message, response.json()["detail"])
                self.assertNotIn("sensitive", response.text)
                self.db.assert_not_called()
                self.ibpt.reset_mock()

        self.allow_ibpt(ok=False)
        response = self.post()
        self.assertEqual(response.status_code, 502)
        self.assertIn("recusou", response.json()["detail"])
        self.db.assert_not_called()

    def test_persistence_failure_returns_service_unavailable(self):
        self.allow_ibpt()
        self.db.side_effect = RuntimeError("sensitive database detail")

        response = self.post()

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("sensitive", response.text)

    def test_history_serializes_results_and_caps_limit(self):
        rows = [
            {
                "id": 7,
                "valor_unitario": Decimal("1.25"),
                "criado_em": datetime(2026, 1, 2, 3, 4),
            }
        ]
        connection, cursor = self.allow_database(rows=rows)

        response = self.client.get("/api/historico", params={"limit": 999})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["valor_unitario"], "1.25")
        self.assertEqual(
            response.json()[0]["criado_em"], "2026-01-02T03:04:00"
        )
        self.assertEqual(cursor.execute.call_args.args[1], (50,))
        self.assertIn("ORDER BY criado_em DESC, id DESC", cursor.execute.call_args.args[0])
        connection.close.assert_called_once()

    def test_history_rejects_bad_limit_and_handles_database_errors(self):
        invalid = self.client.get("/api/historico", params={"limit": 0})
        self.assertEqual(invalid.status_code, 422)
        self.db.assert_not_called()

        self.db.side_effect = main.pymysql.MySQLError("sensitive database detail")
        response = self.client.get("/api/historico")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("sensitive", response.text)
        self.ibpt.assert_not_called()

    def test_startup_calls_initializer_and_safe_schema_uses_mocked_database(self):
        with patch.object(main, "_initialize_database") as initialize:
            main.startup()
        initialize.assert_called_once_with()

        connection, cursor = self.allow_database()
        main._initialize_database()
        self.db.assert_called_once_with()
        self.assertGreaterEqual(cursor.execute.call_count, 1)
        for (statement,), _kwargs in cursor.execute.call_args_list:
            self.assertRegex(statement, r"(?i)^CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS")
        connection.commit.assert_called_once()
        connection.close.assert_called_once()

    def test_schema_rejects_unsafe_create_without_connecting(self):
        with patch("builtins.open", mock_open(read_data="CREATE TABLE users (id INT);")):
            with self.assertRaisesRegex(RuntimeError, "sem IF NOT EXISTS"):
                main._initialize_database()
        self.db.assert_not_called()


if __name__ == "__main__":
    unittest.main()
