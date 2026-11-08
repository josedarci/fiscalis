import os
import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from fastapi import HTTPException
import requests

from app import ConsultaImpostoRequest, consultar_imposto, historico
from services.config import ConfigurationError
from services.database import DatabaseError, consultar_historico, salvar_consulta
from services.ibpt import ErroServicoIBPT, consultar_ibpt


class ConsultaRequestTests(unittest.TestCase):
    def test_accepts_ncm_and_uses_optional_defaults(self):
        request = ConsultaImpostoRequest(
            ncm="01012100",
            uf="sp",
            descricao=" Produto ",
            valor="10.50",
        )
        self.assertEqual(request.codigo, "01012100")
        self.assertEqual(request.uf, "SP")
        self.assertEqual(request.descricao, "Produto")
        self.assertEqual(request.unidadeMedida, "UN")
        self.assertEqual(request.ex, 0)
        self.assertIsNone(request.gtin)

    def test_rejects_invalid_ncm_uf_and_nonpositive_value(self):
        common = {"uf": "SP", "descricao": "Produto", "valor": "1"}
        with self.assertRaises(ValueError):
            ConsultaImpostoRequest(codigo="123", **common)
        with self.assertRaises(ValueError):
            ConsultaImpostoRequest(codigo="01012100", **{**common, "uf": "XX"})
        with self.assertRaises(ValueError):
            ConsultaImpostoRequest(
                codigo="01012100", **{**common, "valor": "0"}
            )
        with self.assertRaises(ValueError):
            ConsultaImpostoRequest(
                codigo="01012100", **common, token="must-not-be-accepted"
            )


class IbptClientTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {"IBPT_TOKEN": "secret-token", "IBPT_CNPJ": "12345678000199"},
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.payload = ConsultaImpostoRequest(
            codigo="01012100",
            uf="SP",
            descricao="Produto",
            valor="9.99",
            gtin="7891234567890",
        )

    @patch("services.ibpt.requests.get")
    def test_maps_tax_fields_and_sends_credentials_only_from_environment(self, get):
        response = get.return_value
        response.status_code = 200
        response.json.return_value = {
            "Nacional": 12.5,
            "Estadual": "18.00",
            "Municipal": 0,
            "Importado": 15,
            "Fonte": "IBPT",
        }

        result = consultar_ibpt(self.payload)

        self.assertEqual(result["Nacional"], Decimal("12.5"))
        self.assertEqual(result["Estadual"], Decimal("18.00"))
        self.assertEqual(result["Fonte"], "IBPT")
        args, kwargs = get.call_args
        self.assertEqual(args[0], "https://apidoni.ibpt.org.br/api/v1/produtos")
        self.assertEqual(kwargs["timeout"], 10)
        self.assertEqual(kwargs["params"]["token"], "secret-token")
        self.assertEqual(kwargs["params"]["cnpj"], "12345678000199")

    @patch("services.ibpt.requests.get", side_effect=requests.Timeout)
    def test_timeout_has_safe_error_message(self, _get):
        with self.assertRaises(ErroServicoIBPT) as caught:
            consultar_ibpt(self.payload)
        self.assertEqual(caught.exception.status_code, 504)
        self.assertNotIn("secret-token", caught.exception.detail)

    @patch("services.ibpt.requests.get", side_effect=requests.ConnectionError)
    def test_connection_error_has_safe_message(self, _get):
        with self.assertRaises(ErroServicoIBPT) as caught:
            consultar_ibpt(self.payload)
        self.assertEqual(caught.exception.status_code, 502)
        self.assertNotIn("secret-token", caught.exception.detail)

    @patch("services.ibpt.requests.get")
    def test_http_and_json_errors_do_not_expose_response(self, get):
        get.return_value.status_code = 403
        get.return_value.text = "secret-token"
        with self.assertRaises(ErroServicoIBPT) as http_error:
            consultar_ibpt(self.payload)
        self.assertNotIn("secret-token", http_error.exception.detail)

        get.return_value.status_code = 200
        get.return_value.json.side_effect = ValueError("secret-token")
        with self.assertRaises(ErroServicoIBPT) as json_error:
            consultar_ibpt(self.payload)
        self.assertIn("JSON inválido", json_error.exception.detail)
        self.assertNotIn("secret-token", json_error.exception.detail)

    @patch("services.ibpt.requests.get")
    def test_missing_result_is_an_error(self, get):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {"Fonte": "IBPT"}
        with self.assertRaises(ErroServicoIBPT) as caught:
            consultar_ibpt(self.payload)
        self.assertIn("não retornou resultado", caught.exception.detail)

    @patch("services.ibpt.requests.get")
    def test_missing_ibpt_configuration_is_operational_error(self, get):
        with patch.dict(os.environ, {"IBPT_TOKEN": "", "IBPT_CNPJ": ""}):
            with self.assertRaises(ConfigurationError) as caught:
                consultar_ibpt(self.payload)
        self.assertIn("IBPT_TOKEN", str(caught.exception))
        get.assert_not_called()


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.payload = ConsultaImpostoRequest(
            codigo="01012100",
            uf="SP",
            descricao="Produto",
            valor="3.25",
        )

    @patch("app.validar_configuracao_banco")
    @patch("app.salvar_consulta", return_value=42)
    @patch(
        "app.consultar_ibpt",
        return_value={
            "Nacional": Decimal("12.3"),
            "Estadual": None,
            "Municipal": None,
            "Importado": None,
            "Fonte": "IBPT",
        },
    )
    def test_consulta_returns_persisted_result(self, _ibpt, _save, _config):
        response = consultar_imposto(self.payload)
        self.assertEqual(response["id"], 42)
        self.assertEqual(response["Nacional"], "12.3")

    @patch("app.validar_configuracao_banco")
    @patch("app.salvar_consulta", side_effect=DatabaseError())
    @patch("app.consultar_ibpt", return_value={})
    def test_database_failure_does_not_return_success(self, _ibpt, _save, _config):
        with self.assertRaises(HTTPException) as caught:
            consultar_imposto(self.payload)
        self.assertEqual(caught.exception.status_code, 503)

    @patch("app.validar_configuracao_banco", side_effect=ConfigurationError("MYSQL_USER"))
    @patch("app.consultar_ibpt")
    def test_missing_database_configuration_skips_external_call(self, external, _config):
        with self.assertRaises(HTTPException) as caught:
            consultar_imposto(self.payload)
        self.assertEqual(caught.exception.status_code, 503)
        external.assert_not_called()

    @patch(
        "app.consultar_historico",
        return_value=[
            {"valor": Decimal("1.25"), "criado_em": datetime(2026, 1, 2, 3, 4)}
        ],
    )
    def test_history_serializes_decimal_and_timestamp(self, _history):
        response = historico(10)
        self.assertEqual(response[0]["valor"], "1.25")
        self.assertEqual(response[0]["criado_em"], "2026-01-02T03:04:00")

    @patch("app.consultar_historico", side_effect=ConfigurationError("missing env"))
    def test_history_exposes_operational_configuration_error(self, _history):
        with self.assertRaises(HTTPException) as caught:
            historico(None)
        self.assertEqual(caught.exception.status_code, 503)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "MYSQL_HOST": "db.local",
                "MYSQL_PORT": "3306",
                "MYSQL_DATABASE": "fiscalis",
                "MYSQL_USER": "app",
                "MYSQL_PASSWORD": "private",
                "IBPT_CNPJ": "12345678000199",
                "HISTORY_MAX_LIMIT": "2",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.payload = ConsultaImpostoRequest(
            codigo="01012100",
            uf="SP",
            descricao="Produto",
            valor="3.25",
        )
        self.result = {
            "Nacional": Decimal("12.3"),
            "Estadual": None,
            "Municipal": None,
            "Importado": None,
            "Fonte": "IBPT",
        }

    @patch("services.database.pymysql.connect")
    def test_insert_commits_and_closes_with_bound_parameters(self, connect):
        connection = connect.return_value
        connection.cursor.return_value.__enter__.return_value.lastrowid = 17

        record_id = salvar_consulta(self.payload, self.result)

        self.assertEqual(record_id, 17)
        connection.cursor.return_value.__enter__.return_value.execute.assert_called_once()
        sql, params = (
            connection.cursor.return_value.__enter__.return_value.execute.call_args.args
        )
        self.assertIn("%(codigo)s", sql)
        self.assertEqual(params["codigo"], "01012100")
        self.assertIn("%(cnpj_empresa)s", sql)
        self.assertEqual(params["cnpj_empresa"], "12345678000199")
        connection.commit.assert_called_once()
        connection.close.assert_called_once()

    @patch("services.database.pymysql.connect")
    def test_insert_failure_rolls_back_and_closes(self, connect):
        connection = connect.return_value
        connection.cursor.return_value.__enter__.return_value.execute.side_effect = (
            RuntimeError("db details")
        )

        with self.assertRaises(DatabaseError):
            salvar_consulta(self.payload, self.result)

        connection.rollback.assert_called_once()
        connection.close.assert_called_once()

    @patch("services.database.pymysql.connect")
    def test_history_clamps_limit_to_configured_maximum(self, connect):
        connection = connect.return_value
        consultar_historico(999)

        cursor = connection.cursor.return_value.__enter__.return_value
        self.assertEqual(cursor.execute.call_args.args[1], (2,))
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
