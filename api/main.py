"""Protótipo da API REST da Forzy — proposta "Ir além" da Sprint 4.

Expõe por HTTP a mesma camada `app/services/` que o Streamlit consome hoje. É o
primeiro passo da separação front-end/back-end: nenhuma regra foi reescrita, a
API só troca o chamador (página Streamlit -> requisição HTTP).

Rodar:
    set FORZY_API_KEY=<chave>        (PowerShell: $env:FORZY_API_KEY = "<chave>")
    uvicorn api.main:app --port 8000
Documentação interativa em http://localhost:8000/docs
"""

import logging
import os
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.services import analitico, eventos
from app.services.db import init_db
from app.services.equipamentos import get_equipamento, get_equipamentos
from app.services.telemetria import get_historico, status_por_grandeza, ultima_leitura

from api import feedback

trace_id_atual: ContextVar[str] = ContextVar("trace_id", default="-")


class _TraceFilter(logging.Filter):
    def filter(self, record):
        record.trace_id = trace_id_atual.get()
        return True


_handler = logging.StreamHandler()
_handler.addFilter(_TraceFilter())
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [trace=%(trace_id)s] %(message)s"))
log = logging.getLogger("forzy.api")
log.addHandler(_handler)
log.setLevel(logging.INFO)

Janela = Literal["1h", "3h", "24h", "7d"]


@asynccontextmanager
async def _ciclo_de_vida(_app: FastAPI):
    init_db()
    feedback.criar_tabela()
    yield


app = FastAPI(
    lifespan=_ciclo_de_vida,
    title="Forzy — API de Monitoramento de Ativos",
    version="0.1.0-prototipo",
    description="Protótipo da separação front-end/back-end proposta na Sprint 4.",
)


# ------------------------------------------------------------------ observabilidade


@app.middleware("http")
async def contexto_requisicao(request: Request, call_next):
    """Propaga ou gera o trace_id e devolve no header da resposta.

    O front manda `X-Trace-Id` quando já tem um (ex.: a ação do usuário que
    disparou várias chamadas); sem ele, a API gera. O mesmo id aparece no log, no
    corpo de erro e no header — é por ele que um print de erro do usuário é
    encontrado no log do servidor.
    """
    trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex[:16]
    token = trace_id_atual.set(trace_id)
    inicio = datetime.now()
    try:
        resposta = await call_next(request)
        duracao_ms = (datetime.now() - inicio).total_seconds() * 1000
        resposta.headers["X-Trace-Id"] = trace_id
        resposta.headers["X-Duracao-Ms"] = f"{duracao_ms:.0f}"
        log.info("%s %s -> %s (%.0f ms)", request.method, request.url.path,
                 resposta.status_code, duracao_ms)
        return resposta
    finally:
        trace_id_atual.reset(token)


# ------------------------------------------------------------------ erros amigáveis


def _erro(status: int, codigo: str, mensagem: str, request: Request) -> JSONResponse:
    trace_id = request.headers.get("X-Trace-Id") or trace_id_atual.get()
    return JSONResponse(
        status_code=status,
        content={"erro": codigo, "mensagem": mensagem, "trace_id": trace_id},
    )


# Erros que o próprio framework levanta (rota inexistente, corpo que não é JSON
# válido) vêm com texto em inglês; o operador recebe a versão em português.
MENSAGENS_FRAMEWORK = {
    "Not Found": "Rota não encontrada.",
    "Method Not Allowed": "Método HTTP não permitido nesta rota.",
    "There was an error parsing the body": "Corpo da requisição inválido: envie JSON em UTF-8.",
}


# Registrado na classe do Starlette, não na do FastAPI: a do FastAPI é subclasse,
# então só assim os erros levantados pelo framework também saem no formato padrão.
@app.exception_handler(StarletteHTTPException)
async def _http_erro(request: Request, exc: StarletteHTTPException):
    codigo = {401: "nao_autorizado", 404: "nao_encontrado", 503: "indisponivel"}.get(
        exc.status_code, "requisicao_invalida"
    )
    mensagem = MENSAGENS_FRAMEWORK.get(str(exc.detail), str(exc.detail))
    return _erro(exc.status_code, codigo, mensagem, request)


@app.exception_handler(RequestValidationError)
async def _validacao_erro(request: Request, exc: RequestValidationError):
    campos = ", ".join(".".join(str(p) for p in e["loc"][1:]) for e in exc.errors())
    return _erro(422, "dados_invalidos", f"Verifique os campos: {campos}.", request)


@app.exception_handler(Exception)
async def _erro_inesperado(request: Request, exc: Exception):
    # O detalhe técnico vai para o log; o usuário recebe uma frase e o trace_id
    # para informar ao suporte. Stack trace nunca sai pela resposta.
    log.exception("erro não tratado")
    return _erro(
        500, "erro_interno",
        "Não foi possível concluir a operação. Informe o código de rastreio ao suporte.",
        request,
    )


# ------------------------------------------------------------------ autenticação

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def exigir_api_key(chave: str | None = Security(_api_key_header)):
    esperada = os.environ.get("FORZY_API_KEY")
    if not esperada:
        # Sem chave configurada a API recusa tudo: subir aberta por esquecimento
        # é pior do que não subir.
        raise HTTPException(503, "API sem FORZY_API_KEY configurada no servidor.")
    if chave != esperada:
        raise HTTPException(401, "Chave de API ausente ou inválida (header X-API-Key).")


protegido = [Depends(exigir_api_key)]


# ------------------------------------------------------------------ modelos


class Ativo(BaseModel):
    tag: str
    modelo: str | None
    fabricante: str | None
    potencia_w: int | None
    tensao_v: int | None
    planta: str | None
    area: str | None


class AtivoDetalhe(Ativo):
    status_por_grandeza: dict[str, str]
    ultima_leitura: dict | None


class Evento(BaseModel):
    id: int
    tag: str
    ts: datetime
    severidade: str
    origem: str
    grandeza: str | None
    valor: float | None
    titulo: str | None
    resumo: str | None
    recomendacoes: list[str]
    origem_resumo: str | None
    reconhecido: bool


class FeedbackEntrada(BaseModel):
    util: bool = Field(description="O resumo gerado ajudou na decisão?")
    comentario: str | None = Field(default=None, max_length=500)


def _ativo(eq: dict) -> dict:
    return {
        "tag": eq["TAG"], "modelo": eq["Modelo"], "fabricante": eq["Fabricante"],
        "potencia_w": eq["Potência (W)"], "tensao_v": eq["Tensão (V)"],
        "planta": eq["Planta"], "area": eq["Área"],
    }


def _evento(row: dict) -> dict:
    return {**row, "reconhecido": bool(row.get("reconhecido")), "ts": row["ts"].to_pydatetime()}


def _buscar_ativo(tag: str) -> dict:
    eq = get_equipamento(tag.upper())
    if not eq:
        raise HTTPException(404, f"Ativo {tag.upper()} não encontrado.")
    return eq


# ------------------------------------------------------------------ endpoints


@app.get("/health", tags=["infra"])
def health():
    """Público: usado pelo balanceador/healthcheck, não expõe dado."""
    return {"status": "ok"}


@app.get("/ativos", response_model=list[Ativo], dependencies=protegido, tags=["ativos"])
def listar_ativos():
    return [_ativo(eq) for eq in get_equipamentos()]


@app.get("/ativos/{tag}", response_model=AtivoDetalhe, dependencies=protegido, tags=["ativos"])
def detalhar_ativo(tag: str):
    eq = _buscar_ativo(tag)
    leitura = ultima_leitura(eq["TAG"])
    if leitura and leitura.get("ts") is not None:
        leitura = {**leitura, "ts": str(leitura["ts"])}
    return {**_ativo(eq), "status_por_grandeza": status_por_grandeza(eq["TAG"]),
            "ultima_leitura": leitura}


@app.get("/ativos/{tag}/telemetria", dependencies=protegido, tags=["ativos"])
def telemetria(tag: str, janela: Janela = "24h"):
    eq = _buscar_ativo(tag)
    df = get_historico(eq["TAG"], janela)
    df = df.astype(object).where(df.notna(), None)
    df["ts"] = df["ts"].astype(str)
    return {"tag": eq["TAG"], "janela": janela, "leituras": df.to_dict(orient="records")}


@app.get("/ativos/{tag}/diagnostico", dependencies=protegido, tags=["ativos"])
def diagnostico(tag: str):
    """Roda os três detectores (resíduo, CUSUM, variância) sobre o histórico."""
    eq = _buscar_ativo(tag)
    diag = analitico.avaliar(eq["TAG"])
    if diag is None:
        raise HTTPException(404, f"Histórico insuficiente para diagnosticar {eq['TAG']}.")
    return {**diag.__dict__, "ts": str(diag.ts), "detectores_ativos": diag.detectores_ativos}


@app.get("/eventos", response_model=list[Evento], dependencies=protegido, tags=["eventos"])
def listar_alertas_ativos(horas: int = Query(24, ge=1, le=720)):
    return [_evento(e) for e in eventos.eventos_ativos(horas=horas)]


@app.post("/eventos/{evento_id}/reconhecer", status_code=204, dependencies=protegido, tags=["eventos"])
def reconhecer(evento_id: int):
    if not feedback.evento_existe(evento_id):
        raise HTTPException(404, f"Evento {evento_id} não encontrado.")
    eventos.reconhecer(evento_id)


@app.post("/eventos/{evento_id}/feedback", status_code=201, dependencies=protegido, tags=["eventos"])
def avaliar_resumo(evento_id: int, entrada: FeedbackEntrada):
    """Feedback do operador sobre o resumo gerado por IA (👍/👎 + comentário).

    Guarda junto a origem do resumo (gemini/template) e o trace_id: é o dado que
    permite comparar a qualidade do texto da LLM com a do fallback.
    """
    if not feedback.evento_existe(evento_id):
        raise HTTPException(404, f"Evento {evento_id} não encontrado.")
    feedback.registrar(evento_id, entrada.util, entrada.comentario, trace_id_atual.get())
    return {"evento_id": evento_id, "registrado": True}


@app.get("/feedback/resumo", dependencies=protegido, tags=["eventos"])
def resumo_feedback():
    """Taxa de aprovação dos resumos por origem — o painel de qualidade da IA."""
    return feedback.agregado()
