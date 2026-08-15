import os
import sqlite3
from contextlib import contextmanager
import numpy as np
import pandas as pd

DB_DIR  = os.path.join(os.path.dirname(__file__), "..", "..", "data")
DB_PATH = os.path.abspath(os.path.join(DB_DIR, "forzy.db"))
PLACAS_DIR = os.path.abspath(os.path.join(DB_DIR, "placas"))


@contextmanager
def conexao():
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(PLACAS_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS plantas (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS areas (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    planta_id INTEGER NOT NULL REFERENCES plantas(id),
    nome      TEXT NOT NULL,
    UNIQUE (planta_id, nome)
);

CREATE TABLE IF NOT EXISTS equipamentos (
    tag             TEXT PRIMARY KEY,
    modelo          TEXT NOT NULL,
    fabricante      TEXT NOT NULL,
    potencia_w      INTEGER NOT NULL,
    tensao_v        INTEGER NOT NULL,
    area_id         INTEGER REFERENCES areas(id),
    img_placa_path  TEXT
);

CREATE TABLE IF NOT EXISTS leituras (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tag          TEXT NOT NULL REFERENCES equipamentos(tag) ON DELETE CASCADE,
    ts           TIMESTAMP NOT NULL,
    temperatura  REAL,
    vibracao     REAL,
    corrente     REAL,
    rpm          REAL,
    aceleracao   REAL
);

CREATE INDEX IF NOT EXISTS idx_leituras_tag_ts ON leituras(tag, ts);

CREATE TABLE IF NOT EXISTS limites (
    grandeza TEXT PRIMARY KEY,
    warn_min REAL, warn_max REAL,
    crit_min REAL, crit_max REAL,
    unidade  TEXT,
    fundo_escala REAL
);

CREATE TABLE IF NOT EXISTS eventos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tag           TEXT NOT NULL REFERENCES equipamentos(tag) ON DELETE CASCADE,
    ts            TIMESTAMP NOT NULL,
    origem        TEXT NOT NULL,       -- 'limite' | 'ml'
    severidade    TEXT NOT NULL,       -- ok | warn | crit
    grandeza      TEXT,
    valor         REAL,
    unidade       TEXT,
    score         REAL,
    threshold     REAL,
    detectores    TEXT,                -- JSON
    pista         TEXT,
    titulo        TEXT,
    resumo        TEXT,                -- texto gerado pela camada de NLP
    recomendacoes TEXT,                -- JSON (lista de acoes)
    origem_resumo TEXT,                -- 'gemini' | 'template'
    assinatura    TEXT,                -- chave de deduplicacao
    reconhecido   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_eventos_ts ON eventos(ts DESC);
CREATE INDEX IF NOT EXISTS idx_eventos_assinatura ON eventos(assinatura, ts DESC);
"""


PLANTAS_SEED = [
    ("Planta Sao Paulo", ["Linha de Producao A", "Linha de Producao B"]),
    ("Planta Campinas",  ["Compressores", "Bombas Hidraulicas"]),
    ("Planta Sorocaba",  ["Ventilacao", "Esteira Principal"]),
]

EQUIPAMENTOS_SEED = [
    ("EQ-001", "XR-200",        "Siemens",   1500, 220, 0, 0),
    ("EQ-002", "Alpha-50",      "WEG",        750, 380, 0, 0),
    ("EQ-003", "TurboMax",      "ABB",       3000, 220, 0, 1),
    ("EQ-004", "ProLine-1",     "Schneider", 2200, 127, 1, 0),
    ("EQ-005", "XR-200",        "Siemens",   1500, 220, 1, 0),
    ("EQ-006", "Compact-R",     "WEG",        550, 380, 1, 1),
    ("EQ-007", "Delta-V",       "ABB",       4000, 440, 2, 0),
    ("EQ-008", "ProLine-2",     "Schneider", 1800, 220, 2, 1),
    ("EQ-009", "W22-100L-2P",   "WEG",       2200, 220, 0, 0),
]

PERFIS_REAIS = {
    "EQ-009": {"t_base": 38.0, "v_base": 2.1, "c_base": 12.3, "r_base": 3520.0, "ruido_t": 0.8, "ruido_v": 0.25, "ruido_c": 0.6, "ruido_r": 40.0},
}

LIMITES_SEED = [
    ("temperatura",   20.0,     75.0,     10.0,     85.0,     "°C",  120.0),
    ("vibracao",      0.0,      4.5,      0.0,      7.1,      "mm/s", 12.0),
    ("corrente",      2.0,      40.0,     1.0,      48.0,     "A",    50.0),
    ("rpm",           1700.0,   3600.0,   1500.0,   3700.0,   "RPM",  3800.0),
]


def _seed_historico(con, tag: str, dias: int = 7, freq_min: int = 1):
    rng = np.random.default_rng(seed=abs(hash(tag)) % (2**32))
    n = (dias * 24 * 60) // freq_min
    ts_end   = pd.Timestamp.now().floor("min")
    ts_start = ts_end - pd.Timedelta(minutes=n * freq_min)
    timestamps = pd.date_range(start=ts_start, periods=n, freq=f"{freq_min}min")

    perfil = PERFIS_REAIS.get(tag)
    if perfil:
        t_base, v_base, c_base, r_base = perfil["t_base"], perfil["v_base"], perfil["c_base"], perfil["r_base"]
        sigma_t, sigma_v, sigma_c, sigma_r = perfil["ruido_t"], perfil["ruido_v"], perfil["ruido_c"], perfil["ruido_r"]
    else:
        t_base = rng.uniform(45, 65)
        v_base = rng.uniform(1.5, 3.5)
        c_base = rng.uniform(10, 30)
        r_base = rng.uniform(2400, 3200)
        sigma_t, sigma_v, sigma_c, sigma_r = 1.5, 0.4, 1.2, 80.0

    drift = 0.0
    if tag in ("EQ-003", "EQ-007"):
        drift = 1.0
    elif tag in ("EQ-005", "EQ-006"):
        drift = 0.5

    ramp = np.linspace(0, drift, n)

    temperatura = t_base + rng.normal(0, sigma_t, n) + ramp * 35
    vibracao    = np.clip(v_base + rng.normal(0, sigma_v, n) + ramp * 4.5,  0, None)
    corrente    = np.clip(c_base + rng.normal(0, sigma_c, n) + ramp * 18,   0, None)
    rpm         = r_base + rng.normal(0, sigma_r, n) + ramp * 200

    rows = list(zip(
        [tag] * n,
        [t.to_pydatetime() for t in timestamps],
        temperatura.round(2).tolist(),
        vibracao.round(3).tolist(),
        corrente.round(2).tolist(),
        rpm.round(1).tolist(),
    ))
    con.executemany(
        "INSERT INTO leituras (tag, ts, temperatura, vibracao, corrente, rpm) VALUES (?,?,?,?,?,?)",
        rows,
    )


def _migrar(con):
    """Aplica ao banco existente as colunas criadas depois dele.

    CREATE TABLE IF NOT EXISTS nao altera tabela ja criada, entao um forzy.db da
    Sprint 2 fica sem `leituras.aceleracao` e quebra a ingestao da Silver.
    """
    colunas = {r["name"] for r in con.execute("PRAGMA table_info(leituras)").fetchall()}
    if "aceleracao" not in colunas:
        con.execute("ALTER TABLE leituras ADD COLUMN aceleracao REAL")


def init_db():
    from app.services.ingestao_silver import ingerir_silver

    with conexao() as con:
        con.executescript(SCHEMA)
        _migrar(con)

        con.executemany(
            "INSERT OR REPLACE INTO limites VALUES (?,?,?,?,?,?,?)",
            LIMITES_SEED,
        )

        for planta_nome, areas in PLANTAS_SEED:
            con.execute("INSERT OR IGNORE INTO plantas (nome) VALUES (?)", (planta_nome,))
            planta_id = con.execute("SELECT id FROM plantas WHERE nome = ?", (planta_nome,)).fetchone()["id"]
            for area_nome in areas:
                con.execute(
                    "INSERT OR IGNORE INTO areas (planta_id, nome) VALUES (?, ?)",
                    (planta_id, area_nome),
                )

        ja_tem_eq = con.execute("SELECT COUNT(*) AS n FROM equipamentos").fetchone()["n"]
        if ja_tem_eq == 0:
            for tag, modelo, fab, pot, tensao, p_idx, a_idx in EQUIPAMENTOS_SEED:
                planta_nome = PLANTAS_SEED[p_idx][0]
                area_nome   = PLANTAS_SEED[p_idx][1][a_idx]
                area_id = con.execute(
                    """SELECT a.id FROM areas a
                       JOIN plantas p ON p.id = a.planta_id
                       WHERE p.nome = ? AND a.nome = ?""",
                    (planta_nome, area_nome),
                ).fetchone()["id"]
                con.execute(
                    """INSERT INTO equipamentos
                       (tag, modelo, fabricante, potencia_w, tensao_v, area_id)
                       VALUES (?,?,?,?,?,?)""",
                    (tag, modelo, fab, pot, tensao, area_id),
                )

        tem_leituras = con.execute("SELECT COUNT(*) AS n FROM leituras").fetchone()["n"]
        if tem_leituras == 0:
            for tag, *_ in EQUIPAMENTOS_SEED:
                _seed_historico(con, tag)

        # ativo de campo: dado real vindo da camada Silver do Data Lake
        ingerir_silver(con)
