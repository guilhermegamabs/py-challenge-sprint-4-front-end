import streamlit as st
from app.components.cabecalho import cabecalho
from app.components.status_badge import html_badge
from app.components.estilos import html_card_equipamento
from app.services.equipamentos import listar_plantas, listar_areas, listar_por_area
from app.services.telemetria import status_atual, ultima_leitura, get_limites


def _fmt(valor, casas: int, unidade: str = "") -> str:
    if valor is None:
        return "—"
    return f"{valor:.{casas}f} {unidade}".strip()


cabecalho("Navegação por Planta")
st.caption("Selecione uma Planta e Área para visualizar os ativos e seus respectivos status.")

plantas = listar_plantas()
if not plantas:
    st.warning("Nenhuma planta cadastrada.")
    st.stop()

col_p, col_a = st.columns(2)
with col_p:
    nomes_p = [p["nome"] for p in plantas]
    nome_planta = st.selectbox("Planta", nomes_p, key="nav_planta")
    planta_sel = next(p for p in plantas if p["nome"] == nome_planta)

areas = listar_areas(planta_sel["id"])

with col_a:
    if areas:
        nomes_a = [a["nome"] for a in areas]
        nome_area = st.selectbox("Área", nomes_a, key="nav_area")
        area_sel = next(a for a in areas if a["nome"] == nome_area)
    else:
        st.info("Sem áreas nessa planta.")
        st.stop()

st.divider()

equipamentos = listar_por_area(area_sel["id"])
if not equipamentos:
    st.info("Nenhum equipamento nesta área. Cadastre um novo equipamento associado a ela.")
    st.stop()

limites = get_limites()

resumo = {"ok": 0, "warn": 0, "crit": 0}
for eq in equipamentos:
    resumo[status_atual(eq["TAG"], limites)] += 1

c_ok, c_warn, c_crit, c_total = st.columns(4)
c_ok.metric("Saudáveis",  resumo["ok"])
c_warn.metric("Em alerta", resumo["warn"])
c_crit.metric("Críticos",   resumo["crit"])
c_total.metric("Total",     len(equipamentos))

st.divider()
st.subheader(f"Ativos em **{area_sel['nome']}**")

cols_por_linha = 3
for i in range(0, len(equipamentos), cols_por_linha):
    cols = st.columns(cols_por_linha)
    for col, eq in zip(cols, equipamentos[i : i + cols_por_linha]):
        st_eq = status_atual(eq["TAG"], limites)
        ult = ultima_leitura(eq["TAG"])

        with col:
            st.markdown(
                html_card_equipamento(
                    tag=eq["TAG"], modelo=eq["Modelo"], fabricante=eq["Fabricante"],
                    potencia=eq["Potência (W)"], tensao=eq["Tensão (V)"],
                    badge_html=html_badge(st_eq), status=st_eq,
                ),
                unsafe_allow_html=True,
            )
            if ult:
                mc1, mc2 = st.columns(2)
                mc1.caption(f"Temp: {_fmt(ult['temperatura'], 1, '°C')}")
                mc2.caption(f"Vib: {_fmt(ult['vibracao'], 2, 'mm/s')}")
                mc1.caption(f"Corrente: {_fmt(ult['corrente'], 1, 'A')}")
                mc2.caption(f"RPM: {_fmt(ult['rpm'], 0)}")
            if st.button("Abrir Dashboard", key=f"open_{eq['TAG']}", use_container_width=True, type="primary"):
                st.session_state["equipamento_selecionado"] = eq
                st.switch_page("app/pages/dashboard_ativo.py")
            st.write("")
