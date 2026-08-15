from datetime import datetime, timedelta
from typing import Literal
import pandas as pd
from app.services.db import conexao

Status = Literal["ok", "warn", "crit"]
GRANDEZAS = ["temperatura", "vibracao", "corrente", "rpm"]

JANELAS = {
    "1h":  {"delta": timedelta(hours=1),  "resample": None},
    # janela do detector de anomalia: sem reamostragem, para preservar a grade
    # nativa em que o modelo foi calibrado
    "3h":  {"delta": timedelta(hours=3),  "resample": None},
    "24h": {"delta": timedelta(hours=24), "resample": "5min"},
    "7d":  {"delta": timedelta(days=7),   "resample": "1h"},
}


def get_limites() -> dict[str, dict]:
    with conexao() as con:
        rows = con.execute("SELECT * FROM limites").fetchall()
    return {
        r["grandeza"]: {
            "warn_min": r["warn_min"], "warn_max": r["warn_max"],
            "crit_min": r["crit_min"], "crit_max": r["crit_max"],
            "unidade":  r["unidade"],  "fundo_escala": r["fundo_escala"],
        }
        for r in rows
    }


def classificar(valor: float | None, grandeza: str, limites: dict | None = None) -> Status:
    if valor is None:
        return "ok"
    lim = (limites or get_limites()).get(grandeza)
    if not lim:
        return "ok"
    if valor < lim["crit_min"] or valor > lim["crit_max"]:
        return "crit"
    if valor < lim["warn_min"] or valor > lim["warn_max"]:
        return "warn"
    return "ok"


def _pior(statuses: list[Status]) -> Status:
    if "crit" in statuses:
        return "crit"
    if "warn" in statuses:
        return "warn"
    return "ok"


def ultima_leitura(tag: str) -> dict | None:
    with conexao() as con:
        row = con.execute(
            "SELECT ts, temperatura, vibracao, corrente, rpm FROM leituras "
            "WHERE tag = ? ORDER BY ts DESC LIMIT 1",
            (tag.upper(),),
        ).fetchone()
    if not row:
        return None
    return {
        "ts": row["ts"],
        "temperatura": row["temperatura"],
        "vibracao":    row["vibracao"],
        "corrente":    row["corrente"],
        "rpm":         row["rpm"],
    }


def status_atual(tag: str, limites: dict | None = None) -> Status:
    leitura = ultima_leitura(tag)
    if not leitura:
        return "ok"
    lim = limites or get_limites()
    return _pior([classificar(leitura[g], g, lim) for g in GRANDEZAS])


def status_por_grandeza(tag: str, limites: dict | None = None) -> dict[str, Status]:
    leitura = ultima_leitura(tag)
    if not leitura:
        return {g: "ok" for g in GRANDEZAS}
    lim = limites or get_limites()
    return {g: classificar(leitura[g], g, lim) for g in GRANDEZAS}


def get_historico(tag: str, janela: str = "24h") -> pd.DataFrame:
    cfg = JANELAS.get(janela, JANELAS["24h"])
    ts_min = datetime.now() - cfg["delta"]
    with conexao() as con:
        df = pd.read_sql_query(
            "SELECT ts, temperatura, vibracao, corrente, rpm FROM leituras "
            "WHERE tag = ? AND ts >= ? ORDER BY ts",
            con,
            params=(tag.upper(), ts_min),
            parse_dates=["ts"],
        )
    if df.empty:
        return df
    if cfg["resample"]:
        df = df.set_index("ts").resample(cfg["resample"]).mean().dropna(how="all").reset_index()
    return df


def alertas_recentes(tag: str, janela: str = "24h", limites: dict | None = None) -> pd.DataFrame:
    df = get_historico(tag, janela)
    if df.empty:
        return df
    lim = limites or get_limites()
    registros = []
    for _, row in df.iterrows():
        for g in GRANDEZAS:
            val = row.get(g)
            if pd.isna(val):
                continue
            st = classificar(val, g, lim)
            if st in ("warn", "crit"):
                registros.append({
                    "Timestamp": row["ts"],
                    "Grandeza": g.capitalize(),
                    "Valor": round(float(val), 2),
                    "Unidade": lim[g]["unidade"],
                    "Severidade": "Crítico" if st == "crit" else "Atenção",
                })
    out = pd.DataFrame(registros)
    if not out.empty:
        out = out.sort_values("Timestamp", ascending=False).reset_index(drop=True)
    return out


def inserir_leitura(tag: str, temperatura: float, vibracao: float, corrente: float, rpm: float, ts: datetime | None = None):
    ts = ts or datetime.now()
    with conexao() as con:
        con.execute(
            "INSERT INTO leituras (tag, ts, temperatura, vibracao, corrente, rpm) VALUES (?,?,?,?,?,?)",
            (tag.upper(), ts, temperatura, vibracao, corrente, rpm),
        )
