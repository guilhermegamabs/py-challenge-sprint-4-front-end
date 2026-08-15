"""Injeção de degradação para demonstração da transição de estado.

Os modos reproduzem as falhas sintéticas do notebook (célula 25), escolhidas por
corresponderem a defeitos reais de motor. A leitura é gravada de verdade em
`leituras` via `telemetria.inserir_leitura()`: o estado do ativo muda no banco e
propaga para todas as páginas, não apenas para o painel.
"""

from datetime import datetime, timedelta

import numpy as np

from app.services.db import conexao
from app.services.telemetria import GRANDEZAS, get_limites, inserir_leitura, ultima_leitura

MODOS = {
    "sobreaquecimento": "Sobreaquecimento — ventilação obstruída / sobrecarga",
    "spike_vibracao":   "Spike de vibração — desbalanceamento, folga, desalinhamento",
    "deriva_termica":   "Deriva térmica lenta — rolamento degradando",
    "sensor_congelado": "Sensor congelado — falha do sensor / link IO-Link",
}

PASSOS_PADRAO = 25
INTERVALO_MIN = 1     # espaçamento entre as leituras injetadas


def _baseline(tag: str) -> dict:
    """Média das leituras do ativo antes de qualquer injeção, por grandeza."""
    with conexao() as con:
        row = con.execute(
            """SELECT AVG(temperatura) AS temperatura, AVG(vibracao) AS vibracao,
                      AVG(corrente) AS corrente, AVG(rpm) AS rpm
               FROM (SELECT * FROM leituras WHERE tag = ? ORDER BY ts LIMIT 500)""",
            (tag.upper(),),
        ).fetchone()
    return {g: row[g] for g in GRANDEZAS}


def _alvo(modo: str, base: dict, limites: dict) -> dict:
    """Valor final de cada grandeza ao término da degradação."""
    alvo = dict(base)
    if modo == "sobreaquecimento":
        alvo["temperatura"] = limites["temperatura"]["crit_max"] + 8.0
    elif modo == "spike_vibracao":
        alvo["vibracao"] = limites["vibracao"]["crit_max"] + 1.5
        if base.get("corrente") is not None:
            alvo["corrente"] = base["corrente"] * 1.25
    elif modo == "deriva_termica":
        # +0,5 °C/min: fica abaixo do limite operacional de propósito.
        # Só o CUSUM enxerga — é o caso que a regra fixa de limite não pega.
        if base.get("temperatura") is not None:
            alvo["temperatura"] = base["temperatura"] + 0.5 * PASSOS_PADRAO
    elif modo == "sensor_congelado":
        alvo = dict(base)          # valores idênticos: variância da janela vai a zero
    return alvo


def injetar_anomalia(tag: str, modo: str, passos: int = PASSOS_PADRAO) -> int:
    """Grava a rampa completa até o estado alvo. Devolve o nº de leituras inseridas."""
    if modo not in MODOS:
        raise ValueError(f"modo desconhecido: {modo}")

    base = _baseline(tag)
    atual = ultima_leitura(tag) or base
    limites = get_limites()
    alvo = _alvo(modo, base, limites)

    rng = np.random.default_rng(42)
    ts0 = datetime.now() - timedelta(minutes=passos * INTERVALO_MIN)

    # A injeção substitui a leitura do período em vez de conviver com ela: duas
    # séries intercaladas no mesmo minuto falseiam a variância da janela e
    # esconderiam justamente o modo "sensor congelado".
    with conexao() as con:
        con.execute("DELETE FROM leituras WHERE tag = ? AND ts >= ?", (tag.upper(), ts0))

    for i in range(1, passos + 1):
        fracao = i / passos
        valores = {}
        for g in GRANDEZAS:
            partida = atual.get(g)
            destino = alvo.get(g)
            if partida is None or destino is None:
                valores[g] = None                       # grandeza sem sensor
                continue
            if modo == "sensor_congelado":
                # o sinal trava no último valor lido: variância da janela vai a zero
                valores[g] = round(float(partida), 3)
                continue
            valor = partida + (destino - partida) * fracao
            valor += rng.normal(0, abs(destino) * 0.004 + 0.01)
            valores[g] = round(float(valor), 3)

        inserir_leitura(
            tag,
            temperatura=valores["temperatura"],
            vibracao=valores["vibracao"],
            corrente=valores["corrente"],
            rpm=valores["rpm"],
            ts=ts0 + timedelta(minutes=i * INTERVALO_MIN),
        )
    return passos


def avancar_degradacao(tag: str, modo: str, passo: int, total: int = PASSOS_PADRAO) -> bool:
    """Um passo da rampa por tick do timer. Devolve False quando a rampa termina."""
    if passo > total:
        return False

    base = _baseline(tag)
    atual = ultima_leitura(tag) or base
    alvo = _alvo(modo, base, get_limites())
    fracao = passo / total

    valores = {}
    for g in GRANDEZAS:
        partida, destino = base.get(g), alvo.get(g)
        if partida is None or destino is None:
            valores[g] = None
            continue
        valores[g] = round(float(partida + (destino - partida) * fracao), 3)

    inserir_leitura(
        tag,
        temperatura=valores["temperatura"],
        vibracao=valores["vibracao"],
        corrente=valores["corrente"],
        rpm=valores["rpm"],
        ts=datetime.now(),
    )
    return passo < total


def restaurar(tag: str, minutos: int = 30) -> int:
    """Apaga as leituras injetadas e devolve o ativo à baseline.

    Remove tudo que foi gravado na janela recente e escreve leituras normais no
    lugar, para a demonstração poder ser repetida do zero.
    """
    corte = datetime.now() - timedelta(minutes=minutos)
    with conexao() as con:
        cur = con.execute("DELETE FROM leituras WHERE tag = ? AND ts >= ?", (tag.upper(), corte))
        removidas = cur.rowcount

    base = _baseline(tag)
    rng = np.random.default_rng(7)
    for i in range(minutos):
        valores = {}
        for g in GRANDEZAS:
            if base.get(g) is None:
                valores[g] = None
                continue
            valores[g] = round(float(base[g] + rng.normal(0, abs(base[g]) * 0.01 + 0.01)), 3)
        inserir_leitura(
            tag,
            temperatura=valores["temperatura"],
            vibracao=valores["vibracao"],
            corrente=valores["corrente"],
            rpm=valores["rpm"],
            ts=corte + timedelta(minutes=i),
        )
    return removidas
