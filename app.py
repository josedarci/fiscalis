"""Compatibility facade; main.py is the canonical Fiscalis backend."""

from main import (
    ConsultaRequest,
    app,
    home,
    health_check,
    historico,
    consultar_imposto,
)
from services.config import ConfigurationError
from services.database import (
    DatabaseError,
    consultar_historico,
    salvar_consulta,
    validar_configuracao_banco,
)
from services.ibpt import ErroServicoIBPT, consultar_ibpt

ConsultaImpostoRequest = ConsultaRequest
pagina_inicial = home

__all__ = [
    "ConsultaImpostoRequest",
    "ConsultaRequest",
    "ConfigurationError",
    "DatabaseError",
    "ErroServicoIBPT",
    "app",
    "consultar_historico",
    "consultar_ibpt",
    "consultar_imposto",
    "health_check",
    "historico",
    "pagina_inicial",
    "salvar_consulta",
    "validar_configuracao_banco",
]
