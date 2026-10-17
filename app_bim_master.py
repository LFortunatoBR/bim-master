import streamlit as st
import pandas as pd
import ezdxf
import math
import tempfile
import io
import os
import json
import uuid
import time
import hmac
import networkx as nx
import plotly.graph_objects as go
from pathfinding.core.diagonal_movement import DiagonalMovement
from pathfinding.core.grid import Grid
from pathfinding.finder.a_star import AStarFinder

# Importação opcional do IfcOpenShell
try:
    import ifcopenshell
    import ifcopenshell.api
    HAS_IFC = True
except ImportError:
    HAS_IFC = False

# Importação dos geradores PDF na mesma pasta
from gerador_unifilar_pdf import gerar_memorial_unifilar, gerar_pdf_qdg
from gerador_hidraulica_pdf import gerar_memorial_hidraulico, gerar_lista_materiais_pdf

# ==========================================
# 1. CONFIGURAÇÃO GERAL E TELA DE LOGIN (SECRETS)
# ==========================================
st.set_page_config(layout="wide", page_title="BIM Master PRO V14 - Elétrica & Hidrossanitário", page_icon="🏢")

def verificar_autenticacao():
    if st.session_state.get("autenticado", False):
        return True

    st.markdown("<h2 style='text-align: center; margin-top: 40px;'>🔐 Acesso Restrito — BIM Master PRO</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>Insira a credencial configurada no Streamlit Secrets para acessar os módulos de Elétrica e Hidrossanitário.</p>", unsafe_allow_html=True)

    col_esq, col_centro, col_dir = st.columns([1, 1.5, 1])
    with col_centro:
        with st.form("form_login_bim", clear_on_submit=False):
            senha_digitada = st.text_input("Senha do Sistema:", type="password", placeholder="Digite a senha...")
            btn_entrar = st.form_submit_button("🔓 Entrar no Programa", type="primary", use_container_width=True)

            if btn_entrar:
                try:
                    senha_secreta = str(st.secrets["app_password"])
                except Exception:
                    st.error("⚠️ A variável 'app_password' não foi encontrada nos Secrets do Streamlit.")
                    return False

                match_exato = hmac.compare_digest(senha_digitada, senha_secreta)
                match_limpo = hmac.compare_digest(senha_digitada.strip(), senha_secreta.strip())

                if match_exato or match_limpo:
                    st.session_state["autenticado"] = True
                    st.rerun()
                else:
                    st.error("❌ Senha incorreta. Verifique e tente novamente.")
    return False

if not verificar_autenticacao():
    st.stop()

# ==========================================
# 1.B INICIALIZAÇÃO DE ESTADO DO SISTEMA
# ==========================================
if 'circuitos' not in st.session_state:
    st.session_state.circuitos = pd.DataFrame(columns=[
        "ID", "Ambiente", "Equipamento", "Qtd", "Potência Total (W)", "Tensão (V)",
        "Fator de Potência", "Método Inst.", "Eletroduto (Ref)", "FCA", "FCT",
        "Corrente (A)", "Corrente Corrigida (A)", "Bitola (mm²)", "Queda Tensão (%)",
        "Disjuntor (A)", "Curva", "Icc (A)", "Distância (m)", "Fase", "Grupo DR",
        "Eletroduto (mm)", "Ocupação (%)"
    ])
if 'pontos_hidro' not in st.session_state:
    st.session_state.pontos_hidro = []
if 'linhas_3d_master' not in st.session_state:
    st.session_state.linhas_3d_master = {'eletrica': [], 'hidro': [], 'equipamentos_3d': []}
if 'contexto_bim' not in st.session_state:
    st.session_state.contexto_bim = {}
if 'colisoes_detectadas' not in st.session_state:
    st.session_state.colisoes_detectadas = []
if 'quantitativos_master' not in st.session_state:
    st.session_state.quantitativos_master = {
        'eletrica': pd.DataFrame(),
        'agua_fria': pd.DataFrame(),
        'agua_quente': pd.DataFrame(),
        'esgoto': pd.DataFrame()
    }

# ==========================================
# 2. FUNÇÕES DE ENGENHARIA E BIBLIOTECAS NORMATIVAS EXPANDIDAS
# ==========================================
TABELA_AMPACIDADE_NBR5410 = {
    1.5:  {"A1_2": 14.5, "B1_2": 17.5, "B1_3": 15.5, "B2_2": 16.5, "C_2": 19.5, "B1_90": 23.0, "Area_Ext_mm2": 7.1},
    2.5:  {"A1_2": 19.5, "B1_2": 24.0, "B1_3": 21.0, "B2_2": 23.0, "C_2": 27.0, "B1_90": 31.0, "Area_Ext_mm2": 10.2},
    4.0:  {"A1_2": 26.0, "B1_2": 32.0, "B1_3": 28.0, "B2_2": 30.0, "C_2": 36.0, "B1_90": 42.0, "Area_Ext_mm2": 13.8},
    6.0:  {"A1_2": 34.0, "B1_2": 41.0, "B1_3": 36.0, "B2_2": 38.0, "C_2": 46.0, "B1_90": 54.0, "Area_Ext_mm2": 18.1},
    10.0: {"A1_2": 46.0, "B1_2": 57.0, "B1_3": 50.0, "B2_2": 52.0, "C_2": 63.0, "B1_90": 75.0, "Area_Ext_mm2": 28.3},
    16.0: {"A1_2": 61.0, "B1_2": 76.0, "B1_3": 68.0, "B2_2": 69.0, "C_2": 85.0, "B1_90": 100.0, "Area_Ext_mm2": 40.7},
    25.0: {"A1_2": 80.0, "B1_2": 101.0, "B1_3": 89.0, "B2_2": 90.0, "C_2": 112.0, "B1_90": 133.0, "Area_Ext_mm2": 60.8},
    35.0: {"A1_2": 99.0, "B1_2": 125.0, "B1_3": 110.0, "B2_2": 111.0, "C_2": 138.0, "B1_90": 164.0, "Area_Ext_mm2": 78.5},
    50.0: {"A1_2": 119.0, "B1_2": 151.0, "B1_3": 134.0, "B2_2": 133.0, "C_2": 168.0, "B1_90": 198.0, "Area_Ext_mm2": 113.0},
}

ELETRODUTOS_NBR5410 = {
    16: 132.7, 20: 226.9, 25: 380.1, 32: 660.5,
    40: 1017.8, 50: 1661.9, 60: 2463.0, 75: 3848.4
}

DISJUNTORES_PADRAO_DIN = [10, 16, 20, 25, 32, 40, 50, 63, 70, 80, 100, 125]

COMPRIMENTO_EQUIVALENTE_CONEXOES = {
    "Joelho 90°":          {20: 1.1, 22: 1.1, 25: 1.2, 32: 1.5, 40: 2.0, 50: 3.2, 60: 3.5},
    "Joelho 45°":          {20: 0.4, 22: 0.4, 25: 0.5, 32: 0.7, 40: 1.0, 50: 1.3, 60: 1.5},
    "Curva 90°":           {20: 0.4, 22: 0.4, 25: 0.5, 32: 0.6, 40: 0.8, 50: 1.2, 60: 1.4},
    "Tê 90° (Direta)":     {20: 0.7, 22: 0.7, 25: 0.8, 32: 0.9, 40: 1.5, 50: 2.2, 60: 2.5},
    "Tê 90° (Saída Lat.)": {20: 2.3, 22: 2.3, 25: 2.4, 32: 3.1, 40: 4.6, 50: 7.3, 60: 8.0},
    "Registro de Gaveta":  {20: 0.2, 22: 0.2, 25: 0.3, 32: 0.4, 40: 0.7, 50: 0.8, 60: 0.9},
    "Registro de Pressão": {20: 5.4, 22: 5.4, 25: 7.4, 32: 9.5, 40: 11.0, 50: 14.0, 60: 16.0},
    "Saída de Canalização":{20: 0.8, 22: 0.8, 25: 0.9, 32: 1.3, 40: 1.5, 50: 2.0, 60: 2.2},
}

def obter_fca(num_circuitos):
    if num_circuitos <= 1: return 1.00
    elif num_circuitos == 2: return 0.80
    elif num_circuitos == 3: return 0.70
    elif num_circuitos == 4: return 0.65
    elif num_circuitos == 5: return 0.60
    else: return 0.50

def calcular_icc(tensao, bitola, distancia, material="Cobre"):
    if not bitola or bitola == 0 or pd.isna(bitola): return 0.0
    rho = 0.021 if material == "Cobre" else 0.035
    r_cabo = rho * (2.0 * max(1.0, float(distancia))) / float(bitola)
    z_total = r_cabo + 0.05
    icc = float(tensao) / z_total
    return round(icc, 1)

def calcular_disjuntor(corrente_projeto, bitola_capacidade):
    for d in DISJUNTORES_PADRAO_DIN:
        if d >= corrente_projeto and d <= bitola_capacidade:
            return d
    for d in DISJUNTORES_PADRAO_DIN:
        if d >= corrente_projeto:
            return d
    return 125

def calcular_fator_demanda_nbr5410(pot_total_w, qtd_tues=0):
    """Validação Avançada 2: Fator de Demanda Concessionária / NBR 5410."""
    kw = pot_total_w / 1000.0
    if kw <= 1.0: fd_geral = 1.00
    elif kw <= 3.0: fd_geral = 0.85
    elif kw <= 6.0: fd_geral = 0.75
    elif kw <= 10.0: fd_geral = 0.65
    else: fd_geral = 0.55
    # TUEs (chuveiros/ar-condicionado) aplicam fator de simultaneidade decrescente
    if qtd_tues == 1: fd_tue = 1.00
    elif qtd_tues == 2: fd_tue = 0.85
    elif qtd_tues <= 4: fd_tue = 0.75
    else: fd_tue = 0.65
    return fd_geral, fd_tue

def inicializar_bibliotecas_internas():
    if 'bib_hidro' not in st.session_state:
        st.session_state.bib_hidro = pd.DataFrame([
            {"Equipamento": "Bacia Sanitária (Caixa Acoplada) - Popular", "Vazao_Ls": 0.15, "Peso": 0.3, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 6, "Esgoto_mm": 100, "Vent_mm": 50},
            {"Equipamento": "Bacia Sanitária (Caixa Acoplada) - Alto Padrão", "Vazao_Ls": 0.15, "Peso": 0.3, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 6, "Esgoto_mm": 100, "Vent_mm": 50},
            {"Equipamento": "Bacia Sanitária (Válvula de Descarga)", "Vazao_Ls": 1.70, "Peso": 32.0, "Agua_mm": 50, "AQ_mm": 0, "Pressao_kpa": 15, "UHC": 6, "Esgoto_mm": 100, "Vent_mm": 50},
            {"Equipamento": "Chuveiro (revelando uma área de chuveiro simples)", "Vazao_Ls": 0.20, "Peso": 0.4, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 10, "UHC": 2, "Esgoto_mm": 40, "Vent_mm": 40},
            {"Equipamento": "Chuveiro Elétrico Padrão", "Vazao_Ls": 0.20, "Peso": 0.5, "Agua_mm": 20, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 2, "Esgoto_mm": 40, "Vent_mm": 40},
            {"Equipamento": "Chuveiro Misturador (Água Fria + Quente)", "Vazao_Ls": 0.20, "Peso": 0.4, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 10, "UHC": 2, "Esgoto_mm": 40, "Vent_mm": 40},
            {"Equipamento": "Chuveiro Multijato/Spa (Alto Padrão)", "Vazao_Ls": 0.60, "Peso": 2.0, "Agua_mm": 32, "AQ_mm": 28, "Pressao_kpa": 20, "UHC": 6, "Esgoto_mm": 50, "Vent_mm": 40},
            {"Equipamento": "Banheira de Imersão", "Vazao_Ls": 0.40, "Peso": 1.5, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 15, "UHC": 4, "Esgoto_mm": 50, "Vent_mm": 40},
            {"Equipamento": "Banheira Hidromassagem", "Vazao_Ls": 0.50, "Peso": 1.5, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 15, "UHC": 5, "Esgoto_mm": 50, "Vent_mm": 40},
            {"Equipamento": "Banheira / Ducha Híbrida", "Vazao_Ls": 0.30, "Peso": 1.0, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 15, "UHC": 2, "Esgoto_mm": 40, "Vent_mm": 40},
            {"Equipamento": "Lavatório/Pia (Residencial)", "Vazao_Ls": 0.15, "Peso": 0.3, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 10, "UHC": 1, "Esgoto_mm": 40, "Vent_mm": 40},
            {"Equipamento": "Torneira de bancada de banheiro", "Vazao_Ls": 0.15, "Peso": 0.3, "Agua_mm": 20, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 1, "Esgoto_mm": 40, "Vent_mm": 40},
            {"Equipamento": "Torneira de pia de cozinha", "Vazao_Ls": 0.25, "Peso": 0.7, "Agua_mm": 20, "AQ_mm": 22, "Pressao_kpa": 10, "UHC": 2, "Esgoto_mm": 50, "Vent_mm": 40},
            {"Equipamento": "Torneira Gourmet Cozinha (Mono/Duplo)", "Vazao_Ls": 0.30, "Peso": 0.8, "Agua_mm": 20, "AQ_mm": 22, "Pressao_kpa": 15, "UHC": 3, "Esgoto_mm": 50, "Vent_mm": 40},
            {"Equipamento": "Torneira quintal", "Vazao_Ls": 0.20, "Peso": 0.4, "Agua_mm": 20, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
            {"Equipamento": "Pia de Cozinha (Residencial)", "Vazao_Ls": 0.25, "Peso": 0.7, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 10, "UHC": 3, "Esgoto_mm": 50, "Vent_mm": 40},
            {"Equipamento": "Pia de Cozinha - Cuba Simples", "Vazao_Ls": 0.25, "Peso": 0.7, "Agua_mm": 20, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 3, "Esgoto_mm": 50, "Vent_mm": 40},
            {"Equipamento": "Pia de Cozinha - Cuba Dupla Gourmet", "Vazao_Ls": 0.25, "Peso": 0.7, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 15, "UHC": 3, "Esgoto_mm": 50, "Vent_mm": 40},
            {"Equipamento": "Máquina de Lavar Roupa", "Vazao_Ls": 0.30, "Peso": 1.0, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 3, "Esgoto_mm": 50, "Vent_mm": 40},
            {"Equipamento": "Máquina de Lavar Louça", "Vazao_Ls": 0.30, "Peso": 1.0, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 10, "UHC": 2, "Esgoto_mm": 50, "Vent_mm": 40},
            {"Equipamento": "Tanque de Lavar Roupa", "Vazao_Ls": 0.25, "Peso": 0.7, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 3, "Esgoto_mm": 40, "Vent_mm": 40},
            {"Equipamento": "Ducha Higiênica", "Vazao_Ls": 0.10, "Peso": 0.1, "Agua_mm": 20, "AQ_mm": 22, "Pressao_kpa": 10, "UHC": 1, "Esgoto_mm": 40, "Vent_mm": 0},
            {"Equipamento": "Bebedouro", "Vazao_Ls": 0.10, "Peso": 0.1, "Agua_mm": 20, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 0.5, "Esgoto_mm": 40, "Vent_mm": 0},
            {"Equipamento": "Filtro/Purificador de Parede", "Vazao_Ls": 0.05, "Peso": 0.1, "Agua_mm": 20, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 1, "Esgoto_mm": 0, "Vent_mm": 0},
            {"Equipamento": "Mictório Cerâmico (c/ válvula)", "Vazao_Ls": 0.50, "Peso": 2.8, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 15, "UHC": 2, "Esgoto_mm": 50, "Vent_mm": 40},
            {"Equipamento": "Caixa d'Água (Reservatório Superior)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
            {"Equipamento": "Bomba de Recalque", "Vazao_Ls": 1.50, "Peso": 0.0, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 200, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
            {"Equipamento": "Bomba Pressurizadora Residencial", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 150, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
            {"Equipamento": "Boiler (Aquecimento de Água Central)", "Vazao_Ls": 0.30, "Peso": 0.5, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 20, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
            {"Equipamento": "Aquecedor de Passagem a Gás", "Vazao_Ls": 0.30, "Peso": 0.5, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 20, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
            {"Equipamento": "Caixa Sifonada 150x150x50mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 6, "Esgoto_mm": 50, "Vent_mm": 40},
            {"Equipamento": "Caixa de Gordura", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 2, "Esgoto_mm": 75, "Vent_mm": 50},
            {"Equipamento": "Tubo de Queda (TQ - Esgoto Primário)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 100, "Vent_mm": 75},
            {"Equipamento": "Coluna de Ventilação", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 50, "Vent_mm": 50},
            {"Equipamento": "Ponto de Gás (Fogão/Aquecedor)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 2.8, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        ])

    if 'bib_eletrica' not in st.session_state:
        st.session_state.bib_eletrica = pd.DataFrame([
            {"Equipamento": "Lâmpada LED 15W", "Potência (W)": 15, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "Iluminação", "Curva Disjuntor": "B", "Uso de DR": "Opcional"},
            {"Equipamento": "Tomada Uso Geral (TUG)", "Potência (W)": 100, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Opcional"},
            {"Equipamento": "Tomada Cozinha/Serviço (TUG)", "Potência (W)": 600, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
            {"Equipamento": "Chuveiro Elétrico 7500W", "Potência (W)": 7500, "Tensão (V)": 220, "Fator de Potência": 1.0, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
            {"Equipamento": "Cooktop Indução 7000W", "Potência (W)": 7000, "Tensão (V)": 220, "Fator de Potência": 1.0, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
            {"Equipamento": "Ar-Condicionado 12000 BTU", "Potência (W)": 1200, "Tensão (V)": 220, "Fator de Potência": 0.95, "Tipo": "TUE", "Curva Disjuntor": "C", "Uso de DR": "Opcional"},
            {"Equipamento": "Fritadeira Elétrica (Air Fryer)", "Potência (W)": 1500, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
            {"Equipamento": "Computador Desktop", "Potência (W)": 500, "Tensão (V)": 127, "Fator de Potência": 0.9, "Tipo": "TUG", "Curva Disjuntor": "C", "Uso de DR": "Opcional"},
            {"Equipamento": "Microondas", "Potência (W)": 1500, "Tensão (V)": 127, "Fator de Potência": 0.95, "Tipo": "TUG", "Curva Disjuntor": "C", "Uso de DR": "Obrigatório"},
            {"Equipamento": "Geladeira Frost Free", "Potência (W)": 400, "Tensão (V)": 127, "Fator de Potência": 0.85, "Tipo": "TUG", "Curva Disjuntor": "C", "Uso de DR": "Opcional"},
            {"Equipamento": "Forno Elétrico de Embutir", "Potência (W)": 3500, "Tensão (V)": 220, "Fator de Potência": 1.0, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
            {"Equipamento": "Carregador Veículo Elétrico (Wallbox) 7kW", "Potência (W)": 7000, "Tensão (V)": 220, "Fator de Potência": 1.0, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
            {"Equipamento": "Bomba de Pressurização de Água", "Potência (W)": 750, "Tensão (V)": 127, "Fator de Potência": 0.75, "Tipo": "Dedicado", "Curva Disjuntor": "C", "Uso de DR": "Obrigatório"},
            {"Equipamento": "Lava e Seca (Roupas)", "Potência (W)": 750, "Tensão (V)": 127, "Fator de Potência": 0.7, "Tipo": "TUE", "Curva Disjuntor": "C", "Uso de DR": "Obrigatório"},
        ])

    if 'bib_gas_avac' not in st.session_state:
        st.session_state.bib_gas_avac = pd.DataFrame([
            {"Equipamento": "Fogão 4 Bocas c/ Forno (GLP/GN)", "Potencia_kcal_min": 135, "Pressao_kPa": 2.8, "Tubo_Cobre_mm": 15, "Norma": "NBR 15526"},
            {"Equipamento": "Fogão 6 Bocas Gourmet (GLP/GN)", "Potencia_kcal_min": 210, "Pressao_kPa": 2.8, "Tubo_Cobre_mm": 22, "Norma": "NBR 15526"},
            {"Equipamento": "Aquecedor de Passagem 21 L/min", "Potencia_kcal_min": 500, "Pressao_kPa": 2.8, "Tubo_Cobre_mm": 22, "Norma": "NBR 15526"},
            {"Equipamento": "Aquecedor de Passagem 35 L/min", "Potencia_kcal_min": 815, "Pressao_kPa": 2.8, "Tubo_Cobre_mm": 28, "Norma": "NBR 15526"},
            {"Equipamento": "Evaporadora Split 9.000/12.000 BTU", "Potencia_kcal_min": 0, "Pressao_kPa": 0, "Tubo_Cobre_mm": 9.52, "Norma": "NBR 16401 (Dreno 25mm)"},
            {"Equipamento": "Evaporadora Split 18.000/24.000 BTU", "Potencia_kcal_min": 0, "Pressao_kPa": 0, "Tubo_Cobre_mm": 15.87, "Norma": "NBR 16401 (Dreno 25mm)"},
        ])

inicializar_bibliotecas_internas()

# ==========================================
# 2.B FUNÇÕES DE SAVE / LOAD E EXPORTAÇÃO EXCEL
# ==========================================
def exportar_projeto():
    estado = {
        "circuitos": st.session_state.circuitos.to_dict('records') if not st.session_state.circuitos.empty else [],
        "pontos_hidro": st.session_state.pontos_hidro,
        "linhas_3d_master": st.session_state.linhas_3d_master,
        "contexto_bim": st.session_state.contexto_bim,
        "colisoes_detectadas": st.session_state.colisoes_detectadas,
        "bib_hidro": st.session_state.bib_hidro.to_dict('records'),
        "bib_eletrica": st.session_state.bib_eletrica.to_dict('records'),
        "bib_gas_avac": st.session_state.bib_gas_avac.to_dict('records')
    }
    return json.dumps(estado, ensure_ascii=False, indent=2)

def importar_projeto(arquivo_json):
    dados = json.load(arquivo_json)
    st.session_state.circuitos = pd.DataFrame(dados.get("circuitos", []))
    st.session_state.pontos_hidro = dados.get("pontos_hidro", [])
    st.session_state.linhas_3d_master = dados.get("linhas_3d_master", {'eletrica': [], 'hidro': [], 'equipamentos_3d': []})
    st.session_state.contexto_bim = dados.get("contexto_bim", {})
    st.session_state.colisoes_detectadas = dados.get("colisoes_detectadas", [])
    if "bib_hidro" in dados:
        st.session_state.bib_hidro = pd.DataFrame(dados["bib_hidro"])
    if "bib_eletrica" in dados:
        st.session_state.bib_eletrica = pd.DataFrame(dados["bib_eletrica"])
    if "bib_gas_avac" in dados:
        st.session_state.bib_gas_avac = pd.DataFrame(dados["bib_gas_avac"])

def gerar_arquivo_excel_completo():
    buffer = io.BytesIO()
    try:
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            st.session_state.circuitos.to_excel(writer, sheet_name='Quadro_Cargas_NBR5410', index=False)
            pd.DataFrame(st.session_state.pontos_hidro).to_excel(writer, sheet_name='Hidrossanitario_NBR5626', index=False)
            st.session_state.quantitativos_master['eletrica'].to_excel(writer, sheet_name='BOM_Eletrica', index=False)
            st.session_state.quantitativos_master['agua_fria'].to_excel(writer, sheet_name='BOM_Agua_Fria', index=False)
            st.session_state.quantitativos_master['esgoto'].to_excel(writer, sheet_name='BOM_Esgoto', index=False)
        return buffer.getvalue(), "Projeto_Executivo_MEP.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    except Exception:
        try:
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                st.session_state.circuitos.to_excel(writer, sheet_name='Quadro_Cargas_NBR5410', index=False)
                pd.DataFrame(st.session_state.pontos_hidro).to_excel(writer, sheet_name='Hidrossanitario_NBR5626', index=False)
                st.session_state.quantitativos_master['eletrica'].to_excel(writer, sheet_name='BOM_Eletrica', index=False)
            return buffer.getvalue(), "Projeto_Executivo_MEP.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        except Exception:
            csv_bytes = st.session_state.circuitos.to_csv(index=False).encode('utf-8-sig')
            return csv_bytes, "Projeto_Executivo_MEP.csv", "text/csv"

# ==========================================
# 3. MOTOR GEOMÉTRICO E DIMENSIONAMENTO NORMATIVO
# ==========================================
def escalar_coord(val, fator=10): return int(round(val * fator))
def desescalar_coord(val, fator=10): return val / fator
def dist_3d(p1, p2): return math.sqrt((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2 + (p2[2]-p1[2])**2)
def dist_2d(p1, p2): return math.sqrt((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2)

def calcular_comprimento_rota(pontos):
    return sum(dist_3d(pontos[i], pontos[i+1]) for i in range(len(pontos)-1))

def algoritmo_bresenham(x0, y0, x1, y1):
    pontos = []
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx - dy
    while True:
        pontos.append((x0, y0))
        if x0 == x1 and y0 == y1: break
        e2 = 2 * err
        if e2 > -dy: err -= dy; x0 += sx
        if e2 < dx: err += dx; y0 += sy
    return pontos

def liberar_caixa(matriz, x, y, w, h, raio=2):
    for dy in range(-raio, raio+1):
        for dx in range(-raio, raio+1):
            if 0 <= y+dy < h and 0 <= x+dx < w:
                matriz[y+dy][x+dx] = 1

def bloquear_caixa_estrutural(matriz, x, y, w, h, raio=2):
    for dy in range(-raio, raio+1):
        for dx in range(-raio, raio+1):
            if 0 <= y+dy < h and 0 <= x+dx < w:
                matriz[y+dy][x+dx] = 0

def discretizar_linha(p1, p2, passo=0.1):
    d = dist_3d(p1, p2)
    if d == 0: return [p1]
    pts = []
    passos = int(d / passo) + 1
    for i in range(passos):
        t = i * passo / d
        if t > 1: t = 1
        pts.append((p1[0] + t*(p2[0]-p1[0]), p1[1] + t*(p2[1]-p1[1]), p1[2] + t*(p2[2]-p1[2])))
    return pts

def checar_clash_detection(linhas_eletrica, linhas_hidro, tolerancia_metros=0.15):
    colisoes = []
    pts_eletrica = []
    for rota in linhas_eletrica:
        for j in range(len(rota['pontos'])-1):
            for p in discretizar_linha(rota['pontos'][j], rota['pontos'][j+1]):
                pts_eletrica.append({"coord": p, "info": rota.get('fios', 'Eletroduto')})
            
    for rota in linhas_hidro:
        for j in range(len(rota['pontos'])-1):
            for ph in discretizar_linha(rota['pontos'][j], rota['pontos'][j+1]):
                for pe in pts_eletrica:
                    if dist_3d(ph, pe["coord"]) < tolerancia_metros:
                        colisoes.append({"coord": ph, "el_info": pe["info"], "hd_info": rota.get('tipo', 'Tubo')})
                        break
    return colisoes

def dimensionar_tubo_agua(soma_pesos):
    if soma_pesos <= 0: return 20
    vazao_ls = 0.30 * math.sqrt(soma_pesos)
    diametros_comerciais = [20, 25, 32, 40, 50, 60, 75, 85, 110]
    for d_mm in diametros_comerciais:
        d_int_m = (d_mm * 0.88) / 1000.0
        area_m2 = math.pi * ((d_int_m / 2.0) ** 2)
        vel_ms = (vazao_ls / 1000.0) / area_m2
        if vel_ms <= 2.8:
            if soma_pesos <= 1.1: return max(20, d_mm)
            elif soma_pesos <= 3.5: return max(25, d_mm)
            elif soma_pesos <= 18.0: return max(32, d_mm)
            elif soma_pesos <= 44.0: return max(40, d_mm)
            elif soma_pesos <= 100.0: return max(50, d_mm)
            return d_mm
    return 60

def calcular_perda_carga_nbr5626(soma_pesos, diam_mm, comp_real_m, qtd_joelhos90=2, qtd_tes=1, qtd_registros=1):
    if soma_pesos <= 0 or diam_mm <= 0:
        return 0.0, 0.0, 0.0, 0.0
    vazao_ls = 0.30 * math.sqrt(soma_pesos)
    vazao_m3s = vazao_ls / 1000.0
    d_int_m = (diam_mm * 0.88) / 1000.0
    j_unit = 0.000859 * (vazao_m3s ** 1.75) * (d_int_m ** -4.75)
    d_ref = min(COMPRIMENTO_EQUIVALENTE_CONEXOES["Joelho 90°"].keys(), key=lambda k: abs(k - diam_mm))
    comp_eq = (
        qtd_joelhos90 * COMPRIMENTO_EQUIVALENTE_CONEXOES["Joelho 90°"][d_ref] +
        qtd_tes * COMPRIMENTO_EQUIVALENTE_CONEXOES["Tê 90° (Saída Lat.)"][d_ref] +
        qtd_registros * COMPRIMENTO_EQUIVALENTE_CONEXOES["Registro de Pressão"][d_ref] +
        COMPRIMENTO_EQUIVALENTE_CONEXOES["Saída de Canalização"][d_ref]
    )
    perda_total_mca = j_unit * (comp_real_m + comp_eq)
    return round(vazao_ls, 3), round(j_unit, 4), round(comp_eq, 2), round(perda_total_mca, 2)

def dimensionar_tubo_esgoto(soma_uhc):
    if soma_uhc <= 3: return 40
    elif soma_uhc <= 6: return 50
    elif soma_uhc <= 20: return 75
    else: return 100

def dimensionar_circuito_nbr5410(potencia_w, tensao_v, fp=0.95, metodo="B1", fca=0.80, fct=1.00, dist_m=15.0, tipo_circ="TUG", material="Cobre", isolacao="70°C (PVC)"):
    corrente_ib = potencia_w / (tensao_v * fp) if (tensao_v * fp) > 0 else 0.0
    corrente_corrigida = corrente_ib / (fca * fct) if (fca * fct) > 0 else corrente_ib
    secao_minima = 1.5 if str(tipo_circ).strip() == "Iluminação" else 2.5
    n_cond_carregados = 2 if tensao_v in [127, 220] else 3

    if "90" in isolacao: chave_metodo = "B1_90"
    elif metodo == "A1": chave_metodo = "A1_2"
    elif metodo == "B1": chave_metodo = f"B1_{n_cond_carregados}"
    elif metodo == "B2": chave_metodo = "B2_2"
    else: chave_metodo = "C_2"

    bitola_escolhida = 50.0
    iz_escolhido = 151.0
    queda_tensao_pct = 0.0
    rho = 0.0172 if material == "Cobre" else 0.0282

    for bitola, dados in sorted(TABELA_AMPACIDADE_NBR5410.items()):
        if bitola < secao_minima: continue
        iz_tabela = dados.get(chave_metodo, dados["B1_2"])
        if iz_tabela >= corrente_corrigida:
            dv_volts = 2.0 * rho * dist_m * corrente_ib / bitola
            dv_pct = (dv_volts / tensao_v) * 100.0 if tensao_v > 0 else 0.0
            if dv_pct <= 4.0:
                bitola_escolhida = bitola
                iz_escolhido = iz_tabela * fca * fct
                queda_tensao_pct = dv_pct
                break

    disjuntor_in = calcular_disjuntor(corrente_ib, iz_escolhido)
    while disjuntor_in > iz_escolhido and bitola_escolhida < 50.0:
        bitolas_lista = sorted(list(TABELA_AMPACIDADE_NBR5410.keys()))
        idx_b = bitolas_lista.index(bitola_escolhida)
        if idx_b + 1 < len(bitolas_lista):
            bitola_escolhida = bitolas_lista[idx_b + 1]
            iz_escolhido = TABELA_AMPACIDADE_NBR5410[bitola_escolhida].get(chave_metodo, 50.0) * fca * fct
        else:
            break

    area_cabo = TABELA_AMPACIDADE_NBR5410[bitola_escolhida]["Area_Ext_mm2"]
    area_ocupada_total = 3 * area_cabo
    eletroduto_mm = 20
    ocupacao_pct = 0.0
    for dn_elet, area_int in sorted(ELETRODUTOS_NBR5410.items()):
        if dn_elet < 20: continue
        taxa = (area_ocupada_total / area_int) * 100.0
        if taxa <= 40.0:
            eletroduto_mm = dn_elet
            ocupacao_pct = taxa
            break

    icc_amp = calcular_icc(tensao_v, bitola_escolhida, dist_m, material)
    return {
        "Corrente_Ib": round(corrente_ib, 2), "Corrente_Corr": round(corrente_corrigida, 2),
        "Bitola": bitola_escolhida, "Queda_Tensao_Pct": round(queda_tensao_pct, 2),
        "Disjuntor": disjuntor_in, "Icc_A": icc_amp, "Eletroduto_mm": eletroduto_mm, "Ocupacao_Pct": round(ocupacao_pct, 1)
    }

def balancear_fases_automatico(df_circuitos):
    if df_circuitos.empty: return df_circuitos
    cargas_fases = {"R": 0.0, "S": 0.0, "T": 0.0}
    indices_ordenados = df_circuitos.sort_values(by="Potência Total (W)", ascending=False).index
    for idx in indices_ordenados:
        pot = float(df_circuitos.loc[idx, "Potência Total (W)"])
        tensao = int(df_circuitos.loc[idx, "Tensão (V)"])
        if tensao >= 220:
            fases_ord = sorted(cargas_fases.keys(), key=lambda f: cargas_fases[f])
            f1, f2 = fases_ord[0], fases_ord[1]
            df_circuitos.loc[idx, "Fase"] = f"{f1}+{f2}"
            cargas_fases[f1] += pot / 2.0
            cargas_fases[f2] += pot / 2.0
        else:
            fase_min = min(cargas_fases, key=cargas_fases.get)
            df_circuitos.loc[idx, "Fase"] = fase_min
            cargas_fases[fase_min] += pot
    return df_circuitos

def aplicar_desvios_estruturais_e_vaos_3d(linha_3d, elementos_arq, z_base, pe_direito, h_viga=0.40):
    if not elementos_arq or len(linha_3d) < 2: return linha_3d
    nova_linha = [linha_3d[0]]
    for i in range(len(linha_3d) - 1):
        p_ini, p_fim = linha_3d[i], linha_3d[i + 1]
        z_seg = p_fim[2]
        desviou = False
        for elem in elementos_arq:
            if abs(elem.get('z_base', 0) - z_base) > 0.5: continue
            ex, ey = elem['x'], elem['y']
            raio_inf = elem.get('Largura', 1.0) / 2.0 + 0.15
            if dist_2d(p_ini, p_fim) > 0.05 and (dist_2d(p_ini, (ex, ey)) <= raio_inf or dist_2d(p_fim, (ex, ey)) <= raio_inf):
                if elem['Tipo'] == 'Pilar/Viga' and z_seg >= (z_base + pe_direito - h_viga):
                    z_sob_viga = z_base + pe_direito - h_viga - 0.05
                    nova_linha.extend([(p_ini[0], p_ini[1], z_sob_viga), (p_fim[0], p_fim[1], z_sob_viga), p_fim])
                    desviou = True
                    break
                elif elem['Tipo'] == 'Esquadria':
                    peitoril = elem.get('Peitoril', 0.0)
                    altura_esq = elem.get('Altura', 2.10)
                    if (z_base + peitoril) <= z_seg <= (z_base + peitoril + altura_esq):
                        z_desvio = (z_base + peitoril - 0.15) if peitoril >= 0.5 else min(z_base + pe_direito - 0.10, z_base + peitoril + altura_esq + 0.15)
                        nova_linha.extend([(p_ini[0], p_ini[1], z_desvio), (p_fim[0], p_fim[1], z_desvio), p_fim])
                        desviou = True
                        break
        if not desviou: nova_linha.append(p_fim)
    return nova_linha

def rotear_hidro(df_bh, ctx):
    linhas_processadas = []
    matriz = [[1 for _ in range(ctx['grid_w'])] for _ in range(ctx['grid_h'])]
    for (p1_x, p1_y, _), (p2_x, p2_y, _) in ctx['paredes']:
        x0, y0 = escalar_coord(p1_x - ctx['min_x'] + ctx['offset']), escalar_coord(p1_y - ctx['min_y'] + ctx['offset'])
        x1, y1 = escalar_coord(p2_x - ctx['min_x'] + ctx['offset']), escalar_coord(p2_y - ctx['min_y'] + ctx['offset'])
        for px, py in algoritmo_bresenham(x0, y0, x1, y1):
            if 0 <= py < ctx['grid_h'] and 0 <= px < ctx['grid_w']: matriz[py][px] = 0

    elementos_arq = ctx.get('elementos_arquitetonicos', [])
    for elem in elementos_arq:
        if elem['Tipo'] == 'Pilar/Viga' and 'PILAR' in elem['ID_CAD'].upper():
            px, py = escalar_coord(elem['x'] - ctx['min_x'] + ctx['offset']), escalar_coord(elem['y'] - ctx['min_y'] + ctx['offset'])
            bloquear_caixa_estrutural(matriz, px, py, ctx['grid_w'], ctx['grid_h'], raio=2)

    h_af, h_aq, h_viga = ctx.get('h_agua_fria', 2.2), ctx.get('h_agua_quente', 1.1), ctx.get('altura_viga', 0.40)
    prumadas_af = [b for b in df_bh if b['Tipo_BIM'] == 'Prumada Água Fria']
    prumadas_esg = [b for b in df_bh if b['Tipo_BIM'] == 'Prumada Esgoto']
    caixas_dagua = [b for b in df_bh if b['Tipo_BIM'] == "Caixa d'Água"]

    equips_af_validos = set(st.session_state.bib_hidro[st.session_state.bib_hidro['Agua_mm'] > 0]['Equipamento'].values)
    equips_aq_validos = set(st.session_state.bib_hidro[st.session_state.bib_hidro.get('AQ_mm', pd.Series([0]*len(st.session_state.bib_hidro))) > 0]['Equipamento'].values)

    if caixas_dagua and prumadas_af:
        cx_sup = caixas_dagua[0]
        z_barrilete = cx_sup['z_base'] + 0.20
        for prum in prumadas_af:
            pts_barrilete = [(cx_sup['x'], cx_sup['y'], cx_sup['z_base'] + ctx.get('altura_caixa', 1.5)), (cx_sup['x'], cx_sup['y'], z_barrilete), (prum['x'], cx_sup['y'], z_barrilete), (prum['x'], prum['y'], z_barrilete), (prum['x'], prum['y'], 0.0)]
            linhas_processadas.append({'pontos': pts_barrilete, 'cor': '#0044cc', 'tipo': 'Barrilete / Coluna AF', 'diametro': 50})

    if prumadas_af:
        prum_af = prumadas_af[0]
        paf_x, paf_y = escalar_coord(prum_af['x'] - ctx['min_x'] + ctx['offset']), escalar_coord(prum_af['y'] - ctx['min_y'] + ctx['offset'])
        liberar_caixa(matriz, paf_x, paf_y, ctx['grid_w'], ctx['grid_h'])
        soma_pesos = 0.0
        for ap in df_bh:
            if ap['Tipo_BIM'] == 'Aparelho Hidráulico' and ap['Equipamento'] in equips_af_validos:
                filtro_eq = st.session_state.bib_hidro['Equipamento'] == ap['Equipamento']
                peso_ap = float(st.session_state.bib_hidro.loc[filtro_eq, 'Peso'].values[0])
                soma_pesos += peso_ap
                diametro_calculado = dimensionar_tubo_agua(soma_pesos)
                ap_x, ap_y = escalar_coord(ap['x'] - ctx['min_x'] + ctx['offset']), escalar_coord(ap['y'] - ctx['min_y'] + ctx['offset'])
                liberar_caixa(matriz, ap_x, ap_y, ctx['grid_w'], ctx['grid_h'])
                grid = Grid(matrix=matriz)
                finder = AStarFinder(diagonal_movement=DiagonalMovement.never)
                caminho_2d, _ = finder.find_path(grid.node(ap_x, ap_y), grid.node(paf_x, paf_y), grid)
                if caminho_2d:
                    linha_3d = [(ap['x'], ap['y'], ap['z_base'] + ap.get('z_relativo', 0.6)), (ap['x'], ap['y'], ap['z_base'] + h_af)]
                    for p in caminho_2d: linha_3d.append((desescalar_coord(p.x) + ctx['min_x'] - ctx['offset'], desescalar_coord(p.y) + ctx['min_y'] - ctx['offset'], ap['z_base'] + h_af))
                    linha_3d.append((prum_af['x'], prum_af['y'], ap['z_base'] + h_af))
                    linha_3d = aplicar_desvios_estruturais_e_vaos_3d(linha_3d, elementos_arq, ap['z_base'], ap.get('pe_direito', 3.0), h_viga)
                    linhas_processadas.append({'pontos': linha_3d, 'cor': 'blue', 'tipo': 'Água Fria', 'diametro': diametro_calculado, 'equipamento': ap['Equipamento'], 'id_ap': ap['ID_CAD']})

                    if ap['Equipamento'] in equips_aq_validos:
                        linha_aq = [(ap['x'] + 0.10, ap['y'], ap['z_base'] + ap.get('z_relativo', 0.6)), (ap['x'] + 0.10, ap['y'], ap['z_base'] + h_aq)]
                        for p in caminho_2d: linha_aq.append((desescalar_coord(p.x) + ctx['min_x'] - ctx['offset'] + 0.08, desescalar_coord(p.y) + ctx['min_y'] - ctx['offset'], ap['z_base'] + h_aq))
                        linha_aq.append((prum_af['x'] + 0.08, prum_af['y'], ap['z_base'] + h_aq))
                        linha_aq = aplicar_desvios_estruturais_e_vaos_3d(linha_aq, elementos_arq, ap['z_base'], ap.get('pe_direito', 3.0), h_viga)
                        linhas_processadas.append({'pontos': linha_aq, 'cor': 'red', 'tipo': 'Água Quente', 'diametro': 22, 'equipamento': ap['Equipamento'], 'id_ap': ap['ID_CAD']})

    if prumadas_esg:
        prum_esg = prumadas_esg[0]
        pe_x, pe_y = escalar_coord(prum_esg['x'] - ctx['min_x'] + ctx['offset']), escalar_coord(prum_esg['y'] - ctx['min_y'] + ctx['offset'])
        liberar_caixa(matriz, pe_x, pe_y, ctx['grid_w'], ctx['grid_h'])
        z_topo_vent = ctx.get('max_z_cobertura', 6.0) + 0.30
        linhas_processadas.append({'pontos': [(prum_esg['x'], prum_esg['y'], z_topo_vent), (prum_esg['x'], prum_esg['y'], 0.0)], 'cor': '#5c3a21', 'tipo': 'Tubo de Queda (TQ)', 'diametro': 100})
        linhas_processadas.append({'pontos': [(prum_esg['x'] + 0.15, prum_esg['y'], z_topo_vent), (prum_esg['x'] + 0.15, prum_esg['y'], 0.0)], 'cor': '#2ca02c', 'tipo': 'Coluna de Ventilação', 'diametro': 50})
        soma_uhc = 0.0
        for ap in df_bh:
            if ap['Tipo_BIM'] == 'Aparelho Hidráulico':
                filtro_eq = st.session_state.bib_hidro['Equipamento'] == ap['Equipamento']
                if not filtro_eq.any(): continue
                uhc_ap = float(st.session_state.bib_hidro.loc[filtro_eq, 'UHC'].values[0])
                esg_mm_ap = int(st.session_state.bib_hidro.loc[filtro_eq, 'Esgoto_mm'].values[0])
                if esg_mm_ap <= 0: continue
                soma_uhc += uhc_ap
                diam_esg = max(esg_mm_ap, dimensionar_tubo_esgoto(soma_uhc))
                declividade = 0.01 if diam_esg >= 100 else 0.02
                ap_x, ap_y = escalar_coord(ap['x'] - ctx['min_x'] + ctx['offset']), escalar_coord(ap['y'] - ctx['min_y'] + ctx['offset'])
                liberar_caixa(matriz, ap_x, ap_y, ctx['grid_w'], ctx['grid_h'])
                grid = Grid(matrix=matriz)
                finder = AStarFinder(diagonal_movement=DiagonalMovement.always)
                caminho_2d, _ = finder.find_path(grid.node(ap_x, ap_y), grid.node(pe_x, pe_y), grid)
                if caminho_2d:
                    z_inicio_ramal = ap['z_base'] - 0.15
                    linha_3d = [(ap['x'], ap['y'], ap['z_base'] + ap.get('z_relativo', 0.1)), (ap['x'], ap['y'], z_inicio_ramal)]
                    dist_acum, pt_ant = 0.0, (ap['x'], ap['y'])
                    for p in caminho_2d:
                        px_real, py_real = desescalar_coord(p.x) + ctx['min_x'] - ctx['offset'], desescalar_coord(p.y) + ctx['min_y'] - ctx['offset']
                        dist_acum += dist_2d(pt_ant, (px_real, py_real))
                        linha_3d.append((px_real, py_real, z_inicio_ramal - (dist_acum * declividade)))
                        pt_ant = (px_real, py_real)
                    linha_3d.append((prum_esg['x'], prum_esg['y'], z_inicio_ramal - (dist_acum * declividade)))
                    linhas_processadas.append({'pontos': linha_3d, 'cor': 'brown', 'tipo': 'Esgoto', 'diametro': diam_esg, 'declividade_pct': declividade * 100, 'equipamento': ap['Equipamento'], 'id_ap': ap['ID_CAD']})
    return linhas_processadas

def rotear_eletrica(df_be, ctx, evitar_linhas=None):
    matriz = [[1 for _ in range(ctx['grid_w'])] for _ in range(ctx['grid_h'])]
    for (p1_x, p1_y, _), (p2_x, p2_y, _) in ctx['paredes']:
        x0, y0 = escalar_coord(p1_x - ctx['min_x'] + ctx['offset']), escalar_coord(p1_y - ctx['min_y'] + ctx['offset'])
        x1, y1 = escalar_coord(p2_x - ctx['min_x'] + ctx['offset']), escalar_coord(p2_y - ctx['min_y'] + ctx['offset'])
        for px, py in algoritmo_bresenham(x0, y0, x1, y1):
            if 0 <= py < ctx['grid_h'] and 0 <= px < ctx['grid_w']: matriz[py][px] = 0

    elementos_arq = ctx.get('elementos_arquitetonicos', [])
    for elem in elementos_arq:
        if elem['Tipo'] == 'Pilar/Viga' and 'PILAR' in elem['ID_CAD'].upper():
            px, py = escalar_coord(elem['x'] - ctx['min_x'] + ctx['offset']), escalar_coord(elem['y'] - ctx['min_y'] + ctx['offset'])
            bloquear_caixa_estrutural(matriz, px, py, ctx['grid_w'], ctx['grid_h'], raio=2)

    if evitar_linhas:
        for linha in evitar_linhas:
            pts = linha['pontos']
            for i in range(len(pts)-1):
                x0, y0 = escalar_coord(pts[i][0] - ctx['min_x'] + ctx['offset']), escalar_coord(pts[i][1] - ctx['min_y'] + ctx['offset'])
                x1, y1 = escalar_coord(pts[i+1][0] - ctx['min_x'] + ctx['offset']), escalar_coord(pts[i+1][1] - ctx['min_y'] + ctx['offset'])
                for px, py in algoritmo_bresenham(x0, y0, x1, y1):
                    for dy in [-1, 0, 1]:
                        for dx in [-1, 0, 1]:
                            if 0 <= py+dy < ctx['grid_h'] and 0 <= px+dx < ctx['grid_w']: matriz[py+dy][px+dx] = 0

    linhas_processadas = []
    qg = next((b for b in df_be if b['Tipo_BIM'] == 'Quadro Geral'), None)
    h_viga, usar_shaft = ctx.get('altura_viga', 0.40), ctx.get('incluir_shaft', True)

    def achar_caminho(origem, destino, cor, fios, id_ref=""):
        ox, oy = escalar_coord(origem['x'] - ctx['min_x'] + ctx['offset']), escalar_coord(origem['y'] - ctx['min_y'] + ctx['offset'])
        dx, dy = escalar_coord(destino['x'] - ctx['min_x'] + ctx['offset']), escalar_coord(destino['y'] - ctx['min_y'] + ctx['offset'])
        liberar_caixa(matriz, ox, oy, ctx['grid_w'], ctx['grid_h'])
        liberar_caixa(matriz, dx, dy, ctx['grid_w'], ctx['grid_h'])
        grid = Grid(matrix=matriz)
        finder = AStarFinder(diagonal_movement=DiagonalMovement.never)
        caminho_2d, _ = finder.find_path(grid.node(ox, oy), grid.node(dx, dy), grid)
        if caminho_2d:
            z_origem_teto = origem['z_base'] + origem.get('pe_direito', 3.0)
            z_destino_teto = destino['z_base'] + destino.get('pe_direito', 3.0)
            linha_3d = [(origem['x'], origem['y'], origem['z_base'] + origem['z_relativo'])]
            if usar_shaft and abs(origem['z_base'] - destino['z_base']) > 0.1:
                linha_3d.append((origem['x'], origem['y'], z_origem_teto))
                for p in caminho_2d: linha_3d.append((desescalar_coord(p.x) + ctx['min_x'] - ctx['offset'], desescalar_coord(p.y) + ctx['min_y'] - ctx['offset'], z_origem_teto))
                linha_3d.extend([(destino['x'], destino['y'], z_origem_teto), (destino['x'], destino['y'], z_destino_teto)])
            else:
                z_nav = max(z_origem_teto, z_destino_teto)
                linha_3d.append((origem['x'], origem['y'], z_nav))
                for p in caminho_2d: linha_3d.append((desescalar_coord(p.x) + ctx['min_x'] - ctx['offset'], desescalar_coord(p.y) + ctx['min_y'] - ctx['offset'], z_nav))
                linha_3d.append((destino['x'], destino['y'], z_nav))
            linha_3d.append((destino['x'], destino['y'], destino['z_base'] + destino['z_relativo']))
            linha_3d = aplicar_desvios_estruturais_e_vaos_3d(linha_3d, elementos_arq, origem['z_base'], origem.get('pe_direito', 3.0), h_viga)
            linhas_processadas.append({'pontos': linha_3d, 'cor': cor, 'fios': fios, 'id_origem': id_ref, 'comprimento_m': round(calcular_comprimento_rota(linha_3d), 2)})

    if qg:
        luminarias = {b['ID_CAD']: b for b in df_be if b['Tipo_BIM'] == 'Luminária'}
        caixas = {b['ID_CAD']: b for b in df_be if 'Caixa' in b['Tipo_BIM']}
        controle_lum = {lum_id: [] for lum_id in luminarias.keys()}
        for cx_id, cx_dados in caixas.items():
            if cx_dados.get('Qtd_Tomadas', 0) > 0: achar_caminho(cx_dados, qg, 'yellow' if evitar_linhas else 'green', 'F N T', cx_id)
            if cx_dados.get('Qtd_Interruptores', 0) > 0 and cx_dados.get('Luminarias_Controladas'):
                for l in [l.strip() for l in str(cx_dados['Luminarias_Controladas']).split(',') if l.strip()]:
                    if l in controle_lum: controle_lum[l].append(cx_id)

        for lum_id, lum in luminarias.items():
            achar_caminho(lum, qg, 'cyan', 'N T', lum_id)
            caixas_comando = controle_lum.get(lum_id, [])
            if len(caixas_comando) == 1:
                achar_caminho(caixas[caixas_comando[0]], lum, 'orange', 'F R', caixas_comando[0])
            elif len(caixas_comando) == 2:
                cx1, cx2 = caixas[caixas_comando[0]], caixas[caixas_comando[1]]
                achar_caminho(cx1, qg, 'orange', 'F', cx1['ID_CAD'])
                achar_caminho(cx1, cx2, 'orange', '2R (3W)', cx1['ID_CAD'])
                achar_caminho(cx2, lum, 'orange', 'R', cx2['ID_CAD'])
            elif len(caixas_comando) >= 3:
                cx_inicio, cx_fim = caixas[caixas_comando[0]], caixas[caixas_comando[-1]]
                achar_caminho(cx_inicio, qg, 'orange', 'F', cx_inicio['ID_CAD'])
                cx_atual = cx_inicio
                for cx_meio_id in caixas_comando[1:-1]:
                    achar_caminho(cx_atual, caixas[cx_meio_id], '#ff5500', '4R (4W)', cx_atual['ID_CAD'])
                    cx_atual = caixas[cx_meio_id]
                achar_caminho(cx_atual, cx_fim, 'orange', '2R (3W)', cx_atual['ID_CAD'])
                achar_caminho(cx_fim, lum, 'orange', 'R', cx_fim['ID_CAD'])
    return linhas_processadas

# ==========================================
# 3.B QUANTITATIVOS TOTAIS (BOM)
# ==========================================
def calcular_angulo_deflexao(p_ant, p_atual, p_prox):
    v1 = (p_atual[0] - p_ant[0], p_atual[1] - p_ant[1], p_atual[2] - p_ant[2])
    v2 = (p_prox[0] - p_atual[0], p_prox[1] - p_atual[1], p_prox[2] - p_atual[2])
    m1, m2 = math.sqrt(sum(c**2 for c in v1)), math.sqrt(sum(c**2 for c in v2))
    if m1 < 1e-4 or m2 < 1e-4: return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(v1[k]*v2[k] for k in range(3)) / (m1 * m2)))))

def gerar_quantitativos_totais_bim(linhas_elet, linhas_hidro, df_circuitos, df_be, df_bh):
    bom_af, bom_aq, bom_esg = {}, {}, {}
    def add_item(d, item, unid, qtd): d[(item, unid)] = d.get((item, unid), 0.0) + qtd

    for rota in linhas_hidro:
        pts, tipo, dn = rota['pontos'], rota.get('tipo', 'Água Fria'), int(rota.get('diametro', 25))
        comp_m = calcular_comprimento_rota(pts)
        j90, j45 = 0, 0
        for i in range(1, len(pts) - 1):
            ang = calcular_angulo_deflexao(pts[i-1], pts[i], pts[i+1])
            if 70 <= ang <= 115: j90 += 1
            elif 25 <= ang < 70: j45 += 1
        luvas = int(comp_m // 3.0) + 1
        if 'Água Fria' in tipo or 'Barrilete' in tipo:
            add_item(bom_af, f"Tubo PVC Soldável Marrom DN {dn}mm", "m", round(comp_m * 1.05, 1))
            if j90 > 0: add_item(bom_af, f"Joelho 90° Soldável {dn}mm", "un", j90)
            if j45 > 0: add_item(bom_af, f"Joelho 45° Soldável {dn}mm", "un", j45)
            add_item(bom_af, f"Tê 90° Soldável {dn}mm", "un", 1)
            add_item(bom_af, f"Luva Soldável {dn}mm", "un", luvas)
            if 'Barrilete' not in tipo:
                add_item(bom_af, f"Joelho 90° c/ Bucha de Latão {dn}mm x 1/2\"", "un", 1)
                add_item(bom_af, f"Registro de Pressão / Gaveta {dn}mm", "un", 1)
        elif 'Água Quente' in tipo:
            add_item(bom_aq, f"Tubo CPVC/PPR Água Quente DN {dn}mm", "m", round(comp_m * 1.05, 1))
            if j90 > 0: add_item(bom_aq, f"Joelho 90° CPVC/PPR {dn}mm", "un", j90)
            if j45 > 0: add_item(bom_aq, f"Joelho 45° CPVC/PPR {dn}mm", "un", j45)
            add_item(bom_aq, f"Tê 90° CPVC/PPR {dn}mm", "un", 1)
            add_item(bom_aq, f"Misturador / Conector Metálico {dn}mm", "un", 1)
        else:
            add_item(bom_esg, f"Tubo PVC Esgoto Série Normal DN {dn}mm", "m", round(comp_m * 1.05, 1))
            if j45 > 0: add_item(bom_esg, f"Joelho 45° Esgoto {dn}mm", "un", j45)
            if j90 > 0: add_item(bom_esg, f"Curva Curta 90° Esgoto {dn}mm", "un", j90)
            add_item(bom_esg, f"Junção Simples 45° (Y) Esgoto {dn}mm", "un", 1)
            add_item(bom_esg, f"Luva Simples c/ Anel de Borracha {dn}mm", "un", luvas)

    if df_bh:
        add_item(bom_esg, "Caixa Sifonada 150x150x50mm c/ Grelha", "un", max(1, len(df_bh)//3))
        add_item(bom_esg, "Anel de Vedação p/ Esgoto c/ Lábio", "un", len(df_bh) * 3)

    bom_el = {}
    for rota in linhas_elet:
        pts, comp_m, fios_str = rota['pontos'], calcular_comprimento_rota(rota['pontos']) * 1.10, rota.get('fios', 'F N T')
        add_item(bom_el, "Eletroduto PVC Flexível Corrugado Reforçado DN 25mm", "m", round(comp_m, 1))
        curvas_el = sum(1 for i in range(1, len(pts)-1) if calcular_angulo_deflexao(pts[i-1], pts[i], pts[i+1]) >= 60)
        if curvas_el > 0: add_item(bom_el, "Curva 90° Eletroduto PVC 25mm / Luva de Emenda", "un", curvas_el)
        add_item(bom_el, "Par Bucha e Arruela Zamac 3/4\" (25mm)", "par", 2)
        if 'F' in fios_str: add_item(bom_el, "Cabo de Cobre Flexível 750V (Fase) 2.5mm²", "m", round(comp_m, 1))
        if 'N' in fios_str: add_item(bom_el, "Cabo de Cobre Flexível 750V (Neutro) 2.5mm²", "m", round(comp_m, 1))
        if 'T' in fios_str: add_item(bom_el, "Cabo de Cobre Flexível 750V (Terra PE) 2.5mm²", "m", round(comp_m, 1))
        if '4R' in fios_str: add_item(bom_el, "Cabo de Cobre Flexível 750V (Retorno Four-Way) 1.5mm²", "m", round(comp_m * 4, 1))
        elif '2R' in fios_str: add_item(bom_el, "Cabo de Cobre Flexível 750V (Retorno Three-Way) 1.5mm²", "m", round(comp_m * 2, 1))
        elif 'R' in fios_str: add_item(bom_el, "Cabo de Cobre Flexível 750V (Retorno Simples) 1.5mm²", "m", round(comp_m, 1))

    for b in df_be:
        tb = b.get('Tipo_BIM', '')
        if tb == 'Caixa 4x2': add_item(bom_el, "Caixa de Passagem Embutir 4x2\" PVC", "un", 1)
        elif tb == 'Caixa 4x4': add_item(bom_el, "Caixa de Passagem Embutir 4x4\" PVC", "un", 1)
        elif tb == 'Luminária': add_item(bom_el, "Caixa Octogonal de Laje 4x4\" Fundo Móvel", "un", 1)
        elif tb == 'Quadro Geral': add_item(bom_el, "Quadro de Distribuição Embutir c/ Barramento DIN", "un", 1)

    if not df_circuitos.empty:
        for _, r_c in df_circuitos.iterrows():
            disj, bit, dist = r_c.get('Disjuntor (A)', 16), r_c.get('Bitola (mm²)', 2.5), float(r_c.get('Distância (m)', 15.0))
            add_item(bom_el, f"Disjuntor Termomagnético DIN {disj}A", "un", 1)
            add_item(bom_el, f"Terminal Tubular Ilhós Isolado {bit}mm²", "un", 4)
        add_item(bom_el, "Interruptor Diferencial Residual (IDR) Tetrapolar 40A / 30mA", "un", 2)
        add_item(bom_el, "Dispositivo Protetor de Surtos (DPS) Classe II 275V 20kA", "un", 3)

    def dict_to_df(d):
        if not d: return pd.DataFrame(columns=["Descrição do Material / Peça", "Unid.", "Quantidade Total"])
        return pd.DataFrame([{"Descrição do Material / Peça": k[0], "Unid.": k[1], "Quantidade Total": round(v, 1)} for k, v in sorted(d.items())])

    return {'eletrica': dict_to_df(bom_el), 'agua_fria': dict_to_df(bom_af), 'agua_quente': dict_to_df(bom_aq), 'esgoto': dict_to_df(bom_esg)}

# ==========================================
# 3.C MOTOR DE DESENHO TÉCNICO CAD DE PEÇAS (EXPANDIDO - +20 ITENS)
# ==========================================
def gerar_desenho_tecnico_peca_plotly(peca_tipo, dn_mm=25):
    fig = go.Figure()
    d = float(dn_mm)
    esp, bolsa = max(2.0, d * 0.08), d * 0.65

    def add_cota(x0, y0, x1, y1, texto, offset_y=0.0, offset_x=0.0):
        fig.add_trace(go.Scatter(
            x=[x0+offset_x, x1+offset_x], y=[y0+offset_y, y1+offset_y],
            mode='lines+markers+text', line=dict(color='#d62728', width=1.5, dash='dot'),
            marker=dict(symbol='line-ns-open' if offset_y != 0 else 'line-ew-open', size=8, color='#d62728'),
            text=["", texto], textposition="top center" if offset_y >= 0 else "bottom center", showlegend=False
        ))

    if "Joelho 90°" in peca_tipo:
        r_m = d * 1.1
        fig.add_shape(type="rect", x0=-d/2-esp, y0=-r_m-bolsa, x1=d/2+esp, y1=d/2+esp, line=dict(color="#1f77b4", width=2.5), fillcolor="rgba(31,119,180,0.12)")
        fig.add_shape(type="rect", x0=-d/2-esp, y0=-d/2-esp, x1=r_m+bolsa, y1=d/2+esp, line=dict(color="#1f77b4", width=2.5), fillcolor="rgba(31,119,180,0.12)")
        add_cota(-d/2, -r_m-bolsa, d/2, -r_m-bolsa, f"DN {int(d)} mm", offset_y=-8)
    elif "Joelho 45°" in peca_tipo:
        L = d * 1.4
        fig.add_trace(go.Scatter(x=[-d/2, d/2, d/2 + L*0.7, L*0.7 - d/2, -d/2], y=[-L, -L, L*0.7, L*0.7 + d*0.7, -L], fill="toself", line=dict(color="#1f77b4", width=2.5)))
        add_cota(-d/2, -L, d/2, -L, f"DN {int(d)} mm (45°)", offset_y=-8)
    elif "Tê 90°" in peca_tipo:
        L = d * 1.8
        fig.add_shape(type="rect", x0=-L, y0=-d/2-esp, x1=L, y1=d/2+esp, line=dict(color="#1f77b4", width=2.5), fillcolor="rgba(31,119,180,0.12)")
        fig.add_shape(type="rect", x0=-d/2-esp, y0=0, x1=d/2+esp, y1=L, line=dict(color="#1f77b4", width=2.5), fillcolor="rgba(31,119,180,0.12)")
        add_cota(-L, -d/2-esp, L, -d/2-esp, f"Tê 90° DN {int(d)} mm", offset_y=-10)
    elif "Junção 45°" in peca_tipo or "Y" in peca_tipo:
        L = d * 2.0
        fig.add_shape(type="rect", x0=-L, y0=-d/2, x1=L, y1=d/2, line=dict(color="#8c564b", width=2.5), fillcolor="rgba(140,86,75,0.15)")
        fig.add_trace(go.Scatter(x=[-d/2, d/2, d/2 + L*0.7, -d/2 + L*0.7, -d/2], y=[0, 0, L*0.7, L*0.7, 0], fill="toself", line=dict(color="#8c564b", width=2.5)))
        add_cota(-L, -d/2, L, -d/2, f"Junção Y 45° DN {int(d)} mm", offset_y=-12)
    elif "Curva Longa" in peca_tipo:
        fig.add_shape(type="circle", x0=-d*1.5, y0=-d*1.5, x1=d*1.5, y1=d*1.5, line=dict(color="#1f77b4", width=3), fillcolor="rgba(31,119,180,0.1)")
        add_cota(-d*1.5, 0, d*1.5, 0, f"Curva Longa Raio 3x DN {int(d)} mm", offset_y=15)
    elif "Luva" in peca_tipo or "União" in peca_tipo:
        fig.add_shape(type="rect", x0=-d*0.8, y0=-d/2-esp*1.5, x1=d*0.8, y1=d/2+esp*1.5, line=dict(color="#2ca02c", width=2.5), fillcolor="rgba(44,160,44,0.15)")
        add_cota(-d*0.8, -d/2, d*0.8, -d/2, f"Luva de Correr/Simples DN {int(d)} mm", offset_y=-10)
    elif "Redução" in peca_tipo:
        fig.add_shape(type="rect", x0=-d, y0=-d/2, x1=0, y1=d/2, line=dict(color="#9467bd", width=2.5), fillcolor="rgba(148,103,189,0.15)")
        fig.add_shape(type="rect", x0=0, y0=-d*0.35, x1=d, y1=d*0.35, line=dict(color="#9467bd", width=2.5), fillcolor="rgba(148,103,189,0.15)")
        add_cota(-d, -d/2, d, -d/2, f"Redução Excêntrica / Conêntrica DN {int(d)} mm", offset_y=-10)
    elif "Cap" in peca_tipo or "Tampão" in peca_tipo:
        fig.add_shape(type="rect", x0=-d*0.3, y0=-d/2-esp, x1=0, y1=d/2+esp, line=dict(color="#8c564b", width=2.5), fillcolor="rgba(140,86,75,0.2)")
        add_cota(-d*0.3, -d/2, 0, -d/2, f"Cap / Bujão Roscado/Soldável {int(d)} mm", offset_y=-10)
    elif "Registro de Gaveta" in peca_tipo or "Registro de Pressão" in peca_tipo:
        fig.add_shape(type="rect", x0=-d, y0=-d/2, x1=d, y1=d/2, line=dict(color="#e377c2", width=2.5), fillcolor="rgba(227,119,194,0.15)")
        fig.add_shape(type="rect", x0=-d*0.2, y0=d/2, x1=d*0.2, y1=d*1.5, line=dict(color="#e377c2", width=2.5), fillcolor="rgba(227,119,194,0.15)")
        add_cota(-d, -d/2, d, -d/2, f"{peca_tipo} DN {int(d)} mm", offset_y=-10)
    elif "Caixa Sifonada" in peca_tipo or "Ralo" in peca_tipo:
        fig.add_shape(type="rect", x0=-75, y0=-150, x1=75, y1=0, line=dict(color="#2ca02c", width=2.5), fillcolor="rgba(44,160,44,0.1)")
        fig.add_shape(type="rect", x0=-72, y0=-148, x1=72, y1=-85, line=dict(color="#1f77b4", width=1), fillcolor="rgba(31,119,180,0.35)")
        fig.add_shape(type="line", x0=25, y0=-30, x1=25, y1=-115, line=dict(color="black", width=4))
        add_cota(-75, -148, 75, -85, "Fecho Hídrico ≥ 50 mm (NBR 8160)", offset_y=-15)
    elif "Caixa de Gordura" in peca_tipo or "Caixa de Inspeção" in peca_tipo:
        fig.add_shape(type="rect", x0=-120, y0=-120, x1=120, y1=120, line=dict(color="#8c564b", width=3), fillcolor="rgba(140,86,75,0.12)")
        add_cota(-120, -120, 120, -120, f"{peca_tipo} (Cesto Removível / Inspeção)", offset_y=-15)
    elif "Caixa" in peca_tipo or "Octogonal" in peca_tipo:
        fig.add_shape(type="rect", x0=-25, y0=-50, x1=25, y1=50, line=dict(color="#ff7f0e", width=3), fillcolor="rgba(255,127,14,0.15)")
        add_cota(-25, -50, 25, -50, f"{peca_tipo}", offset_y=-12)
    elif "Eletroduto" in peca_tipo or "Canaleta" in peca_tipo:
        fig.add_shape(type="circle", x0=-d, y0=-d, x1=d, y1=d, line=dict(color="#1f77b4", width=2.5), fillcolor="rgba(31,119,180,0.1)")
        add_cota(-d, 0, d, 0, f"Eletroduto Corrugado/Rígido DN {int(d)}mm", offset_y=12)
    else: # Disjuntor / IDR / DPS / Contator / Barramento
        fig.add_shape(type="rect", x0=-9, y0=-40, x1=9, y1=40, line=dict(color="#222", width=2.5), fillcolor="#f0f2f6")
        fig.add_shape(type="rect", x0=-6, y0=-8, x1=6, y1=8, line=dict(color="#d62728", width=2), fillcolor="#d62728")
        add_cota(-9, -40, 9, -40, f"{peca_tipo} (Módulo DIN 35mm)", offset_y=-10)

    fig.update_layout(
        title=f"Desenho Técnico Paramétrico: {peca_tipo} (DN/Dimensão: {dn_mm} mm)",
        xaxis=dict(title="X (mm)", zeroline=False, showgrid=True, gridcolor="#eee", scaleanchor="y", scaleratio=1),
        yaxis=dict(title="Y (mm)", zeroline=False, showgrid=True, gridcolor="#eee"),
        plot_bgcolor="white", height=520, margin=dict(l=20, r=20, t=50, b=20)
    )
    return fig

# ==========================================
# 3.D SIMBOLOGIA ABNT DXF E EXPORTADORES DXF / IFC
# ==========================================
def desenhar_simbologia_abnt(msp, p1, p2, fios_str):
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    if abs(dx) < 0.05 and abs(dy) < 0.05: return
    angulo_tubo = math.atan2(dy, dx)
    angulo_perp = angulo_tubo + (math.pi / 2.0)
    cx, cy = (p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0
    z, tamanho, px_dir, py_dir, afastamento = p1[2], 0.35, math.cos(angulo_perp), math.sin(angulo_perp), -0.25
    for char in fios_str.replace("(3W)", "").replace("(4W)", "").replace(" ", ""):
        if char in ['2', '4']: continue
        bx, by = cx + (math.cos(angulo_tubo) * afastamento), cy + (math.sin(angulo_tubo) * afastamento)
        tx, ty = bx + (px_dir * tamanho), by + (py_dir * tamanho)
        if char == 'F': msp.add_line((bx - (px_dir * tamanho/2), by - (py_dir * tamanho/2), z), (tx, ty, z), dxfattribs={'layer': 'SIMBOLOS_FIOS_ABNT', 'color': 1})
        elif char == 'N':
            msp.add_line((bx, by, z), (tx, ty, z), dxfattribs={'layer': 'SIMBOLOS_FIOS_ABNT', 'color': 5})
            msp.add_line((tx, ty, z), (tx + math.cos(angulo_tubo)*0.15, ty + math.sin(angulo_tubo)*0.15, z), dxfattribs={'layer': 'SIMBOLOS_FIOS_ABNT', 'color': 5})
        elif char == 'T':
            msp.add_line((bx, by, z), (tx, ty, z), dxfattribs={'layer': 'SIMBOLOS_FIOS_ABNT', 'color': 3})
            msp.add_line((tx - math.cos(angulo_tubo)*0.15, ty - math.sin(angulo_tubo)*0.15, z), (tx + math.cos(angulo_tubo)*0.15, ty + math.sin(angulo_tubo)*0.15, z), dxfattribs={'layer': 'SIMBOLOS_FIOS_ABNT', 'color': 3})
        elif char == 'R': msp.add_line((bx, by, z), (bx + (px_dir * tamanho/2), by + (py_dir * tamanho/2), z), dxfattribs={'layer': 'SIMBOLOS_FIOS_ABNT', 'color': 2})
        afastamento += 0.22

def exportar_malha_para_dxf(linhas_elet, linhas_hidro, paredes_raw, modo="UNIFICADO"):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    doc.layers.add(name="ARQ_PAREDES_3D", color=8)
    doc.layers.add(name="MEP_ELETRICA_ELETRODUTOS", color=2)
    doc.layers.add(name="SIMBOLOS_FIOS_ABNT", color=1)
    doc.layers.add(name="MEP_HIDRO_AGUA_FRIA", color=5)
    doc.layers.add(name="MEP_HIDRO_AGUA_QUENTE", color=1)
    doc.layers.add(name="MEP_HIDRO_ESGOTO", color=30)
    doc.layers.add(name="MEP_CONEXOES_CAIXAS", color=3)
    for p1, p2 in paredes_raw: msp.add_line(p1, p2, dxfattribs={'layer': 'ARQ_PAREDES_3D'})
    if modo in ["ELETRICA", "UNIFICADO"]:
        for rota in linhas_elet:
            pts, fios_str = rota['pontos'], rota.get('fios', 'F N T')
            for i in range(len(pts)-1):
                msp.add_line(pts[i], pts[i+1], dxfattribs={'layer': 'MEP_ELETRICA_ELETRODUTOS'})
                if dist_2d(pts[i], pts[i+1]) >= 0.6: desenhar_simbologia_abnt(msp, pts[i], pts[i+1], fios_str)
            for pt in pts: msp.add_circle(pt, radius=0.04, dxfattribs={'layer': 'MEP_CONEXOES_CAIXAS'})
    if modo in ["HIDRO", "UNIFICADO"]:
        for rota in linhas_hidro:
            pts, tipo = rota['pontos'], rota.get('tipo', 'Água Fria')
            layer_dest = "MEP_HIDRO_ESGOTO" if "Esgoto" in tipo or "Queda" in tipo else ("MEP_HIDRO_AGUA_QUENTE" if "Quente" in tipo else "MEP_HIDRO_AGUA_FRIA")
            for i in range(len(pts)-1): msp.add_line(pts[i], pts[i+1], dxfattribs={'layer': layer_dest})
            for pt in pts: msp.add_circle(pt, radius=0.05, dxfattribs={'layer': 'MEP_CONEXOES_CAIXAS'})
    with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
        doc.saveas(tmp.name)
        tmp_path = tmp.name
    with open(tmp_path, "rb") as f: dxf_bytes = f.read()
    os.unlink(tmp_path)
    return dxf_bytes

def exportar_malha_para_ifc_step(linhas_elet, linhas_hidro, modo="UNIFICADO"):
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    linhas_ifc = [
        "ISO-10303-21;", "HEADER;", f"FILE_DESCRIPTION(('ViewDefinition [CoordinationView_V2.0] - Modo {modo}'),('2;1'));",
        f"FILE_NAME('Projeto_BIM_{modo}.ifc','{timestamp}',('Engenharia BIM Master'),('UFF / BIM Master PRO'),'IFC4','BIM Master Engine','');",
        "FILE_SCHEMA(('IFC4'));", "ENDSEC;", "DATA;",
        "#1=IFCPROJECT('0xScRe4tE00001',$,'Projeto Executivo MEP Integrado',$,$,$,$,$,#2);",
        "#2=IFCUNITASSIGNMENT((#3,#4));", "#3=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);", "#4=IFCSIUNIT(*,.VOLUMEUNIT.,$,.CUBIC_METRE.);",
        "#10=IFCSITE('0xScRe4tE00010',$,'Terreno Padrao',$,$,$,$,$,.ELEMENT.,$,$,$,$,$);",
        "#20=IFCBUILDING('0xScRe4tE00020',$,'Edificacao BIM',$,$,$,$,$,.ELEMENT.,$,$,$);",
        "#30=IFCBUILDINGSTOREY('0xScRe4tE00030',$,'Pavimento Tipo',$,$,$,$,$,.ELEMENT.,0.0);",
        "#40=IFCDISTRIBUTIONSYSTEM('0xScRe4tE00040',$,'Sistema Eletrico NBR 5410',$,'ELECTRICAL',.ELECTRICAL.);",
        "#50=IFCDISTRIBUTIONSYSTEM('0xScRe4tE00050',$,'Sistema Hidrossanitario NBR 5626/8160',$,'PLUMBING',.PLUMBING.);"
    ]
    id_step = 100
    if modo in ["ELETRICA", "UNIFICADO"]:
        for idx_r, rota in enumerate(linhas_elet):
            pts, comp = rota['pontos'], calcular_comprimento_rota(rota['pontos'])
            linhas_ifc.append(f"#{id_step}=IFCCABLESEGMENT('{str(uuid.uuid4())[:22]}',$,'Eletroduto_Circ_{idx_r+1}','Fios: {rota.get('fios','F N T')} | L={comp:.2f}m',$,$,$,$,.CABLESEGMENT.);")
            id_step += 1
    if modo in ["HIDRO", "UNIFICADO"]:
        for idx_h, rota in enumerate(linhas_hidro):
            pts, comp, dn, tp = rota['pontos'], calcular_comprimento_rota(rota['pontos']), rota.get('diametro', 25), rota.get('tipo', 'Agua Fria')
            linhas_ifc.append(f"#{id_step}=IFCPIPESEGMENT('{str(uuid.uuid4())[:22]}',$,'Tubo_{tp}_DN{dn}mm','L={comp:.2f}m | DN={dn}mm',$,$,$,$,.RIGIDSEGMENT.);")
            id_step += 1
    linhas_ifc.extend(["ENDSEC;", "END-ISO-10303-21;"])
    return "\n".join(linhas_ifc)

def gerar_fluxograma_ifc_plotly(linhas_elet, linhas_hidro, config_andares):
    G = nx.DiGraph()
    G.add_node("IfcProject\n(Projeto BIM Master)", nivel=0, cor="#1f77b4")
    G.add_node("IfcBuilding\n(Edificação)", nivel=1, cor="#2ca02c")
    G.add_edge("IfcProject\n(Projeto BIM Master)", "IfcBuilding\n(Edificação)")
    andares_nomes = [f"IfcBuildingStorey\n(Pav {c['ordem']} - PD {c['pe_direito']}m)" for c in config_andares] if config_andares else ["IfcBuildingStorey\n(Pavimento Térreo)"]
    for a_nome in andares_nomes:
        G.add_node(a_nome, nivel=2, cor="#ff7f0e")
        G.add_edge("IfcBuilding\n(Edificação)", a_nome)
    sis_el, sis_af, sis_esg = f"IfcDistributionSystem\n[ELÉTRICA - {len(linhas_elet)} Ramais]", "IfcDistributionSystem\n[ÁGUA FRIA/QUENTE]", "IfcDistributionSystem\n[ESGOTO & VENTILAÇÃO]"
    for s_node, cor_s in [(sis_el, "#d62728"), (sis_af, "#0066cc"), (sis_esg, "#8c564b")]:
        G.add_node(s_node, nivel=3, cor=cor_s)
        for a_nome in andares_nomes: G.add_edge(a_nome, s_node)
    for pai, filho, cor_f in [
        (sis_el, "IfcElectricDistributionBoard\n(QDG + Disjuntores + IDR + DPS)", "#e377c2"),
        (sis_el, "IfcCableCarrierSegment\n(Eletrodutos + Caixas 4x2/Oct.)", "#e377c2"),
        (sis_af, "IfcPipeSegment & IfcPipeFitting\n(Tubos AF/AQ + Joelhos/Tês/Registros)", "#17becf"),
        (sis_esg, "IfcSanitaryTerminal & IfcPipeFitting\n(TQ + Cx Sifonada + Junções 45°)", "#bcbd22")
    ]:
        G.add_node(filho, nivel=4, cor=cor_f)
        G.add_edge(pai, filho)
    pos, niveis = {}, {}
    for n, data in G.nodes(data=True): niveis.setdefault(data.get('nivel', 0), []).append(n)
    for niv, lista in niveis.items():
        for i, n in enumerate(lista): pos[n] = ((i - (len(lista) - 1) / 2.0) * 3.0, -niv * 2.0)
    edge_x, edge_y = [], []
    for u, v in G.edges(): edge_x.extend([pos[u][0], pos[v][0], None]); edge_y.extend([pos[u][1], pos[v][1], None])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode='lines', line=dict(width=2, color='#888'), hoverinfo='none'))
    fig.add_trace(go.Scatter(
        x=[pos[n][0] for n in G.nodes()], y=[pos[n][1] for n in G.nodes()], mode='markers+text',
        text=list(G.nodes()), textposition="bottom center", marker=dict(size=28, color=[G.nodes[n]['cor'] for n in G.nodes()], line=dict(width=2, color='white')), hoverinfo='text'
    ))
    fig.update_layout(title="Fluxograma Topológico IFC 4 (Esquema de Classes e Sistemas MEP)", showlegend=False, xaxis=dict(showgrid=False, zeroline=False, showticklabels=False), yaxis=dict(showgrid=False, zeroline=False, showticklabels=False), plot_bgcolor="white", height=480, margin=dict(l=10, r=10, t=45, b=30))
    return fig

# ==========================================
# 4. FRONT-END E SIDEBAR
# ==========================================
with st.sidebar:
    st.header("💾 Arquivo do Projeto")
    arquivo_projeto = st.file_uploader("Abrir Projeto Salvo (.bim)", type=["bim", "json"])
    if arquivo_projeto is not None and st.button("📂 Carregar Dados do Arquivo", use_container_width=True):
        importar_projeto(arquivo_projeto)
        st.success("Projeto carregado com sucesso!")
        st.rerun()
    st.download_button(label="💾 Salvar Projeto Atual (.bim)", data=exportar_projeto(), file_name="meu_projeto.bim", mime="application/json", use_container_width=True, type="primary")
    
    st.divider()
    st.header("🏢 Arquitetura e Pavimentos (DXF / IFC)")
    arquivos_dxf = st.file_uploader("Upload Plantas Baixas (.dxf ou .ifc)", type=["dxf", "ifc"], accept_multiple_files=True)
    
    st.divider()
    st.subheader("Configurações Globais & Estruturais")
    espessura_laje = st.number_input("Espessura da Laje (m)", min_value=0.1, max_value=1.5, value=0.15, step=0.05)
    altura_viga = st.number_input("Altura Média das Vigas (m)", min_value=0.15, max_value=1.20, value=0.40, step=0.05)
    incluir_shaft = st.toggle("Incluir Shaft para tubulação entre andares", value=True)
    
    st.markdown("**Organização e Alturas dos Pavimentos**")
    config_andares = []
    if arquivos_dxf:
        for i, arq in enumerate(arquivos_dxf):
            st.markdown(f"📄 `{arq.name}`")
            c1, c2 = st.columns(2)
            ordem = c1.number_input("Andar (0=Térreo)", min_value=0, max_value=30, value=i, key=f"ord_{i}")
            pd_val = c2.number_input("Pé Dir. (m)", min_value=2.0, max_value=8.0, value=3.0, step=0.1, key=f"pd_{i}")
            config_andares.append({"arquivo": arq, "ordem": ordem, "pe_direito": pd_val})
        config_andares = sorted(config_andares, key=lambda x: x['ordem'])
    else:
        st.info("Faça o upload dos arquivos DXF/IFC para configurar os andares.")

    st.divider()
    st.subheader("⚡ Entrada de Energia (Concessionária)")
    sistema_fornecimento = st.selectbox("Sistema", ["Monofásico (1F+N)", "Bifásico (2F+N)", "Trifásico (3F+N)"], index=2)
    tensao_fase = st.selectbox("Tensão Fase-Neutro (V)", [127, 220], index=0)
    
    st.divider()
    st.subheader("🚰 Config. Caixa d'Água (NBR 5626)")
    pessoas, consumo_pc, dias_reserva = st.number_input("Pessoas", min_value=1, value=4), st.number_input("Consumo (L/dia)", min_value=50, value=150), st.number_input("Dias Reserva", min_value=1, value=2)
    vol_caixa = pessoas * consumo_pc * dias_reserva
    vol_comercial = next((v for v in [500, 1000, 1500, 2000, 2500, 3000, 5000, 10000] if v >= vol_caixa), vol_caixa)
    st.info(f"Volume Calc: **{vol_caixa} L** | Comercial: **{vol_comercial} L**")

    st.divider()
    if st.button("🔒 Bloquear / Sair do Sistema", use_container_width=True):
        st.session_state["autenticado"] = False
        st.rerun()

# ==========================================
# 5. ABAS PRINCIPAIS
# ==========================================
tab_bim, tab_clash, tab_eletrica, tab_hidro, tab_pecas_ifc, tab_export = st.tabs([
    "🗺️ BIM 3D & Roteamento", "⚠️ Clash Detection",
    "⚡ Eng. Elétrica, Alimentador & QDG", "💧 Eng. Hidrossanitária (NBR 5626/8160)",
    "📐 Peças CAD, Quantitativos & IFC", "📦 Config. & Bibliotecas"
])

# --- ABA 1: MODELAGEM BIM 3D ---
with tab_bim:
    st.title("Modelagem e Roteamento Multidisciplinar Consciente de Estrutura")
    if arquivos_dxf:
        todas_layers = []
        dxf_files_only = [f for f in arquivos_dxf if f.name.lower().endswith(".dxf")]
        if dxf_files_only:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp_file:
                tmp_file.write(dxf_files_only[0].getvalue())
                temp_path = tmp_file.name
            doc_base = ezdxf.readfile(temp_path)
            todas_layers = sorted([layer.dxf.name for layer in doc_base.layers])
            os.unlink(temp_path)
        else:
            todas_layers = ["PAREDES", "ESQUADRIAS", "ESTRUTURA", "ELETRICA", "HIDRAULICA"]
        
        c1, c2, c3, c4, c5 = st.columns(5)
        layer_arq = c1.multiselect("Paredes:", todas_layers, default=[todas_layers[0]] if todas_layers else [])
        layer_esquadrias = c2.multiselect("Esquadrias (Portas/Janelas):", todas_layers)
        layer_estrutural = c3.multiselect("Vigas/Pilares:", todas_layers)
        layer_elet = c4.multiselect("Blocos Elétricos:", todas_layers)
        layer_hidro = c5.multiselect("Blocos Hidro/Gás/Bomba:", todas_layers)

        st.divider()
        col_h1, col_h2, col_h3 = st.columns(3)
        h_agua_fria, h_agua_quente, modo_visualizacao = col_h1.number_input("Altura Água Fria (m)", value=2.20, step=0.1), col_h2.number_input("Altura Água Quente (m)", value=1.10, step=0.1), col_h3.selectbox("Visualização:", ["Unificado (Elétrica + Hidráulica)", "Apenas Elétrica", "Apenas Hidrossanitário"])

        blocos_elet, blocos_hidro, paredes_raw, elementos_arquitetonicos, max_z_projeto, z_acumulado = [], [], [], [], 0.0, 0.0
        for andar_idx, config in enumerate(config_andares):
            dxf_file, pe_direito_atual, z_base = config["arquivo"], config["pe_direito"], z_acumulado
            if z_base > max_z_projeto: max_z_projeto = z_base
            if dxf_file.name.lower().endswith(".dxf"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp_file:
                    tmp_file.write(dxf_file.getvalue())
                    temp_path = tmp_file.name
                doc = ezdxf.readfile(temp_path)
                msp = doc.modelspace()
                for le in layer_esquadrias:
                    for e in msp.query(f'INSERT[layer=="{le}"]'):
                        eh_porta = "PORTA" in e.dxf.name.upper() or "PT" in e.dxf.name.upper()
                        elementos_arquitetonicos.append({"ID_CAD": f"{e.dxf.name}_ESQ", "Tipo": "Esquadria", "Subtipo": "Porta" if eh_porta else "Janela", "x": e.dxf.insert.x, "y": e.dxf.insert.y, "z_base": z_base, "Largura": 0.90 if eh_porta else 1.20, "Peitoril": 0.0 if eh_porta else 1.00, "Altura": 2.10 if eh_porta else 1.10})
                for le in layer_estrutural:
                    for e in msp.query(f'INSERT[layer=="{le}"]'):
                        elementos_arquitetonicos.append({"ID_CAD": f"{e.dxf.name}_EST", "Tipo": "Pilar/Viga", "x": e.dxf.insert.x, "y": e.dxf.insert.y, "z_base": z_base, "Largura": 0.40, "Altura_Viga": altura_viga})
                for le in layer_elet:
                    for i, e in enumerate(msp.query(f'INSERT[layer=="{le}"]')): blocos_elet.append({"ID_CAD": f"{e.dxf.name}_P{andar_idx}_{i}", "Nome_Bloco": e.dxf.name, "x": e.dxf.insert.x, "y": e.dxf.insert.y, "z_base": z_base, "Andar": f"Pav {config['ordem']}", "pe_direito": pe_direito_atual})
                for lh in layer_hidro:
                    for i, e in enumerate(msp.query(f'INSERT[layer=="{lh}"]')): blocos_hidro.append({"ID_CAD": f"{e.dxf.name}_P{andar_idx}_{i}", "Nome_Bloco": e.dxf.name, "x": e.dxf.insert.x, "y": e.dxf.insert.y, "z_base": z_base, "Andar": f"Pav {config['ordem']}", "pe_direito": pe_direito_atual})
                for e in msp.query('LINE LWPOLYLINE'):
                    if e.dxf.layer in layer_arq:
                        if e.dxftype() == 'LINE': pts = [((e.dxf.start.x, e.dxf.start.y, z_base), (e.dxf.end.x, e.dxf.end.y, z_base))]
                        else:
                            pontos = list(e.get_points(format='xy'))
                            pts = [((pontos[i][0], pontos[i][1], z_base), (pontos[i+1][0], pontos[i+1][1], z_base)) for i in range(len(pontos)-1)]
                        paredes_raw.extend(pts)
                os.unlink(temp_path)
            z_acumulado += pe_direito_atual + espessura_laje
        
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.subheader("⚡ Equipamentos Elétricos & Validação NBR 5410")
            df_be = pd.DataFrame(blocos_elet) if blocos_elet else pd.DataFrame(columns=["ID_CAD", "Nome_Bloco", "x", "y", "z_base", "Andar", "pe_direito", "Tipo_BIM", "z_relativo"])
            if not df_be.empty:
                df_be['Tipo_BIM'] = 'Luminária'
                df_be.loc[df_be['Nome_Bloco'].str.contains("QUADRO|QDG", case=False, na=False), 'Tipo_BIM'] = 'Quadro Geral'
                df_be.loc[df_be['Nome_Bloco'].str.contains("TOMADA|CX", case=False, na=False), 'Tipo_BIM'] = 'Caixa 4x2'
                df_be['Qtd_Tomadas'] = 1
                df_be['Amperagem_Tomadas'] = '10A'
                df_be['Tensao_V'] = tensao_fase
                df_be['Qtd_Interruptores'] = 0
                df_be['Luminarias_Controladas'] = ""
                df_be['Equipamento_Associado'] = "Tomada Uso Geral (TUG)"
                df_be.loc[df_be['Tipo_BIM'] == 'Luminária', ['Qtd_Tomadas', 'Equipamento_Associado']] = [0, "Lâmpada LED 15W"]
                df_be['z_relativo'] = 1.3
                df_be.loc[df_be['Tipo_BIM'] == 'Luminária', 'z_relativo'] = df_be['pe_direito']
                
                df_editado_elet = st.data_editor(df_be, column_config={
                    "Tipo_BIM": st.column_config.SelectboxColumn("Tipo Físico", options=["Quadro Geral", "Luminária", "Caixa 4x2", "Caixa 4x4"]),
                    "Equipamento_Associado": st.column_config.SelectboxColumn("Carga", options=list(st.session_state.bib_eletrica['Equipamento'])),
                    "Amperagem_Tomadas": st.column_config.SelectboxColumn("Amperagem", options=["10A", "20A"]),
                    "Tensao_V": st.column_config.SelectboxColumn("Tensão (V)", options=[127, 220]),
                    "Qtd_Tomadas": st.column_config.NumberColumn("Qtd Tomadas", min_value=0, max_value=4),
                    "Qtd_Interruptores": st.column_config.NumberColumn("Qtd Interruptores", min_value=0, max_value=6)
                }, use_container_width=True, hide_index=True)

                for idx, row in df_editado_elet.iterrows():
                    if 'Caixa' in row['Tipo_BIM'] and row['Qtd_Interruptores'] > 0:
                        sel = st.multiselect(f"🔌 Caixa {row['ID_CAD']} controla:", options=df_editado_elet[df_editado_elet['Tipo_BIM'] == 'Luminária']['ID_CAD'].tolist(), key=f"ms_{row['ID_CAD']}")
                        df_editado_elet.at[idx, 'Luminarias_Controladas'] = ",".join(sel)
            else:
                st.warning("Nenhum bloco elétrico detectado.")
                df_editado_elet = pd.DataFrame()

        with col_t2:
            st.subheader("💧 Equipamentos Hidráulicos")
            df_bh = pd.DataFrame(blocos_hidro) if blocos_hidro else pd.DataFrame(columns=["ID_CAD", "Nome_Bloco", "x", "y", "z_base", "Andar", "pe_direito", "Tipo_BIM", "Equipamento", "z_relativo"])
            if not df_bh.empty:
                opcoes_equip = list(st.session_state.bib_hidro['Equipamento'])
                df_bh['Tipo_BIM'] = 'Aparelho Hidráulico'
                df_bh.loc[df_bh['Nome_Bloco'].str.contains("PRUMADA|AGUA|AF", case=False, na=False), 'Tipo_BIM'] = 'Prumada Água Fria'
                df_bh.loc[df_bh['Nome_Bloco'].str.contains("ESGOTO|TUBO_QUEDA|TQ", case=False, na=False), 'Tipo_BIM'] = 'Prumada Esgoto'
                df_bh.loc[df_bh['Nome_Bloco'].str.contains("CAIXA|RES|TANQUE", case=False, na=False), 'Tipo_BIM'] = 'Caixa d\'Água'
                df_bh['Equipamento'] = opcoes_equip[0] if opcoes_equip else ""
                df_bh['z_relativo'] = 0.5
                df_editado_hidro = st.data_editor(df_bh, column_config={"Tipo_BIM": st.column_config.SelectboxColumn("Função BIM", options=["Prumada Água Fria", "Prumada Esgoto", "Aparelho Hidráulico", "Caixa d'Água"]), "Equipamento": st.column_config.SelectboxColumn("Eq.", options=opcoes_equip)}, use_container_width=True, hide_index=True)
                altura_caixa = st.number_input("Altura Caixa d'Água Acima da Laje (m)", min_value=0.5, value=1.5, step=0.1) if not df_editado_hidro[df_editado_hidro['Tipo_BIM'] == 'Caixa d\'Água'].empty else 1.5
            else:
                st.warning("Nenhum bloco hidráulico detectado.")
                df_editado_hidro, altura_caixa = pd.DataFrame(), 1.5

        st.divider()
        col_btn_proc, col_tog1, col_tog2 = st.columns([2, 1, 1])
        mostrar_tubos, mostrar_fios = col_tog1.toggle("Ver Tubos / Eletrodutos 3D", value=True), col_tog2.toggle("Ver Rótulos Fios 3D", value=True)

        if col_btn_proc.button("🚀 Processar Rotas, Validações NBR 5410/5626 & Quantitativos", type="primary", use_container_width=True):
            with st.spinner("Executando motor BIM, auditoria de cargas, quedas e pressões..."):
                pontos_gerais = []
                if not df_editado_elet.empty: pontos_gerais.extend(df_editado_elet.to_dict('records'))
                if not df_editado_hidro.empty: pontos_gerais.extend(df_editado_hidro.to_dict('records'))

                min_x = min([b['x'] for b in pontos_gerais] + [min(p1[0], p2[0]) for p1, p2 in paredes_raw] + [0]) if (pontos_gerais or paredes_raw) else 0
                max_x = max([b['x'] for b in pontos_gerais] + [max(p1[0], p2[0]) for p1, p2 in paredes_raw] + [10]) if (pontos_gerais or paredes_raw) else 10
                min_y = min([b['y'] for b in pontos_gerais] + [min(p1[1], p2[1]) for p1, p2 in paredes_raw] + [0]) if (pontos_gerais or paredes_raw) else 0
                max_y = max([b['y'] for b in pontos_gerais] + [max(p1[1], p2[1]) for p1, p2 in paredes_raw] + [10]) if (pontos_gerais or paredes_raw) else 10
                
                offset, grid_w, grid_h = 2.0, escalar_coord((max_x - min_x) + 4.0), escalar_coord((max_y - min_y) + 4.0)
                ultimo_pe_direito = config_andares[-1]["pe_direito"] if config_andares else 3.0
                z_cobertura = max_z_projeto + ultimo_pe_direito

                df_h_processar = df_editado_hidro.to_dict('records') if not df_editado_hidro.empty else []
                for b in df_h_processar:
                    if b['Tipo_BIM'] == 'Caixa d\'Água': b['z_base'] = z_cobertura

                st.session_state.contexto_bim = {
                    'paredes': paredes_raw, 'elementos_arquitetonicos': elementos_arquitetonicos,
                    'df_eletrica': df_editado_elet.to_dict('records') if not df_editado_elet.empty else [],
                    'df_hidro': df_h_processar, 'min_x': min_x, 'min_y': min_y, 'offset': offset,
                    'grid_w': grid_w, 'grid_h': grid_h, 'pe_direito': ultimo_pe_direito, 'max_z_cobertura': z_cobertura,
                    'altura_caixa': altura_caixa, 'h_agua_fria': h_agua_fria, 'h_agua_quente': h_agua_quente,
                    'altura_viga': altura_viga, 'incluir_shaft': incluir_shaft
                }

                ctx = st.session_state.contexto_bim
                linhas_hidro = rotear_hidro(ctx['df_hidro'], ctx) if modo_visualizacao != "Apenas Elétrica" else []
                linhas_elet = rotear_eletrica(ctx['df_eletrica'], ctx) if modo_visualizacao != "Apenas Hidrossanitário" else []
                st.session_state.linhas_3d_master = {'eletrica': linhas_elet, 'hidro': linhas_hidro, 'equipamentos_3d': pontos_gerais}

                # Executa Circuitos e Validação NBR 5410 (Seção 9)
                novos_circuitos, qtd_tues = [], 0
                for b_el in ctx['df_eletrica']:
                    if b_el['Tipo_BIM'] == 'Quadro Geral': continue
                    eq_nome = b_el.get('Equipamento_Associado', 'Tomada Uso Geral (TUG)')
                    filtro_el = st.session_state.bib_eletrica['Equipamento'] == eq_nome
                    if filtro_el.any():
                        row_bib = st.session_state.bib_eletrica.loc[filtro_el].iloc[0]
                        pot_unit, tensao_eq, fp_eq, tipo_eq, curva_eq, uso_dr = float(row_bib['Potência (W)']), int(b_el.get('Tensao_V', row_bib['Tensão (V)'])), float(row_bib['Fator de Potência']), str(row_bib['Tipo']), str(row_bib['Curva Disjuntor']), str(row_bib['Uso de DR'])
                    else:
                        pot_unit, tensao_eq, fp_eq, tipo_eq, curva_eq, uso_dr = 100.0, 127, 1.0, "TUG", "B", "Opcional"

                    if tipo_eq == "TUE": qtd_tues += 1
                    if b_el.get('Amperagem_Tomadas') == '20A' and pot_unit == 100.0: pot_unit = 600.0
                    qtd_pts = max(1, int(b_el.get('Qtd_Tomadas', 1))) if 'Caixa' in b_el['Tipo_BIM'] else 1
                    pot_total = pot_unit * qtd_pts
                    rota_assoc = next((r for r in linhas_elet if r.get('id_origem') == b_el['ID_CAD']), None)
                    dist_circ = rota_assoc['comprimento_m'] if rota_assoc else 15.0

                    dim_5410 = dimensionar_circuito_nbr5410(pot_total, tensao_eq, fp_eq, "B1", 0.80, 1.00, dist_circ, tipo_eq)
                    novos_circuitos.append({
                        "ID": f"C{len(novos_circuitos)+1}", "Ambiente": b_el.get('Andar', 'Pav 0'),
                        "Equipamento": f"{eq_nome} ({b_el['ID_CAD']})", "Qtd": qtd_pts, "Potência Total (W)": pot_total,
                        "Tensão (V)": tensao_eq, "Fator de Potência": fp_eq, "Método Inst.": "B1",
                        "Eletroduto (Ref)": f"Eletroduto {b_el.get('Andar','')} - Teto/Parede", "FCA": 0.80, "FCT": 1.00,
                        "Corrente (A)": dim_5410["Corrente_Ib"], "Corrente Corrigida (A)": dim_5410["Corrente_Corr"],
                        "Bitola (mm²)": dim_5410["Bitola"], "Queda Tensão (%)": dim_5410["Queda_Tensao_Pct"],
                        "Disjuntor (A)": dim_5410["Disjuntor"], "Curva": curva_eq, "Icc (A)": dim_5410["Icc_A"],
                        "Distância (m)": dist_circ, "Fase": "R", "Grupo DR": "DR 1 (Áreas Molhadas)" if uso_dr == "Obrigatório" else "DR 2 (Geral)",
                        "Eletroduto (mm)": dim_5410["Eletroduto_mm"], "Ocupação (%)": dim_5410["Ocupacao_Pct"]
                    })
                if novos_circuitos: st.session_state.circuitos = balancear_fases_automatico(pd.DataFrame(novos_circuitos))

                # Executa Hidráulica e Validação NBR 5626 (Pressão Estática Máxima <= 40 mca)
                novos_pontos_hidro, z_res_mca = [], z_cobertura + altura_caixa
                for b_hd in ctx['df_hidro']:
                    if b_hd['Tipo_BIM'] != 'Aparelho Hidráulico': continue
                    eq_h = b_hd['Equipamento']
                    filtro_h = st.session_state.bib_hidro['Equipamento'] == eq_h
                    if not filtro_h.any(): continue
                    row_h = st.session_state.bib_hidro.loc[filtro_h].iloc[0]
                    peso_h, uhc_h, af_mm, esg_mm, pressao_req_kpa = float(row_h['Peso']), float(row_h['UHC']), int(row_h['Agua_mm']), int(row_h['Esgoto_mm']), float(row_h['Pressao_kpa'])
                    rota_af = next((r for r in linhas_hidro if r.get('id_ap') == b_hd['ID_CAD'] and r.get('tipo') == 'Água Fria'), None)
                    comp_real_af = calcular_comprimento_rota(rota_af['pontos']) if rota_af else 8.0
                    vazao_ls, _, comp_eq, perda_mca = calcular_perda_carga_nbr5626(peso_h, max(20, af_mm), comp_real_af)
                    z_ponto = b_hd['z_base'] + b_hd.get('z_relativo', 0.5)
                    desnivel_estatico_mca = max(1.5, z_res_mca - z_ponto)
                    pressao_estatica_mca = desnivel_estatico_mca
                    pressao_disp_mca = max(0.0, desnivel_estatico_mca - perda_mca)
                    pressao_disp_kpa = round(pressao_disp_mca * 9.81, 1)

                    # Validação Avançada 3: Pressão Estática Máxima <= 40 mca (NBR 5626)
                    status_pressao = "OK (NBR 5626)"
                    if pressao_disp_kpa < pressao_req_kpa: status_pressao = "⚠️ Pressurizar!"
                    elif pressao_estatica_mca > 40.0: status_pressao = "⚠️ Instalar VRP (> 40 m.c.a.)"

                    novos_pontos_hidro.append({
                        "ID": b_hd['ID_CAD'], "Andar": b_hd.get('Andar', 'Pav 0'), "Ambiente": b_hd.get('Andar', 'Banheiro'),
                        "Equipamento": eq_h, "z": round(z_ponto, 2), "Peso (NBR 5626)": peso_h, "Vazão (L/s)": vazao_ls,
                        "Tubo AF (mm)": af_mm, "L Real + Eq (m)": round(comp_real_af + comp_eq, 2), "Perda Carga (m.c.a.)": perda_mca,
                        "Pressão Estática (m.c.a.)": round(pressao_estatica_mca, 1), "Pressão Disp. (kPa)": pressao_disp_kpa,
                        "Status Pressão": status_pressao, "UHC": uhc_h, "Tubo Esgoto (mm)": esg_mm, "Declividade Esg. (%)": 1.0 if esg_mm >= 100 else 2.0
                    })
                st.session_state.pontos_hidro = novos_pontos_hidro
                st.session_state.quantitativos_master = gerar_quantitativos_totais_bim(linhas_elet, linhas_hidro, st.session_state.circuitos, ctx['df_eletrica'], ctx['df_hidro'])
                st.success("✅ Roteamento concluído com auditoria normativa NBR 5410 e NBR 5626 (VRP) aplicada!")

        if st.session_state.linhas_3d_master['eletrica'] or st.session_state.linhas_3d_master['hidro'] or paredes_raw:
            fig = go.Figure()
            for p1, p2 in paredes_raw: fig.add_trace(go.Scatter3d(x=[p1[0], p2[0]], y=[p1[1], p2[1]], z=[p1[2], p2[2]], mode='lines', line=dict(color='#cccccc', width=2), showlegend=False))
            if modo_visualizacao in ["Unificado (Elétrica + Hidráulica)", "Apenas Elétrica"]:
                for linha in st.session_state.linhas_3d_master['eletrica']:
                    pts, fios_txt = linha['pontos'], linha.get('fios', 'F N T')
                    if mostrar_tubos: fig.add_trace(go.Scatter3d(x=[p[0] for p in pts], y=[p[1] for p in pts], z=[p[2] for p in pts], mode='lines', line=dict(color=linha['cor'], width=4), name=f"Elétrica ({fios_txt})"))
                    if mostrar_fios and len(pts) >= 2:
                        p_mid = pts[len(pts) // 2]
                        fig.add_trace(go.Scatter3d(x=[p_mid[0]], y=[p_mid[1]], z=[p_mid[2]+0.15], mode='text', text=[fios_txt], textposition="top center", textfont=dict(color="black", size=11, family="Arial Black"), showlegend=False))
            if modo_visualizacao in ["Unificado (Elétrica + Hidráulica)", "Apenas Hidrossanitário"]:
                for linha in st.session_state.linhas_3d_master['hidro']:
                    pts = linha['pontos']
                    if mostrar_tubos: fig.add_trace(go.Scatter3d(x=[p[0] for p in pts], y=[p[1] for p in pts], z=[p[2] for p in pts], mode='lines', line=dict(color=linha['cor'], width=6), name=f"{linha.get('tipo')} DN{linha.get('diametro')}"))
            fig.update_layout(scene=dict(aspectmode='data', bgcolor='#ffffff'), height=750, margin=dict(l=0, r=0, b=0, t=0))
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Suba os arquivos DXF/IFC na barra lateral.")

# --- ABA 2: CLASH DETECTION ---
with tab_clash:
    st.subheader("Verificação de Interferências (Hard & Soft Clash)")
    if st.button("🔍 Rodar Verificação de Colisões", type="primary"):
        if st.session_state.linhas_3d_master['eletrica'] and st.session_state.linhas_3d_master['hidro']:
            st.session_state.colisoes_detectadas = checar_clash_detection(st.session_state.linhas_3d_master['eletrica'], st.session_state.linhas_3d_master['hidro'], 0.15)
            if not st.session_state.colisoes_detectadas: st.success("✅ O Projeto está limpo! Nenhuma interferência.")
        else: st.warning("Processe as rotas primeiro.")
    if st.session_state.colisoes_detectadas:
        st.error(f"⚠️ Foram detectados {len(st.session_state.colisoes_detectadas)} pontos de colisão!")
        st.dataframe(pd.DataFrame(st.session_state.colisoes_detectadas), use_container_width=True)
        if st.button("🛡️ Evitar Colisões (Re-rotear Elétrica)", type="primary"):
            ctx = st.session_state.contexto_bim
            st.session_state.linhas_3d_master['eletrica'] = rotear_eletrica(ctx['df_eletrica'], ctx, evitar_linhas=st.session_state.linhas_3d_master['hidro'])
            st.session_state.colisoes_detectadas = []
            st.success("✅ Evasão concluída!")
            st.rerun()

# --- ABA 3: ENGENHARIA ELÉTRICA, ALIMENTADOR E QDG ---
with tab_eletrica:
    st.title("⚡ Engenharia Elétrica, Fator de Demanda e QDG")
    df_circ = st.session_state.circuitos
    if not df_circ.empty:
        pot_inst = pd.to_numeric(df_circ['Potência Total (W)'], errors='coerce').fillna(0).sum()
        df_el_ctx = st.session_state.contexto_bim.get('df_eletrica', [])
        tues_count = sum(1 for b in df_el_ctx if "Chuveiro" in str(b.get('Equipamento_Associado','')) or "Ar-Condicionado" in str(b.get('Equipamento_Associado','')))
        fd_geral, fd_tue = calcular_fator_demanda_nbr5410(pot_inst, tues_count)
        demanda_calc = pot_inst * fd_geral

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Potência Instalada", f"{pot_inst:.0f} W")
        c2.metric("Fator de Demanda Aplicado", f"{fd_geral*100:.0f}%")
        c3.metric("Demanda Calculada", f"{demanda_calc:.0f} W")
        tensao_alim = 220 if "Trifásico" in sistema_fornecimento else tensao_fase
        fator_f = 1.732 if "Trifásico" in sistema_fornecimento else 1.0
        corr_alim = demanda_calc / (tensao_alim * fator_f)
        c4.metric("Disjuntor Geral QDG", f"{calcular_disjuntor(corr_alim, 125)} A")

        st.divider()
        st.subheader("📋 Quadro Geral de Cargas Executivo (NBR 5410)")
        df_circ_edit = st.data_editor(df_circ, num_rows="dynamic", use_container_width=True)
        st.session_state.circuitos = df_circ_edit

        st.divider()
        st.subheader("🎛️ Montagem Física Visual do QDG (Trilho DIN)")
        grupos_dr = df_circ['Grupo DR'].unique() if 'Grupo DR' in df_circ.columns else ['DR 1']
        mod_tot = 2 + (len(grupos_dr) * 4) + 2 + len(df_circ)
        res_tot = max(2, math.ceil(mod_tot * 0.25))
        st.info(f"📦 **Caixa Recomendada:** Quadro para **{next((c for c in [12,18,24,36,48,72,100] if c >= (mod_tot+res_tot)), 100)} Módulos DIN** (Ocupados: {mod_tot} | Reserva NBR 5410: {res_tot})")

        html_qdg = '<div style="background-color:#e0e0e0;padding:15px;border-radius:8px;display:flex;gap:6px;flex-wrap:wrap;max-width:850px;margin:auto;">'
        html_qdg += '<div style="background-color:#f44336;color:white;padding:12px 8px;border-radius:4px;font-weight:bold;text-align:center;font-size:11px;">GERAL<br>3P</div>'
        for dr in grupos_dr: html_qdg += f'<div style="background-color:#2196f3;color:white;padding:12px 6px;border-radius:4px;font-weight:bold;text-align:center;font-size:10px;">{dr}<br>IDR 4P</div>'
        html_qdg += '<div style="background-color:#ff9800;color:white;padding:12px 8px;border-radius:4px;font-weight:bold;text-align:center;font-size:11px;">DPS<br>275V</div>'
        for _, r in df_circ.iterrows(): html_qdg += f'<div style="background-color:#4caf50;color:white;padding:10px 4px;border-radius:4px;font-weight:bold;text-align:center;font-size:10px;width:45px;">{r.get("ID","?")}<br>{r.get("Disjuntor (A)","-")}A</div>'
        for _ in range(res_tot): html_qdg += '<div style="background-color:#9e9e9e;color:white;padding:10px 4px;border-radius:4px;font-weight:bold;text-align:center;font-size:9px;">RES</div>'
        html_qdg += '</div>'
        st.markdown(html_qdg, unsafe_allow_html=True)

    st.divider()
    ep1, ep2, ep3 = st.columns(3)
    if not df_circ.empty:
        with ep1:
            with open(gerar_memorial_unifilar(df_circ, "Memorial.pdf"), "rb") as f: st.download_button("📥 Baixar Memorial Unifilar (PDF)", f.read(), "Memorial_NBR5410.pdf", "application/pdf", use_container_width=True)
        with ep2:
            with open(gerar_pdf_qdg(df_circ, "QDG.pdf"), "rb") as f: st.download_button("📥 Baixar Layout QDG (PDF)", f.read(), "Layout_QDG.pdf", "application/pdf", use_container_width=True)
        with ep3:
            eb, en, em = gerar_arquivo_excel_completo()
            st.download_button("📊 Baixar Planilha Completa (.XLSX)", eb, en, em, use_container_width=True)

# --- ABA 4: HIDROSSANITÁRIO ---
with tab_hidro:
    st.title("💧 Engenharia Hidrossanitária (NBR 5626 & NBR 8160)")
    df_h_display = pd.DataFrame(st.session_state.pontos_hidro) if st.session_state.pontos_hidro else pd.DataFrame(columns=["ID", "Andar", "Ambiente", "Equipamento", "z", "Vazão (L/s)", "Tubo AF (mm)", "Pressão Estática (m.c.a.)", "Status Pressão", "UHC", "Tubo Esgoto (mm)"])
    df_hidro_edit = st.data_editor(df_h_display, num_rows="dynamic", use_container_width=True)
    st.session_state.pontos_hidro = df_hidro_edit.to_dict('records')
    st.divider()
    hp1, hp2 = st.columns(2)
    if not df_hidro_edit.empty:
        with hp1:
            with open(gerar_memorial_hidraulico(df_hidro_edit, {"diario": pessoas*consumo_pc, "reserva": vol_caixa, "sugerido": vol_comercial}, "Hidro.pdf"), "rb") as f: st.download_button("📥 Baixar Memorial Hidráulico (PDF)", f.read(), "Memorial_Hidro.pdf", "application/pdf", use_container_width=True)
        with hp2:
            qm = st.session_state.quantitativos_master
            if not qm['agua_fria'].empty:
                with open(gerar_lista_materiais_pdf(qm['agua_fria'], qm['agua_quente'], qm['esgoto'], "Mat.pdf"), "rb") as f: st.download_button("📥 Baixar Lista de Materiais (PDF)", f.read(), "Lista_Materiais.pdf", "application/pdf", use_container_width=True)

# --- ABA 5: PEÇAS CAD (EXPANDIDA COM +20 ITENS) & IFC ---
with tab_pecas_ifc:
    st.title("📐 Desenhos Técnicos de Peças, Quantitativos Totais & Fluxograma IFC")
    st.subheader("1. Gerador de Desenho Técnico CAD (Catálogo Completo ABNT)")
    cp1, cp2 = st.columns([2, 1])
    peca_sel = cp1.selectbox("Selecione a Peça ou Conexão para Detalhamento Técnico Cotado:", [
        "Joelho 90° (Soldável / Roscável)", "Joelho 45° (Soldável / Roscável)", "Tê 90° de Passagem / Derivação",
        "Junção Simples 45° (Y - Esgoto NBR 8160)", "Curva Longa 90° Esgoto / Água", "Luva Simples / Luva de Correr",
        "Redução Excêntrica / Concêntrica", "Cap / Bujão Roscado e Soldável", "Registro de Gaveta 50mm / 25mm",
        "Registro de Pressão 3/4\"", "Caixa Sifonada 150x150x50mm", "Caixa de Gordura / Inspeção",
        "Caixa de Passagem Elétrica 4x2\"", "Caixa de Passagem Elétrica 4x4\"", "Caixa Octogonal de Laje 4x4\"",
        "Eletroduto Corrugado / Rígido PVC", "Disjuntor Termomagnético DIN", "Interruptor Diferencial Residual (IDR)",
        "Dispositivo de Proteção contra Surtos (DPS)", "Barramento Neutro / Terra (PE)"
    ])
    dn_sel = cp2.selectbox("Diâmetro / Dimensão Base (mm):", [15, 20, 22, 25, 32, 40, 50, 75, 100], index=3)
    st.plotly_chart(gerar_desenho_tecnico_peca_plotly(peca_sel, dn_sel), use_container_width=True)

    st.divider()
    st.subheader("2. Quantitativos Totais Extraídos da Geometria 3D (BOM)")
    qm = st.session_state.quantitativos_master
    q1, q2 = st.columns(2)
    with q1:
        st.markdown("**⚡ Quantitativo Total - Elétrica**")
        st.dataframe(qm['eletrica'], use_container_width=True, hide_index=True)
        st.markdown("**🔥 Quantitativo Total - Água Quente**")
        st.dataframe(qm['agua_quente'], use_container_width=True, hide_index=True)
    with q2:
        st.markdown("**💧 Quantitativo Total - Água Fria**")
        st.dataframe(qm['agua_fria'], use_container_width=True, hide_index=True)
        st.markdown("**🤎 Quantitativo Total - Esgoto**")
        st.dataframe(qm['esgoto'], use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("3. Fluxograma Topológico IFC & Exportadores (.DXF com Símbolos ABNT e .IFC)")
    st.plotly_chart(gerar_fluxograma_ifc_plotly(st.session_state.linhas_3d_master['eletrica'], st.session_state.linhas_3d_master['hidro'], config_andares), use_container_width=True)

    paredes_exp, linhas_el_exp, linhas_hd_exp = st.session_state.contexto_bim.get('paredes', []), st.session_state.linhas_3d_master['eletrica'], st.session_state.linhas_3d_master['hidro']
    ce1, ce2, ce3 = st.columns(3)
    with ce1:
        st.download_button("📐 Baixar Elétrica 3D + Símbolos ABNT (.DXF)", exportar_malha_para_dxf(linhas_el_exp, [], paredes_exp, "ELETRICA"), "Eletrica_ABNT.dxf", "application/octet-stream", use_container_width=True)
        st.download_button("🧱 Baixar IFC Elétrica (.IFC)", exportar_malha_para_ifc_step(linhas_el_exp, [], "ELETRICA"), "Eletrico.ifc", "application/octet-stream", use_container_width=True)
    with ce2:
        st.download_button("📐 Baixar Hidráulica 3D (.DXF)", exportar_malha_para_dxf([], linhas_hd_exp, paredes_exp, "HIDRO"), "Hidraulica.dxf", "application/octet-stream", use_container_width=True)
        st.download_button("🧱 Baixar IFC Hidráulica (.IFC)", exportar_malha_para_ifc_step([], linhas_hd_exp, "HIDRO"), "Hidraulico.ifc", "application/octet-stream", use_container_width=True)
    with ce3:
        st.download_button("📐 Baixar Unificado 3D (.DXF)", exportar_malha_para_dxf(linhas_el_exp, linhas_hd_exp, paredes_exp, "UNIFICADO"), "MEP_Unificado.dxf", "application/octet-stream", type="primary", use_container_width=True)
        st.download_button("🧱 Baixar IFC Unificado (.IFC)", exportar_malha_para_ifc_step(linhas_el_exp, linhas_hd_exp, "UNIFICADO"), "MEP_Unificado.ifc", "application/octet-stream", type="primary", use_container_width=True)

# --- ABA 6: BIBLIOTECAS ---
with tab_export:
    st.title("📚 Gerenciamento de Bibliotecas BIM")
    aba_elet, aba_hidro, aba_gas = st.tabs(["⚡ Elétrica", "💧 Hidrossanitário", "🔥 Gás & AVAC"])
    with aba_elet: st.session_state.bib_eletrica = st.data_editor(st.session_state.bib_eletrica, num_rows="dynamic", use_container_width=True)
    with aba_hidro: st.session_state.bib_hidro = st.data_editor(st.session_state.bib_hidro, num_rows="dynamic", use_container_width=True)
    with aba_gas: st.session_state.bib_gas_avac = st.data_editor(st.session_state.bib_gas_avac, num_rows="dynamic", use_container_width=True)
