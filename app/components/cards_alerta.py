"""Componentes reutilizáveis do Painel de Alertas e Estados.

Mesmo padrão dos demais componentes do projeto: a função devolve HTML e o
chamador renderiza com `st.markdown(..., unsafe_allow_html=True)`. As cores
semânticas vêm de `estilos.CORES` — vermelho para anomalia severa, amarelo para
desvio, verde para baseline.
"""

import streamlit as st

from app.components.estilos import COR_BORDA_STATUS, CORES
from app.components.status_badge import html_badge

ROTULO_GRANDEZA = {
    "temperatura": "Temperatura",
    "vibracao":    "Vibração",
    "corrente":    "Corrente",
    "rpm":         "RPM",
    "aceleracao":  "Aceleração",
}

CHIP_ORIGEM = {
    "ml":     ("ML · anomalia", "#4A2C6B", "#D1B3FF"),
    "limite": ("Limite operacional", "#2A2A2A", "#CCCCCC"),
}

CHIP_RESUMO = {
    "gemini":   ("IA · Gemini", "#1A3A4A", "#8ED6F0"),
    "template": ("Resumo automático", "#2A2A2A", "#AAAAAA"),
}


def html_chip(texto: str, fundo: str, cor: str) -> str:
    return (
        f'<span style="display:inline-block; padding:2px 9px; border-radius:999px; '
        f'background:{fundo}; color:{cor}; font-size:0.7rem; font-weight:600; '
        f'letter-spacing:0.02em;">{texto}</span>'
    )


def html_chip_origem(origem: str) -> str:
    texto, fundo, cor = CHIP_ORIGEM.get(origem, CHIP_ORIGEM["limite"])
    return html_chip(texto, fundo, cor)


def html_chip_resumo(origem_resumo: str | None) -> str:
    texto, fundo, cor = CHIP_RESUMO.get(origem_resumo or "template", CHIP_RESUMO["template"])
    return html_chip(texto, fundo, cor)


def html_kpi(rotulo: str, valor, cor: str, sublinha: str = "") -> str:
    return f"""
<div style="border:1px solid {CORES['border_dark']}; border-left:4px solid {cor};
            border-radius:10px; padding:12px 16px; background:{CORES['bg_card']};">
    <div style="color:{CORES['text_muted']}; font-size:0.75rem; text-transform:uppercase;
                letter-spacing:0.06em;">{rotulo}</div>
    <div style="color:{cor}; font-size:2rem; font-weight:900; line-height:1.15;">{valor}</div>
    <div style="color:{CORES['text_muted']}; font-size:0.72rem;">{sublinha}</div>
</div>
"""


def html_barra_score(score: float | None, threshold: float | None) -> str:
    """Barra proporcional do score contra o limiar do detector."""
    if score is None or not threshold:
        return ""
    razao = min(score / threshold, 2.0) / 2.0
    cor = CORES["crit"] if score > 1.5 * threshold else CORES["warn"]
    return (
        '<div style="margin-top:10px;">'
        f'<div style="display:flex; justify-content:space-between; color:{CORES["text_muted"]};'
        ' font-size:0.72rem; margin-bottom:3px;">'
        f'<span>score de anomalia {score:.3f}</span><span>limiar {threshold:.3f}</span></div>'
        '<div style="height:6px; border-radius:999px; background:#2A2A2A; overflow:hidden;">'
        f'<div style="height:100%; width:{razao * 100:.0f}%; background:{cor};"></div>'
        "</div></div>"
    )


def html_card_alerta(
    tag: str,
    severidade: str,
    *,
    titulo: str = "",
    resumo: str = "",
    grandeza: str | None = None,
    valor: float | None = None,
    unidade: str | None = None,
    score: float | None = None,
    threshold: float | None = None,
    pista: str | None = None,
    origem: str = "limite",
    origem_resumo: str | None = None,
    local: str = "",
    ts_texto: str = "",
) -> str:
    """Card de um alerta operacional, com o resumo textual da camada de NLP."""
    cor_borda = COR_BORDA_STATUS.get(severidade, CORES["ok_border"])
    rotulo_g = ROTULO_GRANDEZA.get(grandeza or "", (grandeza or "").capitalize())

    medida = ""
    if valor is not None and rotulo_g:
        medida = (
            f'<span style="color:{CORES["text_light"]}; font-weight:700;">'
            f'{rotulo_g}: {valor:.2f} {unidade or ""}</span>'
        )

    linha_pista = ""
    if pista:
        linha_pista = (
            f'<div style="color:{CORES["text_muted"]}; font-size:0.78rem; margin-top:8px;">'
            f"Causa provável: {pista}</div>"
        )

    # Sem linhas em branco: no markdown do Streamlit, uma linha vazia encerra o
    # bloco HTML e o restante do card apareceria como texto literal na tela.
    return (
        f'<div style="border:1px solid {cor_borda}; border-left:5px solid {cor_borda};'
        f' border-radius:10px; padding:16px 18px; background:{CORES["bg_card"]};'
        ' margin-bottom:10px;">'
        '<div style="display:flex; justify-content:space-between; align-items:center; gap:10px;">'
        '<div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">'
        f'<strong style="color:{CORES["primary"]}; font-size:1.05rem;">{tag}</strong>'
        f"{html_chip_origem(origem)}</div>"
        f"{html_badge(severidade)}</div>"
        f'<div style="color:{CORES["text_light"]}; font-size:0.98rem; font-weight:700;'
        f' margin-top:10px;">{titulo}</div>'
        f'<div style="color:{CORES["text_dim"]}; font-size:0.87rem; line-height:1.5;'
        f' margin-top:6px;">{resumo}</div>'
        f"{linha_pista}"
        f"{html_barra_score(score, threshold)}"
        '<div style="display:flex; justify-content:space-between; align-items:center;'
        ' margin-top:12px; gap:10px; flex-wrap:wrap;">'
        f'<div style="color:{CORES["text_sub"]}; font-size:0.78rem;">{medida}</div>'
        '<div style="display:flex; align-items:center; gap:8px;">'
        f"{html_chip_resumo(origem_resumo)}"
        f'<span style="color:{CORES["text_muted"]}; font-size:0.72rem;">{local} · {ts_texto}</span>'
        "</div></div></div>"
    )


PRIORIDADES = {
    1: ("Prioridade 1 · imediata", CORES["crit"]),
    2: ("Prioridade 2 · neste turno", CORES["warn"]),
    3: ("Prioridade 3 · planejar", CORES["ok"]),
}


def html_card_recomendacao(prioridade: int, acao: str, contexto: str = "") -> str:
    """Card de apoio à decisão: uma ação sugerida à equipe de manutenção.

    Os três cards ficam lado a lado, então a altura é fixa: conteúdo de tamanhos
    diferentes deixaria a fileira irregular. O contexto da causa aparece uma vez
    acima da fileira, não dentro de cada card.
    """
    rotulo, cor = PRIORIDADES.get(prioridade, PRIORIDADES[3])
    linha_contexto = (
        f'<div style="color:{CORES["text_muted"]}; font-size:0.74rem; margin-top:6px;">{contexto}</div>'
        if contexto else ""
    )
    return (
        f'<div style="border:1px solid {CORES["border_dark"]}; border-top:3px solid {cor};'
        f' border-radius:10px; padding:14px 16px; background:{CORES["bg_card_alt"]};'
        ' min-height:118px; display:flex; flex-direction:column; gap:2px;">'
        f'<div style="color:{cor}; font-size:0.7rem; font-weight:700; text-transform:uppercase;'
        f' letter-spacing:0.06em;">{rotulo}</div>'
        f'<div style="color:{CORES["text_light"]}; font-size:0.9rem; margin-top:8px;'
        f' line-height:1.45;">{acao}</div>'
        f"{linha_contexto}"
        "</div>"
    )


def html_painel_resumo(titulo: str, texto: str, origem_resumo: str, atualizado: str) -> str:
    """Bloco de resumo executivo do topo do painel."""
    return f"""
<div style="border:1px solid {CORES['border_dark']}; border-left:4px solid {CORES['primary']};
            border-radius:10px; padding:16px 20px; background:{CORES['bg_card']};">
    <div style="display:flex; justify-content:space-between; align-items:center; gap:12px;
                flex-wrap:wrap;">
        <strong style="color:{CORES['text_light']}; font-size:1.02rem;">{titulo}</strong>
        {html_chip_resumo(origem_resumo)}
    </div>
    <div style="color:{CORES['text_dim']}; font-size:0.88rem; line-height:1.55; margin-top:8px;">
        {texto}
    </div>
    <div style="color:{CORES['text_muted']}; font-size:0.72rem; margin-top:10px;">
        Atualizado em {atualizado}
    </div>
</div>
"""


def render_card_alerta(**kwargs):
    st.markdown(html_card_alerta(**kwargs), unsafe_allow_html=True)


def render_card_recomendacao(prioridade: int, acao: str, contexto: str = ""):
    st.markdown(html_card_recomendacao(prioridade, acao, contexto), unsafe_allow_html=True)
