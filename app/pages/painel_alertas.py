from datetime import datetime

import streamlit as st

from app.components.cabecalho import cabecalho
from app.components.cards_alerta import (
    html_card_alerta,
    html_card_recomendacao,
    html_kpi,
    html_painel_resumo,
)
from app.components.estilos import CORES, estilo_severidade_pandas, html_placeholder_vazio
from app.services import eventos, pipeline_alertas, simulador

INTERVALOS = {"5 segundos": 5, "15 segundos": 15, "30 segundos": 30, "1 minuto": 60}

st.session_state.setdefault("ultimo_evento_visto", eventos.ultimo_id())

cabecalho("Painel de Alertas e Estados")
st.caption(
    "Acompanhamento contínuo da frota. Alertas por limite operacional e por detecção "
    "de anomalia, com resumo textual e recomendação de ação."
)

# --------------------------------------------------------------------- controles

c_btn, c_auto, c_int, c_info = st.columns([1.1, 1, 1.2, 2.2])

with c_btn:
    atualizar = st.button("Atualizar agora", type="primary", use_container_width=True)
with c_auto:
    auto = st.toggle("Auto", key="alerta_auto")
with c_int:
    intervalo_rotulo = st.selectbox(
        "Intervalo", list(INTERVALOS), index=1, key="alerta_intervalo",
        label_visibility="collapsed", disabled=not auto,
    )
with c_info:
    st.caption(
        f"Atualização automática **{'ligada' if auto else 'desligada'}**"
        + (f" · a cada {intervalo_rotulo}" if auto else "")
    )

with st.expander("Demonstração — simular degradação de um ativo"):
    estado = pipeline_alertas.estado_frota()
    tags_saudaveis = [a["eq"]["TAG"] for a in estado["ativos"] if a["status"] == "ok"]
    todas_tags = [a["eq"]["TAG"] for a in estado["ativos"]]

    d1, d2, d3, d4 = st.columns([1.2, 1.6, 1, 1])
    with d1:
        tag_demo = st.selectbox("Ativo", tags_saudaveis or todas_tags, key="demo_tag_sel")
    with d2:
        modo = st.selectbox(
            "Modo de falha", list(simulador.MODOS),
            format_func=lambda m: simulador.MODOS[m], key="demo_modo_sel",
        )
    with d3:
        simular = st.button("Simular anomalia", use_container_width=True)
    with d4:
        restaurar = st.button("Restaurar", use_container_width=True)

    st.caption(
        "A simulação grava leituras reais no banco: o estado do ativo muda também "
        "na Navegação por Planta e no Dashboard do Ativo."
    )

    if simular:
        simulador.injetar_anomalia(tag_demo, modo)
        pipeline_alertas.invalidar_cache()
        st.toast(f"Degradação injetada em {tag_demo}", icon="🧪")
        st.rerun()

    if restaurar:
        simulador.restaurar(tag_demo)
        eventos.limpar_eventos(tag_demo)
        pipeline_alertas.invalidar_cache()
        st.toast(f"{tag_demo} restaurado à baseline", icon="✅")
        st.rerun()

if atualizar:
    pipeline_alertas.invalidar_cache()

st.divider()

# --------------------------------------------------------------------- bloco vivo


@st.fragment(run_every=INTERVALOS[intervalo_rotulo] if auto else None)
def bloco_painel():
    """Único trecho que o timer re-executa — o resto da página não recarrega."""
    pipeline_alertas.invalidar_cache()
    with st.spinner("Analisando telemetria e gerando resumos..."):
        novos = pipeline_alertas.executar_ciclo()

    for evento_id in novos:
        if evento_id > st.session_state["ultimo_evento_visto"]:
            st.session_state["ultimo_evento_visto"] = evento_id
    if novos:
        st.toast(f"{len(novos)} novo(s) alerta(s) detectado(s)", icon="🚨")

    estado = pipeline_alertas.estado_frota()
    contadores = estado["contadores"]

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(html_kpi("Críticos", contadores["crit"], CORES["crit"], "ação imediata"),
                unsafe_allow_html=True)
    k2.markdown(html_kpi("Em alerta", contadores["warn"], CORES["warn"], "desvio detectado"),
                unsafe_allow_html=True)
    k3.markdown(html_kpi("Saudáveis", contadores["ok"], CORES["ok"], "dentro da baseline"),
                unsafe_allow_html=True)
    k4.markdown(html_kpi("Anomalias ML", eventos.contar_anomalias_ml(24), CORES["primary"],
                         "últimas 24 h"), unsafe_allow_html=True)

    st.write("")

    resumo_frota = pipeline_alertas.resumo_executivo()
    st.markdown(
        html_painel_resumo(
            resumo_frota.titulo, resumo_frota.texto, resumo_frota.origem,
            estado["atualizado_em"].strftime("%d/%m/%Y %H:%M:%S"),
        ),
        unsafe_allow_html=True,
    )

    st.write("")
    st.subheader("Alertas ativos")

    ativos = eventos.eventos_ativos()
    if not ativos:
        st.markdown(
            html_placeholder_vazio(
                "Nenhum alerta ativo. Todos os ativos monitorados estão dentro da faixa de operação.",
                padding_px=32,
            ),
            unsafe_allow_html=True,
        )
    else:
        mapa_eq = {a["eq"]["TAG"]: a["eq"] for a in estado["ativos"]}
        for evento in ativos:
            eq = mapa_eq.get(evento["tag"], {})
            local = " · ".join(x for x in (eq.get("Planta"), eq.get("Área")) if x)
            st.markdown(
                html_card_alerta(
                    tag=evento["tag"],
                    severidade=evento["severidade"],
                    titulo=evento["titulo"] or "",
                    resumo=evento["resumo"] or "",
                    grandeza=evento["grandeza"],
                    valor=evento["valor"],
                    unidade=evento["unidade"],
                    score=evento["score"],
                    threshold=evento["threshold"],
                    pista=evento["pista"],
                    origem=evento["origem"],
                    origem_resumo=evento["origem_resumo"],
                    local=local,
                    ts_texto=evento["ts"].strftime("%d/%m %H:%M"),
                ),
                unsafe_allow_html=True,
            )
            b1, b2, _ = st.columns([1, 1, 3])
            if b1.button("Abrir Dashboard", key=f"ev_open_{evento['id']}",
                         use_container_width=True, type="primary"):
                st.session_state["equipamento_selecionado"] = eq or {"TAG": evento["tag"]}
                st.switch_page("app/pages/dashboard_ativo.py")
            if b2.button("Reconhecer", key=f"ev_ack_{evento['id']}", use_container_width=True):
                eventos.reconhecer(evento["id"])
                st.rerun(scope="fragment")
            st.write("")

    # ------------------------------------------------------------ apoio à decisão
    st.subheader("Apoio à decisão")
    if ativos and ativos[0].get("recomendacoes"):
        principal = ativos[0]
        # a causa provável vale uma vez, acima da fileira: dentro dos cards ela
        # se repetiria três vezes e desalinharia as alturas
        legenda = f"Ações sugeridas para **{principal['tag']}** — alerta mais severo em aberto."
        if principal.get("pista"):
            legenda += f" Causa provável: {principal['pista']}."
        st.caption(legenda)
        cols = st.columns(3)
        for i, (col, acao) in enumerate(zip(cols, principal["recomendacoes"][:3]), start=1):
            col.markdown(html_card_recomendacao(i, acao), unsafe_allow_html=True)
    else:
        cols = st.columns(3)
        for i, (col, acao) in enumerate(zip(cols, resumo_frota.recomendacoes[:3]), start=1):
            col.markdown(html_card_recomendacao(i, acao), unsafe_allow_html=True)

    st.caption(f"Última verificação: {datetime.now().strftime('%H:%M:%S')}")


bloco_painel()

st.divider()

# --------------------------------------------------------------------- histórico

st.subheader("Histórico de eventos")

f1, f2, f3 = st.columns([1.4, 1, 1])
with f1:
    filtro_sev = st.multiselect(
        "Severidade", ["crit", "warn", "ok"], default=["crit", "warn"],
        format_func=lambda s: eventos.ROTULO_SEVERIDADE[s],
    )
with f2:
    periodo = st.selectbox("Período", ["24 h", "7 dias", "Tudo"], index=0)
with f3:
    st.write("")
    if st.button("Reconhecer todos", use_container_width=True):
        eventos.reconhecer_todos()
        st.rerun()

horas = {"24 h": 24, "7 dias": 168, "Tudo": None}[periodo]
df_eventos = eventos.listar_eventos(severidades=filtro_sev or None, horas=horas)

if df_eventos.empty:
    st.markdown(
        html_placeholder_vazio("Nenhum evento registrado no período selecionado."),
        unsafe_allow_html=True,
    )
else:
    st.dataframe(
        df_eventos.style.map(estilo_severidade_pandas, subset=["Severidade"]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Timestamp": st.column_config.DatetimeColumn("Timestamp", format="DD/MM/YYYY HH:mm"),
            "Valor":     st.column_config.NumberColumn("Valor", format="%.2f"),
            "Resumo":    st.column_config.TextColumn("Resumo", width="large"),
        },
    )
