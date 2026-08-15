"""Orquestração do ciclo de monitoramento.

    telemetria (regra de limite)  ─┐
                                   ├─► resumos (NLP) ─► eventos (SQLite) ─► painel
    analitico  (detecção ML)     ──┘

O painel dispara `executar_ciclo()` no botão e a cada tick do timer, e depois lê
os eventos do banco. Nenhuma página fala com o detector ou com a LLM diretamente.
"""

from datetime import datetime

import streamlit as st

from app.services import analitico, eventos, resumos
from app.services.equipamentos import get_equipamentos
from app.services.telemetria import (
    GRANDEZAS,
    classificar,
    get_limites,
    ultima_leitura,
)

TTL_ESTADO = 10   # segundos; o timer do painel pode bater mais rápido que isso

# Teto de chamadas de LLM por ciclo. Uma frota inteira em alerta geraria uma
# chamada por ativo e o painel ficaria dezenas de segundos em branco; o excedente
# recebe o resumo por template, que é instantâneo e diz a mesma coisa.
ORCAMENTO_LLM = 3

ORDEM_SEVERIDADE = {"crit": 0, "warn": 1, "ok": 2}


def _contexto_limite(eq: dict, grandeza: str, valor: float, severidade: str, lim: dict) -> dict:
    return {
        "tag":         eq["TAG"],
        "modelo":      eq.get("Modelo"),
        "fabricante":  eq.get("Fabricante"),
        "planta":      eq.get("Planta"),
        "area":        eq.get("Área"),
        "origem":      "limite",
        "severidade":  severidade,
        "grandeza":    grandeza,
        "valor":       round(float(valor), 2),
        "unidade":     lim["unidade"],
        "limite_warn": lim["warn_max"],
        "limite_crit": lim["crit_max"],
        "detectores":  {},
        "pista":       analitico.PISTA.get(grandeza),
    }


def _contexto_ml(eq: dict, diag: analitico.Diagnostico, leitura: dict, limites: dict) -> dict:
    lim = limites.get(diag.feature_dominante, {})
    valor = (leitura or {}).get(diag.feature_dominante)
    return {
        "tag":         eq["TAG"],
        "modelo":      eq.get("Modelo"),
        "fabricante":  eq.get("Fabricante"),
        "planta":      eq.get("Planta"),
        "area":        eq.get("Área"),
        "origem":      "ml",
        "severidade":  diag.severidade,
        "grandeza":    diag.feature_dominante,
        "valor":       round(float(valor), 2) if valor is not None else None,
        "unidade":     lim.get("unidade"),
        "limite_warn": lim.get("warn_max"),
        "limite_crit": lim.get("crit_max"),
        "score":       diag.score,
        "threshold":   diag.threshold,
        "detectores":  diag.detectores,
        "pista":       diag.pista,
    }


def _pior_grandeza(item: dict, status: str) -> str | None:
    """Grandeza que define o status do ativo — a que está mais longe do limite."""
    candidatas = [g for g, e in item["por_grandeza"].items() if e == status]
    if not candidatas:
        return None
    leitura = item["leitura"] or {}
    return max(candidatas, key=lambda g: abs(leitura.get(g) or 0))


@st.cache_data(ttl=TTL_ESTADO, show_spinner=False)
def estado_frota() -> dict:
    """Fotografia atual da frota: status por ativo e contagem por severidade.

    Cacheado porque `ultima_leitura()` abre uma conexão por ativo; sem isso o
    timer de 5 s multiplicaria consultas sem necessidade.
    """
    limites = get_limites()
    ativos = []
    contadores = {"ok": 0, "warn": 0, "crit": 0}

    for eq in get_equipamentos():
        leitura = ultima_leitura(eq["TAG"])
        por_grandeza = {}
        pior = "ok"
        for g in GRANDEZAS:
            valor = (leitura or {}).get(g)
            estado = classificar(valor, g, limites) if valor is not None else "ok"
            por_grandeza[g] = estado
            if estado == "crit" or (estado == "warn" and pior != "crit"):
                pior = estado
        contadores[pior] += 1
        ativos.append({
            "eq": eq,
            "leitura": leitura,
            "status": pior,
            "por_grandeza": por_grandeza,
        })

    return {"ativos": ativos, "contadores": contadores, "limites": limites,
            "atualizado_em": datetime.now()}


def executar_ciclo(janela_tempo: str | None = None) -> list[int]:
    """Avalia a frota, gera os resumos e persiste os eventos novos.

    Devolve os ids criados nesta passada — o painel usa isso para notificar.
    `janela_tempo=None` deixa o detector escolher a janela por ativo.
    """
    estado = estado_frota()
    limites = estado["limites"]
    novos: list[int] = []
    orcamento = ORCAMENTO_LLM

    # Os ativos mais severos primeiro: são eles que merecem o resumo gerado por LLM
    # quando o orçamento do ciclo é apertado.
    ativos = sorted(estado["ativos"], key=lambda a: ORDEM_SEVERIDADE.get(a["status"], 3))

    for item in ativos:
        eq, leitura, status = item["eq"], item["leitura"], item["status"]
        tag = eq["TAG"]

        # --- 1. alerta por limite operacional (regra fixa, determinística)
        # Só a pior grandeza do ativo vira evento: um motor sobreaquecido costuma
        # violar temperatura e corrente ao mesmo tempo, e dois cards dizendo a
        # mesma coisa poluem o painel.
        if status in ("warn", "crit") and leitura:
            grandeza = _pior_grandeza(item, status)
            assinatura = f"limite|{tag}|{grandeza}|{status}"
            if grandeza and not eventos.existe_recente(assinatura):
                contexto = _contexto_limite(
                    eq, grandeza, leitura[grandeza], status, limites[grandeza]
                )
                resumo = resumos.gerar_resumo(contexto, permitir_llm=orcamento > 0)
                orcamento -= 1
                evento_id = eventos.registrar_evento(
                    tag, status, "limite",
                    grandeza=grandeza,
                    valor=contexto["valor"],
                    unidade=contexto["unidade"],
                    pista=contexto["pista"],
                    titulo=resumo.titulo,
                    resumo=resumo.texto,
                    recomendacoes=resumo.recomendacoes,
                    origem_resumo=resumo.origem,
                    assinatura=assinatura,
                )
                if evento_id:
                    novos.append(evento_id)

        # --- 2. anomalia detectada pelo modelo (desvio do comportamento aprendido)
        diag = analitico.avaliar(tag, janela_tempo)
        if diag and diag.alarme and not eventos.existe_recente(diag.assinatura):
            contexto = _contexto_ml(eq, diag, leitura, limites)
            resumo = resumos.gerar_resumo(contexto, permitir_llm=orcamento > 0)
            orcamento -= 1
            evento_id = eventos.registrar_evento(
                tag, diag.severidade, "ml",
                ts=datetime.now(),
                grandeza=diag.feature_dominante,
                valor=contexto["valor"],
                unidade=contexto["unidade"],
                score=diag.score,
                threshold=diag.threshold,
                detectores=diag.detectores,
                pista=diag.pista,
                titulo=resumo.titulo,
                resumo=resumo.texto,
                recomendacoes=resumo.recomendacoes,
                origem_resumo=resumo.origem,
                assinatura=diag.assinatura,
            )
            if evento_id:
                novos.append(evento_id)

    return novos


def resumo_executivo() -> resumos.ResumoAlerta:
    """Parágrafo de abertura do painel, sobre o estado geral da frota."""
    estado = estado_frota()
    contadores = estado["contadores"]
    destaques = [
        {"tag": a["eq"]["TAG"], "severidade": a["status"],
         "planta": a["eq"].get("Planta"), "area": a["eq"].get("Área")}
        for a in estado["ativos"] if a["status"] in ("crit", "warn")
    ]
    destaques.sort(key=lambda d: 0 if d["severidade"] == "crit" else 1)

    return resumos.gerar_resumo_frota({
        "total":      len(estado["ativos"]),
        "criticos":   contadores["crit"],
        "em_alerta":  contadores["warn"],
        "saudaveis":  contadores["ok"],
        "destaques":  destaques[:5],
        "anomalias_ml_24h": eventos.contar_anomalias_ml(24),
    })


def invalidar_cache():
    """Força a próxima leitura a bater no banco (botão Atualizar, simulação)."""
    estado_frota.clear()
