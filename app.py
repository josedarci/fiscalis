from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, root_validator, validator
from dotenv import load_dotenv

from services.config import ConfigurationError
from services.database import (
    DatabaseError,
    consultar_historico,
    salvar_consulta,
    validar_configuracao_banco,
)
from services.ibpt import ErroServicoIBPT, consultar_ibpt

load_dotenv()

app = FastAPI(title="Fiscalis API")
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
def pagina_inicial() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "index.html")


class ConsultaImpostoRequest(BaseModel):
    codigo: str = Field(..., description="NCM com oito dígitos.")
    uf: str
    descricao: str
    valor: Decimal
    unidadeMedida: str = "UN"
    gtin: str | None = None
    ex: int = 0

    class Config:
        extra = "forbid"

    @root_validator(pre=True)
    def aceitar_ncm(cls, values: Any) -> Any:
        if isinstance(values, dict):
            values = dict(values)
            ncm_lower = values.pop("ncm", None)
            ncm_upper = values.pop("NCM", None)
            ncm = ncm_lower if ncm_lower is not None else ncm_upper
            if (
                values.get("codigo") is not None
                and ncm is not None
                and str(values["codigo"]) != str(ncm)
            ):
                raise ValueError("Informe apenas um valor consistente para codigo/NCM.")
            if not values.get("codigo") and ncm is not None:
                values["codigo"] = ncm
        return values

    @validator("codigo")
    def validar_codigo(cls, value: str) -> str:
        codigo = value.strip()
        if len(codigo) != 8 or not codigo.isdigit():
            raise ValueError("codigo/NCM deve conter exatamente oito dígitos.")
        return codigo

    @validator("uf")
    def validar_uf(cls, value: str) -> str:
        uf = value.strip().upper()
        ufs = {
            "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA",
            "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN",
            "RS", "RO", "RR", "SC", "SP", "SE", "TO",
        }
        if uf not in ufs:
            raise ValueError("uf deve ser uma sigla válida de estado brasileiro.")
        return uf

    @validator("descricao")
    def validar_descricao(cls, value: str) -> str:
        descricao = value.strip()
        if not descricao:
            raise ValueError("descricao não pode ser vazia.")
        if len(descricao) > 255:
            raise ValueError("descricao deve ter no máximo 255 caracteres.")
        return descricao

    @validator("valor")
    def validar_valor(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0:
            raise ValueError("valor deve ser um número positivo.")
        return value

    @validator("unidadeMedida")
    def validar_unidade_medida(cls, value: str) -> str:
        unidade = value.strip()
        if not unidade or len(unidade) > 20:
            raise ValueError("unidadeMedida deve ter entre 1 e 20 caracteres.")
        return unidade

    @validator("gtin")
    def validar_gtin(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                return None
            if len(value) > 20:
                raise ValueError("gtin deve ter no máximo 20 caracteres.")
        return value

    @validator("ex")
    def validar_ex(cls, value: int) -> int:
        if value < 0:
            raise ValueError("ex não pode ser negativo.")
        return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/consultar-imposto")
def consultar_imposto(payload: ConsultaImpostoRequest) -> dict[str, Any]:
    try:
        validar_configuracao_banco()
        resultado = consultar_ibpt(payload)
        registro_id = salvar_consulta(payload, resultado)
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ErroServicoIBPT as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    except DatabaseError:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível persistir a consulta no banco de dados.",
        ) from None

    return {
        "id": registro_id,
        "codigo": payload.codigo,
        "uf": payload.uf,
        **_json_safe(resultado),
    }


@app.get("/api/historico")
def historico(
    limit: int | None = Query(default=None, ge=1),
) -> list[dict[str, Any]]:
    try:
        rows = consultar_historico(limit)
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except DatabaseError:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível consultar o histórico no banco de dados.",
        ) from None
    return _json_safe(rows)
