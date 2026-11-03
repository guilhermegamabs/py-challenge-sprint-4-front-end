"""Componentes HTML não podem deixar texto externo virar markup."""

from app.components.cards_alerta import html_card_alerta, html_card_recomendacao
from app.components.estilos import esc, html_card_equipamento

MALICIOSO = '<img src=x onerror="alert(1)">'


def test_esc_trata_none_e_numero():
    assert esc(None) == ""
    assert esc(220) == "220"


def test_card_alerta_escapa_texto_da_llm():
    html = html_card_alerta(
        "EQ-001", "crit", titulo=MALICIOSO, resumo=MALICIOSO, pista=MALICIOSO,
    )
    assert "<img" not in html
    assert "&lt;img" in html


def test_card_recomendacao_escapa_acao():
    assert "<img" not in html_card_recomendacao(1, MALICIOSO)


def test_card_equipamento_escapa_dados_do_ocr():
    html = html_card_equipamento(MALICIOSO, MALICIOSO, MALICIOSO, 2200, 220, "", "ok")
    assert "<img" not in html
