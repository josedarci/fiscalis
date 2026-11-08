"""Leitura e validação de configuração operacional por variáveis de ambiente."""

import os


class ConfigurationError(RuntimeError):
    """Configuração ausente ou inválida, sem incluir valores sensíveis."""


def required_env(*names: str) -> dict[str, str]:
    values = {name: os.getenv(name, "") for name in names}
    missing = [name for name, value in values.items() if not value.strip()]
    if missing:
        raise ConfigurationError(
            "Variáveis de ambiente obrigatórias ausentes: " + ", ".join(missing)
        )
    return values
