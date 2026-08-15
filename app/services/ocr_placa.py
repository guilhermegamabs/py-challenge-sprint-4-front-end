import json

from app.services.gemini_client import get_client as _get_client

MODEL_NAME = "gemini-2.5-flash"

CAMPOS = ["TAG", "Modelo", "Fabricante", "Potência (W)", "Tensão (V)"]

PROMPT = """Voce e um assistente que extrai informacoes tecnicas da placa de identificacao
de um motor eletrico industrial. Analise a imagem e devolva os campos solicitados.

Regras:
- Devolva APENAS o JSON, sem texto extra.
- Use null quando o campo nao estiver legivel ou ausente.
- TAG: codigo de identificacao (ex.: "EQ-001", "MTR-1234"). Se nao houver, null.
- Modelo: identificador do modelo do equipamento.
- Fabricante: nome do fabricante (Siemens, WEG, ABB, Schneider, etc).
- potencia_w: potencia normalizada em Watts (inteiro). Converter kW para W (multiplicar por 1000),
  HP para W (multiplicar por 745.7), CV para W (multiplicar por 735.5).
- tensao_v: tensao nominal em Volts (inteiro).

Se houver multiplos valores de tensao (ex.: 220/380V), escolha o primeiro.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "tag":         {"type": "string", "nullable": True},
        "modelo":      {"type": "string", "nullable": True},
        "fabricante":  {"type": "string", "nullable": True},
        "potencia_w":  {"type": "integer", "nullable": True},
        "tensao_v":    {"type": "integer", "nullable": True},
        "texto_bruto": {"type": "string", "nullable": True},
    },
    "required": ["tag", "modelo", "fabricante", "potencia_w", "tensao_v"],
}


def _detect_mime(img_bytes: bytes) -> str:
    if img_bytes.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if img_bytes.startswith(b"\x89PNG"):
        return "image/png"
    if img_bytes[:4] == b"RIFF" and img_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def extrair(img_bytes: bytes) -> dict:
    from google.genai import types

    client = _get_client()
    mime = _detect_mime(img_bytes)

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[
            types.Part.from_bytes(data=img_bytes, mime_type=mime),
            PROMPT,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            temperature=0.0,
        ),
    )

    try:
        data = json.loads(response.text or "{}")
    except json.JSONDecodeError:
        data = {}

    resultado: dict = {}
    if data.get("tag"):
        resultado["TAG"] = str(data["tag"]).strip().upper()
    if data.get("modelo"):
        resultado["Modelo"] = str(data["modelo"]).strip()
    if data.get("fabricante"):
        resultado["Fabricante"] = str(data["fabricante"]).strip()
    if data.get("potencia_w") is not None:
        try:
            resultado["Potência (W)"] = int(data["potencia_w"])
        except (TypeError, ValueError):
            pass
    if data.get("tensao_v") is not None:
        try:
            resultado["Tensão (V)"] = int(data["tensao_v"])
        except (TypeError, ValueError):
            pass

    resultado["_texto_bruto"] = data.get("texto_bruto") or ""
    resultado["_faltando"] = [c for c in CAMPOS if c not in resultado]
    return resultado
