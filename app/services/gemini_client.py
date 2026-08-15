"""Cliente Gemini compartilhado — usado pelo OCR da placa e pelos resumos de alerta.

A chave vem de variável de ambiente ou de `.streamlit/secrets.toml`, nessa ordem.
"""

import os
from typing import Optional

import streamlit as st

NOMES_CHAVE = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


def get_api_key() -> Optional[str]:
    for nome in NOMES_CHAVE:
        valor = os.environ.get(nome)
        if valor:
            return valor
    try:
        for nome in NOMES_CHAVE:
            if nome in st.secrets and st.secrets[nome]:
                return st.secrets[nome]
    except Exception:
        pass
    return None


def disponivel() -> bool:
    return get_api_key() is not None


@st.cache_resource(show_spinner=False)
def get_client():
    from google import genai

    key = get_api_key()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY nao configurada. Defina a variavel de ambiente "
            "GEMINI_API_KEY ou adicione em .streamlit/secrets.toml."
        )
    return genai.Client(api_key=key)
