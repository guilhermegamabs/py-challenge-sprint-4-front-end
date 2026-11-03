"""Contrato do protótipo da API: autenticação, trace_id e erros amigáveis.

Roda contra um SQLite temporário, nunca contra data/forzy.db.
"""

import pytest
from fastapi.testclient import TestClient

from app.services import db

CHAVE = "chave-de-teste"


@pytest.fixture(scope="module")
def cliente(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("dados")
    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_DIR", str(pasta))
    mp.setattr(db, "DB_PATH", str(pasta / "forzy.db"))
    mp.setattr(db, "PLACAS_DIR", str(pasta / "placas"))
    mp.setenv("FORZY_API_KEY", CHAVE)

    from api.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        c.headers["X-API-Key"] = CHAVE
        yield c
    mp.undo()


def test_health_e_publico(cliente):
    r = cliente.get("/health", headers={"X-API-Key": ""})
    assert r.status_code == 200


def test_sem_chave_recebe_401_amigavel(cliente):
    r = cliente.get("/ativos", headers={"X-API-Key": "errada"})
    assert r.status_code == 401
    corpo = r.json()
    assert corpo["erro"] == "nao_autorizado"
    assert corpo["trace_id"] == r.headers["X-Trace-Id"]


def test_trace_id_do_cliente_e_propagado(cliente):
    r = cliente.get("/ativos", headers={"X-Trace-Id": "abc123"})
    assert r.status_code == 200
    assert r.headers["X-Trace-Id"] == "abc123"
    assert any(a["tag"] == "EQ-001" for a in r.json())


def test_ativo_inexistente_404_em_portugues(cliente):
    r = cliente.get("/ativos/NAO-EXISTE")
    assert r.status_code == 404
    assert "não encontrado" in r.json()["mensagem"]


def test_detalhe_e_telemetria(cliente):
    detalhe = cliente.get("/ativos/eq-001").json()
    assert detalhe["tag"] == "EQ-001"
    assert set(detalhe["status_por_grandeza"]) >= {"temperatura", "vibracao"}

    tele = cliente.get("/ativos/EQ-001/telemetria", params={"janela": "1h"}).json()
    assert tele["leituras"]


def test_validacao_vira_mensagem_legivel(cliente):
    r = cliente.get("/eventos", params={"horas": 0})
    assert r.status_code == 422
    assert r.json()["erro"] == "dados_invalidos"
    assert "horas" in r.json()["mensagem"]


def test_feedback_de_resumo(cliente):
    with db.conexao() as con:
        evento_id = con.execute(
            """INSERT INTO eventos (tag, ts, severidade, origem, titulo, resumo,
                                    recomendacoes, origem_resumo, assinatura)
               VALUES ('EQ-001', CURRENT_TIMESTAMP, 'crit', 'ml', 't', 'r', '[]',
                       'gemini', 'teste')"""
        ).lastrowid

    r = cliente.post(f"/eventos/{evento_id}/feedback", json={"util": True})
    assert r.status_code == 201
    agregado = cliente.get("/feedback/resumo").json()
    assert agregado == [{"origem_resumo": "gemini", "avaliacoes": 1, "uteis": 1,
                         "taxa_aprovacao": 1.0}]

    assert cliente.post("/eventos/999999/feedback", json={"util": False}).status_code == 404
