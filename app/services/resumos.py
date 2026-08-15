"""Camada de NLP — transforma o diagnóstico numérico em texto de operação.

Entrada: o dicionário de contexto montado pelo pipeline a partir do `Diagnostico`
da camada analítica e do cadastro do ativo. Saída: `ResumoAlerta`.

Geração por Gemini 2.5 Flash, reaproveitando a chave já usada no OCR da placa.
Sem chave, sem rede ou com resposta inválida, cai em um gerador determinístico por
template com o mesmo formato — a interface indica qual dos dois produziu o texto.
Nenhuma falha de rede pode derrubar o painel.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Literal

import streamlit as st

from app.services.gemini_client import disponivel, get_client

MODEL_NAME = "gemini-2.5-flash"

# O plano gratuito do Gemini tem cota diária baixa. Cache longo e dedupe de evento
# são o que mantém o painel dentro dela: sem isso, um timer de 5 s consome a cota
# em minutos e todos os resumos caem para o template.
TTL_CACHE = 1800

OrigemResumo = Literal["gemini", "template"]

ROTULO_GRANDEZA = {
    "temperatura": "temperatura",
    "vibracao":    "vibração",
    "corrente":    "corrente",
    "rpm":         "rotação",
    "aceleracao":  "aceleração",
}

ROTULO_SEVERIDADE = {"crit": "crítico", "warn": "atenção", "ok": "normal"}

ACOES_PADRAO = {
    "temperatura": [
        "Verificar ventilação e limpeza das aletas de refrigeração",
        "Medir temperatura do mancal com termômetro infravermelho",
        "Conferir carga acoplada e corrente de operação",
    ],
    "vibracao": [
        "Inspecionar alinhamento e fixação da base do motor",
        "Avaliar folga e ruído dos rolamentos",
        "Programar análise de vibração espectral",
    ],
    "corrente": [
        "Conferir equilíbrio entre as fases",
        "Avaliar sobrecarga mecânica no acoplamento",
        "Revisar ajuste do relé de proteção",
    ],
    "rpm": [
        "Verificar parâmetros do inversor de frequência",
        "Checar acoplamento e possível travamento da carga",
        "Confirmar leitura do encoder / tacômetro",
    ],
    "aceleracao": [
        "Inspecionar rolamentos e engrenamento",
        "Verificar fixação do sensor IO-Link",
        "Programar análise de envelope",
    ],
}

ACOES_INSTRUMENTACAO = [
    "Verificar o link IO-Link e a alimentação do sensor",
    "Confirmar se o valor lido está congelado no supervisório",
    "Abrir chamado de instrumentação antes de intervir no motor",
]

PROMPT_ALERTA = """Você é um engenheiro de manutenção preditiva escrevendo para o operador
de uma planta industrial. Escreva em português do Brasil, direto e sem jargão de IA.

Dados do alerta (JSON):
{contexto}

Devolva APENAS JSON com:
- titulo: uma linha de até 70 caracteres resumindo o problema.
- texto: 2 a 3 frases explicando o que foi detectado, desde quando e qual a
  provável causa física. Cite o valor medido e o limite quando existirem.
  Não invente dado que não esteja no JSON.
- recomendacoes: lista de exatamente 3 ações objetivas de manutenção, na ordem
  em que devem ser executadas, começando por verbo no infinitivo.
"""

PROMPT_FROTA = """Você é um engenheiro de manutenção preditiva resumindo o turno para o
supervisor de operação. Escreva em português do Brasil, objetivo.

Situação da frota (JSON):
{contexto}

Devolva APENAS JSON com:
- titulo: uma linha de até 70 caracteres com o estado geral da frota.
- texto: 2 a 3 frases citando os ativos mais críticos e o que exige ação agora.
- recomendacoes: lista de exatamente 3 prioridades para o turno.
"""

SCHEMA_RESUMO = {
    "type": "object",
    "properties": {
        "titulo":        {"type": "string"},
        "texto":         {"type": "string"},
        "recomendacoes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["titulo", "texto", "recomendacoes"],
}


@dataclass
class ResumoAlerta:
    titulo: str
    texto: str
    recomendacoes: list[str] = field(default_factory=list)
    origem: OrigemResumo = "template"


# --------------------------------------------------------------------------- Gemini


def _chamar_gemini(prompt: str, tentativas: int = 2) -> dict | None:
    """Devolve o JSON do modelo, ou None em qualquer falha (chave, rede, parsing).

    Uma segunda tentativa cobre o caso comum de limite de requisições por minuto
    quando vários alertas surgem juntos; além disso, cai para o template.
    """
    if not disponivel():
        print("[resumos] sem GEMINI_API_KEY, usando template")
        return None

    from google.genai import types

    dados = {}
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = get_client().models.generate_content(
                model=MODEL_NAME,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=SCHEMA_RESUMO,
                    temperature=0.2,
                ),
            )
            dados = json.loads(resposta.text or "{}")
            break
        except Exception as erro:                   # sem rede, cota estourada, JSON quebrado
            print(f"[resumos] tentativa {tentativa}/{tentativas} falhou: {erro}")
            if tentativa == tentativas:
                return None
            time.sleep(1.5)

    if not dados.get("titulo") or not dados.get("texto"):
        print(f"[resumos] resposta incompleta, usando template: {str(dados)[:120]}")
        return None
    return dados


def _do_json(dados: dict) -> ResumoAlerta:
    acoes = [str(a).strip() for a in dados.get("recomendacoes", []) if str(a).strip()]
    return ResumoAlerta(
        titulo=str(dados["titulo"]).strip(),
        texto=str(dados["texto"]).strip(),
        recomendacoes=acoes[:3],
        origem="gemini",
    )


# --------------------------------------------------------------------------- templates


def _acoes_para(contexto: dict) -> list[str]:
    if contexto.get("detectores", {}).get("variancia"):
        return ACOES_INSTRUMENTACAO
    return ACOES_PADRAO.get(contexto.get("grandeza") or "", ACOES_INSTRUMENTACAO)


def _resumo_template(contexto: dict) -> ResumoAlerta:
    tag = contexto.get("tag", "—")
    grandeza = ROTULO_GRANDEZA.get(contexto.get("grandeza") or "", contexto.get("grandeza") or "sinal")
    severidade = ROTULO_SEVERIDADE.get(contexto.get("severidade"), "atenção")
    unidade = contexto.get("unidade") or ""
    valor = contexto.get("valor")
    limite = contexto.get("limite_crit") if contexto.get("severidade") == "crit" else contexto.get("limite_warn")

    if contexto.get("origem") == "ml":
        titulo = f"{tag}: desvio de {grandeza} fora do comportamento esperado"
        base = (
            f"O detector de anomalia acusou estado {severidade} em {tag}: o score de desvio "
            f"chegou a {contexto.get('score')} contra um limiar de {contexto.get('threshold')}, "
            f"com {grandeza} como grandeza dominante."
        )
    else:
        titulo = f"{tag}: {grandeza} em nível {severidade}"
        if isinstance(valor, (int, float)):
            base = f"A leitura de {grandeza} em {tag} está em {valor:.2f} {unidade}".rstrip()
            base += (f", fora do limite de {limite:.1f} {unidade}."
                     if isinstance(limite, (int, float)) else ".")
        else:
            base = f"A leitura de {grandeza} em {tag} está em nível {severidade}."

    ativos = [d for d, on in (contexto.get("detectores") or {}).items() if on]
    if ativos:
        base += f" Detectores acionados: {', '.join(ativos)}."
    if contexto.get("pista"):
        base += f" Causa provável: {contexto['pista']}."

    local = " · ".join(x for x in (contexto.get("planta"), contexto.get("area")) if x)
    if local:
        base += f" Localização: {local}."

    return ResumoAlerta(titulo=titulo, texto=base, recomendacoes=_acoes_para(contexto), origem="template")


def _resumo_frota_template(contexto: dict) -> ResumoAlerta:
    crit = contexto.get("criticos", 0)
    warn = contexto.get("em_alerta", 0)
    total = contexto.get("total", 0)
    destaques = contexto.get("destaques") or []

    if crit == 0 and warn == 0:
        return ResumoAlerta(
            titulo="Frota em operação normal",
            texto=(
                f"Os {total} ativos monitorados estão dentro da faixa de operação e nenhum "
                "detector de anomalia disparou nas últimas 24 horas."
            ),
            recomendacoes=[
                "Manter o monitoramento contínuo no painel",
                "Revisar o plano de manutenção preventiva do período",
                "Conferir a cobertura de sensores dos ativos sem telemetria",
            ],
            origem="template",
        )

    lista = ", ".join(f"{d['tag']} ({ROTULO_SEVERIDADE.get(d['severidade'], d['severidade'])})"
                      for d in destaques[:3]) or "—"
    return ResumoAlerta(
        titulo=f"{crit} ativo(s) em estado crítico e {warn} em atenção",
        texto=(
            f"De {total} ativos monitorados, {crit} estão em estado crítico e {warn} em atenção. "
            f"Prioridade imediata: {lista}. Os demais seguem dentro da faixa de operação."
        ),
        recomendacoes=[
            f"Atender primeiro o ativo {destaques[0]['tag']}" if destaques else "Revisar os alertas ativos",
            "Confirmar a leitura em campo antes de intervir",
            "Registrar a ação tomada para fechar o evento no histórico",
        ],
        origem="template",
    )


# --------------------------------------------------------------------------- fachada


@st.cache_data(ttl=TTL_CACHE, show_spinner=False)
def gerar_resumo(contexto: dict, permitir_llm: bool = True) -> ResumoAlerta:
    """Resumo textual de um alerta. Cacheado para não chamar a LLM a cada tick.

    `permitir_llm=False` força o template: usado quando o ciclo já gastou o
    orçamento de chamadas, para o painel não travar esperando a rede.
    """
    if not permitir_llm:
        return _resumo_template(contexto)
    dados = _chamar_gemini(PROMPT_ALERTA.format(contexto=json.dumps(contexto, ensure_ascii=False, default=str)))
    if dados:
        resumo = _do_json(dados)
        if not resumo.recomendacoes:
            resumo.recomendacoes = _acoes_para(contexto)
        return resumo
    return _resumo_template(contexto)


@st.cache_data(ttl=TTL_CACHE, show_spinner=False)
def gerar_resumo_frota(contexto: dict) -> ResumoAlerta:
    """Parágrafo executivo do topo do painel."""
    dados = _chamar_gemini(PROMPT_FROTA.format(contexto=json.dumps(contexto, ensure_ascii=False, default=str)))
    if dados:
        return _do_json(dados)
    return _resumo_frota_template(contexto)
