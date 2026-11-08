"""Persistência MySQL de consultas tributárias."""

import os
from decimal import Decimal
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from services.config import ConfigurationError, required_env


class DatabaseError(RuntimeError):
    """Falha na conexão ou operação do banco de dados."""


def _connection_config() -> dict[str, Any]:
    env = required_env(
        "MYSQL_HOST",
        "MYSQL_DATABASE",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
    )
    port_value = os.getenv("MYSQL_PORT", "3306").strip()
    try:
        port = int(port_value)
    except ValueError:
        raise ConfigurationError("A variável MYSQL_PORT deve ser uma porta válida.") from None
    if not 1 <= port <= 65535:
        raise ConfigurationError("A variável MYSQL_PORT deve ser uma porta válida.")
    return {
        "host": env["MYSQL_HOST"].strip(),
        "port": port,
        "database": env["MYSQL_DATABASE"].strip(),
        "user": env["MYSQL_USER"].strip(),
        "password": env["MYSQL_PASSWORD"],
        "charset": "utf8mb4",
        "cursorclass": DictCursor,
        "autocommit": False,
        "connect_timeout": 5,
    }


def _connect() -> Any:
    try:
        return pymysql.connect(**_connection_config())
    except ConfigurationError:
        raise
    except pymysql.MySQLError:
        raise DatabaseError("Falha ao conectar ao banco de dados.") from None


def validar_configuracao_banco() -> None:
    _connection_config()


def salvar_consulta(payload: Any, resultado: dict[str, Any]) -> int:
    cnpj_empresa = required_env("IBPT_CNPJ")["IBPT_CNPJ"].strip()
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO consultas_tributos (
                    cnpj_empresa, codigo_ncm, uf, descricao_produto, valor_unitario,
                    aliquota_nacional, aliquota_estadual, aliquota_municipal,
                    aliquota_importado, fonte_informacao
                ) VALUES (
                    %(cnpj_empresa)s, %(codigo)s, %(uf)s, %(descricao)s, %(valor)s,
                    %(nacional)s, %(estadual)s, %(municipal)s, %(importado)s,
                    %(fonte)s
                )
                """,
                {
                    "cnpj_empresa": cnpj_empresa,
                    "codigo": payload.codigo,
                    "uf": payload.uf,
                    "descricao": payload.descricao,
                    "valor": payload.valor,
                    "nacional": resultado["Nacional"],
                    "estadual": resultado["Estadual"],
                    "municipal": resultado["Municipal"],
                    "importado": resultado["Importado"],
                    "fonte": resultado["Fonte"],
                },
            )
            registro_id = cursor.lastrowid
        connection.commit()
        return int(registro_id)
    except Exception:
        try:
            connection.rollback()
        except Exception:
            pass
        raise DatabaseError("Falha ao salvar consulta no banco de dados.") from None
    finally:
        try:
            connection.close()
        except Exception:
            raise DatabaseError("Falha ao fechar conexão com o banco de dados.") from None


def _history_limit(requested_limit: int | None) -> int:
    max_value = os.getenv("HISTORY_MAX_LIMIT", "100").strip()
    try:
        max_limit = int(max_value)
    except ValueError:
        raise ConfigurationError(
            "A variável HISTORY_MAX_LIMIT deve ser um inteiro positivo."
        ) from None
    if max_limit < 1:
        raise ConfigurationError(
            "A variável HISTORY_MAX_LIMIT deve ser um inteiro positivo."
        )
    limit = max_limit if requested_limit is None else min(requested_limit, max_limit)
    return max(1, limit)


def consultar_historico(requested_limit: int | None = None) -> list[dict[str, Any]]:
    limit = _history_limit(requested_limit)
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, codigo_ncm AS codigo, uf,
                       descricao_produto AS descricao,
                       valor_unitario AS valor,
                       aliquota_nacional AS nacional,
                       aliquota_estadual AS estadual,
                       aliquota_municipal AS municipal,
                       aliquota_importado AS importado,
                       fonte_informacao AS fonte, criado_em
                FROM consultas_tributos
                ORDER BY criado_em DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            )
            return cursor.fetchall()
    except Exception:
        raise DatabaseError("Falha ao consultar histórico no banco de dados.") from None
    finally:
        try:
            connection.close()
        except Exception:
            raise DatabaseError("Falha ao fechar conexão com o banco de dados.") from None
