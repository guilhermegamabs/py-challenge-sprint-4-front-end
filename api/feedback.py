"""Persistência do feedback do operador sobre os resumos gerados por IA."""

from datetime import datetime

from app.services.db import conexao

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback_resumo (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_id  INTEGER NOT NULL REFERENCES eventos(id) ON DELETE CASCADE,
    util       INTEGER NOT NULL,
    comentario TEXT,
    trace_id   TEXT,
    ts         TIMESTAMP NOT NULL
);
"""


def criar_tabela():
    with conexao() as con:
        con.executescript(SCHEMA)


def evento_existe(evento_id: int) -> bool:
    with conexao() as con:
        return con.execute("SELECT 1 FROM eventos WHERE id = ?", (evento_id,)).fetchone() is not None


def registrar(evento_id: int, util: bool, comentario: str | None, trace_id: str):
    with conexao() as con:
        con.execute(
            "INSERT INTO feedback_resumo (evento_id, util, comentario, trace_id, ts) VALUES (?,?,?,?,?)",
            (evento_id, int(util), comentario, trace_id, datetime.now()),
        )


def agregado() -> list[dict]:
    with conexao() as con:
        linhas = con.execute(
            """SELECT COALESCE(e.origem_resumo, 'template') AS origem_resumo,
                      COUNT(*) AS avaliacoes,
                      SUM(f.util) AS uteis
               FROM feedback_resumo f JOIN eventos e ON e.id = f.evento_id
               GROUP BY 1"""
        ).fetchall()
    return [
        {**dict(l), "taxa_aprovacao": round(l["uteis"] / l["avaliacoes"], 3)}
        for l in linhas
    ]
