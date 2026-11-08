import os
import time
from contextlib import closing
from decimal import Decimal, InvalidOperation
from typing import Any

import pymysql
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pymysql.cursors import DictCursor

IBPT_URL = "https://apidoni.ibpt.org.br/api/v1/produtos"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TAX_FIELDS = ("Nacional", "Estadual", "Municipal", "Importado")

app = FastAPI(title="Fiscalis - Consulta de Impostos", version="1.0.0")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


class ConsultaRequest(BaseModel):
    token: str = Field(min_length=1, max_length=500)
    cnpj: str = Field(min_length=1, max_length=20)
    codigo: str | None = Field(default=None, max_length=20)
    NCM: str | None = Field(default=None, max_length=20)
    uf: str = Field(min_length=2, max_length=2)
    descricao: str = Field(min_length=1, max_length=255)
    unidadeMedida: str = Field(default="UN", min_length=1, max_length=20)
    valor: Decimal = Field(gt=0)
    gtin: str | None = Field(default=None, max_length=20)
    ex: int = Field(default=0, ge=0)


def _db_connection():
    required = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Variáveis de banco ausentes: {', '.join(missing)}")
    try:
        port = int(os.getenv("DB_PORT", "3306"))
    except ValueError:
        raise RuntimeError("DB_PORT deve ser uma porta numérica.") from None
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=port,
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        charset="utf8mb4",
        cursorclass=DictCursor,
        connect_timeout=5,
        autocommit=False,
    )


def _initialize_database() -> None:
    create_table = """
        CREATE TABLE IF NOT EXISTS consultas_tributos (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            cnpj_empresa VARCHAR(20) NOT NULL,
            uf CHAR(2) NOT NULL,
            codigo_ncm VARCHAR(20) NOT NULL,
            descricao_produto VARCHAR(255) NOT NULL,
            valor_unitario DECIMAL(15, 4) NOT NULL,
            aliquota_nacional DECIMAL(10, 4) NULL,
            aliquota_estadual DECIMAL(10, 4) NULL,
            aliquota_municipal DECIMAL(10, 4) NULL,
            aliquota_importado DECIMAL(10, 4) NULL,
            fonte_informacao VARCHAR(255) NULL,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_consultas_criado (criado_em, id)
        ) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4
          COLLATE=utf8mb4_unicode_ci
    """
    last_error = None
    for attempt in range(30):
        try:
            with closing(_db_connection()) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(create_table)
                connection.commit()
            return
        except (pymysql.MySQLError, RuntimeError) as error:
            last_error = error
            if attempt < 29:
                time.sleep(2)
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


def _get_codigo(data: ConsultaRequest) -> str:
    codigo = (data.codigo or data.NCM or "").strip()
    if not codigo:
        raise HTTPException(status_code=422, detail="Informe o código NCM.")
    if data.codigo and data.NCM and data.codigo.strip() != data.NCM.strip():
        raise HTTPException(status_code=422, detail="Os valores de código e NCM devem ser iguais.")
    return codigo


def _tax_result(raw: Any) -> dict[str, Any]:
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail="A API do IBPT não retornou uma consulta válida.")
    result = {}
    for key in TAX_FIELDS:
        value = raw.get(key)
        if value is None or value == "":
            result[key] = None
            continue
        try:
            rate = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise HTTPException(status_code=502, detail="A API do IBPT retornou uma alíquota inválida.") from None
        if not rate.is_finite():
            raise HTTPException(status_code=502, detail="A API do IBPT retornou uma alíquota inválida.")
        result[key] = rate
    result["Fonte"] = str(raw.get("Fonte") or "")
    return result


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


@app.get("/api/historico")
def historico() -> list[dict[str, Any]]:
    try:
        with closing(_db_connection()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, cnpj_empresa, uf, codigo_ncm, descricao_produto,
                           valor_unitario, aliquota_nacional, aliquota_estadual,
                           aliquota_municipal, aliquota_importado, fonte_informacao,
                           criado_em
                    FROM consultas_tributos
                    ORDER BY criado_em DESC, id DESC
                    LIMIT 50
                    """
                )
                rows = cursor.fetchall()
    except (pymysql.MySQLError, RuntimeError):
        raise HTTPException(status_code=503, detail="Não foi possível carregar o histórico.") from None
    return rows
