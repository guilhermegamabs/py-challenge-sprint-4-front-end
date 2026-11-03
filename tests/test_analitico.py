"""Testes da camada analítica: cada modo de falha precisa ser pego pelo detector certo.

O histórico vem de uma série sintética injetada no lugar de `get_historico`, então
os testes não dependem do SQLite nem do seed.
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.services import analitico

N = 240
BASE = {"temperatura": 40.0, "vibracao": 2.0, "corrente": 12.0, "rpm": 3500.0}
RUIDO = {"temperatura": 0.5, "vibracao": 0.1, "corrente": 0.3, "rpm": 5.0}


def _serie(seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    inicio = datetime(2026, 11, 1, 8, 0)
    df = pd.DataFrame({"ts": [inicio + timedelta(minutes=i) for i in range(N)]})
    for g, media in BASE.items():
        df[g] = media + rng.normal(0, RUIDO[g], N)
    return df


def _avaliar(monkeypatch, df: pd.DataFrame) -> analitico.Diagnostico:
    monkeypatch.setattr(analitico, "get_historico", lambda tag, janela: df)
    monkeypatch.setattr(analitico, "_carregar_metadados", lambda: {})
    diag = analitico.avaliar("EQ-TESTE", "3h")
    assert diag is not None
    return diag


def test_operacao_normal_nao_dispara(monkeypatch):
    diag = _avaliar(monkeypatch, _serie())
    assert not diag.alarme
    assert diag.severidade == "ok"
    assert diag.pista is None


def test_spike_de_vibracao_dispara_residuo(monkeypatch):
    df = _serie()
    df.loc[N - 4 :, "vibracao"] = BASE["vibracao"] + 3.0
    diag = _avaliar(monkeypatch, df)
    assert diag.detectores["residuo"]
    assert diag.feature_dominante == "vibracao"
    assert "mecânico" in diag.pista


def test_deriva_termica_lenta_dispara_cusum(monkeypatch):
    df = _serie()
    inicio = int(N * 0.75)
    df.loc[inicio:, "temperatura"] += np.linspace(0, 4.0, N - inicio)
    diag = _avaliar(monkeypatch, df)
    assert diag.detectores["cusum"]
    assert diag.alarme


def test_sensor_congelado_dispara_variancia(monkeypatch):
    df = _serie()
    for g in BASE:
        df.loc[N - 30 :, g] = df.loc[N - 31, g]
    diag = _avaliar(monkeypatch, df)
    assert diag.detectores["variancia"]
    assert diag.pista == analitico.PISTA_INSTRUMENTACAO


def test_sem_historico_devolve_none(monkeypatch):
    monkeypatch.setattr(analitico, "get_historico", lambda tag, janela: pd.DataFrame())
    assert analitico.avaliar("EQ-VAZIO") is None


@pytest.mark.parametrize(
    "ativos, score, esperado",
    [([], 10.0, "ok"), (["cusum"], 1.0, "warn"), (["cusum", "residuo"], 1.0, "crit"),
     (["residuo"], 2.0, "crit")],
)
def test_severidade(ativos, score, esperado):
    assert analitico._severidade(score, 1.0, ativos) == esperado


def test_cusum_acumula_vies_e_ignora_ruido():
    rng = np.random.default_rng(0)
    ruido = rng.normal(0, 1, (200, 1)) * 0.1
    vies = ruido + 0.5
    assert analitico.cusum(ruido, k=0.15).max() < 1.0
    assert analitico.cusum(vies, k=0.15)[-1] > 50.0
