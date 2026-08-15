import os
import streamlit as st
import plotly.graph_objects as go
from app.components.cabecalho import cabecalho
from app.components.status_badge import html_badge
from app.components.estilos import (
    CORES, COR_PLOTLY,
    html_header_ativo, html_placeholder_vazio, html_titulo_grandeza,
    estilo_severidade_pandas,
)
from app.services.equipamentos import get_equipamento
from app.services.telemetria import (
    GRANDEZAS, get_limites, ultima_leitura,
    status_por_grandeza, get_historico, alertas_recentes,
)

if "equipamento_selecionado" not in st.session_state:
    st.warning("Nenhum equipamento selecionado. Use a navegação por planta.")
    if st.button("← Ir para Navegação por Planta"):
        st.switch_page("app/pages/navegacao_planta.py")
    st.stop()

tag = st.session_state["equipamento_selecionado"]["TAG"]
eq = get_equipamento(tag)
if not eq:
    st.error(f"Equipamento {tag} não encontrado no banco.")
    st.stop()

cabecalho(f"Dashboard — {eq['TAG']}", pagina_voltar="app/pages/navegacao_planta.py")

col_info, col_img = st.columns([3, 1])
with col_info:
    st.markdown(
        html_header_ativo(
            planta=eq.get("Planta"), area=eq.get("Área"),
            modelo=eq["Modelo"], fabricante=eq["Fabricante"],
            potencia=eq["Potência (W)"], tensao=eq["Tensão (V)"],
        ),
        unsafe_allow_html=True,
    )

with col_img:
    img_path = eq.get("img_placa_path")
    if img_path and os.path.exists(img_path):
        st.image(img_path, caption="Placa do motor", use_container_width=True)
    else:
        st.markdown(html_placeholder_vazio("Sem imagem da placa cadastrada"), unsafe_allow_html=True)

st.divider()

st.subheader("Telemetria Atual")

leitura = ultima_leitura(tag)
limites = get_limites()

if not leitura:
    st.info("Nenhuma leitura registrada para este ativo.")
else:
    statuses = status_por_grandeza(tag, limites)
    cols = st.columns(4)

    rotulos = {
        "temperatura": "Temperatura",
        "vibracao":    "Vibração",
        "corrente":    "Corrente",
        "rpm":         "RPM",
    }
    for col, g in zip(cols, GRANDEZAS):
        lim = limites[g]
        valor = leitura[g]
        st_g  = statuses[g]
        cor   = COR_PLOTLY[st_g]

        if valor is None:
            col.markdown(html_titulo_grandeza(rotulos[g], ""), unsafe_allow_html=True)
            col.markdown(
                html_placeholder_vazio("Sensor não instalado", padding_px=76),
                unsafe_allow_html=True,
            )
            continue

        fig = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=float(valor or 0),
                number={"suffix": f" {lim['unidade']}", "font": {"size": 22, "color": CORES["text_light"]}},
                gauge={
                    "axis": {"range": [0, lim["fundo_escala"]], "tickcolor": "#777", "tickfont": {"color": "#999"}},
                    "bar":  {"color": cor, "thickness": 0.3},
                    "bgcolor": CORES["bg_card"],
                    "borderwidth": 1,
                    "bordercolor": CORES["border_dark"],
                    "steps": [
                        {"range": [0, max(0, lim["crit_min"])], "color": "rgba(244,67,54,0.22)"},
                        {"range": [max(0, lim["crit_min"]), max(0, lim["warn_min"])], "color": "rgba(255,179,0,0.20)"},
                        {"range": [max(0, lim["warn_min"]), lim["warn_max"]], "color": "rgba(76,175,80,0.20)"},
                        {"range": [lim["warn_max"], lim["crit_max"]], "color": "rgba(255,179,0,0.20)"},
                        {"range": [lim["crit_max"], lim["fundo_escala"]], "color": "rgba(244,67,54,0.22)"},
                    ],
                    "threshold": {
                        "line": {"color": CORES["text_light"], "width": 2},
                        "thickness": 0.75,
                        "value": float(valor or 0),
                    },
                },
            )
        )
        fig.update_layout(
            height=220,
            margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor=CORES["bg_dark"],
            font={"color": CORES["text_light"], "family": "Inter"},
        )
        col.markdown(html_titulo_grandeza(rotulos[g], html_badge(st_g)), unsafe_allow_html=True)
        col.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

st.divider()

st.subheader("Histórico — Série Temporal")

c1, c2 = st.columns([2, 1])
with c1:
    rotulos_inv = {
        "Temperatura (°C)": "temperatura",
        "Vibração (mm/s)":   "vibracao",
        "Corrente (A)":      "corrente",
        "RPM":                "rpm",
    }
    label_sel = st.selectbox("Grandeza", list(rotulos_inv.keys()))
    g_sel = rotulos_inv[label_sel]
with c2:
    janela = st.selectbox("Janela", ["1h", "24h", "7d"], index=1)

df_hist = get_historico(tag, janela)

if df_hist.empty:
    st.info("Sem dados no período selecionado.")
else:
    lim = limites[g_sel]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_hist["ts"], y=df_hist[g_sel],
        mode="lines",
        line=dict(color=CORES["primary"], width=2),
        name=label_sel,
        hovertemplate="%{x|%d/%m %H:%M}<br>%{y:.2f} " + lim["unidade"] + "<extra></extra>",
    ))
    fig.add_hrect(y0=lim["warn_min"], y1=lim["warn_max"], fillcolor="rgba(76,175,80,0.07)", line_width=0)
    fig.add_hline(y=lim["warn_max"], line=dict(color=CORES["warn"], width=1, dash="dash"))
    fig.add_hline(y=lim["crit_max"], line=dict(color=CORES["crit"], width=1, dash="dash"))
    if lim["warn_min"] > 0:
        fig.add_hline(y=lim["warn_min"], line=dict(color=CORES["warn"], width=1, dash="dash"))
    if lim["crit_min"] > 0:
        fig.add_hline(y=lim["crit_min"], line=dict(color=CORES["crit"], width=1, dash="dash"))

    fig.update_layout(
        height=380,
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor=CORES["bg_dark"], plot_bgcolor=CORES["bg_card"],
        font={"color": CORES["text_light"], "family": "Inter"},
        xaxis=dict(gridcolor="#2A2A2A", title=""),
        yaxis=dict(gridcolor="#2A2A2A", title=lim["unidade"]),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    serie = df_hist[g_sel].dropna()
    if not serie.empty:
        cs1, cs2, cs3, cs4 = st.columns(4)
        cs1.metric("Mínimo",  f"{serie.min():.2f} {lim['unidade']}")
        cs2.metric("Máximo",  f"{serie.max():.2f} {lim['unidade']}")
        cs3.metric("Média",   f"{serie.mean():.2f} {lim['unidade']}")
        cs4.metric("Desvio",  f"{serie.std():.2f} {lim['unidade']}")

st.divider()

st.subheader("Alertas no período")
df_alertas = alertas_recentes(tag, janela, limites)
if df_alertas.empty:
    st.success("Nenhum alerta detectado no período selecionado.")
else:
    st.dataframe(
        df_alertas.style.map(estilo_severidade_pandas, subset=["Severidade"]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Timestamp": st.column_config.DatetimeColumn("Timestamp", format="DD/MM/YYYY HH:mm"),
            "Valor":     st.column_config.NumberColumn("Valor", format="%.2f"),
        },
    )
