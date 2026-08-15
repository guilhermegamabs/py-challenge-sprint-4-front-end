# Challenge Sprint 3: Inteligência Operacional e Apoio à Decisão

### FRONT END & MOBILE DEVELOPMENT

---

## Integrantes

| Nome | RM |
|---|---|
| Guilherme Gama | RM565293 |
| Bruno Fernandes Nascimento | RM552574 |
| Edgar Lódula de Assis | RM565260 |
| Júlia Aben-Athar | RM566325 |
| Igor Thiago Nakajima Vieira | RM563632 |

**Professor:** Lucas Tadeu Cunha Rios

---

Interface web desenvolvida em **Streamlit** para monitoramento operacional de motores industriais, com painel de alertas e estados, navegação por planta, dashboards de telemetria, detecção de anomalia por desvio de comportamento, resumos textuais gerados por IA e cadastro visual da placa do motor.

Evolução das Sprints 1 e 2: antes o operador precisava abrir cada equipamento para descobrir que algo estava errado. Agora a página inicial agrega o estado de toda a frota, dispara o alerta, explica em texto o que aconteceu e sugere a ação.

---

## O que a Sprint 3 acrescenta

| Recurso | Descrição |
|---|---|
| **Painel de Alertas e Estados** | Página inicial, antes de qualquer seleção de equipamento. KPIs da frota, resumo executivo, cards de alerta, apoio à decisão e histórico de eventos. |
| **Detecção de anomalia** | Três detectores complementares rodando sobre a telemetria de todos os ativos: resíduo de previsão (mudança brusca), CUSUM (deriva lenta) e variância nula (sensor congelado). |
| **Resumos por NLP** | Cada alerta ganha título, explicação e 3 recomendações em português, geradas pelo Gemini 2.5 Flash a partir do diagnóstico numérico — com fallback determinístico por template. |
| **Atualização por botão e por timer** | `Atualizar agora` mais auto-refresh via `st.fragment(run_every=...)`, com toggle e intervalo selecionável (5 s a 1 min). Alerta novo dispara notificação (`st.toast`). |
| **Ativo de campo real** | `MOTOR-220V-01` ingerido da camada Silver do Data Lake (`part-*.parquet`), com temperatura e vibração medidas em bancada. |
| **Simulação de degradação** | Quatro modos de falha injetáveis pelo painel, gravando leituras reais no banco — o estado muda também na Navegação por Planta e no Dashboard do Ativo. |

---

## Funcionalidades

| Tela | Descrição |
|---|---|
| **Painel de Alertas e Estados** | Página inicial. Estado agregado da frota, alertas ativos com resumo textual, cards de recomendação e histórico de eventos filtrável. |
| **Navegação por Planta** | Página inicial. Seleciona Planta → Área e exibe os ativos da área em cards com status colorido (verde/amarelo/vermelho) e mini-leituras de cada sensor. |
| **Dashboard do Ativo** | Cabeçalho do equipamento + thumbnail da placa, 4 gauges Plotly (Temperatura, Vibração, Corrente, RPM) com cores dinâmicas por limites operacionais, série temporal histórica com bandas warn/crit e tabela de alertas no período. |
| **Consulta de Equipamentos** | Lista de equipamentos com filtros por Planta, Área, Fabricante e busca por TAG/Modelo. Coluna Status colorida com a última condição do ativo. |
| **Novo Equipamento** | Upload da imagem da placa do motor → extração automática via Gemini 2.5 Flash (TAG, Modelo, Fabricante, Potência, Tensão). Campos detectados marcados com ✓ IA e ausentes com ⚠ — todos editáveis pelo operador antes do cadastro. |
| **Módulo Técnico** | Ficha técnica completa do equipamento + Planta/Área + imagem da placa cadastrada. Edição inline dos dados. |
| **Dados Brutos** | Visualização das leituras ADC do sensor com conversão para unidades de engenharia (mantido da Sprint 1). |

---

## Stack

| Camada | Tecnologia |
|---|---|
| UI | Streamlit (`st.navigation`, `st.fragment`) |
| Gráficos | Plotly (gauges + séries temporais) |
| Persistência | SQLite (`data/forzy.db`) |
| Detecção de anomalia | numpy — resíduo de previsão + CUSUM + variância |
| NLP / OCR | Google Gemini 2.5 Flash via `google-genai` |
| Ingestão | pandas + pyarrow (Parquet da camada Silver) |

---

## Arquitetura da camada analítica

```
part-*.parquet ──► ingestao_silver.py ──► SQLite (leituras)
                                              │
                                              ▼
              telemetria.py (regra de limite) ─┐
                                               ├─► resumos.py ─► eventos.py ─► painel_alertas.py
              analitico.py  (detecção ML)    ──┘    (NLP)       (histórico)     (cards + timer)
```

**Desacoplamento:** a página nunca chama o detector nem a LLM. Ela lê eventos do banco. Quem grava é o pipeline (`pipeline_alertas.executar_ciclo()`), disparado pelo botão ou pelo timer. Trocar o modelo ou o gerador de texto não toca a interface.

### Detectores (`app/services/analitico.py`)

Portados do notebook `modelo_lstm_forecaster.ipynb`, do módulo de Modelagem. O contrato de saída (`Diagnostico`) espelha a função `inferir()` do notebook: `score`, `threshold`, `alarme`, `feature_dominante`, `pista`, `residuo_por_feature`.

| Detector | Cobre | Por quê |
|---|---|---|
| Resíduo de previsão | Spike, travamento | O previsor erra na hora quando o sinal muda bruscamente |
| CUSUM do resíduo com sinal | Deriva térmica lenta | O erro instantâneo é minúsculo, mas o viés é consistente e acumula |
| Variância da janela ≈ 0 | Sensor congelado | Sinal parado é *fácil* de prever: o resíduo fica menor, não maior |

Os limiares saem da própria baseline de cada ativo (p99 do resíduo, múltiplo do CUSUM observado em operação normal) — uma constante global não transfere entre ativos com amostragem e ruído diferentes.

**Trocar o previsor pela LSTM treinada** é substituir uma única função: `analitico._prever()`. Enquanto os artefatos (`artefatos/modelo_lstm.pt`, `scalers.pkl`, `metadados.json`) não são publicados, o previsor é uma média exponencial da janela, sem dependência de torch. Se `artefatos/metadados.json` existir, seus limiares calibrados sobrescrevem os padrões automaticamente.

### Dado real — MOTOR-220V-01

`part-000.parquet` é a saída da camada Silver do Data Lake: 20.152 linhas na grade de 1 s, 2 portas IO-Link, estado ON/OFF derivado do limiar de velocidade. O sensor é de vibração, então `velocidade` (0,04 a 7,73 mm/s) entra como **vibração** — faixa que casa com os limites ISO 10816 já usados no app — e `aceleracao` é guardada na coluna homônima. Corrente e RPM ficam nulas: não há sensor. Só as amostras com o motor em ON são ingeridas, reamostradas para a grade de 1 min do app e transladadas para terminar no instante atual, já que o painel opera em janelas relativas ao agora.

### Resumos (`app/services/resumos.py`)

O prompt recebe o diagnóstico completo em JSON e pede título, texto e 3 recomendações, com `response_schema` estrito e `temperature=0.2`. Sem chave, sem rede ou com resposta inválida, cai no gerador por template — a interface marca com o selo `IA · Gemini` ou `Resumo automático`.

> **Cota:** o plano gratuito do Gemini limita as requisições diárias por modelo. O painel respeita isso com cache de 30 min por diagnóstico, deduplicação de eventos em 30 min e teto de chamadas por ciclo. Estourada a cota, os resumos continuam aparecendo pelo template e nada quebra.

---

## Estrutura do Projeto

```
front-end/
├── main.py                            # entry point + init_db + roteamento de páginas
├── requirements.txt
├── modelo_lstm_forecaster.ipynb       # notebook de Modelagem — origem dos detectores
├── part-000.parquet                   # camada Silver do Data Lake (MOTOR-220V-01)
├── .streamlit/
│   ├── config.toml                    # tema dark Forzy
│   └── secrets.toml                   # GEMINI_API_KEY (gitignored)
├── artefatos/                         # opcional (gitignored) — modelo_lstm.pt, scalers.pkl, metadados.json
├── data/                              # gerado em runtime (gitignored)
│   ├── forzy.db                       # SQLite — plantas, áreas, equipamentos, leituras, limites, eventos
│   └── placas/                        # imagens das placas cadastradas
├── img/
└── app/
    ├── components/
    │   ├── cabecalho.py               # header reutilizável
    │   ├── estilos.py                 # tokens de cor + builders de HTML
    │   ├── status_badge.py            # pill OK / Atenção / Crítico
    │   └── cards_alerta.py            # card de alerta, card de recomendação, KPI, barra de score
    ├── pages/
    │   ├── painel_alertas.py          # PÁGINA INICIAL — alertas, estados, timer, histórico
    │   ├── navegacao_planta.py        # tree Planta → Área → Equipamento
    │   ├── dashboard_ativo.py         # gauges + série temporal + alertas
    │   ├── consulta_equipamentos.py
    │   ├── cadastro_equipamento.py    # upload + OCR Gemini
    │   ├── modulo_tecnico.py
    │   └── dados_brutos.py
    └── services/
        ├── db.py                      # conexão SQLite + schema + migração + seed
        ├── ingestao_silver.py         # Parquet da Silver → leituras do MOTOR-220V-01
        ├── equipamentos.py            # CRUD de equipamentos/plantas/áreas
        ├── telemetria.py              # leituras, classificação de status, histórico, alertas
        ├── analitico.py               # 3 detectores + contrato Diagnostico
        ├── resumos.py                 # camada de NLP (Gemini + fallback por template)
        ├── eventos.py                 # persistência e leitura do histórico de eventos
        ├── pipeline_alertas.py        # orquestração do ciclo de monitoramento
        ├── simulador.py               # injeção de degradação para demonstração
        ├── gemini_client.py           # cliente Gemini compartilhado
        └── ocr_placa.py               # extração da placa do motor
```

---

## Modelo de Dados (SQLite)

| Tabela | Conteúdo |
|---|---|
| `plantas` | Lista de plantas industriais |
| `areas` | Áreas dentro de cada planta |
| `equipamentos` | Motores cadastrados (TAG, modelo, fabricante, potência, tensão, área, caminho da imagem da placa) |
| `leituras` | Histórico de telemetria (temperatura, vibração, corrente, RPM, aceleração) com timestamp |
| `limites` | Faixas warn/crit por grandeza para classificação de status |
| `eventos` | Alertas persistidos: severidade, origem (`limite` / `ml`), score, detectores, resumo, recomendações, reconhecimento |

O seed inicial popula 3 plantas, 6 áreas, 9 equipamentos sintéticos e 7 dias de histórico (≈90 720 leituras totais), mais o ativo real `MOTOR-220V-01` ingerido do Parquet. EQ-003 e EQ-007 são forçados a estado crítico, EQ-005 e EQ-006 a alerta, para demonstração visual.

### Dados reais — WEG W22 (EQ-009)

O equipamento **EQ-009 (W22-100L-2P / WEG)** usa specs e baselines extraídos do catálogo técnico oficial da WEG processado no projeto de PLN da Sprint 1 (`corpus_estruturado.csv`):

| Campo | Valor (datasheet/SCADA real) |
|---|---|
| Modelo | W22 carcaça 100L, 2 polos |
| Potência | 2,2 kW |
| Tensão nominal | 220 V (220-254 V) |
| Corrente nominal | 12,5 A (operação normal) |
| Rotação nominal | 3525 rpm |
| Classe de isolamento | F |
| Grau de proteção | IP55 |
| Baseline operacional | 38 °C / 12,3 A / 3520 rpm / 2,1 mm/s |
| Limite crítico de temperatura | 85 °C (log SCADA: "Temp. 95°C > limite 85°C") |

Os demais equipamentos seguem perfis sintéticos para fins de demonstração.

---

## Como rodar localmente

### Pré-requisitos

- Python 3.11 ou superior
- pip
- Chave da API do Google Gemini (https://aistudio.google.com/apikey) — opcional: sem ela os resumos são gerados por template

### Passos

**1. Clone o repositório**
```bash
git clone git@github.com:guilhermegamabs/py-challenge-sprint-2-front-end-mobile-development.git
cd py-challenge-sprint-2-front-end-mobile-development
```

**2. Crie e ative o ambiente virtual**
```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate
```

**3. Instale as dependências**
```bash
pip install -r requirements.txt
```

**4. Configure a chave do Gemini**

Crie o arquivo `.streamlit/secrets.toml` (não comitado):
```toml
GEMINI_API_KEY = "sua-chave-aqui"
```

Alternativa via variável de ambiente:
```bash
# Windows (PowerShell)
$env:GEMINI_API_KEY = "sua-chave-aqui"

# Linux / macOS
export GEMINI_API_KEY="sua-chave-aqui"
```

**5. Inicie o servidor**
```bash
streamlit run main.py
```

Na primeira execução o banco `data/forzy.db` é criado e populado automaticamente. O app abre em `http://localhost:8501`.

---

## Jornada do Operador (demo)

1. **Painel de Alertas e Estados** (abre por padrão) → KPIs da frota, resumo executivo e os alertas ativos ordenados por severidade.
2. Abre **Demonstração**, escolhe um ativo saudável e um modo de falha (ex.: `Spike de vibração` em EQ-001) e clica **Simular anomalia**.
3. A notificação aparece, o card entra em vermelho no topo do painel com o resumo textual do que aconteceu, e os **cards de recomendação** listam as três ações na ordem de execução.
4. **Abrir Dashboard** → confere a telemetria do ativo nos gauges e a tendência na série temporal.
5. **Navegação por Planta** → o card do mesmo ativo também está Crítico: o estado é real, não visual.
6. **Restaurar** no painel devolve o ativo à baseline e a demonstração pode ser repetida.

Para a transição ao vivo, ligue o **Auto** com intervalo de 5 s: o painel reexecuta o ciclo sozinho e o alerta aparece sem nenhum clique.

### Qual detector pega o quê

O modo `Deriva térmica lenta` é o que mostra o valor da camada analítica: a temperatura sobe 0,5 °C/min e **fica abaixo do limite operacional** — a regra fixa não dispara, mas o CUSUM acusa o desvio. Já `Sensor congelado` não é detectado por erro de previsão (sinal parado é trivial de prever): quem o pega é o detector de variância.

