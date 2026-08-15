"""Ingestão da camada Silver do Data Lake para o SQLite operacional.

O arquivo Parquet é a saída real do pipeline (IO-Link Master -> Bronze -> Silver)
do motor de bancada MOTOR-220V-01, na mesma forma que alimenta a LSTM do notebook
`modelo_lstm_forecaster.ipynb`: 1 linha por porta por passo de grade de 1 s.

Mapeamento de grandezas (o sensor IO-Link é de vibração, não de acionamento):

    velocidade  (mm/s)  -> leituras.vibracao     faixa 0,04 a 7,73 mm/s (ISO 10816)
    aceleracao  (g)     -> leituras.aceleracao
    temperatura (°C)    -> leituras.temperatura

Corrente e RPM ficam NULL: não existe sensor para elas neste ativo.
"""

import glob
import os

import pandas as pd

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

TAG_REAL    = "MOTOR-220V-01"
PLANTA_REAL = "Planta Forzy - Campo"
AREA_REAL   = "Bancada IO-Link"

MODELO_REAL     = "IO-Link 220V"
FABRICANTE_REAL = "Forzy"
POTENCIA_REAL   = 2200
TENSAO_REAL     = 220

LIMIAR_OFF = 0.1     # mesmo limiar do notebook: separa motor parado de rodando
FREQ_ALVO  = "1min"  # a grade nativa é de 1 s; o app trabalha em minutos


def _localizar_parquet() -> list[str]:
    """Arquivos da Silver na raiz do projeto ou em silver/ (particionado)."""
    return sorted(
        glob.glob(os.path.join(RAIZ, "part-*.parquet"))
        + glob.glob(os.path.join(RAIZ, "silver", "**", "*.parquet"), recursive=True)
    )


def carregar_silver() -> pd.DataFrame | None:
    arquivos = _localizar_parquet()
    if not arquivos:
        return None
    df = pd.concat([pd.read_parquet(a) for a in arquivos], ignore_index=True)
    return df if not df.empty else None


def _preparar(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra operação, agrega as portas e reamostra para a grade do app.

    Os timestamps da amostra são de uma coleta passada. Como o painel opera em
    janelas relativas ao agora (1h / 24h / 7d), a série é transladada para
    terminar no instante atual, preservando o espaçamento original.
    """
    df = df[(df["estado"] == "ON") & (df["velocidade"] > LIMIAR_OFF)].copy()
    if df.empty:
        return df

    df["event_time"] = pd.to_datetime(df["event_time"])
    deslocamento = pd.Timestamp.now().floor("min") - df["event_time"].max()
    df["event_time"] = df["event_time"] + deslocamento

    colunas = ["velocidade", "aceleracao", "temperatura"]
    agregado = (
        df.set_index("event_time")[colunas]   # as duas portas do mesmo motor
        .resample(FREQ_ALVO)
        .mean()
        .dropna(how="all")
        .reset_index()
    )
    return agregado


def ingerir_silver(con) -> int:
    """Cria o ativo real e grava suas leituras. Devolve o nº de leituras inseridas.

    Idempotente: não faz nada se o ativo já existe. Nunca levanta exceção — a
    ausência do Parquet apenas deixa o app sem o ativo de campo.
    """
    ja_existe = con.execute(
        "SELECT COUNT(*) AS n FROM equipamentos WHERE tag = ?", (TAG_REAL,)
    ).fetchone()["n"]
    if ja_existe:
        return 0

    try:
        bruto = carregar_silver()
        if bruto is None:
            return 0
        dados = _preparar(bruto)
        if dados.empty:
            return 0
    except Exception as erro:                      # parquet corrompido, pyarrow ausente...
        print(f"[silver] ingestao ignorada: {erro}")
        return 0

    con.execute("INSERT OR IGNORE INTO plantas (nome) VALUES (?)", (PLANTA_REAL,))
    planta_id = con.execute(
        "SELECT id FROM plantas WHERE nome = ?", (PLANTA_REAL,)
    ).fetchone()["id"]

    con.execute(
        "INSERT OR IGNORE INTO areas (planta_id, nome) VALUES (?, ?)",
        (planta_id, AREA_REAL),
    )
    area_id = con.execute(
        "SELECT id FROM areas WHERE planta_id = ? AND nome = ?",
        (planta_id, AREA_REAL),
    ).fetchone()["id"]

    con.execute(
        """INSERT INTO equipamentos
           (tag, modelo, fabricante, potencia_w, tensao_v, area_id)
           VALUES (?,?,?,?,?,?)""",
        (TAG_REAL, MODELO_REAL, FABRICANTE_REAL, POTENCIA_REAL, TENSAO_REAL, area_id),
    )

    linhas = [
        (
            TAG_REAL,
            r.event_time.to_pydatetime(),
            round(float(r.temperatura), 2),
            round(float(r.velocidade), 3),
            round(float(r.aceleracao), 4),
        )
        for r in dados.itertuples()
    ]
    con.executemany(
        """INSERT INTO leituras (tag, ts, temperatura, vibracao, aceleracao, corrente, rpm)
           VALUES (?,?,?,?,?,NULL,NULL)""",
        linhas,
    )
    return len(linhas)
