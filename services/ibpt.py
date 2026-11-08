"""Cliente da API de tributação IBPT."""

from decimal import Decimal, InvalidOperation
from typing import Any

import requests

from services.config import ConfigurationError, required_env

IBPT_URL = "https://apidoni.ibpt.org.br/api/v1/produtos"
IBPT_TIMEOUT_SECONDS = 10
_TAX_FIELDS = ("Nacional", "Estadual", "Municipal", "Importado")


class ErroServicoIBPT(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _decimal_field(result: dict[str, Any], name: str) -> Decimal | None:
    value = next(
        (value for key, value in result.items() if key.casefold() == name.casefold()),
        None,
    )
    if value is None:
        return None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ErroServicoIBPT(502, "A API IBPT retornou alíquotas inválidas.") from None
    if not decimal_value.is_finite():
        raise ErroServicoIBPT(502, "A API IBPT retornou alíquotas inválidas.")
    return decimal_value


def _result_value(result: dict[str, Any], name: str) -> Any:
    return next(
        (value for key, value in result.items() if key.casefold() == name.casefold()),
        None,
    )


def consultar_ibpt(payload: Any) -> dict[str, Any]:
    env = required_env("IBPT_TOKEN", "IBPT_CNPJ")
    raw_cnpj = env["IBPT_CNPJ"].strip()
    cnpj = "".join(char for char in raw_cnpj if char.isdigit())
    if len(cnpj) != 14 or any(
        not char.isdigit() and char not in "./- " for char in raw_cnpj
    ):
        raise ConfigurationError("A variável IBPT_CNPJ deve conter um CNPJ válido.")

    params: dict[str, Any] = {
        "token": env["IBPT_TOKEN"].strip(),
        "cnpj": cnpj,
        "codigo": payload.codigo,
        "uf": payload.uf,
        "ex": payload.ex,
        "descricao": payload.descricao,
        "unidadeMedida": payload.unidadeMedida,
        "valor": str(payload.valor),
    }
    if payload.gtin:
        params["gtin"] = payload.gtin

    try:
        response = requests.get(
            IBPT_URL,
            params=params,
            timeout=IBPT_TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        raise ErroServicoIBPT(504, "Tempo esgotado ao consultar a API IBPT.") from None
    except requests.ConnectionError:
        raise ErroServicoIBPT(502, "Não foi possível conectar à API IBPT.") from None
    except requests.RequestException:
        raise ErroServicoIBPT(502, "Falha ao consultar a API IBPT.") from None

    if not 200 <= response.status_code < 300:
        raise ErroServicoIBPT(
            502, "A API IBPT retornou uma resposta HTTP inválida."
        )
    try:
        body = response.json()
    except ValueError:
        raise ErroServicoIBPT(502, "A API IBPT retornou JSON inválido.") from None

    if not isinstance(body, dict) or not any(
        key.casefold() in {field.casefold() for field in _TAX_FIELDS}
        and value is not None
        for key, value in body.items()
    ):
        raise ErroServicoIBPT(502, "A API IBPT não retornou resultado para a consulta.")

    mapped = {field: _decimal_field(body, field) for field in _TAX_FIELDS}
    mapped["Fonte"] = _result_value(body, "Fonte")
    return mapped
