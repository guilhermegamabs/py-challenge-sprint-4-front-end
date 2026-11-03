import html

import streamlit as st


def esc(valor) -> str:
    """Escapa texto antes de interpolar em HTML renderizado com unsafe_allow_html.

    TAG, modelo e fabricante chegam do OCR e do cadastro manual; título e resumo
    chegam da LLM. Um `<` em qualquer um deles quebrava o card ou injetava markup.
    """
    return "" if valor is None else html.escape(str(valor))

CORES = {
    "primary":     "#FFB300",
    "bg_dark":     "#111111",
    "bg_card":     "#1A1A1A",
    "bg_card_alt": "#1f1f1f",
    "border_dark": "#333333",
    "text_light":  "#F5F5F5",
    "text_dim":    "#CCCCCC",
    "text_muted":  "#888888",
    "text_sub":    "#AAAAAA",
    "ok":          "#4CAF50",
    "warn":        "#FFB300",
    "crit":        "#F44336",
    "ok_border":   "#2E7D32",
    "warn_border": "#FFB300",
    "crit_border": "#EF5350",
}

COR_BORDA_STATUS = {
    "ok":   CORES["ok_border"],
    "warn": CORES["warn_border"],
    "crit": CORES["crit_border"],
}

COR_PLOTLY = {
    "ok":   CORES["ok"],
    "warn": CORES["warn"],
    "crit": CORES["crit"],
}


CSS_GLOBAL = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap');

html, body, [class*="css"], .stMarkdown, .stText, label, p, div {
    font-family: 'Inter', sans-serif !important;
}

[data-testid="stSidebar"] {
    background-color: #1A1A1A !important;
}

[data-testid="stSidebarNav"] a {
    border-left: 3px solid transparent;
    padding-left: 10px !important;
    transition: border-color 0.2s, color 0.2s, background-color 0.2s;
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    border-radius: 0 6px 6px 0;
}

[data-testid="stSidebarNav"] a[aria-current="page"] {
    border-left: 3px solid #FFB300 !important;
    color: #FFB300 !important;
    background-color: #2A2A2A !important;
}

.stButton > button {
    border-radius: 8px !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    transition: opacity 0.2s;
}

.stButton > button:hover {
    opacity: 0.85;
}

[data-testid="baseButton-secondary"] {
    border: 1px solid #FFB300 !important;
    color: #FFB300 !important;
}

[data-testid="stTextInput"] > div > div > input,
[data-testid="stNumberInput"] > div > div > input {
    border: 1px solid #FFB300 !important;
    border-radius: 6px !important;
    background-color: #1A1A1A !important;
}

[data-testid="stSelectbox"] > div > div,
[data-testid="stMultiSelect"] > div > div {
    border: 1px solid #FFB300 !important;
    border-radius: 6px !important;
    background-color: #1A1A1A !important;
}

[data-testid="stDataFrame"] th {
    background-color: #2A2A2A !important;
    color: #FFB300 !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 700 !important;
    border-bottom: 2px solid #FFB300 !important;
}

[data-testid="stDataFrame"] tr:hover td {
    background-color: rgba(255, 179, 0, 0.08) !important;
}

hr {
    border-color: #333333 !important;
}
</style>
"""


def aplicar_estilo_global():
    st.markdown(CSS_GLOBAL, unsafe_allow_html=True)


def html_titulo_pagina(texto: str) -> str:
    return (
        f'<h1 style="color:{CORES["primary"]}; font-family:Inter,sans-serif; '
        f'font-weight:900; margin-top:4px;">{texto}</h1>'
    )


def html_divider_laranja() -> str:
    return f'<hr style="border:none; border-top:2px solid {CORES["primary"]}; margin:6px 0 18px 0;">'


def html_card_equipamento(tag: str, modelo: str, fabricante: str,
                          potencia: int, tensao: int,
                          badge_html: str, status: str) -> str:
    cor_borda = COR_BORDA_STATUS.get(status, CORES["ok_border"])
    return f"""
<div style="border:1px solid {cor_borda}; border-radius:10px;
            padding:14px 16px; background:{CORES['bg_card']}; margin-bottom:8px;">
    <div style="display:flex; justify-content:space-between; align-items:center;">
        <strong style="color:{CORES['primary']}; font-size:1.05rem;">{esc(tag)}</strong>
        {badge_html}
    </div>
    <div style="color:{CORES['text_dim']}; font-size:0.85rem; margin-top:6px;">
        {esc(modelo)} · {esc(fabricante)}
    </div>
    <div style="color:{CORES['text_muted']}; font-size:0.78rem; margin-top:4px;">
        {esc(potencia)} W · {esc(tensao)} V
    </div>
</div>
"""


def html_header_ativo(planta: str, area: str, modelo: str, fabricante: str,
                      potencia: int, tensao: int) -> str:
    breadcrumb = f"{esc(planta or '—')}  ›  {esc(area or '—')}"
    modelo, fabricante = esc(modelo), esc(fabricante)
    potencia, tensao = esc(potencia), esc(tensao)
    return f"""
<div style="background:{CORES['bg_card']}; border-left:4px solid {CORES['primary']};
            padding:14px 18px; border-radius:6px;">
    <div style="color:{CORES['text_muted']}; font-size:0.78rem;">{breadcrumb}</div>
    <div style="color:{CORES['text_light']}; font-size:1.1rem; margin-top:4px;">
        <strong>{modelo}</strong> &nbsp;·&nbsp; {fabricante}
    </div>
    <div style="color:{CORES['text_sub']}; font-size:0.85rem; margin-top:2px;">
        {potencia} W &nbsp;·&nbsp; {tensao} V
    </div>
</div>
"""


def html_placeholder_vazio(texto: str, padding_px: int = 24) -> str:
    return (
        f'<div style="border:1px dashed #444; border-radius:6px; '
        f'padding:{padding_px}px; text-align:center; color:#666; '
        f'font-size:0.85rem;">{texto}</div>'
    )


def html_titulo_grandeza(rotulo: str, badge_html: str) -> str:
    return (
        f"<div style='display:flex; justify-content:space-between; align-items:center;'>"
        f"<strong style='color:{CORES['text_light']};'>{rotulo}</strong>{badge_html}</div>"
    )


def html_linha_check(texto: str) -> str:
    return f'<span style="color:{CORES["ok"]};">✓</span> {esc(texto)}'


def html_linha_alerta(texto: str) -> str:
    return f'<span style="color:{CORES["warn"]};">⚠</span> {esc(texto)}'


def estilo_severidade_pandas(valor: str) -> str:
    if valor == "Crítico":
        return f"color:{CORES['crit']}; font-weight:700;"
    if valor == "Atenção":
        return f"color:{CORES['warn']}; font-weight:700;"
    if valor == "OK":
        return f"color:{CORES['ok']}; font-weight:700;"
    return ""
