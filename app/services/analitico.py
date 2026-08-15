"""Camada analítica — detecção de anomalia por desvio do comportamento esperado.

Porta para o app a arquitetura de detecção do notebook `modelo_lstm_forecaster.ipynb`.
O dado de sensor não tem rótulo de falha, então não há classificação supervisionada:
o que existe é um modelo que **prevê o próximo instante** e um alarme sobre o resíduo.

Três detectores complementares, exatamente como no notebook:

    resíduo    erro de previsão instantâneo  -> mudança brusca (spike, travamento)
    CUSUM      soma acumulada do erro com sinal -> deriva lenta (rolamento degradando)
    variância  desvio da janela de entrada ~ 0  -> sensor congelado / link caído

O alarme final é a união dos três. Nenhum sozinho cobre os quatro modos de falha.

Este módulo não importa Streamlit: é consumido pelo pipeline da página, nunca o
contrário. Trocar o preditor não muda nada acima dele.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import numpy as np
import pandas as pd

from app.services.telemetria import GRANDEZAS, Status, get_historico

Detector = Literal["residuo", "cusum", "variancia"]

ARTEFATOS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "artefatos")
)

CFG = {
    "janela":         20,     # passos de contexto do preditor
    "horizonte":      1,      # previsão 1-step
    "percentil_thr":  99.0,   # threshold do resíduo = p99 da baseline
    "fracao_baseline": 0.6,   # primeira fatia da série usada como operação normal
    "k_cusum":        0.15,   # folga do CUSUM, em desvios-padrão
    "thr_cusum":      6.0,    # piso absoluto do CUSUM
    "fator_cusum":    1.7,    # ... e múltiplo do CUSUM observado na baseline
    "margem_residuo": 1.25,   # folga sobre o p99 antes de considerar desvio
    "min_janelas_residuo": 2, # quantas das janelas recentes precisam estourar
    "thr_variancia":  0.02,   # desvio da janela abaixo disso = sinal travado
    "alpha_ewma":     0.35,
    "janelas_recentes": 3,    # quantos passos finais definem o estado atual
    "folga_amostras": 15,     # margem acima da janela para a série ser utilizável
}

# Resolução vence span: "3h" é a única janela sem reamostragem com histórico
# suficiente, e um evento de 20 min desaparece dentro dos baldes de 1 h da janela
# de 7 dias. Ativos com pouca coleta caem para a próxima da lista.
JANELAS_CANDIDATAS = ["3h", "24h", "7d", "1h"]

# Grandeza dominante -> família de causa provável (célula 33 do notebook)
PISTA = {
    "temperatura": "térmico (rolamento, ventilação obstruída, sobrecarga, ambiente)",
    "vibracao":    "mecânico (desbalanceamento, folga, desalinhamento, rolamento)",
    "corrente":    "carga / acionamento (sobrecarga, perda de fase, inversor)",
    "rpm":         "acionamento (perda de carga, travamento, falha do inversor)",
    "aceleracao":  "mecânico de alta frequência (rolamento, engrenamento)",
}
PISTA_INSTRUMENTACAO = "instrumentação (sensor travado ou link IO-Link caído)"

ROTULO_DETECTOR = {
    "residuo":   "desvio brusco do previsto",
    "cusum":     "deriva sustentada",
    "variancia": "sinal congelado",
}


@dataclass
class Diagnostico:
    """Contrato de saída da camada analítica — espelha `inferir()` do notebook."""

    tag: str
    ts: datetime
    score: float                        # média |real - previsto|, em desvios-padrão
    threshold: float
    alarme: bool
    severidade: Status                  # ok | warn | crit
    feature_dominante: str
    pista: str | None
    detectores: dict[str, bool] = field(default_factory=dict)
    residuo_por_feature: dict[str, float] = field(default_factory=dict)
    features_avaliadas: list[str] = field(default_factory=list)
    n_amostras: int = 0

    @property
    def detectores_ativos(self) -> list[str]:
        return [d for d, ativo in self.detectores.items() if ativo]

    @property
    def assinatura(self) -> str:
        return f"ml|{self.tag}|{self.feature_dominante}|{self.severidade}"


def _carregar_metadados() -> dict:
    """Thresholds calibrados exportados pelo notebook, se estiverem disponíveis."""
    caminho = os.path.join(ARTEFATOS_DIR, "metadados.json")
    if not os.path.exists(caminho):
        return {}
    try:
        with open(caminho, encoding="utf-8") as arq:
            return json.load(arq)
    except (OSError, json.JSONDecodeError):
        return {}


def _cfg_efetiva() -> dict:
    cfg = dict(CFG)
    meta = _carregar_metadados()
    for chave_meta, chave_cfg in (
        ("janela", "janela"),
        ("threshold_cusum", "thr_cusum"),
        ("threshold_variancia", "thr_variancia"),
        ("percentil_threshold", "percentil_thr"),
    ):
        if chave_meta in meta:
            cfg[chave_cfg] = meta[chave_meta]
    return cfg


# --------------------------------------------------------------------------- preditor


def _prever(X: np.ndarray, alpha: float) -> np.ndarray:
    """Previsão 1-step para cada janela. X: (n, janela, F) -> (n, F).

    PONTO ÚNICO DE TROCA PELO MODELO TREINADO. A LSTM do notebook entra aqui:
    carregar `artefatos/modelo_lstm.pt` + `scalers.pkl` e devolver `modelo(X)`.
    Tudo acima desta função — score, CUSUM, variância, severidade, contrato —
    permanece igual.

    Enquanto o artefato não é publicado, o baseline é uma média exponencial da
    janela: previsor ingênuo, sem dependência de torch, suficiente para que o
    resíduo carregue o sinal de desvio.
    """
    n, janela, _ = X.shape
    pesos = alpha * (1.0 - alpha) ** np.arange(janela)[::-1]
    pesos /= pesos.sum()
    return np.einsum("njf,j->nf", X, pesos)


# --------------------------------------------------------------------------- detectores


def cusum(residuo_sinal: np.ndarray, k: float) -> np.ndarray:
    """Soma acumulada bilateral por feature; devolve a estatística máxima por passo.

    S+ acumula desvio persistente para cima, S- para baixo. Ruído sem viés mantém
    ambos perto de zero; viés sustentado faz um deles crescer sem limite.
    """
    n, f = residuo_sinal.shape
    s_pos = np.zeros(f)
    s_neg = np.zeros(f)
    stat = np.zeros(n)
    for t in range(n):
        s_pos = np.maximum(0.0, s_pos + residuo_sinal[t] - k)
        s_neg = np.maximum(0.0, s_neg - residuo_sinal[t] - k)
        stat[t] = max(s_pos.max(), s_neg.max())
    return stat


def variancia_janela(X: np.ndarray) -> np.ndarray:
    """MAIOR desvio-padrão entre as features dentro de cada janela de entrada.

    Tem que ser o maior, não o menor: a temperatura é quantizada e fica
    legitimamente constante por vários passos em operação normal. Sensor
    congelado trava TODAS as grandezas, então é o maior desvio que vai a zero.
    """
    return X.std(axis=1).max(axis=1)


def _janelar(z: np.ndarray, janela: int, horizonte: int):
    """(T, F) -> X (n, janela, F), y (n, F), idx (n,) com o índice do alvo."""
    n = len(z) - janela - horizonte + 1
    if n <= 0:
        return None, None, None
    X = np.stack([z[i : i + janela] for i in range(n)])
    y = np.stack([z[i + janela + horizonte - 1] for i in range(n)])
    idx = np.arange(janela + horizonte - 1, janela + horizonte - 1 + n)
    return X, y, idx


# --------------------------------------------------------------------------- avaliação


def _features_utilizaveis(df: pd.DataFrame, minimo: int) -> list[str]:
    """Descarta grandezas sem sensor (coluna toda nula) ou com pouca amostra."""
    return [g for g in GRANDEZAS if g in df.columns and df[g].notna().sum() >= minimo]


def _severidade(score: float, threshold: float, ativos: list[str]) -> Status:
    if not ativos:
        return "ok"
    if len(ativos) >= 2 or score > 1.5 * threshold:
        return "crit"
    return "warn"


def _carregar_serie(tag: str, cfg: dict, janela_tempo: str | None):
    """Escolhe a maior janela temporal com amostra suficiente para o detector."""
    minimo = cfg["janela"] + cfg["horizonte"] + cfg["folga_amostras"]
    candidatas = [janela_tempo] if janela_tempo else JANELAS_CANDIDATAS

    for nome in candidatas:
        df = get_historico(tag, nome)
        if df.empty:
            continue
        features = _features_utilizaveis(df, minimo)
        if features and len(df) >= minimo:
            return df, features
    return None, None


def avaliar(tag: str, janela_tempo: str | None = None) -> Diagnostico | None:
    """Roda os três detectores sobre o histórico do ativo.

    Devolve None quando não há amostra suficiente para formar uma janela — não é
    erro, é ausência de dado.
    """
    cfg = _cfg_efetiva()
    df, features = _carregar_serie(tag, cfg, janela_tempo)
    if df is None:
        return None

    serie = df[features].interpolate().bfill().ffill()
    bruto = serie.to_numpy(dtype=float)
    if len(bruto) < cfg["janela"] + cfg["horizonte"] + 10:
        return None

    # normalização contra a própria baseline do ativo: a fatia inicial da janela
    # é tomada como operação normal, como o scaler do notebook é ajustado só no treino.
    corte = max(cfg["janela"] + 5, int(len(bruto) * cfg["fracao_baseline"]))
    corte = min(corte, len(bruto) - 1)
    media = bruto[:corte].mean(axis=0)
    desvio = bruto[:corte].std(axis=0)
    desvio[desvio < 1e-6] = 1e-6
    z = (bruto - media) / desvio

    X, y, idx = _janelar(z, cfg["janela"], cfg["horizonte"])
    if X is None:
        return None

    residuo_sinal = _prever(X, cfg["alpha_ewma"]) - y
    residuo = np.abs(residuo_sinal)
    score = residuo.mean(axis=1)

    n_base = max(1, int((idx < corte).sum()))
    threshold = float(np.percentile(score[:n_base], cfg["percentil_thr"]))
    threshold = max(threshold, 1e-3)

    stat_cusum = cusum(residuo_sinal, cfg["k_cusum"])
    var_janela = variancia_janela(X)

    # O limiar do CUSUM também sai da baseline do próprio ativo: uma constante
    # global não transfere entre ativos com amostragem e ruído diferentes.
    thr_cusum = max(
        cfg["thr_cusum"],
        cfg["fator_cusum"] * float(np.percentile(stat_cusum[:n_base], 99)),
    )

    recentes = slice(-min(cfg["janelas_recentes"], len(score)), None)
    # Uma única janela acima do p99 é o falso positivo esperado por construção;
    # exigir a maioria das janelas recentes é o que separa desvio de ruído.
    estouros = int((score[recentes] > threshold * cfg["margem_residuo"]).sum())

    detectores = {
        "residuo":   estouros >= cfg["min_janelas_residuo"],
        "cusum":     bool((stat_cusum[recentes] > thr_cusum).any()),
        "variancia": bool((var_janela[recentes] < cfg["thr_variancia"]).any()),
    }
    ativos = [d for d, on in detectores.items() if on]

    residuo_atual = residuo[-1]
    dominante = features[int(np.argmax(residuo_atual))]
    score_atual = float(score[recentes].max())
    severidade = _severidade(score_atual, threshold, ativos)

    if detectores["variancia"]:
        pista = PISTA_INSTRUMENTACAO
    elif ativos:
        pista = PISTA.get(dominante)
    else:
        pista = None

    ts_final = df["ts"].iloc[-1]

    return Diagnostico(
        tag=tag,
        ts=ts_final.to_pydatetime() if hasattr(ts_final, "to_pydatetime") else ts_final,
        score=round(score_atual, 4),
        threshold=round(threshold, 4),
        alarme=bool(ativos),
        severidade=severidade,
        feature_dominante=dominante,
        pista=pista,
        detectores=detectores,
        residuo_por_feature={
            f: round(float(r), 4) for f, r in zip(features, residuo_atual)
        },
        features_avaliadas=features,
        n_amostras=int(len(bruto)),
    )


def avaliar_frota(tags: list[str], janela_tempo: str = "24h") -> list[Diagnostico]:
    diagnosticos = []
    for tag in tags:
        diag = avaliar(tag, janela_tempo)
        if diag is not None:
            diagnosticos.append(diag)
    return diagnosticos
