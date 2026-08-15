import streamlit as st
from app.services.db import init_db
from app.components.estilos import aplicar_estilo_global

st.set_page_config(
    page_title="Forzy — Monitoramento de Ativos",
    page_icon="img/forzy_logo.jpg",
    layout="wide",
)

init_db()
aplicar_estilo_global()

paginas = {
    "Início": [
        st.Page("app/pages/painel_alertas.py",       title="Painel de Alertas e Estados", default=True),
    ],
    "Operação": [
        st.Page("app/pages/navegacao_planta.py",     title="Navegação por Planta"),
        st.Page("app/pages/dashboard_ativo.py",      title="Dashboard do Ativo"),
    ],
    "Cadastro": [
        st.Page("app/pages/consulta_equipamentos.py", title="Consulta de Equipamentos"),
        st.Page("app/pages/cadastro_equipamento.py",  title="Novo Equipamento"),
        st.Page("app/pages/modulo_tecnico.py",        title="Módulo Técnico"),
        st.Page("app/pages/dados_brutos.py",          title="Dados Brutos"),
    ],
}

with st.sidebar:
    st.markdown(
        '<p style="text-align:center; color:#888; font-size:0.8rem; margin:0;">Sprint 3 — Inteligência Operacional</p>',
        unsafe_allow_html=True,
    )
    st.divider()
    st.markdown("**Integrantes**")
    st.caption("Guilherme Gama · RM565293")
    st.caption("Bruno Fernandes · RM552574")
    st.caption("Edgar Lódula · RM565260")
    st.caption("Júlia Aben-Athar · RM566325")
    st.caption("Igor Nakajima · RM563632")
    st.divider()

pg = st.navigation(paginas, position="sidebar")
pg.run()
