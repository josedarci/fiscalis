import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal
from typing import Any

import pymysql
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator
from pymysql.cursors import DictCursor

from services.calculation import (
    CALCULATION_ALGORITHM_VERSION,
    ROUNDING_POLICY,
    calculate_estimate,
)

load_dotenv()

IBPT_URL = "https://apidoni.ibpt.org.br/api/v1/produtos"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TAX_FIELDS = ("Nacional", "Estadual", "Municipal", "Importado")
BRAZILIAN_UFS = frozenset(
    {
        "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
        "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
        "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
    }
)


def _cnpj_check_digit(number: str, weights: tuple[int, ...]) -> str:
    remainder = sum(int(digit) * weight for digit, weight in zip(number, weights)) % 11
    return "0" if remainder < 2 else str(11 - remainder)


def _is_valid_cnpj(cnpj: str) -> bool:
    if len(set(cnpj)) == 1:
        return False
    first_digit = _cnpj_check_digit(cnpj[:12], (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    second_digit = _cnpj_check_digit(
        cnpj[:12] + first_digit,
        (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2),
    )
    return cnpj[-2:] == first_digit + second_digit


def _validate_item_context(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    payload = dict(payload)
    aliases = [payload.pop(name) for name in ("NCM", "ncm") if name in payload]
    aliases = [value for value in aliases if value is not None]
    if aliases and any(str(value).strip() != str(aliases[0]).strip() for value in aliases[1:]):
        raise ValueError("Os valores de NCM devem ser iguais.")
    if aliases:
        codigo = payload.get("codigo")
        if (
            codigo is not None
            and str(codigo).strip()
            and str(codigo).strip() != str(aliases[0]).strip()
        ):
            raise ValueError("Os valores de código e NCM devem ser iguais.")
        if not codigo or not str(codigo).strip():
            payload["codigo"] = aliases[0]
    for field in ("tipo", "type"):
        value = payload.get(field)
        if value is None:
            continue
        if isinstance(value, bool):
            raise ValueError("Tipo de item inválido; informe produto ou deixe o campo vazio.")
        if isinstance(value, int):
            if value == 2:
                raise ValueError(
                    "Consultas de serviços não são suportadas pela API de produtos do IBPT."
                )
            if value in {0, 1}:
                payload[field] = str(value)
                continue
            raise ValueError("Tipo de item inválido; informe produto ou deixe o campo vazio.")
        if not isinstance(value, str):
            raise ValueError("Tipo de item inválido; informe produto ou deixe o campo vazio.")
        if value == "2":
            raise ValueError(
                "Consultas de serviços não são suportadas pela API de produtos do IBPT."
            )
        normalized = "".join(
            character
            for character in unicodedata.normalize("NFKD", value.strip().casefold())
            if not unicodedata.combining(character)
        )
        if normalized in {"servico", "servicos", "service", "services", "2"}:
            raise ValueError(
                "Consultas de serviços não são suportadas pela API de produtos do IBPT."
            )
        if normalized not in {"produto", "produtos", "product", "products", "0", "1"}:
            raise ValueError("Tipo de item inválido; informe produto ou deixe o campo vazio.")
    return payload

app = FastAPI(title="Fiscalis - Consulta de Impostos", version="1.0.0")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


class ConsultaRequest(BaseModel):
    token: str = Field(
        default_factory=lambda: os.getenv("IBPT_TOKEN", ""),
        min_length=1,
        max_length=500,
        validate_default=True,
    )
    cnpj: str = Field(
        default_factory=lambda: os.getenv("IBPT_CNPJ", ""),
        min_length=14,
        max_length=14,
        validate_default=True,
    )
    codigo: str | None = Field(default=None, max_length=20)
    NCM: str | None = Field(default=None, max_length=20)
    uf: str = Field(min_length=2, max_length=2)
    descricao: str = Field(min_length=1, max_length=255)
    unidadeMedida: str = Field(default="UN", min_length=1, max_length=20)
    valor: Decimal
    gtin: str | None = Field(default=None, max_length=20)
    ex: int = Field(default=0, ge=0)
    tipo: str | None = Field(default=None, max_length=50)
    type: str | None = Field(default=None, max_length=50)

    @model_validator(mode="before")
    @classmethod
    def reject_unsupported_item_context(cls, payload: Any) -> Any:
        return _validate_item_context(payload)

    @field_validator("token", mode="before")
    @classmethod
    def normalize_token(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Informe um token IBPT válido.")
        return value.strip()

    @field_validator("cnpj", mode="before")
    @classmethod
    def normalize_and_validate_cnpj(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("Informe um CNPJ válido.")
        raw_cnpj = value.strip()
        if not (
            re.fullmatch(r"[0-9]{14}", raw_cnpj)
            or re.fullmatch(r"[0-9]{2}\.[0-9]{3}\.[0-9]{3}/[0-9]{4}-[0-9]{2}", raw_cnpj)
        ):
            raise ValueError("Informe um CNPJ válido com 14 dígitos.")
        cnpj = re.sub(r"\D", "", raw_cnpj)
        if not _is_valid_cnpj(cnpj):
            raise ValueError("O CNPJ informado possui dígitos verificadores inválidos.")
        return cnpj

    @field_validator("codigo", "NCM", mode="before")
    @classmethod
    def normalize_ncm(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("O NCM deve conter exatamente 8 dígitos.")
        ncm = value.strip()
        if not ncm:
            return None
        if not re.fullmatch(r"[0-9]{8}", ncm):
            raise ValueError("O NCM deve conter exatamente 8 dígitos.")
        return ncm

    @field_validator("uf", mode="before")
    @classmethod
    def normalize_uf(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("Informe uma UF brasileira válida.")
        uf = value.strip().upper()
        if uf not in BRAZILIAN_UFS:
            raise ValueError("Informe uma UF brasileira válida.")
        return uf

    @field_validator("valor", mode="before")
    @classmethod
    def validate_positive_finite_value(cls, value: Any) -> Decimal:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("O valor deve ser um número decimal positivo e finito.") from None
        if not amount.is_finite() or amount <= 0:
            raise ValueError("O valor deve ser um número decimal positivo e finito.")
        return amount

    @model_validator(mode="after")
    def validate_product_code(self) -> "ConsultaRequest":
        if not self.codigo and not self.NCM:
            raise ValueError("Informe o código NCM com exatamente 8 dígitos.")
        if self.codigo and self.NCM and self.codigo != self.NCM:
            raise ValueError("Os valores de código e NCM devem ser iguais.")
        return self


class CompararRequest(BaseModel):
    token: str = Field(
        default_factory=lambda: os.getenv("IBPT_TOKEN", ""),
        min_length=1,
        max_length=500,
        validate_default=True,
    )
    cnpj: str = Field(
        default_factory=lambda: os.getenv("IBPT_CNPJ", ""),
        min_length=14,
        max_length=14,
        validate_default=True,
    )
    codigo: str | None = Field(default=None, max_length=20)
    NCM: str | None = Field(default=None, max_length=20)
    descricao: str = Field(min_length=1, max_length=255)
    valor: Decimal
    ufs: list[str] = Field(min_length=2, max_length=27)
    cenario: Literal["nacional", "importado"]
    unidadeMedida: str = Field(default="UN", min_length=1, max_length=20)
    gtin: str = Field(max_length=20)
    ex: int = Field(default=0, ge=0, le=999999)
    tipo: str | None = Field(default=None, max_length=50)
    type: str | None = Field(default=None, max_length=50)

    @model_validator(mode="before")
    @classmethod
    def reject_unsupported_item_context(cls, payload: Any) -> Any:
        return _validate_item_context(payload)

    @field_validator("token", mode="before")
    @classmethod
    def normalize_token(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Informe um token IBPT válido.")
        return value.strip()

    @field_validator("cnpj", mode="before")
    @classmethod
    def normalize_and_validate_cnpj(cls, value: Any) -> str:
        return ConsultaRequest.normalize_and_validate_cnpj(value)

    @field_validator("codigo", "NCM", mode="before")
    @classmethod
    def normalize_ncm(cls, value: Any) -> str | None:
        return ConsultaRequest.normalize_ncm(value)

    @field_validator("valor", mode="before")
    @classmethod
    def validate_positive_finite_value(cls, value: Any) -> Decimal:
        return ConsultaRequest.validate_positive_finite_value(value)

    @field_validator("gtin", mode="before")
    @classmethod
    def require_gtin(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Informe um GTIN não vazio.")
        return value

    @field_validator("ufs", mode="before")
    @classmethod
    def normalize_ufs(cls, value: Any) -> Any:
        if not isinstance(value, list):
            raise ValueError("Informe uma lista de UFs brasileiras.")
        normalized = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("Informe UFs brasileiras válidas.")
            uf = item.strip().upper()
            if uf not in BRAZILIAN_UFS:
                raise ValueError("Informe UFs brasileiras válidas.")
            normalized.append(uf)
        if len(set(normalized)) != len(normalized):
            raise ValueError("Não informe UFs duplicadas.")
        if not 2 <= len(normalized) <= 27:
            raise ValueError("Informe entre 2 e 27 UFs.")
        return normalized

    @model_validator(mode="after")
    def validate_comparison(self) -> "CompararRequest":
        if not self.codigo and not self.NCM:
            raise ValueError("Informe o código NCM com exatamente 8 dígitos.")
        if self.codigo and self.NCM and self.codigo != self.NCM:
            raise ValueError("Os valores de código e NCM devem ser iguais.")
        if not self.descricao.strip():
            raise ValueError("Informe uma descrição válida.")
        if not self.unidadeMedida.strip():
            raise ValueError("Informe uma unidade de medida válida.")
        return self


def _db_connection():
    legacy_names = {
        "DB_HOST": "MYSQL_HOST",
        "DB_NAME": "MYSQL_DATABASE",
        "DB_USER": "MYSQL_USER",
        "DB_PASSWORD": "MYSQL_PASSWORD",
    }
    config = {
        key: os.getenv(key) or os.getenv(legacy_name)
        for key, legacy_name in legacy_names.items()
    }
    missing = [key for key, value in config.items() if not value]
    if missing:
        raise RuntimeError(f"Variáveis de banco ausentes: {', '.join(missing)}")
    try:
        port = int(os.getenv("DB_PORT") or os.getenv("MYSQL_PORT", "3306"))
    except ValueError:
        raise RuntimeError("DB_PORT deve ser uma porta numérica.") from None
    return pymysql.connect(
        host=config["DB_HOST"],
        port=port,
        user=config["DB_USER"],
        password=config["DB_PASSWORD"],
        database=config["DB_NAME"],
        charset="utf8mb4",
        cursorclass=DictCursor,
        connect_timeout=5,
        autocommit=False,
    )


def _initialize_database() -> None:
    schema_path = os.path.join(BASE_DIR, "schema.sql")
    try:
        with open(schema_path, encoding="utf-8") as schema_file:
            schema = schema_file.read()
    except OSError as error:
        raise RuntimeError(f"Não foi possível ler o arquivo de schema: {schema_path}") from error

    create_statements = []
    for statement in schema.split(";"):
        statement = statement.strip()
        if not statement:
            continue
        statement = re.sub(
            r"/\*.*?\*/|--[^\r\n]*|#[^\r\n]*",
            "",
            statement,
            flags=re.DOTALL,
        ).strip()
        if not statement:
            continue
        if re.match(r"CREATE\s+TABLE\b", statement, flags=re.IGNORECASE):
            if not re.match(
                r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\b",
                statement,
                flags=re.IGNORECASE,
            ):
                raise RuntimeError(
                    "schema.sql contém uma instrução CREATE TABLE sem IF NOT EXISTS."
                )
            create_statements.append(statement)

    if not create_statements or not any(
        re.match(
            r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+`?consultas_tributos`?\b",
            statement,
            flags=re.IGNORECASE,
        )
        for statement in create_statements
    ):
        raise RuntimeError(
            "schema.sql está ausente ou malformado: nenhuma definição "
            "CREATE TABLE IF NOT EXISTS para consultas_tributos foi encontrada."
        )

    last_error = None
    for attempt in range(30):
        try:
            connection = _db_connection()
        except (pymysql.MySQLError, RuntimeError) as error:
            last_error = error
            if attempt < 29:
                time.sleep(2)
            continue
        try:
            with closing(connection) as connection:
                with connection.cursor() as cursor:
                    for statement in create_statements:
                        cursor.execute(statement)
                connection.commit()
            return
        except pymysql.MySQLError as error:
            raise RuntimeError(
                "Não foi possível executar as definições CREATE TABLE de schema.sql."
            ) from error
    raise RuntimeError("Não foi possível inicializar o banco MySQL.") from last_error


@app.on_event("startup")
def startup() -> None:
    _initialize_database()


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(os.path.join(BASE_DIR, "index.html"))


@app.get("/tabela", include_in_schema=False)
def tabela_ibpt() -> FileResponse:
    return FileResponse(os.path.join(BASE_DIR, "tabela.html"))


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


def _get_codigo(data: ConsultaRequest) -> str:
    codigo = (data.codigo or data.NCM or "").strip()
    if not codigo:
        raise HTTPException(status_code=422, detail="Informe o código NCM.")
    if data.codigo and data.NCM and data.codigo.strip() != data.NCM.strip():
        raise HTTPException(status_code=422, detail="Os valores de código e NCM devem ser iguais.")
    return codigo


def _tax_result(raw: Any) -> dict[str, Any]:
    if isinstance(raw, list):
        if not raw or any(not isinstance(item, dict) for item in raw):
            raise HTTPException(status_code=502, detail="A API do IBPT não retornou uma consulta válida.")
        raw = raw[0]
    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail="A API do IBPT não retornou uma consulta válida.")
    result = {}
    has_rate = False
    for key in TAX_FIELDS:
        value = raw.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            result[key] = None
            continue
        has_rate = True
        try:
            rate = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise HTTPException(status_code=502, detail="A API do IBPT retornou uma alíquota inválida.") from None
        if not rate.is_finite() or rate < 0:
            raise HTTPException(status_code=502, detail="A API do IBPT retornou uma alíquota inválida.")
        result[key] = rate
    if not has_rate:
        raise HTTPException(status_code=502, detail="A API do IBPT não retornou alíquotas utilizáveis.")
    result["Fonte"] = str(raw.get("Fonte") or "")
    return result


def _comparison_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    def text_value(key: str) -> str | None:
        value = raw.get(key)
        if value is None or isinstance(value, (dict, list, bool)):
            return None
        text = str(value).strip()
        return text or None

    def date_value(key: str) -> date | None:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None

    start = date_value("VigenciaInicio")
    end = date_value("VigenciaFim")
    return {
        "Fonte": text_value("Fonte"),
        "Versao": text_value("Versao"),
        "VigenciaInicio": start,
        "VigenciaFim": end,
        "Codigo": text_value("Codigo"),
        "UF": text_value("UF"),
    }


def _parse_comparison_tax(raw: Any) -> tuple[dict[str, Decimal | None], dict[str, Any]]:
    if isinstance(raw, list):
        if not raw or any(not isinstance(item, dict) for item in raw):
            raise ValueError("resposta inválida")
        raw = raw[0]
    if not isinstance(raw, dict):
        raise ValueError("resposta inválida")

    rates: dict[str, Decimal | None] = {}
    found_rate = False
    for key in TAX_FIELDS:
        value = raw.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            rates[key] = None
            continue
        found_rate = True
        try:
            rate = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("alíquota inválida") from None
        if not rate.is_finite() or rate < 0:
            raise ValueError("alíquota inválida")
        rates[key] = rate
    if not found_rate:
        raise ValueError("alíquotas ausentes")
    return rates, _comparison_metadata(raw)


def _request_comparison_uf(
    uf: str,
    codigo: str,
    base_params: dict[str, Any],
    scenario: str,
    base: Decimal,
) -> dict[str, Any]:
    params = {**base_params, "uf": uf}
    try:
        response = requests.get(IBPT_URL, params=params, timeout=10)
    except requests.Timeout:
        return {"uf": uf, "status": "ERROR", "erro": "A consulta excedeu o tempo limite."}
    except requests.RequestException:
        return {"uf": uf, "status": "ERROR", "erro": "Não foi possível conectar à API do IBPT."}

    if not response.ok:
        return {"uf": uf, "status": "ERROR", "erro": "A API do IBPT recusou ou não processou a consulta."}
    try:
        rates, metadata = _parse_comparison_tax(response.json())
    except ValueError:
        return {"uf": uf, "status": "ERROR", "erro": "A API do IBPT retornou dados inválidos."}

    response_code = metadata.pop("Codigo")
    response_uf = metadata.pop("UF")
    if response_code is not None and response_code != codigo:
        return {
            "uf": uf,
            "status": "ERROR",
            "erro": "A API do IBPT retornou um código de produto diferente.",
        }
    if response_uf is not None and response_uf.upper() != uf:
        return {
            "uf": uf,
            "status": "ERROR",
            "erro": "A API do IBPT retornou uma UF diferente.",
        }
    identity_confirmed = response_code is not None and response_uf is not None

    try:
        estimate = calculate_estimate(base, rates, scenario)
    except (TypeError, ValueError):
        return {"uf": uf, "status": "ERROR", "erro": "Não foi possível calcular os tributos."}
    return {
        "uf": uf,
        "status": "SUCCESS",
        "rates": rates,
        "estimate": estimate,
        "identity_confirmed": identity_confirmed,
        **metadata,
    }


def _comparison_status(results: list[dict[str, Any]]) -> str:
    successful = [item for item in results if item["status"] == "SUCCESS"]
    for key in ("VigenciaInicio", "VigenciaFim", "Versao", "Fonte"):
        known_values = {item.get(key) for item in successful if item.get(key) is not None}
        if len(known_values) > 1:
            return "INCOMPATIBLE"

    if len(successful) != len(results):
        return "UNVERIFIED"
    if not successful or any(
        not item.get("identity_confirmed")
        or any(item.get(key) is None for key in ("Fonte", "Versao", "VigenciaInicio", "VigenciaFim"))
        or any(
            item["estimate"].get(field) is None
            for field in ("Federal", "Estadual", "Municipal", "total", "percentual_total")
        )
        for item in successful
    ):
        return "UNVERIFIED"
    return "COMPARABLE"


def _money_or_rate(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


@app.get("/comparar", include_in_schema=False)
def pagina_comparar() -> FileResponse:
    return FileResponse(os.path.join(BASE_DIR, "comparar.html"))


@app.post("/api/consultar-imposto")
def consultar_imposto(data: ConsultaRequest) -> dict[str, Any]:
    codigo = _get_codigo(data)
    uf = data.uf.strip().upper()
    if not uf.isalpha():
        raise HTTPException(status_code=422, detail="Informe uma UF válida.")
    params = {
        "token": data.token,
        "cnpj": data.cnpj,
        "codigo": codigo,
        "uf": uf,
        "descricao": data.descricao.strip(),
        "unidadeMedida": data.unidadeMedida,
        "valor": str(data.valor),
        "gtin": data.gtin or "",
        "ex": data.ex,
    }

    try:
        response = requests.get(IBPT_URL, params=params, timeout=10)
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="A consulta ao IBPT excedeu o tempo limite.") from None
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="Não foi possível conectar à API do IBPT.") from None

    if not response.ok:
        raise HTTPException(status_code=502, detail="A API do IBPT recusou ou não conseguiu processar a consulta.")
    try:
        result = _tax_result(response.json())
    except ValueError:
        raise HTTPException(status_code=502, detail="A API do IBPT retornou uma resposta inválida.") from None

    insert_sql = """
        INSERT INTO consultas_tributos (
            cnpj_empresa, uf, codigo_ncm, descricao_produto, valor_unitario,
            aliquota_nacional, aliquota_estadual, aliquota_municipal,
            aliquota_importado, fonte_informacao
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    try:
        with closing(_db_connection()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    insert_sql,
                    (
                        data.cnpj,
                        uf,
                        codigo,
                        data.descricao.strip(),
                        data.valor,
                        result["Nacional"],
                        result["Estadual"],
                        result["Municipal"],
                        result["Importado"],
                        result["Fonte"],
                    ),
                )
                record_id = cursor.lastrowid
            connection.commit()
    except (pymysql.MySQLError, RuntimeError):
        raise HTTPException(status_code=503, detail="Não foi possível salvar a consulta no banco de dados.") from None

    return {
        "id": record_id,
        "codigo": codigo,
        "uf": uf,
        **{key: str(value) if value is not None else None for key, value in result.items()},
    }


@app.post("/api/comparar-tributos")
def comparar_tributos(data: CompararRequest) -> dict[str, Any]:
    codigo = (data.codigo or data.NCM or "").strip()
    if not codigo:
        raise HTTPException(status_code=422, detail="Informe o código NCM.")

    base_params = {
        "token": data.token,
        "cnpj": data.cnpj,
        "codigo": codigo,
        "descricao": data.descricao.strip(),
        "unidadeMedida": data.unidadeMedida,
        "valor": str(data.valor),
        "gtin": data.gtin,
        "ex": data.ex,
    }
    fetched_by_uf: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(
                _request_comparison_uf,
                uf,
                codigo,
                base_params,
                data.cenario,
                data.valor,
            ): uf
            for uf in data.ufs
        }
        for future in as_completed(futures):
            uf = futures[future]
            fetched_by_uf[uf] = future.result()

    fetched = [fetched_by_uf[uf] for uf in data.ufs]
    comparabilidade = _comparison_status(fetched)
    results = []
    comparable_values = []
    for item in fetched:
        rates = item.get("rates", {})
        estimate = item.get("estimate", {})
        federal_key = "Nacional" if data.cenario == "nacional" else "Importado"
        is_error = item["status"] == "ERROR"
        if not is_error and estimate.get("total") is not None:
            comparable_values.append((estimate["total"], item["uf"]))
        results.append(
            {
                "id": None,
                "uf": item["uf"],
                "status": item["status"],
                "comparabilidade": "ERROR" if is_error else comparabilidade,
                "Federal": _money_or_rate(rates.get(federal_key)),
                "Estadual": _money_or_rate(rates.get("Estadual")),
                "Municipal": _money_or_rate(rates.get("Municipal")),
                "Importado": _money_or_rate(rates.get("Importado")),
                "valor_federal": _money_or_rate(estimate.get("Federal")),
                "valor_estadual": _money_or_rate(estimate.get("Estadual")),
                "valor_municipal": _money_or_rate(estimate.get("Municipal")),
                "total_estimado": _money_or_rate(estimate.get("total")),
                "percentual_total": _money_or_rate(estimate.get("percentual_total")),
                "Fonte": item.get("Fonte"),
                "Versao": item.get("Versao"),
                "VigenciaInicio": (
                    item["VigenciaInicio"].isoformat()
                    if item.get("VigenciaInicio") is not None
                    else None
                ),
                "VigenciaFim": (
                    item["VigenciaFim"].isoformat()
                    if item.get("VigenciaFim") is not None
                    else None
                ),
                "erro": item.get("erro"),
            }
        )

    resumo: dict[str, str | None] = {"menor_uf": None, "maior_uf": None}
    if comparabilidade == "COMPARABLE" and comparable_values:
        ordered = sorted(comparable_values, key=lambda value: (value[0], value[1]))
        resumo = {"menor_uf": ordered[0][1], "maior_uf": ordered[-1][1]}
    return {
        "comparison_id": None,
        "history_status": "BLOCKED_LICENSE",
        "cenario": data.cenario,
        "comparabilidade": comparabilidade,
        "resumo": resumo,
        "resultados": results,
    }


@app.get("/api/historico")
def historico(
    limit: int | None = None,
    ncm: str | None = None,
    uf: str | None = None,
    cenario: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    if limit is not None and limit < 1:
        raise HTTPException(status_code=422, detail="O limite deve ser maior que zero.")
    if ncm is not None and not re.fullmatch(r"[0-9]{8}", ncm.strip()):
        raise HTTPException(status_code=422, detail="O NCM deve conter exatamente 8 dígitos.")
    if uf is not None and uf.strip().upper() not in BRAZILIAN_UFS:
        raise HTTPException(status_code=422, detail="Informe uma UF brasileira válida.")
    if cenario is not None and cenario not in {"nacional", "importado"}:
        raise HTTPException(status_code=422, detail="Informe um cenário válido.")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(status_code=422, detail="O início do período deve ser anterior ao fim.")

    limit = min(limit or 50, 50)
    conditions = []
    parameters: list[Any] = []
    if ncm is not None:
        conditions.append("codigo_ncm = %s")
        parameters.append(ncm.strip())
    if uf is not None:
        conditions.append("uf = %s")
        parameters.append(uf.strip().upper())
    if cenario is not None:
        conditions.append("cenario = %s")
        parameters.append(cenario)
    if start_date is not None:
        conditions.append("criado_em >= %s")
        parameters.append(start_date)
    if end_date is not None:
        conditions.append("criado_em < %s")
        parameters.append(end_date + timedelta(days=1))
    conditions.append("comparison_id IS NULL")
    where_clause = f"WHERE {' AND '.join(conditions)}"
    parameters.append(limit)
    try:
        with closing(_db_connection()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, cnpj_empresa, uf, codigo_ncm, descricao_produto,
                           valor_unitario, aliquota_nacional, aliquota_estadual,
                           aliquota_municipal, aliquota_importado, fonte_informacao,
                           criado_em, comparison_id AS audit_group_id,
                           unidade_medida AS audit_unit, gtin AS audit_gtin,
                           ex AS audit_ex_code, cenario AS audit_scenario,
                           provedor AS audit_provider, versao_fonte AS audit_source_version,
                           vigencia_inicio AS audit_vigency_start,
                           vigencia_fim AS audit_vigency_end,
                           obtido_em_utc AS audit_acquired_at_utc,
                           percentual_total AS audit_percent_total,
                           CASE WHEN cenario = 'nacional' THEN valor_federal END
                               AS audit_estimated_national,
                           valor_estadual AS audit_estimated_state,
                           valor_municipal AS audit_estimated_municipal,
                           CASE WHEN cenario = 'importado' THEN valor_federal END
                               AS audit_estimated_imported,
                           total_estimado AS audit_estimated_total,
                           algoritmo_versao AS audit_calc_algorithm,
                           politica_arredondamento AS audit_rounding_policy,
                           status_consulta AS audit_status, erro_consulta AS audit_error
                    FROM consultas_tributos
                    {where_clause}
                    ORDER BY criado_em DESC, id DESC
                    LIMIT %s
                    """
                    ,
                    tuple(parameters),
                )
                rows = cursor.fetchall()
    except (pymysql.MySQLError, RuntimeError):
        raise HTTPException(status_code=503, detail="Não foi possível carregar o histórico.") from None
    return rows


@app.get("/api/historico/{record_id}")
def historico_detalhe(record_id: int) -> dict[str, Any]:
    if record_id < 1:
        raise HTTPException(status_code=422, detail="O identificador deve ser positivo.")
    try:
        with closing(_db_connection()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT comparison_id FROM consultas_tributos WHERE id = %s",
                    (record_id,),
                )
                access = cursor.fetchone()
                if access is None:
                    raise HTTPException(status_code=404, detail="Registro não encontrado.")
                if access.get("comparison_id") is not None:
                    raise HTTPException(
                        status_code=451,
                        detail="Leitura de registros de comparação está bloqueada por restrição de licença.",
                    )
                cursor.execute(
                    """
                    SELECT id, cnpj_empresa, uf, codigo_ncm, descricao_produto,
                           valor_unitario, aliquota_nacional, aliquota_estadual,
                           aliquota_municipal, aliquota_importado, fonte_informacao,
                           criado_em, comparison_id AS audit_group_id,
                           unidade_medida AS audit_unit, gtin AS audit_gtin,
                           ex AS audit_ex_code, cenario AS audit_scenario,
                           provedor AS audit_provider, versao_fonte AS audit_source_version,
                           vigencia_inicio AS audit_vigency_start,
                           vigencia_fim AS audit_vigency_end,
                           obtido_em_utc AS audit_acquired_at_utc,
                           percentual_total AS audit_percent_total,
                           CASE WHEN cenario = 'nacional' THEN valor_federal END
                               AS audit_estimated_national,
                           valor_estadual AS audit_estimated_state,
                           valor_municipal AS audit_estimated_municipal,
                           CASE WHEN cenario = 'importado' THEN valor_federal END
                               AS audit_estimated_imported,
                           total_estimado AS audit_estimated_total,
                           algoritmo_versao AS audit_calc_algorithm,
                           politica_arredondamento AS audit_rounding_policy,
                           status_consulta AS audit_status, erro_consulta AS audit_error
                    FROM consultas_tributos
                    WHERE id = %s
                    """,
                    (record_id,),
                )
                row = cursor.fetchone()
    except HTTPException:
        raise
    except (pymysql.MySQLError, RuntimeError):
        raise HTTPException(status_code=503, detail="Não foi possível carregar o registro.") from None
    if row is None:
        raise HTTPException(status_code=404, detail="Registro não encontrado.")
    return row


@app.post("/api/historico/{record_id}/reproduzir")
def reproduzir_historico(record_id: int) -> dict[str, Any]:
    if record_id < 1:
        raise HTTPException(status_code=422, detail="O identificador deve ser positivo.")
    try:
        with closing(_db_connection()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT comparison_id FROM consultas_tributos WHERE id = %s",
                    (record_id,),
                )
                access = cursor.fetchone()
                if access is None:
                    raise HTTPException(status_code=404, detail="Registro não encontrado.")
                if access.get("comparison_id") is not None:
                    return {
                        "id": record_id,
                        "status": "UNAVAILABLE",
                        "erro": "A reprodução de registros de comparação está bloqueada por restrição de licença.",
                    }
                cursor.execute(
                    """
                    SELECT id, valor_unitario, aliquota_nacional, aliquota_estadual,
                           aliquota_municipal, aliquota_importado,
                           cenario AS audit_scenario
                    FROM consultas_tributos
                    WHERE id = %s
                    """,
                    (record_id,),
                )
                row = cursor.fetchone()
    except HTTPException:
        raise
    except (pymysql.MySQLError, RuntimeError):
        raise HTTPException(status_code=503, detail="Não foi possível carregar o registro.") from None
    if row is None:
        raise HTTPException(status_code=404, detail="Registro não encontrado.")

    scenario = row.get("audit_scenario")
    if scenario not in {"nacional", "importado"}:
        return {
            "id": record_id,
            "status": "UNAVAILABLE",
            "erro": "O cenário ou as alíquotas necessárias não estão disponíveis no registro.",
        }
    federal_rate = row.get(
        "aliquota_nacional" if scenario == "nacional" else "aliquota_importado"
    )
    rates = {
        "Nacional": row.get("aliquota_nacional"),
        "Importado": row.get("aliquota_importado"),
        "Estadual": row.get("aliquota_estadual"),
        "Municipal": row.get("aliquota_municipal"),
    }
    if federal_rate is None or rates["Estadual"] is None or rates["Municipal"] is None:
        return {
            "id": record_id,
            "status": "UNAVAILABLE",
            "erro": "O cenário ou as alíquotas necessárias não estão disponíveis no registro.",
        }
    try:
        estimate = calculate_estimate(
            Decimal(str(row["valor_unitario"])),
            {
                key: Decimal(str(rate)) if rate is not None else None
                for key, rate in rates.items()
            },
            scenario,
        )
    except (InvalidOperation, TypeError, ValueError):
        return {
            "id": record_id,
            "status": "UNAVAILABLE",
            "erro": "Os parâmetros persistidos não permitem reproduzir o cálculo.",
        }
    return {
        "id": record_id,
        "status": "AVAILABLE",
        "cenario": scenario,
        "Federal": _money_or_rate(estimate["Federal"]),
        "Estadual": _money_or_rate(estimate["Estadual"]),
        "Municipal": _money_or_rate(estimate["Municipal"]),
        "total_estimado": _money_or_rate(estimate["total"]),
        "percentual_total": _money_or_rate(estimate["percentual_total"]),
        "algoritmo_versao": CALCULATION_ALGORITHM_VERSION,
        "politica_arredondamento": ROUNDING_POLICY,
    }
