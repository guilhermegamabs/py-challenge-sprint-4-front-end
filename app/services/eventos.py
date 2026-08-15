"""Histórico de eventos operacionais — a fronteira entre o modelo e a interface.

A página nunca chama detector nem LLM: ela lê eventos daqui. Quem grava é o
pipeline (`analitico` -> `resumos` -> `eventos`), disparado pelo botão ou pelo
timer do painel. Trocar o preditor ou o gerador de texto não toca a interface.
"""

import json
from datetime import datetime, timedelta

import pandas as pd

from app.services.db import conexao

SEVERIDADE_ORDEM = {"crit": 0, "warn": 1, "ok": 2}
ROTULO_SEVERIDADE = {"crit": "Crítico", "warn": "Atenção", "ok": "OK"}
ROTULO_ORIGEM = {"ml": "ML · anomalia", "limite": "Limite operacional"}

JANELA_DEDUPE_MIN = 30   # mesmo alerta dentro deste intervalo não vira evento novo


def registrar_evento(
    tag: str,
    severidade: str,
    origem: str,
    *,
    ts: datetime | None = None,
    grandeza: str | None = None,
    valor: float | None = None,
    unidade: str | None = None,
    score: float | None = None,
    threshold: float | None = None,
    detectores: dict | None = None,
    pista: str | None = None,
    titulo: str | None = None,
    resumo: str | None = None,
    recomendacoes: list[str] | None = None,
    origem_resumo: str | None = None,
    assinatura: str | None = None,
) -> int | None:
    """Grava um evento. Devolve o id, ou None se for repetição recente.

    A deduplicação evita que um ativo em falha contínua gere um evento por tick
    do timer: o painel ficaria ilegível e cada repetição custaria uma chamada de LLM.
    """
    ts = ts or datetime.now()
    assinatura = assinatura or f"{origem}|{tag}|{grandeza}|{severidade}"

    # Teste e inserção em um único statement: duas execuções simultâneas do script
    # (o rerun do Streamlit é concorrente) passariam por um SELECT seguido de
    # INSERT e gravariam o mesmo alerta duas vezes.
    with conexao() as con:
        cur = con.execute(
            """INSERT INTO eventos
               (tag, ts, origem, severidade, grandeza, valor, unidade, score, threshold,
                detectores, pista, titulo, resumo, recomendacoes, origem_resumo, assinatura)
               SELECT ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
               WHERE NOT EXISTS (
                   SELECT 1 FROM eventos WHERE assinatura = ? AND ts >= ?
               )""",
            (
                tag, ts, origem, severidade, grandeza, valor, unidade, score, threshold,
                json.dumps(detectores or {}), pista, titulo, resumo,
                json.dumps(recomendacoes or [], ensure_ascii=False),
                origem_resumo, assinatura,
                assinatura, ts - timedelta(minutes=JANELA_DEDUPE_MIN),
            ),
        )
        return cur.lastrowid if cur.rowcount else None


def existe_recente(assinatura: str, ts: datetime | None = None) -> bool:
    """Já há evento com esta assinatura na janela de dedupe?

    Consultado ANTES de gerar o resumo: sem isso, cada tick do timer pagaria uma
    chamada de LLM para um alerta que seria descartado na gravação.
    """
    ts = ts or datetime.now()
    with conexao() as con:
        row = con.execute(
            "SELECT 1 FROM eventos WHERE assinatura = ? AND ts >= ? LIMIT 1",
            (assinatura, ts - timedelta(minutes=JANELA_DEDUPE_MIN)),
        ).fetchone()
    return row is not None


def _row_to_dict(row) -> dict:
    evento = dict(row)
    evento["detectores"] = json.loads(evento.get("detectores") or "{}")
    evento["recomendacoes"] = json.loads(evento.get("recomendacoes") or "[]")
    evento["ts"] = pd.to_datetime(evento["ts"])
    return evento


def eventos_ativos(horas: int = 24, limite: int = 20) -> list[dict]:
    """Alertas não reconhecidos no período, do mais severo para o mais recente."""
    desde = datetime.now() - timedelta(hours=horas)
    with conexao() as con:
        linhas = con.execute(
            """SELECT * FROM eventos
               WHERE reconhecido = 0 AND severidade IN ('warn','crit') AND ts >= ?
               ORDER BY ts DESC LIMIT ?""",
            (desde, limite),
        ).fetchall()
    eventos = [_row_to_dict(l) for l in linhas]
    eventos.sort(key=lambda e: (SEVERIDADE_ORDEM.get(e["severidade"], 9), -e["ts"].timestamp()))
    return eventos


def listar_eventos(
    limite: int = 100,
    severidades: list[str] | None = None,
    horas: int | None = None,
) -> pd.DataFrame:
    """Histórico para exibição em tabela, já com rótulos legíveis."""
    sql = "SELECT * FROM eventos WHERE 1=1"
    params: list = []
    if severidades:
        sql += f" AND severidade IN ({','.join('?' * len(severidades))})"
        params += severidades
    if horas:
        sql += " AND ts >= ?"
        params.append(datetime.now() - timedelta(hours=horas))
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(limite)

    with conexao() as con:
        df = pd.read_sql_query(sql, con, params=params, parse_dates=["ts"])

    if df.empty:
        return pd.DataFrame(
            columns=["Timestamp", "TAG", "Severidade", "Origem", "Grandeza", "Valor", "Resumo"]
        )

    saida = pd.DataFrame({
        "Timestamp":  df["ts"],
        "TAG":        df["tag"],
        "Severidade": df["severidade"].map(ROTULO_SEVERIDADE).fillna(df["severidade"]),
        "Origem":     df["origem"].map(ROTULO_ORIGEM).fillna(df["origem"]),
        "Grandeza":   df["grandeza"].fillna("—").str.capitalize(),
        "Valor":      df["valor"],
        "Resumo":     df["titulo"].fillna(df["resumo"]).fillna("—"),
    })
    return saida


def contar_por_severidade(horas: int = 24) -> dict[str, int]:
    desde = datetime.now() - timedelta(hours=horas)
    with conexao() as con:
        linhas = con.execute(
            "SELECT severidade, COUNT(*) AS n FROM eventos WHERE ts >= ? GROUP BY severidade",
            (desde,),
        ).fetchall()
    return {l["severidade"]: l["n"] for l in linhas}


def contar_anomalias_ml(horas: int = 24) -> int:
    desde = datetime.now() - timedelta(hours=horas)
    with conexao() as con:
        row = con.execute(
            "SELECT COUNT(*) AS n FROM eventos WHERE origem = 'ml' AND ts >= ?",
            (desde,),
        ).fetchone()
    return row["n"]


def ultimo_id() -> int:
    with conexao() as con:
        row = con.execute("SELECT COALESCE(MAX(id), 0) AS ultimo FROM eventos").fetchone()
    return row["ultimo"]


def reconhecer(evento_id: int):
    with conexao() as con:
        con.execute("UPDATE eventos SET reconhecido = 1 WHERE id = ?", (evento_id,))


def reconhecer_todos():
    with conexao() as con:
        con.execute("UPDATE eventos SET reconhecido = 1 WHERE reconhecido = 0")


def limpar_eventos(tag: str | None = None):
    """Usado pela restauração da demo, para o painel voltar ao estado limpo."""
    with conexao() as con:
        if tag:
            con.execute("DELETE FROM eventos WHERE tag = ?", (tag,))
        else:
            con.execute("DELETE FROM eventos")
