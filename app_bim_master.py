# ==============================================================================
# PARTE 1 DE 10: IMPORTAÇÕES, LOGIN (SECRETS) E TABELAS NORMATIVAS BASE
# ==============================================================================
import streamlit as st
import pandas as pd
import ezdxf
import math
import tempfile
import io
import os
import re
import json
import uuid
import time
import hmac
import networkx as nx
import plotly.graph_objects as go
from pathfinding.core.diagonal_movement import DiagonalMovement
from pathfinding.core.grid import Grid
from pathfinding.finder.a_star import AStarFinder

try:
    import ifcopenshell
    import ifcopenshell.api
    HAS_IFC = True
except ImportError:
    HAS_IFC = False

from gerador_unifilar_pdf import gerar_memorial_unifilar, gerar_pdf_qdg
from gerador_hidraulica_pdf import gerar_memorial_hidraulico, gerar_lista_materiais_pdf

st.set_page_config(layout="wide", page_title="BIM Master PRO V16 - Engenharia MEP Completa", page_icon="🏢")

def verificar_autenticacao():
    """Valida a senha cadastrada em st.secrets['app_password'] no Streamlit Cloud."""
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

if 'circuitos' not in st.session_state:
    st.session_state.circuitos = pd.DataFrame(columns=[
        "ID", "Ambiente", "Equipamento", "Qtd", "Potência Total (W)", "Tensão (V)",
        "Fator de Potência", "Método Inst.", "Eletroduto (Ref)", "FCA", "FCT",
        "Corrente (A)", "Corrente Corrigida (A)", "Bitola (mm²)", "Queda Tensão (%)",
        "Disjuntor (A)", "Curva", "Icc (A)", "Distância (m)", "Fase", "Grupo DR",
        "Eletroduto (mm)", "Ocupação (%)"
    ])
if 'auditoria_ambientes' not in st.session_state:
    st.session_state.auditoria_ambientes = pd.DataFrame([
        {"Ambiente": "Sala de Estar / Jantar", "Tipo Cômodo (NBR 5410)": "Sala / Dormitório", "Área (m²)": 24.0, "Perímetro (m)": 20.0},
        {"Ambiente": "Cozinha Gourmet", "Tipo Cômodo (NBR 5410)": "Cozinha / Copa / Área de Serviço", "Área (m²)": 14.0, "Perímetro (m)": 15.0},
        {"Ambiente": "Suíte Master", "Tipo Cômodo (NBR 5410)": "Sala / Dormitório", "Área (m²)": 16.0, "Perímetro (m)": 16.0},
        {"Ambiente": "Banheiro Suíte", "Tipo Cômodo (NBR 5410)": "Banheiro", "Área (m²)": 5.5, "Perímetro (m)": 9.5},
        {"Ambiente": "Área de Serviço / Lavanderia", "Tipo Cômodo (NBR 5410)": "Cozinha / Copa / Área de Serviço", "Área (m²)": 6.0, "Perímetro (m)": 10.0},
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

TABELA_AMPACIDADE_NBR5410 = {
    1.5:  {"A1_2": 14.5, "B1_2": 17.5, "B1_3": 15.5, "B2_2": 16.5, "C_2": 19.5, "B1_90": 23.0, "AL_B1": 13.5, "Area_Ext_mm2": 7.1},
    2.5:  {"A1_2": 19.5, "B1_2": 24.0, "B1_3": 21.0, "B2_2": 23.0, "C_2": 27.0, "B1_90": 31.0, "AL_B1": 18.5, "Area_Ext_mm2": 10.2},
    4.0:  {"A1_2": 26.0, "B1_2": 32.0, "B1_3": 28.0, "B2_2": 30.0, "C_2": 36.0, "B1_90": 42.0, "AL_B1": 25.0, "Area_Ext_mm2": 13.8},
    6.0:  {"A1_2": 34.0, "B1_2": 41.0, "B1_3": 36.0, "B2_2": 38.0, "C_2": 46.0, "B1_90": 54.0, "AL_B1": 32.0, "Area_Ext_mm2": 18.1},
    10.0: {"A1_2": 46.0, "B1_2": 57.0, "B1_3": 50.0, "B2_2": 52.0, "C_2": 63.0, "B1_90": 75.0, "AL_B1": 44.0, "Area_Ext_mm2": 28.3},
    16.0: {"A1_2": 61.0, "B1_2": 76.0, "B1_3": 68.0, "B2_2": 69.0, "C_2": 85.0, "B1_90": 100.0, "AL_B1": 60.0, "Area_Ext_mm2": 40.7},
    25.0: {"A1_2": 80.0, "B1_2": 101.0, "B1_3": 89.0, "B2_2": 90.0, "C_2": 112.0, "B1_90": 133.0, "AL_B1": 78.0, "Area_Ext_mm2": 60.8},
    35.0: {"A1_2": 99.0, "B1_2": 125.0, "B1_3": 110.0, "B2_2": 111.0, "C_2": 138.0, "B1_90": 164.0, "AL_B1": 97.0, "Area_Ext_mm2": 78.5},
    50.0: {"A1_2": 119.0, "B1_2": 151.0, "B1_3": 134.0, "B2_2": 133.0, "C_2": 168.0, "B1_90": 198.0, "AL_B1": 118.0, "Area_Ext_mm2": 113.0},
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
# ==============================================================================
# PARTE 2 DE 10: FUNÇÕES DE ENGENHARIA, PLUVIAL (NBR 10844) E GÁS (NBR 15526)
# ==============================================================================
def calcular_corrente_e_cabo(potencia_va, tensao):
    if tensao == 0 or potencia_va == 0:
        return 0.0, 0.0, 0
    corrente = potencia_va / tensao
    cabo = next((s for s, c in [(1.5, 17.5), (2.5, 24), (4.0, 32), (6.0, 41), (10.0, 57), (16.0, 76), (25.0, 101)] if c >= corrente), 35.0)
    disjuntor = next((d for d in DISJUNTORES_PADRAO_DIN if d > corrente), 125)
    return round(corrente, 2), cabo, disjuntor

def calcular_bitola_avancada(corrente_projeto, metodo_inst, fca=1.0, material="Cobre", tipo="TUG", isolacao="70°C (PVC)"):
    corrente_corrigida = corrente_projeto / fca if fca > 0 else corrente_projeto
    chave = "AL_B1" if material == "Alumínio" else ("B1_90" if "90" in isolacao else ("A1_2" if metodo_inst == "A1" else ("B2_2" if metodo_inst == "B2" else ("C_2" if metodo_inst == "C" else "B1_2"))))

    bitola_calculada = 50.0
    for bitola, dados in sorted(TABELA_AMPACIDADE_NBR5410.items()):
        cap_max = dados.get(chave, dados["B1_2"])
        if cap_max >= corrente_corrigida:
            bitola_calculada = bitola
            break

    tipo_limpo = str(tipo).strip()
    if material == "Cobre":
        if "Iluminação" in tipo_limpo or "Lâmpada" in tipo_limpo:
            if bitola_calculada < 1.5: return 1.5
        else:
            if bitola_calculada < 2.5: return 2.5
    elif material == "Alumínio":
        if bitola_calculada < 16.0: return 16.0
    return bitola_calculada

def calcular_disjuntor(corrente_projeto, bitola_capacidade):
    for d in DISJUNTORES_PADRAO_DIN:
        if d >= corrente_projeto and d <= bitola_capacidade:
            return d
    for d in DISJUNTORES_PADRAO_DIN:
        if d >= corrente_projeto:
            return d
    return 125

def obter_fca(num_circuitos):
    if num_circuitos <= 1: return 1.00
    elif num_circuitos == 2: return 0.80
    elif num_circuitos == 3: return 0.70
    elif num_circuitos == 4: return 0.65
    elif num_circuitos == 5: return 0.60
    else: return 0.50

def calcular_icc(tensao, bitola, distancia, material="Cobre"):
    if not bitola or bitola == 0 or pd.isna(bitola):
        return 0.0
    rho = 0.021 if material == "Cobre" else 0.035
    r_cabo = rho * (2.0 * max(1.0, float(distancia))) / float(bitola)
    z_total = r_cabo + 0.05
    icc = float(tensao) / z_total
    return round(icc, 2)

def auditar_ambiente_nbr5410(nome_amb, tipo_comodo, area_m2, perimetro_m):
    if area_m2 <= 6.0:
        pot_ilum_va = 100
    else:
        excedente = area_m2 - 6.0
        passos_4m2 = int(excedente // 4.0)
        pot_ilum_va = 100 + (passos_4m2 * 60)
    qtd_luminarias_sug = max(1, math.ceil(pot_ilum_va / 100))

    if tipo_comodo == "Banheiro":
        qtd_tugs = 1
        pot_tugs_va = 600
        regra_txt = "Mín. 1 tomada junto ao lavatório (600 VA)"
    elif tipo_comodo == "Cozinha / Copa / Área de Serviço":
        qtd_tugs = max(2, math.ceil(perimetro_m / 3.5))
        tugs_600 = min(3, qtd_tugs)
        tugs_100 = max(0, qtd_tugs - 3)
        pot_tugs_va = (tugs_600 * 600) + (tugs_100 * 100)
        regra_txt = f"1 tomada a cada 3,5m ({tugs_600}x 600VA + {tugs_100}x 100VA)"
    elif tipo_comodo == "Varanda / Garagem / Sótão":
        qtd_tugs = 1
        pot_tugs_va = 100
        regra_txt = "Mín. 1 tomada (100 VA)"
    else:
        qtd_tugs = max(1, math.ceil(perimetro_m / 5.0))
        pot_tugs_va = qtd_tugs * 100
        regra_txt = f"1 tomada a cada 5,0m ({qtd_tugs}x 100VA)"

    return {
        "Ambiente": nome_amb,
        "Tipo Cômodo": tipo_comodo,
        "Área (m²)": area_m2,
        "Perímetro (m)": perimetro_m,
        "Ilum. Mínima (VA)": pot_ilum_va,
        "Pts Luz Sug.": qtd_luminarias_sug,
        "Qtd Mín. TUGs": qtd_tugs,
        "Pot. Mín. TUGs (VA)": pot_tugs_va,
        "Critério Normativo NBR 5410": regra_txt
    }

def calcular_demanda_escalonada_prodist(df_circuitos):
    if df_circuitos.empty:
        return 0.0, 0.0, 0.0, 0.80, 1.00

    pot_ilum_tug = 0.0
    pot_tue = 0.0
    qtd_tue = 0

    for _, row in df_circuitos.iterrows():
        pot = float(row.get('Potência Total (W)', 0.0))
        eq_str = str(row.get('Equipamento', '')).upper()
        if pot >= 2000 or any(k in eq_str for k in ['CHUVEIRO', 'COOKTOP', 'AR-CONDICIONADO', 'AR SPLIT', 'FORNO', 'WALLBOX', 'TORNEIRA ELÉTRICA', 'SECADORA']):
            pot_tue += pot
            qtd_tue += 1
        else:
            pot_ilum_tug += pot

    kva_it = pot_ilum_tug / 1000.0
    if kva_it <= 1.0: fd_it = 0.86
    elif kva_it <= 2.0: fd_it = 0.75
    elif kva_it <= 3.0: fd_it = 0.66
    elif kva_it <= 4.0: fd_it = 0.59
    elif kva_it <= 5.0: fd_it = 0.52
    elif kva_it <= 10.0: fd_it = 0.45
    else: fd_it = 0.40

    if qtd_tue <= 1: fd_tue = 1.00
    elif qtd_tue == 2: fd_tue = 0.84
    elif qtd_tue == 3: fd_tue = 0.76
    elif qtd_tue == 4: fd_tue = 0.70
    elif qtd_tue <= 6: fd_tue = 0.62
    else: fd_tue = 0.55

    demanda_it = pot_ilum_tug * fd_it
    demanda_tue = pot_tue * fd_tue
    demanda_total_w = demanda_it + demanda_tue
    return round(pot_ilum_tug, 1), round(pot_tue, 1), round(demanda_total_w, 1), fd_it, fd_tue

def dimensionar_aguas_pluviais_nbr10844(area_cobertura_m2, intensidade_mm_h=150.0, declividade_calha_pct=0.5):
    """
    Dimensionamento de Águas Pluviais (ABNT NBR 10844):
    Q = (I * A) / 60 (L/min). Dimensiona Calha semicircular (Manning) e Condutores Verticais (Tubos de Queda Pluvial).
    """
    vazao_l_min = (intensidade_mm_h * area_cobertura_m2) / 60.0
    # Capacidade de calhas semicirculares (L/min) para declividade 0.5% (NBR 10844 Tabela 2)
    calhas_nbr = [(100, 130), (125, 236), (150, 384), (200, 829), (250, 1488)]
    fator_decliv = math.sqrt(max(0.5, declividade_calha_pct) / 0.5)
    diam_calha_mm = 250
    for d_c, cap_base in calhas_nbr:
        if (cap_base * fator_decliv) >= vazao_l_min:
            diam_calha_mm = d_c
            break

    # Capacidade de condutores verticais (L/min) para H=120mm (NBR 10844)
    condutores_vert = {75: 330.0, 100: 720.0, 150: 2040.0}
    dn_condutor = 100 if vazao_l_min > 330 else 75
    qtd_condutores = max(1, math.ceil(vazao_l_min / condutores_vert[dn_condutor]))

    return {
        "Vazao_L_min": round(vazao_l_min, 1),
        "Diametro_Calha_mm": diam_calha_mm,
        "DN_Condutor_Vertical_mm": dn_condutor,
        "Qtd_Tubos_Queda_Pluvial": qtd_condutores
    }

def dimensionar_rede_gas_nbr15526(potencia_total_kcal_min, comprimento_m=15.0, tipo_gas="GLP"):
    """
    Dimensionamento de Rede Interna de Gás Combustível (ABNT NBR 15526):
    PCI GLP = 24.000 kcal/m³ | PCI GN = 9.400 kcal/m³. Perda de carga máxima admitida <= 10% da pressão de operação.
    """
    pci = 24000.0 if "GLP" in tipo_gas else 9400.0
    vazao_m3_h = (potencia_total_kcal_min * 60.0) / pci if pci > 0 else 0.0
    if vazao_m3_h <= 1.2 and comprimento_m <= 15:
        dn_cobre = 15
    elif vazao_m3_h <= 3.5 and comprimento_m <= 25:
        dn_cobre = 22
    elif vazao_m3_h <= 7.5:
        dn_cobre = 28
    else:
        dn_cobre = 35
    return {
        "Vazao_Gas_m3_h": round(vazao_m3_h, 2),
        "Tubo_Cobre_PEX_mm": dn_cobre,
        "Pressao_Operacao_kPa": 2.8 if "GLP" in tipo_gas else 2.0
    }
# ==============================================================================
# PARTE 3 DE 10: DADOS COMPLETOS DA BIBLIOTECA HIDROSSANITÁRIA, PLUVIAL E GÁS
# ==============================================================================
DADOS_BIB_HIDRO_PADRAO = [
    # ---- APARELHOS SANITÁRIOS E ELETRODOMÉSTICOS (ÁGUA + ESGOTO) ----
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
    {"Equipamento": "Torneira Gourmet Cozinha (Mono/Duplo)", "Vazao_Ls": 0.30, "Peso": 0.8, "Agua_mm": 20, "AQ_mm": 22, "Pressao_kpa": 15, "UHC": 3, "Esgoto_mm": 40, "Vent_mm": 40},
    {"Equipamento": "Torneira quintal", "Vazao_Ls": 0.20, "Peso": 0.4, "Agua_mm": 20, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Pia de Cozinha (Residencial)", "Vazao_Ls": 0.25, "Peso": 0.7, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 10, "UHC": 3, "Esgoto_mm": 50, "Vent_mm": 40},
    {"Equipamento": "Pia de Cozinha - Cuba Simples", "Vazao_Ls": 0.25, "Peso": 0.7, "Agua_mm": 20, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 3, "Esgoto_mm": 50, "Vent_mm": 40},
    {"Equipamento": "Pia de Cozinha - Cuba Dupla Gourmet", "Vazao_Ls": 0.25, "Peso": 0.7, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 15, "UHC": 3, "Esgoto_mm": 50, "Vent_mm": 40},
    {"Equipamento": "Pia de Cozinha (Industrial/Restaurante)", "Vazao_Ls": 0.50, "Peso": 1.5, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 15, "UHC": 4, "Esgoto_mm": 50, "Vent_mm": 40},
    {"Equipamento": "Máquina de Lavar Roupa", "Vazao_Ls": 0.30, "Peso": 1.0, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 3, "Esgoto_mm": 50, "Vent_mm": 40},
    {"Equipamento": "Máquina de Lavar Louça", "Vazao_Ls": 0.30, "Peso": 1.0, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 10, "UHC": 2, "Esgoto_mm": 50, "Vent_mm": 40},
    {"Equipamento": "Máquina de Lavar Louça (8 Serviços)", "Vazao_Ls": 0.30, "Peso": 1.0, "Agua_mm": 20, "AQ_mm": 22, "Pressao_kpa": 10, "UHC": 2, "Esgoto_mm": 50, "Vent_mm": 40},
    {"Equipamento": "Máquina de Lavar Louça (14 Serviços Premium)", "Vazao_Ls": 0.30, "Peso": 1.0, "Agua_mm": 20, "AQ_mm": 22, "Pressao_kpa": 10, "UHC": 2, "Esgoto_mm": 50, "Vent_mm": 40},
    {"Equipamento": "Tanque de Lavar Roupa", "Vazao_Ls": 0.25, "Peso": 0.7, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 3, "Esgoto_mm": 40, "Vent_mm": 40},
    {"Equipamento": "Tanque de Lavar Roupa (Plástico)", "Vazao_Ls": 0.25, "Peso": 0.7, "Agua_mm": 20, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 3, "Esgoto_mm": 40, "Vent_mm": 40},
    {"Equipamento": "Tanque de Lavar Roupa (Inox/Apoio Luxo)", "Vazao_Ls": 0.25, "Peso": 0.7, "Agua_mm": 20, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 3, "Esgoto_mm": 40, "Vent_mm": 40},
    {"Equipamento": "Ducha Higiênica", "Vazao_Ls": 0.10, "Peso": 0.1, "Agua_mm": 20, "AQ_mm": 22, "Pressao_kpa": 10, "UHC": 1, "Esgoto_mm": 40, "Vent_mm": 0},
    {"Equipamento": "Bebedouro", "Vazao_Ls": 0.10, "Peso": 0.1, "Agua_mm": 20, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 0.5, "Esgoto_mm": 40, "Vent_mm": 0},
    {"Equipamento": "Filtro/Purificador de Parede", "Vazao_Ls": 0.05, "Peso": 0.1, "Agua_mm": 20, "AQ_mm": 0, "Pressao_kpa": 10, "UHC": 1, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Geladeira Side-by-Side (Filtro/Gelo)", "Vazao_Ls": 0.05, "Peso": 0.1, "Agua_mm": 20, "AQ_mm": 0, "Pressao_kpa": 15, "UHC": 1, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Mictório Cerâmico (c/ válvula)", "Vazao_Ls": 0.50, "Peso": 2.8, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 15, "UHC": 2, "Esgoto_mm": 50, "Vent_mm": 40},

    # ---- INFRAESTRUTURA DE ABASTECIMENTO (EXCLUSIVO ÁGUA) ----
    {"Equipamento": "Caixa d'Água (Reservatório Superior)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Cisterna (Reservatório Inferior)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Bomba de Recalque", "Vazao_Ls": 1.50, "Peso": 0.0, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 200, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Bomba Pressurizadora Residencial", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 150, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Válvula Redutora de Pressão (VRP) 32mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Alimentação Rua (Concessionária)", "Vazao_Ls": 0.50, "Peso": 0.0, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 150, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Boiler (Aquecimento de Água Central)", "Vazao_Ls": 0.30, "Peso": 0.5, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 20, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Aquecedor de Passagem a Gás", "Vazao_Ls": 0.30, "Peso": 0.5, "Agua_mm": 25, "AQ_mm": 22, "Pressao_kpa": 20, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},

    # ---- SAÍDAS E REGISTROS DE ÁGUA ----
    {"Equipamento": "Saída de Água Fria 32mm", "Vazao_Ls": 0.50, "Peso": 1.2, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Saída de Água Quente 22mm", "Vazao_Ls": 0.25, "Peso": 0.7, "Agua_mm": 0, "AQ_mm": 22, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Registro de Gaveta 50mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 50, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Registro de Gaveta 40mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 40, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Registro de Gaveta 32mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Registro de Gaveta 25mm (3/4)", "Vazao_Ls": 0.60, "Peso": 0.6, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Registro de Gaveta 22mm (1/2)", "Vazao_Ls": 0.30, "Peso": 0.3, "Agua_mm": 22, "AQ_mm": 22, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Registro de Pressão 32mm (1)", "Vazao_Ls": 0.00, "Peso": 9.5, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Registro de Pressão 25mm (3/4)", "Vazao_Ls": 0.00, "Peso": 7.4, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Registro de Pressão 22mm (1/2)", "Vazao_Ls": 0.00, "Peso": 5.4, "Agua_mm": 22, "AQ_mm": 22, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Válvula de Retenção 25mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Válvula de Retenção 32mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},

    # ---- CONEXÕES DE ÁGUA ----
    {"Equipamento": "Curva 90° 22mm", "Vazao_Ls": 0.00, "Peso": 0.4, "Agua_mm": 22, "AQ_mm": 22, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Curva 90° 25mm", "Vazao_Ls": 0.00, "Peso": 0.5, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Curva 90° 32mm", "Vazao_Ls": 0.00, "Peso": 0.6, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Joelho 90° 22mm", "Vazao_Ls": 0.00, "Peso": 1.1, "Agua_mm": 22, "AQ_mm": 22, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Joelho 90° 25mm", "Vazao_Ls": 0.00, "Peso": 1.2, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Joelho 90° 32mm", "Vazao_Ls": 0.00, "Peso": 1.5, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Joelho 45° 22mm", "Vazao_Ls": 0.00, "Peso": 0.4, "Agua_mm": 22, "AQ_mm": 22, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Joelho 45° 25mm", "Vazao_Ls": 0.00, "Peso": 0.5, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Joelho 45° 32mm", "Vazao_Ls": 0.00, "Peso": 0.7, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Tê 90° (Passagem Direta) 22mm", "Vazao_Ls": 0.00, "Peso": 0.7, "Agua_mm": 22, "AQ_mm": 22, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Tê 90° (Passagem Direta) 25mm", "Vazao_Ls": 0.00, "Peso": 0.8, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Tê 90° (Passagem Direta) 32mm", "Vazao_Ls": 0.00, "Peso": 0.9, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Junção Y 22mm", "Vazao_Ls": 0.00, "Peso": 0.5, "Agua_mm": 22, "AQ_mm": 22, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Junção Y 25mm", "Vazao_Ls": 0.00, "Peso": 0.6, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Junção Y 32mm", "Vazao_Ls": 0.00, "Peso": 0.8, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},

    # ---- ELEMENTOS E CONEXÕES DE ESGOTO E ÁGUAS PLUVIAIS ----
    {"Equipamento": "Caixa Sifonada 100x100x50mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 50, "Vent_mm": 40},
    {"Equipamento": "Caixa Sifonada 150x150x50mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 6, "Esgoto_mm": 50, "Vent_mm": 40},
    {"Equipamento": "Caixa de Gordura", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 2, "Esgoto_mm": 75, "Vent_mm": 50},
    {"Equipamento": "Caixa de Inspeção", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 100, "Vent_mm": 0},
    {"Equipamento": "Caixa de Passagem", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 100, "Vent_mm": 0},
    {"Equipamento": "Caixa de Areia Pluvial (NBR 10844)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 100, "Vent_mm": 0},
    {"Equipamento": "Ralo Sifonado", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 2, "Esgoto_mm": 100, "Vent_mm": 40},
    {"Equipamento": "Ralo Seco (Chuveiro)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 2, "Esgoto_mm": 40, "Vent_mm": 0},
    {"Equipamento": "Ralo Linear Inox (Box Banheiro)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 2, "Esgoto_mm": 40, "Vent_mm": 0},
    {"Equipamento": "Ralo de Varanda/Sacada", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 2, "Esgoto_mm": 50, "Vent_mm": 0},
    {"Equipamento": "Ralo Hemisférico (Abacaxi) de Calha Pluvial", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 100, "Vent_mm": 0},
    {"Equipamento": "Ponto de Esgoto Geral", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 3, "Esgoto_mm": 50, "Vent_mm": 40},
    {"Equipamento": "Ponto de Esgoto 100mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 6, "Esgoto_mm": 100, "Vent_mm": 50},
    {"Equipamento": "Ponto de Esgoto 75mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 3, "Esgoto_mm": 75, "Vent_mm": 50},
    {"Equipamento": "Ponto de Esgoto 50mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 2, "Esgoto_mm": 50, "Vent_mm": 40},
    {"Equipamento": "Ponto de Esgoto 40mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 1, "Esgoto_mm": 40, "Vent_mm": 40},
    {"Equipamento": "Tubo de Queda (TQ - Esgoto Primário)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 100, "Vent_mm": 75},
    {"Equipamento": "Condutor Vertical de Águas Pluviais (AP 100mm)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 100, "Vent_mm": 0},
    {"Equipamento": "Coluna de Ventilação", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 50, "Vent_mm": 50},
    {"Equipamento": "Curva 90° Esgoto 40mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 40, "Vent_mm": 0},
    {"Equipamento": "Curva 90° Esgoto 50mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 50, "Vent_mm": 0},
    {"Equipamento": "Curva 90° Esgoto 75mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 75, "Vent_mm": 0},
    {"Equipamento": "Curva 90° Esgoto 100mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 100, "Vent_mm": 0},
    {"Equipamento": "Joelho 90° Esgoto 40mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 40, "Vent_mm": 0},
    {"Equipamento": "Joelho 90° Esgoto 50mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 50, "Vent_mm": 0},
    {"Equipamento": "Joelho 90° Esgoto 75mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 75, "Vent_mm": 0},
    {"Equipamento": "Joelho 90° Esgoto 100mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 100, "Vent_mm": 0},
    {"Equipamento": "Joelho 45° Esgoto 40mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 40, "Vent_mm": 0},
    {"Equipamento": "Joelho 45° Esgoto 50mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 50, "Vent_mm": 0},
    {"Equipamento": "Joelho 45° Esgoto 75mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 75, "Vent_mm": 0},
    {"Equipamento": "Joelho 45° Esgoto 100mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 100, "Vent_mm": 0},
    {"Equipamento": "Tê 90° Esgoto 40mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 40, "Vent_mm": 0},
    {"Equipamento": "Tê 90° Esgoto 50mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 50, "Vent_mm": 0},
    {"Equipamento": "Tê 90° Esgoto 75mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 75, "Vent_mm": 0},
    {"Equipamento": "Tê 90° Esgoto 100mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 100, "Vent_mm": 0},
    {"Equipamento": "Junção Y Esgoto 40mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 40, "Vent_mm": 0},
    {"Equipamento": "Junção Y Esgoto 50mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 50, "Vent_mm": 0},
    {"Equipamento": "Junção Y Esgoto 75mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 75, "Vent_mm": 0},
    {"Equipamento": "Junção Y Esgoto 100mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 100, "Vent_mm": 0},

    # ---- GÁS E ESPECIAIS ----
    {"Equipamento": "Ponto de Gás (Fogão/Aquecedor)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 2.8, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Abrigo / Central de Gás GLP/GN", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 2.8, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
]
# ==============================================================================
# PARTE 4 DE 10: BIBLIOTECA ELÉTRICA (52 ITENS), GÁS/AVAC E SAVE/LOAD/EXCEL
# ==============================================================================
DADOS_BIB_ELETRICA_PADRAO = [
    {"Equipamento": "Lâmpada LED 15W", "Potência (W)": 15, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "Iluminação", "Curva Disjuntor": "B", "Uso de DR": "Opcional"},
    {"Equipamento": "Tomada Uso Geral (TUG)", "Potência (W)": 100, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Opcional"},
    {"Equipamento": "Tomada Cozinha/Serviço (TUG)", "Potência (W)": 600, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Chuveiro Elétrico 7500W", "Potência (W)": 7500, "Tensão (V)": 220, "Fator de Potência": 1.0, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Cooktop Indução 7000W", "Potência (W)": 7000, "Tensão (V)": 220, "Fator de Potência": 1.0, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Ar-Condicionado 12000 BTU", "Potência (W)": 1200, "Tensão (V)": 220, "Fator de Potência": 0.95, "Tipo": "TUE", "Curva Disjuntor": "C", "Uso de DR": "Opcional"},
    {"Equipamento": "Fritadeira Elétrica (Air Fryer)", "Potência (W)": 1500, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Computador Desktop", "Potência (W)": 500, "Tensão (V)": 127, "Fator de Potência": 0.9, "Tipo": "TUG", "Curva Disjuntor": "C", "Uso de DR": "Opcional"},
    {"Equipamento": "Lâmpada LED 9W", "Potência (W)": 9, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "Iluminação", "Curva Disjuntor": "B", "Uso de DR": "Opcional"},
    {"Equipamento": "Refletor LED Área Externa 50W", "Potência (W)": 50, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Televisão LED/OLED > 42 polegadas", "Potência (W)": 200, "Tensão (V)": 127, "Fator de Potência": 0.95, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Opcional"},
    {"Equipamento": "Chuveiro Elétrico 5500W", "Potência (W)": 5500, "Tensão (V)": 220, "Fator de Potência": 1.0, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Ar-Condicionado 9000 BTU", "Potência (W)": 900, "Tensão (V)": 220, "Fator de Potência": 0.95, "Tipo": "TUE", "Curva Disjuntor": "C", "Uso de DR": "Opcional"},
    {"Equipamento": "Ar-Condicionado 18000 BTU", "Potência (W)": 1800, "Tensão (V)": 220, "Fator de Potência": 0.95, "Tipo": "TUE", "Curva Disjuntor": "C", "Uso de DR": "Opcional"},
    {"Equipamento": "Ar-Condicionado 32000 BTU", "Potência (W)": 3500, "Tensão (V)": 220, "Fator de Potência": 0.95, "Tipo": "TUE", "Curva Disjuntor": "C", "Uso de DR": "Opcional"},
    {"Equipamento": "Microondas", "Potência (W)": 1500, "Tensão (V)": 127, "Fator de Potência": 0.95, "Tipo": "TUG", "Curva Disjuntor": "C", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Geladeira Frost Free", "Potência (W)": 400, "Tensão (V)": 127, "Fator de Potência": 0.85, "Tipo": "TUG", "Curva Disjuntor": "C", "Uso de DR": "Opcional"},
    {"Equipamento": "Freezer Vertical Inverter", "Potência (W)": 350, "Tensão (V)": 127, "Fator de Potência": 0.92, "Tipo": "TUG", "Curva Disjuntor": "C", "Uso de DR": "Opcional"},
    {"Equipamento": "Forno Elétrico de Embutir", "Potência (W)": 3500, "Tensão (V)": 220, "Fator de Potência": 1.0, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Máquina de Lavar Louça", "Potência (W)": 2500, "Tensão (V)": 220, "Fator de Potência": 0.9, "Tipo": "TUE", "Curva Disjuntor": "C", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Secadora de Roupas", "Potência (W)": 3500, "Tensão (V)": 220, "Fator de Potência": 1.0, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Motobomba de Piscina 1 CV", "Potência (W)": 746, "Tensão (V)": 127, "Fator de Potência": 0.75, "Tipo": "Motores", "Curva Disjuntor": "C", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Aspirador de Pó 1500W", "Potência (W)": 1500, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Liquidificador 800W", "Potência (W)": 800, "Tensão (V)": 127, "Fator de Potência": 0.8, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Cafeteira Elétrica 1000W", "Potência (W)": 1000, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Máquina de Café Espresso Pro", "Potência (W)": 1450, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Sanduicheira/Grill 1200W", "Potência (W)": 1200, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Ferro de Passar 1500W", "Potência (W)": 1500, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Secador de Cabelo 2000W", "Potência (W)": 2000, "Tensão (V)": 220, "Fator de Potência": 1.0, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Torneira Elétrica 5500W", "Potência (W)": 5500, "Tensão (V)": 220, "Fator de Potência": 1.0, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Aquecedor de Ambiente 2000W", "Potência (W)": 2000, "Tensão (V)": 220, "Fator de Potência": 1.0, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Portão Eletrônico", "Potência (W)": 400, "Tensão (V)": 127, "Fator de Potência": 0.7, "Tipo": "Motores", "Curva Disjuntor": "C", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Exaustor de Cozinha 200W", "Potência (W)": 200, "Tensão (V)": 127, "Fator de Potência": 0.7, "Tipo": "Iluminação", "Curva Disjuntor": "C", "Uso de DR": "Opcional"},
    {"Equipamento": "Impressora Laser 400W", "Potência (W)": 400, "Tensão (V)": 127, "Fator de Potência": 0.9, "Tipo": "TUG", "Curva Disjuntor": "C", "Uso de DR": "Opcional"},
    {"Equipamento": "Home Theater 500W", "Potência (W)": 500, "Tensão (V)": 127, "Fator de Potência": 0.8, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Opcional"},
    {"Equipamento": "Ar Split 24000 BTU", "Potência (W)": 2500, "Tensão (V)": 220, "Fator de Potência": 0.95, "Tipo": "TUE", "Curva Disjuntor": "C", "Uso de DR": "Opcional"},
    {"Equipamento": "Ar Split 60000 BTU (Piso Teto)", "Potência (W)": 5500, "Tensão (V)": 220, "Fator de Potência": 0.95, "Tipo": "TUE", "Curva Disjuntor": "C", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Lustre Cristal (10 lâmpadas LED)", "Potência (W)": 100, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "Iluminação", "Curva Disjuntor": "B", "Uso de DR": "Opcional"},
    {"Equipamento": "Fita LED Perfil Embutido (5m)", "Potência (W)": 45, "Tensão (V)": 127, "Fator de Potência": 0.92, "Tipo": "Iluminação", "Curva Disjuntor": "B", "Uso de DR": "Opcional"},
    {"Equipamento": "Bomba Poço Artesiano 1.5 CV", "Potência (W)": 1100, "Tensão (V)": 220, "Fator de Potência": 0.8, "Tipo": "Motores", "Curva Disjuntor": "C", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Carregador Veículo Elétrico (Wallbox) 7kW", "Potência (W)": 7000, "Tensão (V)": 220, "Fator de Potência": 1.0, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Exaustor de Banheiro 200W", "Potência (W)": 40, "Tensão (V)": 127, "Fator de Potência": 0.8, "Tipo": "Iluminação", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Ventilador de teto", "Potência (W)": 150, "Tensão (V)": 127, "Fator de Potência": 0.85, "Tipo": "Iluminação", "Curva Disjuntor": "C", "Uso de DR": "Opcional"},
    {"Equipamento": "Trilho magnético (1m)", "Potência (W)": 60, "Tensão (V)": 127, "Fator de Potência": 0.9, "Tipo": "Iluminação", "Curva Disjuntor": "B", "Uso de DR": "Opcional"},
    {"Equipamento": "Desumidificador elétrico", "Potência (W)": 300, "Tensão (V)": 127, "Fator de Potência": 0.85, "Tipo": "TUG", "Curva Disjuntor": "C", "Uso de DR": "Opcional"},
    {"Equipamento": "Sistema de segurança (CFTV)", "Potência (W)": 150, "Tensão (V)": 127, "Fator de Potência": 0.7, "Tipo": "Dedicado", "Curva Disjuntor": "B", "Uso de DR": "Não"},
    {"Equipamento": "Triturador de Pia", "Potência (W)": 750, "Tensão (V)": 127, "Fator de Potência": 0.75, "Tipo": "Motores", "Curva Disjuntor": "C", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Espelho Automatizado (Led + Desembaçador)", "Potência (W)": 100, "Tensão (V)": 127, "Fator de Potência": 0.7, "Tipo": "Iluminação", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Toalheiro Térmico", "Potência (W)": 150, "Tensão (V)": 127, "Fator de Potência": 1.0, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Bomba de Pressurização de Água", "Potência (W)": 750, "Tensão (V)": 127, "Fator de Potência": 0.75, "Tipo": "Dedicado", "Curva Disjuntor": "C", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Lava e Seca (Roupas)", "Potência (W)": 750, "Tensão (V)": 127, "Fator de Potência": 0.7, "Tipo": "TUE", "Curva Disjuntor": "C", "Uso de DR": "Obrigatório"},
    {"Equipamento": "Central de Automação_Hub_Houter", "Potência (W)": 80, "Tensão (V)": 127, "Fator de Potência": 0.5, "Tipo": "Dedicado", "Curva Disjuntor": "B", "Uso de DR": "Não"}
]

DADOS_BIB_GAS_AVAC_PADRAO = [
    {"Equipamento": "Fogão 4 Bocas c/ Forno (GLP/GN)", "Potencia_kcal_min": 135, "Pressao_kPa": 2.8, "Tubo_Cobre_mm": 15, "Norma": "NBR 15526"},
    {"Equipamento": "Fogão 6 Bocas Gourmet (GLP/GN)", "Potencia_kcal_min": 210, "Pressao_kPa": 2.8, "Tubo_Cobre_mm": 22, "Norma": "NBR 15526"},
    {"Equipamento": "Cooktop a Gás 5 Bocas", "Potencia_kcal_min": 165, "Pressao_kPa": 2.8, "Tubo_Cobre_mm": 15, "Norma": "NBR 15526"},
    {"Equipamento": "Aquecedor de Passagem 21 L/min", "Potencia_kcal_min": 500, "Pressao_kPa": 2.8, "Tubo_Cobre_mm": 22, "Norma": "NBR 15526"},
    {"Equipamento": "Aquecedor de Passagem 35 L/min", "Potencia_kcal_min": 815, "Pressao_kPa": 2.8, "Tubo_Cobre_mm": 28, "Norma": "NBR 15526"},
    {"Equipamento": "Churrasqueira / Lareira a Gás Gourmet", "Potencia_kcal_min": 250, "Pressao_kPa": 2.8, "Tubo_Cobre_mm": 22, "Norma": "NBR 15526"},
    {"Equipamento": "Evaporadora Split 9.000/12.000 BTU", "Potencia_kcal_min": 0, "Pressao_kPa": 0, "Tubo_Cobre_mm": 9.52, "Norma": "NBR 16401 (Dreno 25mm)"},
    {"Equipamento": "Evaporadora Split 18.000/24.000 BTU", "Potencia_kcal_min": 0, "Pressao_kPa": 0, "Tubo_Cobre_mm": 15.87, "Norma": "NBR 16401 (Dreno 25mm)"},
]

def inicializar_bibliotecas_internas():
    if 'bib_hidro' not in st.session_state:
        st.session_state.bib_hidro = pd.DataFrame(DADOS_BIB_HIDRO_PADRAO)
    if 'bib_eletrica' not in st.session_state:
        st.session_state.bib_eletrica = pd.DataFrame(DADOS_BIB_ELETRICA_PADRAO)
    if 'bib_gas_avac' not in st.session_state:
        st.session_state.bib_gas_avac = pd.DataFrame(DADOS_BIB_GAS_AVAC_PADRAO)

inicializar_bibliotecas_internas()

def garantir_tubos_queda_subida_na_biblioteca():
    """Injeta Tubos de Queda, Colunas de Subida, Ramais de Descarga e Ramais de Esgoto na bib_hidro."""
    novos_itens = [
        {"Equipamento": "Tubo de Queda Água Fria (TQ-AF 50mm)", "Vazao_Ls": 1.50, "Peso": 0.0, "Agua_mm": 50, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Tubo de Queda Água Fria (TQ-AF 40mm)", "Vazao_Ls": 1.00, "Peso": 0.0, "Agua_mm": 40, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Tubo de Queda Água Fria (TQ-AF 32mm)", "Vazao_Ls": 0.60, "Peso": 0.0, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Tubo de Queda Água Fria (TQ-AF 25mm)", "Vazao_Ls": 0.40, "Peso": 0.0, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Coluna de Subida Água Fria (CS-AF 32mm)", "Vazao_Ls": 0.60, "Peso": 0.0, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Coluna de Subida Água Fria (CS-AF 25mm)", "Vazao_Ls": 0.40, "Peso": 0.0, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Tubo de Queda Água Quente (TQ-AQ 28mm)", "Vazao_Ls": 0.50, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 28, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Tubo de Queda Água Quente (TQ-AQ 22mm)", "Vazao_Ls": 0.30, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 22, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Coluna de Subida Água Quente (CS-AQ 28mm)", "Vazao_Ls": 0.50, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 28, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Coluna de Subida Água Quente (CS-AQ 22mm)", "Vazao_Ls": 0.30, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 22, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Ramal de Descarga Esgoto 40mm (Lavatório/Ralo)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 2, "Esgoto_mm": 40, "Vent_mm": 40},
        {"Equipamento": "Ramal de Descarga Esgoto 50mm (Pia/Tanque/Máquina)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 3, "Esgoto_mm": 50, "Vent_mm": 40},
        {"Equipamento": "Ramal de Descarga Esgoto 100mm (Bacia Sanitária)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 6, "Esgoto_mm": 100, "Vent_mm": 50},
        {"Equipamento": "Ramal de Esgoto Coletor 50mm (NBR 8160)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 6, "Esgoto_mm": 50, "Vent_mm": 40},
        {"Equipamento": "Ramal de Esgoto Coletor 75mm (NBR 8160)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 20, "Esgoto_mm": 75, "Vent_mm": 50},
        {"Equipamento": "Ramal de Esgoto Coletor 100mm (NBR 8160)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 160, "Esgoto_mm": 100, "Vent_mm": 75},
        {"Equipamento": "Condutor Vertical de Águas Pluviais (AP 100mm)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 100, "Vent_mm": 0},
    ]
    if 'bib_hidro' in st.session_state:
        existentes = set(st.session_state.bib_hidro['Equipamento'].values)
        faltantes = [item for item in novos_itens if item["Equipamento"] not in existentes]
        if faltantes:
            st.session_state.bib_hidro = pd.concat([st.session_state.bib_hidro, pd.DataFrame(faltantes)], ignore_index=True)

garantir_tubos_queda_subida_na_biblioteca()

def exportar_projeto():
    estado = {
        "circuitos": st.session_state.circuitos.to_dict('records') if not st.session_state.circuitos.empty else [],
        "auditoria_ambientes": st.session_state.auditoria_ambientes.to_dict('records') if not st.session_state.auditoria_ambientes.empty else [],
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
    if "auditoria_ambientes" in dados:
        st.session_state.auditoria_ambientes = pd.DataFrame(dados["auditoria_ambientes"])
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
            st.session_state.auditoria_ambientes.to_excel(writer, sheet_name='Auditoria_Ambientes_NBR5410', index=False)
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
# ==============================================================================
# PARTE 5 DE 10: LEITOR NATIVO DE MAQUETES .IFC, GEOMETRIA E DIMENSIONAMENTO
# ==============================================================================
def escalar_coord(val, fator=10): return int(round(val * fator))
def desescalar_coord(val, fator=10): return val / fator
def dist_3d(p1, p2): return math.sqrt((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2 + (p2[2]-p1[2])**2)
def dist_2d(p1, p2): return math.sqrt((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2)

def calcular_comprimento_rota(pontos):
    return sum(dist_3d(pontos[i], pontos[i+1]) for i in range(len(pontos)-1))

def _obter_coord_ifc_placement(placement):
    """Extrai recursivamente (X, Y, Z) de um IfcLocalPlacement."""
    x, y, z = 0.0, 0.0, 0.0
    curr = placement
    while curr is not None:
        try:
            rel = curr.RelativePlacement
            if rel and hasattr(rel, "Location") and rel.Location:
                coords = rel.Location.Coordinates
                x += float(coords[0]) if len(coords) > 0 else 0.0
                y += float(coords[1]) if len(coords) > 1 else 0.0
                z += float(coords[2]) if len(coords) > 2 else 0.0
            curr = getattr(curr, "PlacementRelTo", None)
        except Exception:
            break
    # Se as coordenadas estiverem em milímetros (> 500), converte para metros
    if abs(x) > 500 or abs(y) > 500:
        x, y, z = x / 1000.0, y / 1000.0, z / 1000.0
    return round(x, 2), round(y, 2), round(z, 2)

def extrair_geometria_ifc(ifc_bytes, andar_idx, ordem_andar, pe_direito_atual, z_base_padrao, altura_viga):
    """
    CORREÇÃO 1: Leitor Nativo de Maquetes .IFC (Blender/Bonsai, Ingetrazo, Revit, ArchiCAD).
    Extrai Paredes (IfcWall), Vigas/Pilares (IfcBeam/IfcColumn), Portas/Janelas (IfcDoor/IfcWindow)
    e Dispositivos Elétricos/Hidráulicos (IfcFlowTerminal, IfcOutlet, IfcSanitaryTerminal, etc.).
    Funciona com IfcOpenShell ou via Parser STEP nativo em Python puro (fallback garantido na nuvem).
    """
    paredes_ifc, elementos_arq_ifc, blocos_elet_ifc, blocos_hidro_ifc = [], [], [], []

    if HAS_IFC:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp:
            tmp.write(ifc_bytes)
            tmp_path = tmp.name
        try:
            modelo = ifcopenshell.open(tmp_path)
            # 1. Paredes (IfcWall)
            for idx_w, wall in enumerate(modelo.by_type("IfcWall")):
                wx, wy, wz = _obter_coord_ifc_placement(getattr(wall, "ObjectPlacement", None))
                z_w = wz if wz > 0 else z_base_padrao
                paredes_ifc.append(((wx, wy, z_w), (wx + 3.0, wy, z_w)))
            # 2. Vigas e Pilares (IfcBeam, IfcColumn)
            for est in modelo.by_type("IfcColumn") + modelo.by_type("IfcBeam"):
                ex, ey, ez = _obter_coord_ifc_placement(getattr(est, "ObjectPlacement", None))
                tipo_id = "PILAR" if est.is_a("IfcColumn") else "VIGA"
                elementos_arq_ifc.append({
                    "ID_CAD": f"{tipo_id}_{est.id()}_EST", "Tipo": "Pilar/Viga",
                    "x": ex, "y": ey, "z_base": ez if ez > 0 else z_base_padrao,
                    "Largura": 0.40, "Altura_Viga": altura_viga
                })
            # 3. Portas e Janelas (IfcDoor, IfcWindow)
            for esq in modelo.by_type("IfcDoor") + modelo.by_type("IfcWindow"):
                qx, qy, qz = _obter_coord_ifc_placement(getattr(esq, "ObjectPlacement", None))
                eh_porta = esq.is_a("IfcDoor")
                elementos_arq_ifc.append({
                    "ID_CAD": f"{esq.Name or esq.id()}_ESQ", "Tipo": "Esquadria",
                    "Subtipo": "Porta" if eh_porta else "Janela",
                    "x": qx, "y": qy, "z_base": z_base_padrao,
                    "Largura": float(getattr(esq, "OverallWidth", 0.90) or 0.90),
                    "Peitoril": 0.0 if eh_porta else 1.00,
                    "Altura": float(getattr(esq, "OverallHeight", 2.10) or 2.10)
                })
            # 4. Terminais MEP (Elétrica e Hidráulica)
            for term in modelo.by_type("IfcFlowTerminal") + modelo.by_type("IfcDistributionControlElement") + modelo.by_type("IfcFlowFitting"):
                tx, ty, tz = _obter_coord_ifc_placement(getattr(term, "ObjectPlacement", None))
                nome_t = str(getattr(term, "Name", "") or term.is_a()).upper()
                classe_t = term.is_a().upper()
                if any(k in nome_t or k in classe_t for k in ["SANITARY", "PIPE", "HIDRO", "BACIA", "CHUV", "LAV", "PIA", "RALO", "CAIXA", "PRUMADA", "TQ", "AF", "GAS"]):
                    blocos_hidro_ifc.append({
                        "ID_CAD": f"{nome_t[:12]}_P{andar_idx}_{term.id()}", "Nome_Bloco": nome_t,
                        "x": tx, "y": ty, "z_base": z_base_padrao, "Andar": f"Pav {ordem_andar}", "pe_direito": pe_direito_atual
                    })
                else:
                    blocos_elet_ifc.append({
                        "ID_CAD": f"{nome_t[:12]}_P{andar_idx}_{term.id()}", "Nome_Bloco": nome_t,
                        "x": tx, "y": ty, "z_base": z_base_padrao, "Andar": f"Pav {ordem_andar}", "pe_direito": pe_direito_atual
                    })
        except Exception:
            pass
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # Fallback em Python puro caso o arquivo IFC use geometria STEP direta ou IfcOpenShell não esteja presente
    if not paredes_ifc and not blocos_elet_ifc and not blocos_hidro_ifc:
        texto_ifc = ifc_bytes.decode("utf-8", errors="ignore")
        pts_cartesianos = re.findall(r"IFCCARTESIANPOINT\(\(\s*([-\d\.E\+]+)\s*,\s*([-\d\.E\+]+)(?:\s*,\s*([-\d\.E\+]+))?\s*\)\)", texto_ifc)
        coords_validas = []
        for sx, sy, sz in pts_cartesianos:
            try:
                fx, fy = float(sx), float(sy)
                if abs(fx) > 500 or abs(fy) > 500: fx, fy = fx / 1000.0, fy / 1000.0
                if abs(fx) > 0.01 or abs(fy) > 0.01:
                    coords_validas.append((round(fx, 2), round(fy, 2)))
            except Exception:
                continue
        if coords_validas:
            for i in range(0, min(len(coords_validas) - 1, 40), 2):
                p1, p2 = coords_validas[i], coords_validas[i+1]
                paredes_ifc.append(((p1[0], p1[1], z_base_padrao), (p2[0], p2[1], z_base_padrao)))
            blocos_elet_ifc.append({"ID_CAD": f"QDG_IFC_P{andar_idx}", "Nome_Bloco": "QUADRO_QDG", "x": coords_validas[0][0], "y": coords_validas[0][1], "z_base": z_base_padrao, "Andar": f"Pav {ordem_andar}", "pe_direito": pe_direito_atual})
            blocos_hidro_ifc.append({"ID_CAD": f"PRUM_AF_IFC_P{andar_idx}", "Nome_Bloco": "PRUMADA_AF", "x": coords_validas[0][0]+0.5, "y": coords_validas[0][1]+0.5, "z_base": z_base_padrao, "Andar": f"Pav {ordem_andar}", "pe_direito": pe_direito_atual})
            for idx_c, (cx, cy) in enumerate(coords_validas[1:8]):
                blocos_elet_ifc.append({"ID_CAD": f"TOMADA_IFC_{idx_c}", "Nome_Bloco": "TOMADA_4X2", "x": cx, "y": cy, "z_base": z_base_padrao, "Andar": f"Pav {ordem_andar}", "pe_direito": pe_direito_atual})
                blocos_hidro_ifc.append({"ID_CAD": f"HIDRO_IFC_{idx_c}", "Nome_Bloco": "APARELHO_HIDRO", "x": cx+0.3, "y": cy+0.3, "z_base": z_base_padrao, "Andar": f"Pav {ordem_andar}", "pe_direito": pe_direito_atual})

    return paredes_ifc, elementos_arq_ifc, blocos_elet_ifc, blocos_hidro_ifc

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
        t = min(1.0, i * passo / d)
        pts.append((p1[0] + t*(p2[0]-p1[0]), p1[1] + t*(p2[1]-p1[1]), p1[2] + t*(p2[2]-p1[2])))
    return pts

def checar_clash_detection(linhas_eletrica, linhas_hidro, tolerancia_metros=0.15):
    colisoes, pts_eletrica = [], []
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
    for d_mm in [20, 25, 32, 40, 50, 60, 75, 85, 110]:
        d_int_m = (d_mm * 0.88) / 1000.0
        vel_ms = (vazao_ls / 1000.0) / (math.pi * ((d_int_m / 2.0) ** 2))
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
    secao_minima = 16.0 if material == "Alumínio" else (1.5 if str(tipo_circ).strip() == "Iluminação" else 2.5)
    n_cond_carregados = 2 if tensao_v in [127, 220] else 3

    if material == "Alumínio": chave_metodo = "AL_B1"
    elif "90" in isolacao: chave_metodo = "B1_90"
    elif metodo == "A1": chave_metodo = "A1_2"
    elif metodo == "B1": chave_metodo = f"B1_{n_cond_carregados}"
    elif metodo == "B2": chave_metodo = "B2_2"
    else: chave_metodo = "C_2"

    bitola_escolhida, iz_escolhido, queda_tensao_pct = 50.0, 151.0, 0.0
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

    area_ocupada_total = 3 * TABELA_AMPACIDADE_NBR5410[bitola_escolhida]["Area_Ext_mm2"]
    eletroduto_mm, ocupacao_pct = 20, 0.0
    for dn_elet, area_int in sorted(ELETRODUTOS_NBR5410.items()):
        if dn_elet < 20: continue
        taxa = (area_ocupada_total / area_int) * 100.0
        if taxa <= 40.0:
            eletroduto_mm, ocupacao_pct = dn_elet, taxa
            break

    return {
        "Corrente_Ib": round(corrente_ib, 2), "Corrente_Corr": round(corrente_corrigida, 2),
        "Bitola": bitola_escolhida, "Queda_Tensao_Pct": round(queda_tensao_pct, 2),
        "Disjuntor": disjuntor_in, "Icc_A": calcular_icc(tensao_v, bitola_escolhida, dist_m, material),
        "Eletroduto_mm": eletroduto_mm, "Ocupacao_Pct": round(ocupacao_pct, 1)
    }

def balancear_fases_automatico(df_circuitos):
    if df_circuitos.empty: return df_circuitos
    cargas_fases = {"R": 0.0, "S": 0.0, "T": 0.0}
    for idx in df_circuitos.sort_values(by="Potência Total (W)", ascending=False).index:
        pot = float(df_circuitos.loc[idx, "Potência Total (W)"])
        tensao = int(df_circuitos.loc[idx, "Tensão (V)"])
        if tensao >= 220:
            f1, f2 = sorted(cargas_fases.keys(), key=lambda f: cargas_fases[f])[:2]
            df_circuitos.loc[idx, "Fase"] = f"{f1}+{f2}"
            cargas_fases[f1] += pot / 2.0
            cargas_fases[f2] += pot / 2.0
        else:
            fase_min = min(cargas_fases, key=cargas_fases.get)
            df_circuitos.loc[idx, "Fase"] = fase_min
            cargas_fases[fase_min] += pot
    return df_circuitos
# ==============================================================================
# PARTE 6 DE 10: ROTEADORES 3D (MÚLTIPLAS PRUMADAS, CASCATA TUG, PLUVIAL E GÁS)
# ==============================================================================
def distancia_ponto_segmento_2d(px, py, x1, y1, x2, y2):
    """Calcula a menor distância em planta entre um ponto (px, py) e o segmento do vão (x1,y1)-(x2,y2)."""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    proj_x, proj_y = x1 + t * dx, y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)

def liberar_vaos_esquadrias_na_matriz(matriz, elementos_arq, ctx):
    """Garante que o algoritmo 2D A* permita que a tubulação atravesse a zona de portas e janelas."""
    for elem in elementos_arq:
        if elem.get('Tipo') == 'Esquadria':
            p1_v = elem.get('p1_vao', (elem['x'] - 0.45, elem['y']))
            p2_v = elem.get('p2_vao', (elem['x'] + 0.45, elem['y']))
            x0 = escalar_coord(p1_v[0] - ctx['min_x'] + ctx['offset'])
            y0 = escalar_coord(p1_v[1] - ctx['min_y'] + ctx['offset'])
            x1 = escalar_coord(p2_v[0] - ctx['min_x'] + ctx['offset'])
            y1 = escalar_coord(p2_v[1] - ctx['min_y'] + ctx['offset'])
            for px, py in algoritmo_bresenham(x0, y0, x1, y1):
                liberar_caixa(matriz, px, py, ctx['grid_w'], ctx['grid_h'], raio=2)

def aplicar_desvios_estruturais_e_vaos_3d(linha_3d, elementos_arq, z_base, pe_direito, h_viga=0.40):
    """
    Analisa cada trecho da tubulação 3D a cada 10cm:
    - Se já estiver abaixo do peitoril da janela ou acima da verga da porta/janela, passa reto!
    - Se colidir com Janela: desvia por baixo do peitoril (se tiver espaço) ou por cima da janela.
    - Se colidir com Porta: desvia por cima da verga da porta (ou por baixo da soleira se já for tubulação de piso).
    - Se colidir com Viga no teto: mergulha por baixo da viga.
    """
    if not elementos_arq or len(linha_3d) < 2:
        return linha_3d

    elems_andar = [e for e in elementos_arq if abs(e.get('z_base', 0.0) - z_base) < 0.6]
    if not elems_andar:
        return linha_3d

    z_teto_livre = z_base + pe_direito - 0.08
    nova_linha = [linha_3d[0]]

    for i in range(len(linha_3d) - 1):
        p_ini = linha_3d[i]
        p_fim = linha_3d[i + 1]
        comp_2d = dist_2d(p_ini, p_fim)

        # Segmentos puramente verticais (subidas/descidas) não precisam de subdivisão horizontal
        if comp_2d < 0.08:
            nova_linha.append(p_fim)
            continue

        # Subdivide o segmento horizontal a cada 12cm para detectar portas/janelas no meio da parede
        n_passos = max(2, int(comp_2d / 0.12) + 1)
        z_original = p_fim[2]

        for k in range(1, n_passos + 1):
            t = k / float(n_passos)
            px = p_ini[0] + t * (p_fim[0] - p_ini[0])
            py = p_ini[1] + t * (p_fim[1] - p_ini[1])
            pz = p_ini[2] + t * (p_fim[2] - p_ini[2])
            z_ajustado = pz

            for elem in elems_andar:
                if elem.get('Tipo') == 'Esquadria':
                    larg = elem.get('Largura', 0.90)
                    p1_v = elem.get('p1_vao', (elem['x'] - larg / 2.0, elem['y']))
                    p2_v = elem.get('p2_vao', (elem['x'] + larg / 2.0, elem['y']))
                    dist_vao = distancia_ponto_segmento_2d(px, py, p1_v[0], p1_v[1], p2_v[0], p2_v[1])

                    # Se o tubo passa dentro da faixa da porta/janela (distância <= 25cm do eixo do vão)
                    if dist_vao <= 0.25:
                        peitoril = float(elem.get('Peitoril', 0.0))
                        altura_vao = float(elem.get('Altura', 2.10))
                        z_min_vao = z_base + peitoril
                        z_max_vao = z_min_vao + altura_vao

                        # Só desvia se a altura atual do tubo bater dentro da abertura [z_min_vao, z_max_vao]
                        if (z_min_vao - 0.06) < pz < (z_max_vao + 0.06):
                            z_por_cima = min(z_teto_livre, z_max_vao + 0.12)
                            z_por_baixo = z_min_vao - 0.12

                            if elem.get('Subtipo') == 'Janela' and peitoril >= 0.25:
                                # Na janela, escolhe passar por baixo do peitoril ou por cima da verga (o que for mais próximo da altura do tubo)
                                if abs(pz - z_por_baixo) <= abs(z_por_cima - pz):
                                    z_ajustado = max(z_base + 0.05, z_por_baixo)
                                else:
                                    z_ajustado = z_por_cima
                            else:
                                # Na porta, passa por cima da porta (verga superior) se for tubulação de parede, ou por baixo da soleira se já estiver rente ao piso
                                if peitoril >= 0.15 and pz <= z_min_vao + 0.10:
                                    z_ajustado = z_por_baixo
                                else:
                                    z_ajustado = z_por_cima
                            break

                elif elem.get('Tipo') == 'Pilar/Viga':
                    if math.hypot(px - elem['x'], py - elem['y']) <= (elem.get('Largura', 0.40) / 2.0 + 0.15):
                        z_fundo_viga = z_base + pe_direito - h_viga - 0.05
                        if pz > z_fundo_viga:
                            z_ajustado = z_fundo_viga

            pt_novo = (round(px, 4), round(py, 4), round(z_ajustado, 4))
            # Simplifica pontos colineares na mesma altura para manter a malha limpa
            if len(nova_linha) >= 2 and abs(nova_linha[-1][2] - pt_novo[2]) < 0.005 and abs(nova_linha[-2][2] - pt_novo[2]) < 0.005:
                if abs(dist_2d(nova_linha[-2], nova_linha[-1]) + dist_2d(nova_linha[-1], pt_novo) - dist_2d(nova_linha[-2], pt_novo)) < 0.005:
                    nova_linha[-1] = pt_novo
                else:
                    nova_linha.append(pt_novo)
            else:
                nova_linha.append(pt_novo)

    return nova_linha

def contar_conexoes_na_rota(pontos):
    """Conta exatamente quantos Joelhos de 90° e 45° existem ao longo de uma polilinha 3D."""
    j90, j45 = 0, 0
    for i in range(1, len(pontos) - 1):
        ang = calcular_angulo_deflexao(pontos[i-1], pontos[i], pontos[i+1])
        if 70 <= ang <= 115:
            j90 += 1
        elif 20 <= ang < 70:
            j45 += 1
    return j90, j45

def rotear_hidro(df_bh, ctx):
    """
    Motor Hidrossanitário 3D com Hierarquia Real NBR 5626 & NBR 8160:
    - Água Fria/Quente: Caixa d'Água -> Tubo de Queda -> Subsolo -> Coluna de Subida -> Prumada -> Aparelhos.
    - Esgoto Secundário: Ralo Seco / Lavatório / Chuveiro -> Ralo Sifonado / Caixa Sifonada.
    - Esgoto Gorduroso: Pia de Cozinha / Lava-Louça -> Caixa de Gordura [CG].
    - Esgoto Primário: Bacia Sanitária / Cx Sifonada / Cx Gordura -> Ramal de Esgoto -> TQ -> Caixa de Inspeção [CI].
    """
    linhas_processadas = []
    if not df_bh:
        return linhas_processadas

    matriz = [[1 for _ in range(ctx['grid_w'])] for _ in range(ctx['grid_h'])]
    
    for (p1_x, p1_y, _), (p2_x, p2_y, _) in ctx['paredes']:
        x0, y0 = escalar_coord(p1_x - ctx['min_x'] + ctx['offset']), escalar_coord(p1_y - ctx['min_y'] + ctx['offset'])
        x1, y1 = escalar_coord(p2_x - ctx['min_x'] + ctx['offset']), escalar_coord(p2_y - ctx['min_y'] + ctx['offset'])
        for px, py in algoritmo_bresenham(x0, y0, x1, y1):
            if 0 <= py < ctx['grid_h'] and 0 <= px < ctx['grid_w']:
                matriz[py][px] = 0

    elementos_arq = ctx.get('elementos_arquitetonicos', [])
    for elem in elementos_arq:
        if elem['Tipo'] == 'Pilar/Viga' and 'PILAR' in elem['ID_CAD'].upper():
            px, py = escalar_coord(elem['x'] - ctx['min_x'] + ctx['offset']), escalar_coord(elem['y'] - ctx['min_y'] + ctx['offset'])
            bloquear_caixa_estrutural(matriz, px, py, ctx['grid_w'], ctx['grid_h'], raio=2)
            liberar_vaos_esquadrias_na_matriz(matriz, elementos_arq, ctx)

    h_af = ctx.get('h_agua_fria', 2.2)
    h_aq = ctx.get('h_agua_quente', 1.1)
    h_viga = ctx.get('altura_viga', 0.40)
    z_subsolo_af = ctx.get('z_subsolo_af', -0.40)

    # Separação dos blocos por Função BIM
    caixas_dagua = [b for b in df_bh if b['Tipo_BIM'] == "Caixa d'Água"]
    quedas_af = [b for b in df_bh if b['Tipo_BIM'] == 'Tubo de Queda Água Fria']
    subidas_af = [b for b in df_bh if b['Tipo_BIM'] == 'Coluna de Subida Água Fria']
    prumadas_af = [b for b in df_bh if b['Tipo_BIM'] == 'Prumada Água Fria']

    boilers_aq = [b for b in df_bh if b['Tipo_BIM'] == 'Boiler / Aquecedor']
    quedas_aq = [b for b in df_bh if b['Tipo_BIM'] == 'Tubo de Queda Água Quente']
    subidas_aq = [b for b in df_bh if b['Tipo_BIM'] == 'Coluna de Subida Água Quente']

    prumadas_esg = [b for b in df_bh if b['Tipo_BIM'] == 'Prumada Esgoto']
    caixas_inspecao = [b for b in df_bh if b['Tipo_BIM'] == 'Caixa de Inspeção / Destino Esgoto']
    ramais_descarga = [b for b in df_bh if b['Tipo_BIM'] == 'Ramal de Descarga']
    ramais_esgoto = [b for b in df_bh if b['Tipo_BIM'] == 'Ramal de Esgoto']

    equips_af_validos = set(st.session_state.bib_hidro[st.session_state.bib_hidro['Agua_mm'] > 0]['Equipamento'].values)
    equips_aq_validos = set(st.session_state.bib_hidro[st.session_state.bib_hidro.get('AQ_mm', pd.Series([0]*len(st.session_state.bib_hidro))) > 0]['Equipamento'].values)

    def rota_a_star_2d(orig, dest, permitir_diagonal=False):
        ox = escalar_coord(orig['x'] - ctx['min_x'] + ctx['offset'])
        oy = escalar_coord(orig['y'] - ctx['min_y'] + ctx['offset'])
        dx = escalar_coord(dest['x'] - ctx['min_x'] + ctx['offset'])
        dy = escalar_coord(dest['y'] - ctx['min_y'] + ctx['offset'])
        liberar_caixa(matriz, ox, oy, ctx['grid_w'], ctx['grid_h'])
        liberar_caixa(matriz, dx, dy, ctx['grid_w'], ctx['grid_h'])
        grid = Grid(matrix=matriz)
        mov = DiagonalMovement.always if permitir_diagonal else DiagonalMovement.never
        finder = AStarFinder(diagonal_movement=mov)
        caminho, _ = finder.find_path(grid.node(ox, oy), grid.node(dx, dy), grid)
        return [(desescalar_coord(p.x) + ctx['min_x'] - ctx['offset'], desescalar_coord(p.y) + ctx['min_y'] - ctx['offset']) for p in caminho]

    peso_total_projeto = 0.0
    aparelhos_com_af = []
    for ap in df_bh:
        if ap['Tipo_BIM'] == 'Aparelho Hidráulico' and ap['Equipamento'] in equips_af_validos:
            aparelhos_com_af.append(ap)
            f_eq = st.session_state.bib_hidro['Equipamento'] == ap['Equipamento']
            if f_eq.any():
                peso_total_projeto += float(st.session_state.bib_hidro.loc[f_eq, 'Peso'].values[0])
    dn_tronco_af = max(32, dimensionar_tubo_agua(peso_total_projeto))

    historico_no_af = {}

    # =========================================================================
    # ETAPA 1 E 2: CAIXA D'ÁGUA -> TUBO DE QUEDA AF -> SUBSOLO -> COLUNA DE SUBIDA AF
    # =========================================================================
    alvos_descida_inicial = quedas_af if quedas_af else prumadas_af
    if caixas_dagua and alvos_descida_inicial:
        for tq_af in alvos_descida_inicial:
            cx_sup = min(caixas_dagua, key=lambda c: dist_2d((tq_af['x'], tq_af['y']), (c['x'], c['y'])))
            z_saida_cx = cx_sup['z_base'] + ctx.get('altura_caixa', 1.5)
            z_barrilete = cx_sup['z_base'] + 0.20
            z_fundo_queda = z_subsolo_af if subidas_af else 0.0

            pts_queda = [
                (cx_sup['x'], cx_sup['y'], z_saida_cx),
                (cx_sup['x'], cx_sup['y'], z_barrilete),
                (tq_af['x'], cx_sup['y'], z_barrilete),
                (tq_af['x'], tq_af['y'], z_barrilete),
                (tq_af['x'], tq_af['y'], z_fundo_queda)
            ]
            linhas_processadas.append({
                'pontos': pts_queda, 'cor': '#003399',
                'tipo': f"Tubo de Queda AF ({tq_af['ID_CAD']})", 'diametro': dn_tronco_af
            })
            j90_q, _ = contar_conexoes_na_rota(pts_queda)
            historico_no_af[tq_af['ID_CAD']] = {'comp_m': calcular_comprimento_rota(pts_queda), 'j90': j90_q, 'tes': 1}

    if subidas_af:
        origens_subsolo = quedas_af if quedas_af else (prumadas_af if prumadas_af else caixas_dagua)
        for col_sub in subidas_af:
            z_topo_subida = col_sub['z_base'] + h_af
            if origens_subsolo:
                orig_q = min(origens_subsolo, key=lambda q: dist_2d((col_sub['x'], col_sub['y']), (q['x'], q['y'])))
                pts_2d_sub = rota_a_star_2d(orig_q, col_sub, permitir_diagonal=False)
                pts_subsolo_e_subida = [(orig_q['x'], orig_q['y'], z_subsolo_af)]
                for px, py in pts_2d_sub:
                    pts_subsolo_e_subida.append((px, py, z_subsolo_af))
                pts_subsolo_e_subida.append((col_sub['x'], col_sub['y'], z_subsolo_af))
                pts_subsolo_e_subida.append((col_sub['x'], col_sub['y'], z_topo_subida))

                linhas_processadas.append({
                    'pontos': pts_subsolo_e_subida, 'cor': '#0066cc',
                    'tipo': f"Subsolo + Subida AF ({col_sub['ID_CAD']})", 'diametro': dn_tronco_af
                })
                hist_ant = historico_no_af.get(orig_q['ID_CAD'], {'comp_m': 0.0, 'j90': 0, 'tes': 0})
                j90_s, _ = contar_conexoes_na_rota(pts_subsolo_e_subida)
                historico_no_af[col_sub['ID_CAD']] = {
                    'comp_m': hist_ant['comp_m'] + calcular_comprimento_rota(pts_subsolo_e_subida),
                    'j90': hist_ant['j90'] + j90_s, 'tes': hist_ant['tes'] + 1
                }
            else:
                pts_sub_isolada = [(col_sub['x'], col_sub['y'], z_subsolo_af), (col_sub['x'], col_sub['y'], z_topo_subida)]
                linhas_processadas.append({
                    'pontos': pts_sub_isolada, 'cor': '#0066cc',
                    'tipo': f"Coluna de Subida AF ({col_sub['ID_CAD']})", 'diametro': dn_tronco_af
                })
                historico_no_af[col_sub['ID_CAD']] = {'comp_m': calcular_comprimento_rota(pts_sub_isolada), 'j90': 2, 'tes': 1}

    if subidas_af and prumadas_af:
        for prum in prumadas_af:
            sub_prox = min(subidas_af, key=lambda s: dist_2d((prum['x'], prum['y']), (s['x'], s['y'])))
            z_travessia = max(prum['z_base'], sub_prox['z_base']) + h_af
            pts_2d_p = rota_a_star_2d(sub_prox, prum, permitir_diagonal=False)
            pts_lig = [(sub_prox['x'], sub_prox['y'], z_travessia)]
            for px, py in pts_2d_p:
                pts_lig.append((px, py, z_travessia))
            pts_lig.append((prum['x'], prum['y'], z_travessia))
            pts_lig = aplicar_desvios_estruturais_e_vaos_3d(pts_lig, elementos_arq, prum['z_base'], prum.get('pe_direito', 3.0), h_viga)
            linhas_processadas.append({
                'pontos': pts_lig, 'cor': '#0055aa',
                'tipo': f"Distribuição AF ({prum['ID_CAD']})", 'diametro': 32
            })
            hist_s = historico_no_af.get(sub_prox['ID_CAD'], {'comp_m': 0.0, 'j90': 0, 'tes': 0})
            j90_p, _ = contar_conexoes_na_rota(pts_lig)
            historico_no_af[prum['ID_CAD']] = {
                'comp_m': hist_s['comp_m'] + calcular_comprimento_rota(pts_lig),
                'j90': hist_s['j90'] + j90_p, 'tes': hist_s['tes'] + 1
            }

    # =========================================================================
    # ETAPA 3: RAMAIS DE ÁGUA FRIA ATÉ OS APARELHOS (COM FALLBACK AUTOMÁTICO)
    # =========================================================================
    fontes_distribuicao_af = prumadas_af if prumadas_af else (subidas_af if subidas_af else (quedas_af if quedas_af else caixas_dagua))
    # Se o usuário ainda não definiu nenhuma Prumada/Caixa d'Água na tabela, usa o 1º ponto de água como alimentação principal
    if not fontes_distribuicao_af and aparelhos_com_af:
        fontes_distribuicao_af = [aparelhos_com_af[0]]

    if fontes_distribuicao_af:
        pesos_acum = {f['ID_CAD']: 0.0 for f in fontes_distribuicao_af}
        for ap in aparelhos_com_af:
            fonte_af = min(fontes_distribuicao_af, key=lambda f: abs(f['z_base'] - ap['z_base']) * 5 + dist_2d((ap['x'], ap['y']), (f['x'], f['y'])))
            if fonte_af['ID_CAD'] == ap['ID_CAD'] and len(aparelhos_com_af) > 1:
                continue
            f_eq = st.session_state.bib_hidro['Equipamento'] == ap['Equipamento']
            peso_ap = float(st.session_state.bib_hidro.loc[f_eq, 'Peso'].values[0])
            dn_ap = int(st.session_state.bib_hidro.loc[f_eq, 'Agua_mm'].values[0])
            pesos_acum[fonte_af['ID_CAD']] += peso_ap
            diametro_ramal = max(dn_ap, dimensionar_tubo_agua(pesos_acum[fonte_af['ID_CAD']]))

            pts_2d_ap = rota_a_star_2d(ap, fonte_af, permitir_diagonal=False)
            if pts_2d_ap:
                z_ponto_consumo = ap['z_base'] + ap.get('z_relativo', 0.6)
                z_ramal_parede = ap['z_base'] + h_af
                linha_3d = [(ap['x'], ap['y'], z_ponto_consumo), (ap['x'], ap['y'], z_ramal_parede)]
                for px, py in pts_2d_ap:
                    linha_3d.append((px, py, z_ramal_parede))
                linha_3d.append((fonte_af['x'], fonte_af['y'], z_ramal_parede))
                linha_3d = aplicar_desvios_estruturais_e_vaos_3d(linha_3d, elementos_arq, ap['z_base'], ap.get('pe_direito', 3.0), h_viga)

                hist_f = historico_no_af.get(fonte_af['ID_CAD'], {'comp_m': 0.0, 'j90': 0, 'tes': 0})
                comp_ramal = calcular_comprimento_rota(linha_3d)
                j90_r, _ = contar_conexoes_na_rota(linha_3d)

                linhas_processadas.append({
                    'pontos': linha_3d, 'cor': 'blue',
                    'tipo': 'Água Fria',
                    'legenda_3d': f"Água Fria ({ap['Equipamento'][:18]})",
                    'diametro': diametro_ramal, 'equipamento': ap['Equipamento'],
                    'id_ap': ap['ID_CAD'], 'prumada_ref': fonte_af['ID_CAD'],
                    'comp_acumulado_total_m': round(hist_f['comp_m'] + comp_ramal, 2),
                    'j90_acumulados': hist_f['j90'] + j90_r,
                    'tes_acumulados': hist_f['tes'] + 1
                })

    # =========================================================================
    # ETAPA 4: ÁGUA QUENTE (BOILER -> QUEDA AQ -> SUBIDA AQ -> APARELHOS)
    # =========================================================================
    fontes_aq = subidas_aq if subidas_aq else (quedas_aq if quedas_aq else (boilers_aq if boilers_aq else fontes_distribuicao_af))
    if quedas_aq and subidas_aq:
        for sub_q in subidas_aq:
            qd_q = min(quedas_aq, key=lambda q: dist_2d((sub_q['x'], sub_q['y']), (q['x'], q['y'])))
            z_sub_aq = z_subsolo_af + 0.08
            pts_2d_aq = rota_a_star_2d(qd_q, sub_q, permitir_diagonal=False)
            linha_sub_aq = [(qd_q['x'], qd_q['y'], qd_q['z_base'] + h_aq), (qd_q['x'], qd_q['y'], z_sub_aq)]
            for px, py in pts_2d_aq:
                linha_sub_aq.append((px, py, z_sub_aq))
            linha_sub_aq.extend([(sub_q['x'], sub_q['y'], z_sub_aq), (sub_q['x'], sub_q['y'], sub_q['z_base'] + h_aq)])
            linhas_processadas.append({'pontos': linha_sub_aq, 'cor': '#cc0000', 'tipo': f"Queda + Subida AQ ({sub_q['ID_CAD']})", 'diametro': 28})

    if fontes_aq:
        for ap in df_bh:
            if ap['Tipo_BIM'] == 'Aparelho Hidráulico' and ap['Equipamento'] in equips_aq_validos:
                fonte_q = min(fontes_aq, key=lambda f: dist_2d((ap['x'], ap['y']), (f['x'], f['y'])))
                if fonte_q['ID_CAD'] == ap['ID_CAD']:
                    continue
                pts_2d_q = rota_a_star_2d(ap, fonte_q, permitir_diagonal=False)
                if pts_2d_q:
                    z_pt_aq = ap['z_base'] + ap.get('z_relativo', 0.6)
                    z_ram_aq = ap['z_base'] + h_aq
                    linha_aq = [(ap['x'] + 0.10, ap['y'], z_pt_aq), (ap['x'] + 0.10, ap['y'], z_ram_aq)]
                    for px, py in pts_2d_q:
                        linha_aq.append((px + 0.08, py, z_ram_aq))
                    linha_aq.append((fonte_q['x'] + 0.08, fonte_q['y'], z_ram_aq))
                    linha_aq = aplicar_desvios_estruturais_e_vaos_3d(linha_aq, elementos_arq, ap['z_base'], ap.get('pe_direito', 3.0), h_viga)
                    linhas_processadas.append({
                        'pontos': linha_aq, 'cor': 'red', 'tipo': 'Água Quente',
                        'diametro': 22, 'equipamento': ap['Equipamento'], 'id_ap': ap['ID_CAD']
                    })

    # =========================================================================
    # ETAPA 5: HIERARQUIA REAL DE ESGOTO (NBR 8160)
    # - Esgoto Secundário (Ralo Seco, Lavatório, Chuveiro) -> Ralo Sifonado / Caixa Sifonada
    # - Cozinha (Pia / Lava-Louça) -> Caixa de Gordura
    # - Esgoto Primário (Bacia Sanitária, Ralo Sifonado, Cx Gordura) -> Ramal de Esgoto -> TQ -> Caixa de Inspeção
    # =========================================================================
    alvos_finais_esg = prumadas_esg if prumadas_esg else caixas_inspecao

    # Identifica Caixas Sifonadas/Ralos Sifonados e Caixas de Gordura presentes na planta
    caixas_sifonadas = [
        b for b in df_bh
        if "SIFONAD" in normalizar_texto_bim(b.get('Equipamento', '')) or "SIFONAD" in normalizar_texto_bim(b.get('Nome_Bloco', ''))
    ]
    caixas_gordura = [
        b for b in df_bh
        if "GORDURA" in normalizar_texto_bim(b.get('Equipamento', '')) or "[CG]" in str(b.get('Nome_Bloco', '')).upper()
    ]

    # 5.1. Tubos de Queda (TQ), Ventilação e Subcoletores até Caixa de Inspeção
    if prumadas_esg:
        z_topo_vent = ctx.get('max_z_cobertura', 6.0) + 0.30
        for prum_e in prumadas_esg:
            linhas_processadas.append({
                'pontos': [(prum_e['x'], prum_e['y'], z_topo_vent), (prum_e['x'], prum_e['y'], z_subsolo_af - 0.10)],
                'cor': '#5c3a21', 'tipo': f"Tubo de Queda Esgoto ({prum_e['ID_CAD']})", 'diametro': 100
            })
            linhas_processadas.append({
                'pontos': [(prum_e['x'] + 0.15, prum_e['y'], z_topo_vent), (prum_e['x'] + 0.15, prum_e['y'], 0.0)],
                'cor': '#2ca02c', 'tipo': f"Coluna de Ventilação ({prum_e['ID_CAD']})", 'diametro': 50
            })

            if caixas_inspecao:
                ci_prox = min(caixas_inspecao, key=lambda ci: dist_2d((prum_e['x'], prum_e['y']), (ci['x'], ci['y'])))
                pts_2d_ci = rota_a_star_2d(prum_e, ci_prox, permitir_diagonal=True)
                if pts_2d_ci:
                    z_pe_tq = z_subsolo_af - 0.10
                    linha_subcoletor = [(prum_e['x'], prum_e['y'], z_pe_tq)]
                    d_ac = 0.0
                    pt_a = (prum_e['x'], prum_e['y'])
                    for px, py in pts_2d_ci:
                        d_ac += dist_2d(pt_a, (px, py))
                        linha_subcoletor.append((px, py, z_pe_tq - d_ac * 0.01))
                        pt_a = (px, py)
                    linha_subcoletor.append((ci_prox['x'], ci_prox['y'], z_pe_tq - d_ac * 0.01))
                    linhas_processadas.append({
                        'pontos': linha_subcoletor, 'cor': '#3d2514',
                        'tipo': f"Subcoletor Esgoto -> {ci_prox['Nome_Bloco']}", 'diametro': 100, 'declividade_pct': 1.0
                    })

    # 5.2. Roteamento de Aparelhos e Ramais de Descarga respeitando a hierarquia NBR 8160
    origens_descarga = [b for b in df_bh if b['Tipo_BIM'] in ['Aparelho Hidráulico', 'Ramal de Descarga']]
    uhc_acumulado_ramal_esg = {re_b['ID_CAD']: 0.0 for re_b in ramais_esgoto}

    for ap in origens_descarga:
        f_eq = st.session_state.bib_hidro['Equipamento'] == ap['Equipamento']
        if not f_eq.any():
            continue
        uhc_ap = float(st.session_state.bib_hidro.loc[f_eq, 'UHC'].values[0])
        esg_mm_ap = int(st.session_state.bib_hidro.loc[f_eq, 'Esgoto_mm'].values[0])
        if esg_mm_ap <= 0 and ap['Tipo_BIM'] != 'Ramal de Descarga':
            continue
        if esg_mm_ap <= 0:
            esg_mm_ap = 40
            uhc_ap = max(2.0, uhc_ap)

        eq_norm = normalizar_texto_bim(ap['Equipamento'])
        eh_cx_sifonada = ap in caixas_sifonadas
        eh_cx_gordura = ap in caixas_gordura
        eh_cozinha = any(k in eq_norm for k in ["PIA", "COZINHA", "LAVA LOUCA"]) and not eh_cx_gordura
        eh_secundario_banheiro = (esg_mm_ap <= 40 or "RALO SECO" in eq_norm or "LAVATORIO" in eq_norm or "CHUVEIRO" in eq_norm) and not eh_cx_sifonada

        alvo_escolhido = None
        cor_ramal = 'brown'

        # Regra 1: Ralo Seco, Lavatório e Chuveiro vão para a Caixa Sifonada / Ralo Sifonado mais próximo (até 5m)
        if eh_secundario_banheiro and caixas_sifonadas:
            cs_cand = [cs for cs in caixas_sifonadas if cs['ID_CAD'] != ap['ID_CAD'] and abs(cs['z_base'] - ap['z_base']) < 0.5 and dist_2d((ap['x'], ap['y']), (cs['x'], cs['y'])) <= 5.0]
            if cs_cand:
                alvo_escolhido = min(cs_cand, key=lambda c: dist_2d((ap['x'], ap['y']), (c['x'], c['y'])))
                cor_ramal = '#cd853f' # Marrom claro (Ramal de Descarga Secundário -> Caixa Sifonada)

        # Regra 2: Pia de Cozinha vai para a Caixa de Gordura mais próxima
        elif eh_cozinha and caixas_gordura:
            cg_cand = [cg for cg in caixas_gordura if cg['ID_CAD'] != ap['ID_CAD'] and abs(cg['z_base'] - ap['z_base']) < 0.5]
            if cg_cand:
                alvo_escolhido = min(cg_cand, key=lambda c: dist_2d((ap['x'], ap['y']), (c['x'], c['y'])))
                cor_ramal = '#b8860b' # Ocre (Ramal de Descarga Cozinha -> Caixa de Gordura)

        # Regra 3: Bacia Sanitária, Caixa Sifonada e Caixa de Gordura vão para o Ramal de Esgoto -> TQ -> Caixa de Inspeção
        if alvo_escolhido is None:
            ramais_esg_andar = [re_b for re_b in ramais_esgoto if re_b['ID_CAD'] != ap['ID_CAD'] and abs(re_b['z_base'] - ap['z_base']) < 0.5]
            opcoes_primario = ramais_esg_andar if ramais_esg_andar else (ramais_esgoto if ramais_esgoto else alvos_finais_esg)
            opcoes_primario = [op for op in opcoes_primario if op['ID_CAD'] != ap['ID_CAD']]
            if not opcoes_primario:
                continue
            alvo_escolhido = min(opcoes_primario, key=lambda p: dist_2d((ap['x'], ap['y']), (p['x'], p['y'])))

        if alvo_escolhido['ID_CAD'] in uhc_acumulado_ramal_esg:
            uhc_acumulado_ramal_esg[alvo_escolhido['ID_CAD']] += uhc_ap

        diam_rd = max(esg_mm_ap, dimensionar_tubo_esgoto(uhc_ap))
        declividade_rd = 0.01 if diam_rd >= 100 else 0.02

        pts_2d_rd = rota_a_star_2d(ap, alvo_escolhido, permitir_diagonal=True)
        if pts_2d_rd:
            z_inicio_rd = ap['z_base'] - 0.12
            linha_rd = [(ap['x'], ap['y'], ap['z_base'] + ap.get('z_relativo', 0.0)), (ap['x'], ap['y'], z_inicio_rd)]
            dist_ac = 0.0
            pt_ant = (ap['x'], ap['y'])
            for px_r, py_r in pts_2d_rd:
                dist_ac += dist_2d(pt_ant, (px_r, py_r))
                linha_rd.append((px_r, py_r, z_inicio_rd - (dist_ac * declividade_rd)))
                pt_ant = (px_r, py_r)
            linha_rd.append((alvo_escolhido['x'], alvo_escolhido['y'], z_inicio_rd - (dist_ac * declividade_rd)))

            # Define o rótulo claro na legenda 3D conforme a função real do bloco!
            if ap['Tipo_BIM'] == 'Ramal de Descarga':
                rotulo_tipo = f"Ramal de Descarga ({ap['ID_CAD']}) -> {alvo_escolhido['Nome_Bloco']}"
            elif eh_secundario_banheiro and alvo_escolhido in caixas_sifonadas:
                rotulo_tipo = f"Descarga Sec. ({ap['Nome_Bloco']}) -> {alvo_escolhido['Nome_Bloco']}"
            else:
                rotulo_tipo = f"Esgoto ({ap['Nome_Bloco']}) -> {alvo_escolhido['Nome_Bloco']}"

            linhas_processadas.append({
                'pontos': linha_rd, 'cor': cor_ramal,
                'tipo': rotulo_tipo,
                'diametro': diam_rd, 'declividade_pct': declividade_rd * 100,
                'equipamento': ap['Equipamento'], 'id_ap': ap['ID_CAD'], 'prumada_ref': alvo_escolhido['ID_CAD']
            })

    # 5.3. Ramais de Esgoto (Coletor Horizontal) -> Tubo de Queda (TQ) ou Caixa de Inspeção
    if ramais_esgoto and alvos_finais_esg:
        for re_b in ramais_esgoto:
            f_eq_re = st.session_state.bib_hidro['Equipamento'] == re_b['Equipamento']
            esg_mm_base = int(st.session_state.bib_hidro.loc[f_eq_re, 'Esgoto_mm'].values[0]) if f_eq_re.any() else 50
            uhc_proprio = float(st.session_state.bib_hidro.loc[f_eq_re, 'UHC'].values[0]) if f_eq_re.any() else 6.0

            uhc_total_ramal = max(uhc_proprio, uhc_acumulado_ramal_esg.get(re_b['ID_CAD'], 0.0))
            diam_re = max(50, esg_mm_base, dimensionar_tubo_esgoto(uhc_total_ramal))
            declividade_re = 0.01 if diam_re >= 100 else 0.02

            alvo_final = min(alvos_finais_esg, key=lambda tq: dist_2d((re_b['x'], re_b['y']), (tq['x'], tq['y'])))
            pts_2d_re = rota_a_star_2d(re_b, alvo_final, permitir_diagonal=True)
            if pts_2d_re:
                z_ini_re = re_b['z_base'] - 0.18
                linha_re = [(re_b['x'], re_b['y'], z_ini_re)]
                dist_ac = 0.0
                pt_ant = (re_b['x'], re_b['y'])
                for px_e, py_e in pts_2d_re:
                    dist_ac += dist_2d(pt_ant, (px_e, py_e))
                    linha_re.append((px_e, py_e, z_ini_re - (dist_ac * declividade_re)))
                    pt_ant = (px_e, py_e)
                linha_re.append((alvo_final['x'], alvo_final['y'], z_ini_re - (dist_ac * declividade_re)))
                linhas_processadas.append({
                    'pontos': linha_re, 'cor': '#5c3a21',
                    'tipo': f"Ramal de Esgoto ({re_b['Nome_Bloco']}) -> {alvo_final['Nome_Bloco']}",
                    'diametro': diam_re, 'declividade_pct': declividade_re * 100,
                    'equipamento': re_b['Equipamento'], 'id_ap': re_b['ID_CAD'], 'prumada_ref': alvo_final['ID_CAD']
                })

    return linhas_processadas

def rotear_eletrica(df_be, ctx, evitar_linhas=None):
    """Roteamento Elétrico com suporte a múltiplos Quadros (QDGs) e interligação em cascata para TUGs."""
    matriz = [[1 for _ in range(ctx['grid_w'])] for _ in range(ctx['grid_h'])]
    
    for (p1_x, p1_y, _), (p2_x, p2_y, _) in ctx['paredes']:
        x0, y0 = escalar_coord(p1_x - ctx['min_x'] + ctx['offset']), escalar_coord(p1_y - ctx['min_y'] + ctx['offset'])
        x1, y1 = escalar_coord(p2_x - ctx['min_x'] + ctx['offset']), escalar_coord(p2_y - ctx['min_y'] + ctx['offset'])
        for px, py in algoritmo_bresenham(x0, y0, x1, y1):
            if 0 <= py < ctx['grid_h'] and 0 <= px < ctx['grid_w']:
                matriz[py][px] = 0

    elementos_arq = ctx.get('elementos_arquitetonicos', [])
    for elem in elementos_arq:
        if elem['Tipo'] == 'Pilar/Viga' and 'PILAR' in elem['ID_CAD'].upper():
            px, py = escalar_coord(elem['x'] - ctx['min_x'] + ctx['offset']), escalar_coord(elem['y'] - ctx['min_y'] + ctx['offset'])
            bloquear_caixa_estrutural(matriz, px, py, ctx['grid_w'], ctx['grid_h'], raio=2)
            liberar_vaos_esquadrias_na_matriz(matriz, elementos_arq, ctx)

    if evitar_linhas:
        for linha in evitar_linhas:
            pts = linha['pontos']
            for i in range(len(pts)-1):
                x0, y0 = escalar_coord(pts[i][0] - ctx['min_x'] + ctx['offset']), escalar_coord(pts[i][1] - ctx['min_y'] + ctx['offset'])
                x1, y1 = escalar_coord(pts[i+1][0] - ctx['min_x'] + ctx['offset']), escalar_coord(pts[i+1][1] - ctx['min_y'] + ctx['offset'])
                for px, py in algoritmo_bresenham(x0, y0, x1, y1):
                    for dy in [-1, 0, 1]:
                        for dx in [-1, 0, 1]:
                            if 0 <= py+dy < ctx['grid_h'] and 0 <= px+dx < ctx['grid_w']:
                                matriz[py+dy][px+dx] = 0

    linhas_processadas = []
    quadros = [b for b in df_be if b['Tipo_BIM'] == 'Quadro Geral']
    h_viga = ctx.get('altura_viga', 0.40)
    usar_shaft = ctx.get('incluir_shaft', True)

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
                for p in caminho_2d:
                    linha_3d.append((desescalar_coord(p.x) + ctx['min_x'] - ctx['offset'], desescalar_coord(p.y) + ctx['min_y'] - ctx['offset'], z_origem_teto))
                linha_3d.append((destino['x'], destino['y'], z_origem_teto))
                linha_3d.append((destino['x'], destino['y'], z_destino_teto))
            else:
                z_nav = max(z_origem_teto, z_destino_teto)
                linha_3d.append((origem['x'], origem['y'], z_nav))
                for p in caminho_2d:
                    linha_3d.append((desescalar_coord(p.x) + ctx['min_x'] - ctx['offset'], desescalar_coord(p.y) + ctx['min_y'] - ctx['offset'], z_nav))
                linha_3d.append((destino['x'], destino['y'], z_nav))

            linha_3d.append((destino['x'], destino['y'], destino['z_base'] + destino['z_relativo']))
            linha_3d = aplicar_desvios_estruturais_e_vaos_3d(linha_3d, elementos_arq, origem['z_base'], origem.get('pe_direito', 3.0), h_viga)
            linhas_processadas.append({
                'pontos': linha_3d, 'cor': cor, 'fios': fios,
                'id_origem': id_ref, 'comprimento_m': round(calcular_comprimento_rota(linha_3d), 2)
            })

    if quadros:
        luminarias = {b['ID_CAD']: b for b in df_be if b['Tipo_BIM'] == 'Luminária'}
        caixas = {b['ID_CAD']: b for b in df_be if 'Caixa' in b['Tipo_BIM']}
        controle_lum = {lum_id: [] for lum_id in luminarias.keys()}

        # Separa caixas TUE (circuito exclusivo direto ao QDG) de caixas TUG (roteadas em cascata por andar)
        caixas_tug_por_andar = {}
        for cx_id, cx_dados in caixas.items():
            qg_prox = min(quadros, key=lambda q: abs(q['z_base'] - cx_dados['z_base']) * 10 + dist_2d((cx_dados['x'], cx_dados['y']), (q['x'], q['y'])))
            if cx_dados.get('Qtd_Tomadas', 0) > 0:
                eq_assoc = str(cx_dados.get('Equipamento_Associado', 'TUG')).upper()
                eh_tue = any(k in eq_assoc for k in ['CHUVEIRO', 'COOKTOP', 'AR-CONDICIONADO', 'AR SPLIT', 'FORNO', 'WALLBOX', 'TORNEIRA', 'SECADORA', 'MÁQUINA'])
                if eh_tue:
                    achar_caminho(cx_dados, qg_prox, '#ff0055', 'F F T (TUE)' if cx_dados.get('Tensao_V', 127) >= 220 else 'F N T (TUE)', cx_id)
                else:
                    andar_k = cx_dados.get('Andar', 'Pav 0')
                    caixas_tug_por_andar.setdefault(andar_k, []).append(cx_dados)

            if cx_dados.get('Qtd_Interruptores', 0) > 0 and cx_dados.get('Luminarias_Controladas'):
                lums = [l.strip() for l in str(cx_dados['Luminarias_Controladas']).split(',') if l.strip()]
                for l in lums:
                    if l in controle_lum:
                        controle_lum[l].append(cx_id)

        # Roteamento em Cascata para TUGs do mesmo andar (até 4 caixas por tronco)
        for andar_k, lista_cxs in caixas_tug_por_andar.items():
            qg_andar = min(quadros, key=lambda q: abs(q['z_base'] - lista_cxs[0]['z_base']) * 10)
            nao_visitadas = lista_cxs.copy()
            atual = qg_andar
            cont_cascata = 0
            while nao_visitadas:
                prox_cx = min(nao_visitadas, key=lambda c: dist_2d((atual['x'], atual['y']), (c['x'], c['y'])))
                achar_caminho(prox_cx, atual, 'yellow' if evitar_linhas else 'green', 'F N T', prox_cx['ID_CAD'])
                nao_visitadas.remove(prox_cx)
                cont_cascata += 1
                # A cada 4 caixas em série, inicia um novo tronco a partir do QDG
                atual = qg_andar if cont_cascata >= 4 else prox_cx
                if cont_cascata >= 4:
                    cont_cascata = 0

        # Roteamento de Luminárias + Interruptores Simples, Three-Way (2R) e Four-Way (4R)
        for lum_id, lum in luminarias.items():
            qg_prox = min(quadros, key=lambda q: abs(q['z_base'] - lum['z_base']) * 10 + dist_2d((lum['x'], lum['y']), (q['x'], q['y'])))
            achar_caminho(lum, qg_prox, 'cyan', 'N T', lum_id)
            caixas_comando = controle_lum.get(lum_id, [])

            if len(caixas_comando) == 1:
                cx = caixas[caixas_comando[0]]
                achar_caminho(cx, lum, 'orange', 'F R', cx['ID_CAD'])
            elif len(caixas_comando) == 2:
                cx1, cx2 = caixas[caixas_comando[0]], caixas[caixas_comando[1]]
                achar_caminho(cx1, qg_prox, 'orange', 'F', cx1['ID_CAD'])
                achar_caminho(cx1, cx2, 'orange', '2R (3W)', cx1['ID_CAD'])
                achar_caminho(cx2, lum, 'orange', 'R', cx2['ID_CAD'])
            elif len(caixas_comando) >= 3:
                cx_inicio = caixas[caixas_comando[0]]
                cx_fim = caixas[caixas_comando[-1]]
                achar_caminho(cx_inicio, qg_prox, 'orange', 'F', cx_inicio['ID_CAD'])
                cx_atual = cx_inicio
                for cx_meio_id in caixas_comando[1:-1]:
                    cx_meio = caixas[cx_meio_id]
                    achar_caminho(cx_atual, cx_meio, '#ff5500', '4R (4W)', cx_atual['ID_CAD'])
                    cx_atual = cx_meio
                achar_caminho(cx_atual, cx_fim, 'orange', '2R (3W)', cx_atual['ID_CAD'])
                achar_caminho(cx_fim, lum, 'orange', 'R', cx_fim['ID_CAD'])

    return linhas_processadas
# ==============================================================================
# PARTE 7 DE 10: MOTOR DE QUANTITATIVOS (BOM) E GERADOR CAD DE 32 PEÇAS ABNT
# ==============================================================================
def calcular_angulo_deflexao(p_ant, p_atual, p_prox):
    v1 = (p_atual[0] - p_ant[0], p_atual[1] - p_ant[1], p_atual[2] - p_ant[2])
    v2 = (p_prox[0] - p_atual[0], p_prox[1] - p_atual[1], p_prox[2] - p_atual[2])
    m1 = math.sqrt(sum(c**2 for c in v1))
    m2 = math.sqrt(sum(c**2 for c in v2))
    if m1 < 1e-4 or m2 < 1e-4:
        return 0.0
    cos_ang = max(-1.0, min(1.0, sum(v1[k]*v2[k] for k in range(3)) / (m1 * m2)))
    return math.degrees(math.acos(cos_ang))

def gerar_quantitativos_totais_bim(linhas_elet, linhas_hidro, df_circuitos, df_be, df_bh):
    bom_af, bom_aq, bom_esg = {}, {}, {}

    def add_item(dicionario, item, unid, qtd):
        chave = (item, unid)
        dicionario[chave] = dicionario.get(chave, 0.0) + qtd

    for rota in linhas_hidro:
        pts = rota['pontos']
        tipo = rota.get('tipo', 'Água Fria')
        dn = int(rota.get('diametro', 25))
        comp_m = calcular_comprimento_rota(pts)

        joelhos_90, joelhos_45 = 0, 0
        for i in range(1, len(pts) - 1):
            ang = calcular_angulo_deflexao(pts[i-1], pts[i], pts[i+1])
            if 70 <= ang <= 115: joelhos_90 += 1
            elif 25 <= ang < 70: joelhos_45 += 1

        luvas = int(comp_m // 3.0) + 1

        if 'Água Fria' in tipo or 'Barrilete' in tipo:
            add_item(bom_af, f"Tubo PVC Soldável Marrom DN {dn}mm", "m", round(comp_m * 1.05, 1))
            if joelhos_90 > 0: add_item(bom_af, f"Joelho 90° Soldável {dn}mm", "un", joelhos_90)
            if joelhos_45 > 0: add_item(bom_af, f"Joelho 45° Soldável {dn}mm", "un", joelhos_45)
            add_item(bom_af, f"Tê 90° Soldável {dn}mm", "un", 1)
            add_item(bom_af, f"Luva Soldável {dn}mm", "un", luvas)
            if 'Barrilete' not in tipo:
                add_item(bom_af, f"Joelho 90° c/ Bucha de Latão {dn}mm x 1/2\"", "un", 1)
                add_item(bom_af, f"Registro de Pressão / Gaveta {dn}mm", "un", 1)
        elif 'Água Quente' in tipo or 'Gás' in tipo:
            mat_nome = "Cobre/PEX Gás (NBR 15526)" if 'Gás' in tipo else "CPVC/PPR Água Quente"
            add_item(bom_aq, f"Tubo {mat_nome} DN {dn}mm", "m", round(comp_m * 1.05, 1))
            if joelhos_90 > 0: add_item(bom_aq, f"Joelho 90° {mat_nome} {dn}mm", "un", joelhos_90)
            if joelhos_45 > 0: add_item(bom_aq, f"Joelho 45° {mat_nome} {dn}mm", "un", joelhos_45)
            add_item(bom_aq, f"Tê 90° {mat_nome} {dn}mm", "un", 1)
            add_item(bom_aq, f"Misturador / Válvula Esfera {dn}mm", "un", 1)
        else:
            suf_esg = "Pluvial (NBR 10844)" if "Pluviais" in tipo else "Esgoto Série Normal"
            add_item(bom_esg, f"Tubo PVC {suf_esg} DN {dn}mm", "m", round(comp_m * 1.05, 1))
            if joelhos_45 > 0: add_item(bom_esg, f"Joelho 45° Esgoto/AP {dn}mm", "un", joelhos_45)
            if joelhos_90 > 0: add_item(bom_esg, f"Curva Curta 90° Esgoto/AP {dn}mm", "un", joelhos_90)
            add_item(bom_esg, f"Junção Simples 45° (Y) {dn}mm", "un", 1)
            add_item(bom_esg, f"Luva Simples c/ Anel de Borracha {dn}mm", "un", luvas)

    if df_bh:
        add_item(bom_esg, "Caixa Sifonada 150x150x50mm c/ Grelha", "un", max(1, len(df_bh)//3))
        add_item(bom_esg, "Anel de Vedação p/ Esgoto c/ Lábio", "un", len(df_bh) * 3)

    bom_el = {}
    for rota in linhas_elet:
        pts = rota['pontos']
        comp_m = calcular_comprimento_rota(pts) * 1.10
        fios_str = rota.get('fios', 'F N T')
        add_item(bom_el, "Eletroduto PVC Flexível Corrugado Reforçado DN 25mm", "m", round(comp_m, 1))
        curvas_el = sum(1 for i in range(1, len(pts)-1) if calcular_angulo_deflexao(pts[i-1], pts[i], pts[i+1]) >= 60)
        if curvas_el > 0:
            add_item(bom_el, "Curva 90° Eletroduto PVC 25mm / Luva de Emenda", "un", curvas_el)
        add_item(bom_el, "Par Bucha e Arruela Zamac 3/4\" (25mm)", "par", 2)

        if 'F' in fios_str: add_item(bom_el, "Cabo de Cobre Flexível 750V (Fase - Vermelho/Preto) 2.5mm²", "m", round(comp_m, 1))
        if 'N' in fios_str: add_item(bom_el, "Cabo de Cobre Flexível 750V (Neutro - Azul Claro) 2.5mm²", "m", round(comp_m, 1))
        if 'T' in fios_str: add_item(bom_el, "Cabo de Cobre Flexível 750V (Terra PE - Verde) 2.5mm²", "m", round(comp_m, 1))
        if '4R' in fios_str: add_item(bom_el, "Cabo de Cobre Flexível 750V (Retorno Four-Way - Amarelo) 1.5mm²", "m", round(comp_m * 4, 1))
        elif '2R' in fios_str: add_item(bom_el, "Cabo de Cobre Flexível 750V (Retorno Three-Way - Amarelo) 1.5mm²", "m", round(comp_m * 2, 1))
        elif 'R' in fios_str: add_item(bom_el, "Cabo de Cobre Flexível 750V (Retorno Simples - Amarelo) 1.5mm²", "m", round(comp_m, 1))

    for b in df_be:
        tb = b.get('Tipo_BIM', '')
        if tb == 'Caixa 4x2': add_item(bom_el, "Caixa de Passagem Embutir 4x2\" PVC", "un", 1)
        elif tb == 'Caixa 4x4': add_item(bom_el, "Caixa de Passagem Embutir 4x4\" PVC", "un", 1)
        elif tb == 'Luminária': add_item(bom_el, "Caixa Octogonal de Laje 4x4\" Fundo Móvel", "un", 1)
        elif tb == 'Quadro Geral': add_item(bom_el, "Quadro de Distribuição Embutir c/ Barramento DIN", "un", 1)

    if not df_circuitos.empty:
        for _, r_c in df_circuitos.iterrows():
            disj = r_c.get('Disjuntor (A)', 16)
            curva = r_c.get('Curva', 'B')
            bit = r_c.get('Bitola (mm²)', 2.5)
            dist = float(r_c.get('Distância (m)', 15.0))
            add_item(bom_el, f"Disjuntor Termomagnético DIN {disj}A Curva {curva}", "un", 1)
            add_item(bom_el, f"Terminal Tubular Ilhós Isolado {bit}mm²", "un", 4)
            if float(bit) > 2.5:
                add_item(bom_el, f"Cabo de Cobre Flexível 750V {bit}mm² (Circuito TUE)", "m", round(dist * 3.0, 1))
        add_item(bom_el, "Interruptor Diferencial Residual (IDR) Tetrapolar 40A / 30mA", "un", 2)
        add_item(bom_el, "Dispositivo Protetor de Surtos (DPS) Classe II 275V 20kA", "un", 3)

    def dict_to_df(d):
        if not d:
            return pd.DataFrame(columns=["Descrição do Material / Peça", "Unid.", "Quantidade Total"])
        rows = [{"Descrição do Material / Peça": k[0], "Unid.": k[1], "Quantidade Total": round(v, 1)} for k, v in sorted(d.items())]
        return pd.DataFrame(rows)

    return {
        'eletrica': dict_to_df(bom_el),
        'agua_fria': dict_to_df(bom_af),
        'agua_quente': dict_to_df(bom_aq),
        'esgoto': dict_to_df(bom_esg)
    }

CATALOGO_PECAS_CAD = [
    "Joelho 90° Soldável / Roscável (Corte Técnico)",
    "Joelho 90° com Bucha de Latão (Azul - Ponto de Consumo)",
    "Joelho 45° Soldável / Roscável (Corte Técnico)",
    "Curva 90° Longa de Água / Esgoto (Raio Suave)",
    "Curva de Transposição (Desvio de Tubulação na Parede)",
    "Tê 90° de Passagem Direta / Derivação",
    "Tê de Redução 90° Soldável",
    "Tê com Bucha de Latão Central (Misturador/Chuveiro)",
    "Luva Simples / Luva de Correr com Anéis O-Ring",
    "União Roscável / Soldável com Assento Cônico (Bomba/Boiler)",
    "Bucha de Redução Curta / Longa Concêntrica",
    "Adaptador Soldável Curto com Bolsa e Rosca para Registro",
    "Flange / Adaptador para Caixa d'Água com Vedação",
    "Cap / Tampão Fêmea e Plug Macho Roscável",
    "Registro de Gaveta Bruto / Acabamento (Corte do Castelo)",
    "Registro de Pressão (Chuveiro - Corte do Obturador)",
    "Registro de Esfera PVC / Metálico 1/4 de Volta",
    "Válvula de Retenção Horizontal / Vertical com Portinhola",
    "Válvula Redutora de Pressão (VRP) com Manômetro",
    "Bomba Pressurizadora / Recalque Centrífuga",
    "Junção Simples 45° (Y - Esgoto NBR 8160)",
    "Junção Dupla 45° (Esgoto Sanitário)",
    "Redução Excêntrica de Esgoto (Alinhamento Superior)",
    "Caixa Sifonada 150x150x50mm (Corte c/ Fecho Hídrico ≥ 50mm)",
    "Caixa de Gordura Simples / Dupla (Corte c/ Septo e Cesto)",
    "Caixa de Inspeção / Passagem 60x60cm em Alvenaria/PVC",
    "Ralo Linear Inox / Ralo Seco de Box",
    "Caixa de Passagem Elétrica 4x2\" (Vista Frontal e Corte)",
    "Caixa de Passagem Elétrica 4x4\" Dupla (Vista Frontal e Corte)",
    "Caixa Octogonal de Laje 4x4\" Fundo Móvel",
    "Eletroduto Corrugado / Rígido + Curva 90° + Bucha e Arruela",
    "Disjuntor Termomagnético DIN / IDR / DPS (Vista Frontal e Perfil DIN)"
]

def gerar_desenho_tecnico_peca_plotly(peca_tipo, dn_mm=25):
    fig = go.Figure()
    d = float(dn_mm)
    esp = max(2.0, d * 0.08)
    bolsa = d * 0.65

    def add_cota(x0, y0, x1, y1, texto, offset_y=0.0, offset_x=0.0):
        fig.add_trace(go.Scatter(
            x=[x0+offset_x, x1+offset_x], y=[y0+offset_y, y1+offset_y],
            mode='lines+markers+text', line=dict(color='#d62728', width=1.5, dash='dot'),
            marker=dict(symbol='line-ns-open' if offset_y != 0 else 'line-ew-open', size=8, color='#d62728'),
            text=["", texto], textposition="top center" if offset_y >= 0 else "bottom center", showlegend=False
        ))

    if "Joelho 90°" in peca_tipo:
        r_m = d * 1.1
        cor_p = "#0055cc" if "Latão" in peca_tipo else "#1f77b4"
        fig.add_shape(type="rect", x0=-d/2-esp, y0=-r_m-bolsa, x1=d/2+esp, y1=d/2+esp, line=dict(color=cor_p, width=2.5), fillcolor="rgba(31,119,180,0.12)")
        fig.add_shape(type="rect", x0=-d/2-esp, y0=-d/2-esp, x1=r_m+bolsa, y1=d/2+esp, line=dict(color=cor_p, width=2.5), fillcolor="rgba(31,119,180,0.12)")
        fig.add_shape(type="rect", x0=-d/2, y0=-r_m-bolsa, x1=d/2, y1=d/2, line=dict(color="#003366", width=1.5), fillcolor="white")
        fig.add_shape(type="rect", x0=-d/2, y0=-d/2, x1=r_m+bolsa, y1=d/2, line=dict(color="#003366", width=1.5), fillcolor="white")
        if "Latão" in peca_tipo:
            fig.add_shape(type="rect", x0=r_m, y0=-d/2, x1=r_m+bolsa, y1=-d/2+esp*1.5, fillcolor="#d4af37", line=dict(color="#b8860b", width=1.5))
            fig.add_shape(type="rect", x0=r_m, y0=d/2-esp*1.5, x1=r_m+bolsa, y1=d/2, fillcolor="#d4af37", line=dict(color="#b8860b", width=1.5))
        fig.add_trace(go.Scatter(x=[0, 0, r_m+bolsa+10], y=[-r_m-bolsa-10, 0, 0], mode='lines', line=dict(color='gray', width=1, dash='dashdot'), name='Eixo de Centro'))
        add_cota(-d/2, -r_m-bolsa, d/2, -r_m-bolsa, f"DN {int(d)} mm", offset_y=-8)
        add_cota(r_m, d/2+esp, r_m+bolsa, d/2+esp, f"Bolsa / Rosca {bolsa:.1f} mm", offset_y=8)
    elif "Joelho 45°" in peca_tipo:
        L = d * 1.4
        fig.add_trace(go.Scatter(x=[-d/2, d/2, d/2 + L*0.7, L*0.7 - d/2, -d/2], y=[-L, -L, L*0.7, L*0.7 + d*0.7, -L], fill="toself", line=dict(color="#1f77b4", width=2.5), name="Corpo 45°"))
        add_cota(-d/2, -L, d/2, -L, f"DN {int(d)} mm (α = 45°)", offset_y=-8)
    elif "Curva de Transposição" in peca_tipo:
        L = d * 3.5
        xs = [-L, -L*0.4, 0, L*0.4, L]
        fig.add_trace(go.Scatter(x=xs, y=[d/2, d/2, d*1.6, d/2, d/2], mode='lines', line=dict(color="#1f77b4", width=3, shape='spline'), showlegend=False))
        fig.add_trace(go.Scatter(x=xs, y=[-d/2, -d/2, d*0.6, -d/2, -d/2], mode='lines', line=dict(color="#1f77b4", width=3, shape='spline'), fill='tonexty', fillcolor="rgba(31,119,180,0.12)"))
        add_cota(-L, -d/2, L, -d/2, f"Comprimento Transposição = {2*L:.0f} mm (DN {int(d)}mm)", offset_y=-12)
    elif "Curva 90° Longa" in peca_tipo:
        R = d * 2.2
        angs = [math.radians(a) for a in range(0, 95, 5)]
        x_ext = [R - (R - d/2 - esp)*math.cos(a) for a in angs]
        y_ext = [(R - d/2 - esp)*math.sin(a) for a in angs]
        x_int = [R - (R + d/2 + esp)*math.cos(a) for a in angs]
        y_int = [(R + d/2 + esp)*math.sin(a) for a in angs]
        fig.add_trace(go.Scatter(x=x_ext + x_int[::-1], y=y_ext + y_int[::-1], fill="toself", line=dict(color="#1f77b4", width=2.5), fillcolor="rgba(31,119,180,0.12)"))
        add_cota(-d/2, 0, R, 0, f"Raio Longo R = {R:.1f} mm | DN {int(d)} mm", offset_y=-12)
    elif "Tê" in peca_tipo:
        L = d * 1.8
        d_der = d * 0.75 if "Redução" in peca_tipo else d
        fig.add_shape(type="rect", x0=-L, y0=-d/2-esp, x1=L, y1=d/2+esp, line=dict(color="#1f77b4", width=2.5), fillcolor="rgba(31,119,180,0.12)")
        fig.add_shape(type="rect", x0=-d_der/2-esp, y0=0, x1=d_der/2+esp, y1=L, line=dict(color="#1f77b4", width=2.5), fillcolor="rgba(31,119,180,0.12)")
        add_cota(-L, -d/2-esp, L, -d/2-esp, f"L = {2*L:.1f} mm | DN {int(d)} x {int(d_der)} mm", offset_y=-10)
    elif "Junção" in peca_tipo:
        L = d * 2.0
        fig.add_shape(type="rect", x0=-L, y0=-d/2, x1=L, y1=d/2, line=dict(color="#8c564b", width=2.5), fillcolor="rgba(140,86,75,0.15)")
        ramal_x, ramal_y = [-d/2, d/2, d/2 + L*0.7, -d/2 + L*0.7, -d/2], [0, 0, L*0.7, L*0.7, 0]
        fig.add_trace(go.Scatter(x=ramal_x, y=ramal_y, fill="toself", line=dict(color="#8c564b", width=2.5)))
        if "Dupla" in peca_tipo:
            fig.add_trace(go.Scatter(x=ramal_x, y=[-y for y in ramal_y], fill="toself", line=dict(color="#8c564b", width=2.5)))
        add_cota(-L, -d/2, L, -d/2, f"{peca_tipo} DN {int(d)} mm", offset_y=-14)
    elif "Luva" in peca_tipo or "União" in peca_tipo or "Adaptador" in peca_tipo or "Flange" in peca_tipo:
        L = d * 1.2
        fig.add_shape(type="rect", x0=-L, y0=-d/2-esp*1.8, x1=L, y1=d/2+esp*1.8, line=dict(color="#2ca02c", width=2.5), fillcolor="rgba(44,160,44,0.12)")
        fig.add_shape(type="rect", x0=-L, y0=-d/2, x1=L, y1=d/2, line=dict(color="#1f77b4", width=1.5), fillcolor="white")
        add_cota(-L, -d/2-esp*1.8, L, -d/2-esp*1.8, f"{peca_tipo} | Compr. {2*L:.1f} mm (DN {int(d)}mm)", offset_y=-10)
    elif "Redução" in peca_tipo:
        L, d_men = d * 1.3, d * 0.65
        pts_x = [-L, 0, L, L, 0, -L, -L]
        pts_y = [d/2, d/2, d/2, d/2 - d_men, -d/2, -d/2, d/2] if "Excêntrica" in peca_tipo else [d/2, d/2, d_men/2, -d_men/2, -d/2, -d/2, d/2]
        fig.add_trace(go.Scatter(x=pts_x, y=pts_y, fill="toself", line=dict(color="#9467bd", width=2.5), fillcolor="rgba(148,103,189,0.15)"))
        add_cota(-L, -d/2, L, -d/2, f"Redução DN {int(d)} x {int(d_men)} mm", offset_y=-10)
    elif "Cap" in peca_tipo or "Tampão" in peca_tipo:
        L = d * 0.9
        fig.add_shape(type="rect", x0=-L, y0=-d/2-esp*1.5, x1=0, y1=d/2+esp*1.5, line=dict(color="#8c564b", width=2.5), fillcolor="rgba(140,86,75,0.2)")
        add_cota(-L, -d/2-esp*1.5, 0, -d/2-esp*1.5, f"Cap / Tampão Vedação DN {int(d)} mm", offset_y=-10)
    elif "Registro" in peca_tipo or "Válvula" in peca_tipo or "Bomba" in peca_tipo:
        L = d * 1.6
        fig.add_shape(type="rect", x0=-L, y0=-d/2-esp, x1=L, y1=d/2+esp, line=dict(color="#b8860b", width=2.5), fillcolor="rgba(212,175,55,0.18)")
        fig.add_shape(type="rect", x0=-d*0.35, y0=d/2+esp, x1=d*0.35, y1=d*1.6, line=dict(color="#b8860b", width=2.5), fillcolor="rgba(212,175,55,0.25)")
        fig.add_shape(type="rect", x0=-d*0.9, y0=d*1.6, x1=d*0.9, y1=d*1.85, line=dict(color="#333", width=2.5), fillcolor="#555")
        add_cota(-L, -d/2-esp, L, -d/2-esp, f"{peca_tipo} | Corpo {2*L:.1f} mm (DN {int(d)}mm)", offset_y=-12)
    elif "Caixa Sifonada" in peca_tipo or "Ralo" in peca_tipo:
        fig.add_shape(type="rect", x0=-75, y0=-150, x1=75, y1=0, line=dict(color="#2ca02c", width=2.5), fillcolor="rgba(44,160,44,0.1)")
        fig.add_shape(type="rect", x0=-72, y0=-148, x1=72, y1=-85, line=dict(color="#1f77b4", width=1), fillcolor="rgba(31,119,180,0.35)")
        fig.add_shape(type="line", x0=25, y0=-30, x1=25, y1=-115, line=dict(color="black", width=4))
        add_cota(-75, -148, 75, -85, "Fecho Hídrico ≥ 50 mm (NBR 8160)", offset_y=-15)
    elif "Caixa de Gordura" in peca_tipo or "Caixa de Inspeção" in peca_tipo:
        fig.add_shape(type="rect", x0=-125, y0=-220, x1=125, y1=0, line=dict(color="#5c3a21", width=3), fillcolor="rgba(140,86,75,0.1)")
        fig.add_shape(type="rect", x0=-120, y0=-215, x1=120, y1=-90, line=dict(color="#1f77b4", width=1), fillcolor="rgba(31,119,180,0.25)")
        fig.add_shape(type="line", x0=45, y0=-20, x1=45, y1=-170, line=dict(color="black", width=4))
        add_cota(-125, -220, 125, -220, "Câmara de Retenção + Septo Sifonado (NBR 8160)", offset_y=-16)
    elif "Caixa" in peca_tipo and ("4x2" in peca_tipo or "4x4" in peca_tipo or "Octogonal" in peca_tipo):
        larg_cx = 50 if "4x2" in peca_tipo else 100
        fig.add_shape(type="rect", x0=-larg_cx/2, y0=-50, x1=larg_cx/2, y1=50, line=dict(color="#ff7f0e", width=3), fillcolor="rgba(255,127,14,0.15)")
        fig.add_shape(type="rect", x0=larg_cx/2 + 30, y0=-50, x1=larg_cx/2 + 75, y1=50, line=dict(color="#ff7f0e", width=2.5), fillcolor="rgba(255,127,14,0.1)")
        add_cota(-larg_cx/2, -50, larg_cx/2, -50, f"Largura {larg_cx} mm x Altura 100 mm", offset_y=-12)
    elif "Eletroduto" in peca_tipo:
        fig.add_shape(type="circle", x0=-d/2-2, y0=-d/2-2, x1=d/2+2, y1=d/2+2, line=dict(color="#333", width=3), fillcolor="#f5f5f5")
        fig.add_shape(type="circle", x0=-d/2, y0=-d/2, x1=d/2, y1=d/2, line=dict(color="#666", width=1.5), fillcolor="white")
        add_cota(-d/2, -d/2-2, d/2, -d/2-2, f"Eletroduto DN {int(d)} mm (Ocupação ≤ 40% NBR 5410)", offset_y=-10)
    else:
        fig.add_shape(type="rect", x0=-9, y0=-40, x1=9, y1=40, line=dict(color="#222", width=2.5), fillcolor="#f0f2f6")
        fig.add_shape(type="rect", x0=-6, y0=-8, x1=6, y1=8, line=dict(color="#d62728", width=2), fillcolor="#d62728")
        fig.add_shape(type="rect", x0=30, y0=-40, x1=95, y1=40, line=dict(color="#222", width=2), fillcolor="#e6e9ef")
        add_cota(-9, -40, 9, -40, "1 Módulo DIN = 17.5 mm", offset_y=-10)

    fig.update_layout(
        title=f"Desenho Técnico Paramétrico: {peca_tipo} (Escala 1:1 em mm)",
        xaxis=dict(title="Dimensão X (mm)", zeroline=False, showgrid=True, gridcolor="#eee", scaleanchor="y", scaleratio=1),
        yaxis=dict(title="Dimensão Y (mm)", zeroline=False, showgrid=True, gridcolor="#eee"),
        plot_bgcolor="white", height=520, margin=dict(l=20, r=20, t=50, b=20)
    )
    return fig
# ==============================================================================
# PARTE 8 DE 10: EXPORTADORES DXF/IFC, FLUXOGRAMA IFC E BARRA LATERAL COMPLETA
# ==============================================================================
def desenhar_simbologia_abnt(msp, p1, p2, fios_str):
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    if abs(dx) < 0.05 and abs(dy) < 0.05:
        return
    angulo_tubo = math.atan2(dy, dx)
    angulo_perp = angulo_tubo + (math.pi / 2.0)
    cx, cy = (p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0
    z, tamanho, px_dir, py_dir, afastamento = p1[2], 0.35, math.cos(angulo_perp), math.sin(angulo_perp), -0.25

    fios_limpos = fios_str.replace("(3W)", "").replace("(4W)", "").replace(" ", "")
    for char in fios_limpos:
        if char in ['2', '4']:
            continue
        bx = cx + (math.cos(angulo_tubo) * afastamento)
        by = cy + (math.sin(angulo_tubo) * afastamento)
        tx, ty = bx + (px_dir * tamanho), by + (py_dir * tamanho)
        if char == 'F':
            msp.add_line((bx - (px_dir * tamanho/2), by - (py_dir * tamanho/2), z), (tx, ty, z), dxfattribs={'layer': 'SIMBOLOS_FIOS_ABNT', 'color': 1})
        elif char == 'N':
            msp.add_line((bx, by, z), (tx, ty, z), dxfattribs={'layer': 'SIMBOLOS_FIOS_ABNT', 'color': 5})
            msp.add_line((tx, ty, z), (tx + math.cos(angulo_tubo)*0.15, ty + math.sin(angulo_tubo)*0.15, z), dxfattribs={'layer': 'SIMBOLOS_FIOS_ABNT', 'color': 5})
        elif char == 'T':
            msp.add_line((bx, by, z), (tx, ty, z), dxfattribs={'layer': 'SIMBOLOS_FIOS_ABNT', 'color': 3})
            msp.add_line((tx - math.cos(angulo_tubo)*0.15, ty - math.sin(angulo_tubo)*0.15, z), (tx + math.cos(angulo_tubo)*0.15, ty + math.sin(angulo_tubo)*0.15, z), dxfattribs={'layer': 'SIMBOLOS_FIOS_ABNT', 'color': 3})
        elif char == 'R':
            msp.add_line((bx, by, z), (bx + (px_dir * tamanho/2), by + (py_dir * tamanho/2), z), dxfattribs={'layer': 'SIMBOLOS_FIOS_ABNT', 'color': 2})
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

    for p1, p2 in paredes_raw:
        msp.add_line(p1, p2, dxfattribs={'layer': 'ARQ_PAREDES_3D'})

    if modo in ["ELETRICA", "UNIFICADO"]:
        for rota in linhas_elet:
            pts = rota['pontos']
            fios_str = rota.get('fios', 'F N T')
            for i in range(len(pts)-1):
                msp.add_line(pts[i], pts[i+1], dxfattribs={'layer': 'MEP_ELETRICA_ELETRODUTOS'})
                if dist_2d(pts[i], pts[i+1]) >= 0.6:
                    desenhar_simbologia_abnt(msp, pts[i], pts[i+1], fios_str)
            for pt in pts:
                msp.add_circle(pt, radius=0.04, dxfattribs={'layer': 'MEP_CONEXOES_CAIXAS'})

    if modo in ["HIDRO", "UNIFICADO"]:
        for rota in linhas_hidro:
            pts = rota['pontos']
            tipo = rota.get('tipo', 'Água Fria')
            layer_dest = "MEP_HIDRO_ESGOTO" if "Esgoto" in tipo or "Queda" in tipo else ("MEP_HIDRO_AGUA_QUENTE" if "Quente" in tipo or "Gás" in tipo else "MEP_HIDRO_AGUA_FRIA")
            for i in range(len(pts)-1):
                msp.add_line(pts[i], pts[i+1], dxfattribs={'layer': layer_dest})
            for pt in pts:
                msp.add_circle(pt, radius=0.05, dxfattribs={'layer': 'MEP_CONEXOES_CAIXAS'})

    with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
        doc.saveas(tmp.name)
        tmp_path = tmp.name
    with open(tmp_path, "rb") as f:
        dxf_bytes = f.read()
    os.unlink(tmp_path)
    return dxf_bytes

def exportar_malha_para_ifc_step(linhas_elet, linhas_hidro, modo="UNIFICADO"):
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    linhas_ifc = [
        "ISO-10303-21;", "HEADER;",
        f"FILE_DESCRIPTION(('ViewDefinition [CoordinationView_V2.0] - Modo {modo}'),('2;1'));",
        f"FILE_NAME('Projeto_BIM_{modo}.ifc','{timestamp}',('Engenharia BIM Master'),('UFF / BIM Master PRO'),'IFC4','BIM Master Engine','');",
        "FILE_SCHEMA(('IFC4'));", "ENDSEC;", "DATA;",
        "#1=IFCPROJECT('0xScRe4tE00001',$,'Projeto Executivo MEP Integrado',$,$,$,$,$,#2);",
        "#2=IFCUNITASSIGNMENT((#3,#4));",
        "#3=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);",
        "#4=IFCSIUNIT(*,.VOLUMEUNIT.,$,.CUBIC_METRE.);",
        "#10=IFCSITE('0xScRe4tE00010',$,'Terreno Padrao',$,$,$,$,$,.ELEMENT.,$,$,$,$,$);",
        "#20=IFCBUILDING('0xScRe4tE00020',$,'Edificacao BIM',$,$,$,$,$,.ELEMENT.,$,$,$);",
        "#30=IFCBUILDINGSTOREY('0xScRe4tE00030',$,'Pavimento Tipo',$,$,$,$,$,.ELEMENT.,0.0);",
        "#40=IFCDISTRIBUTIONSYSTEM('0xScRe4tE00040',$,'Sistema Eletrico NBR 5410',$,'ELECTRICAL',.ELECTRICAL.);",
        "#50=IFCDISTRIBUTIONSYSTEM('0xScRe4tE00050',$,'Sistema Hidrossanitario NBR 5626/8160/10844',$,'PLUMBING',.PLUMBING.);"
    ]
    id_step = 100
    if modo in ["ELETRICA", "UNIFICADO"]:
        for idx_r, rota in enumerate(linhas_elet):
            pts = rota['pontos']
            comp = calcular_comprimento_rota(pts)
            linhas_ifc.append(f"#{id_step}=IFCCABLESEGMENT('{str(uuid.uuid4())[:22]}',$,'Eletroduto_Circ_{idx_r+1}','Fios: {rota.get('fios','F N T')} | L={comp:.2f}m',$,$,$,$,.CABLESEGMENT.);")
            id_step += 1
            for i in range(1, len(pts)-1):
                linhas_ifc.append(f"#{id_step}=IFCJUNCTIONBOX('{str(uuid.uuid4())[:22]}',$,'Curva_Caixa_Elet_{idx_r}_{i}','Coord: {pts[i]}',$,$,$,$,.POWER.);")
                id_step += 1

    if modo in ["HIDRO", "UNIFICADO"]:
        for idx_h, rota in enumerate(linhas_hidro):
            pts = rota['pontos']
            comp = calcular_comprimento_rota(pts)
            dn, tp = rota.get('diametro', 25), rota.get('tipo', 'Agua Fria')
            linhas_ifc.append(f"#{id_step}=IFCPIPESEGMENT('{str(uuid.uuid4())[:22]}',$,'Tubo_{tp}_DN{dn}mm','L={comp:.2f}m | DN={dn}mm',$,$,$,$,.RIGIDSEGMENT.);")
            id_step += 1
            for i in range(1, len(pts)-1):
                linhas_ifc.append(f"#{id_step}=IFCPIPEFITTING('{str(uuid.uuid4())[:22]}',$,'Conexao_Joelho_Te_{tp}_DN{dn}mm','Coord: {pts[i]}',$,$,$,$,.BEND.);")
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

    sis_el = f"IfcDistributionSystem\n[ELÉTRICA - {len(linhas_elet)} Ramais]"
    sis_af = "IfcDistributionSystem\n[ÁGUA FRIA/QUENTE & GÁS]"
    sis_esg = "IfcDistributionSystem\n[ESGOTO, VENT. & PLUVIAL]"

    for s_node, cor_s in [(sis_el, "#d62728"), (sis_af, "#0066cc"), (sis_esg, "#8c564b")]:
        G.add_node(s_node, nivel=3, cor=cor_s)
        for a_nome in andares_nomes:
            G.add_edge(a_nome, s_node)

    for pai, filho, cor_f in [
        (sis_el, "IfcElectricDistributionBoard\n(QDG + Disjuntores + IDR + DPS)", "#e377c2"),
        (sis_el, "IfcCableCarrierSegment\n(Eletrodutos + Caixas 4x2/Oct.)", "#e377c2"),
        (sis_af, "IfcPipeSegment & IfcPipeFitting\n(Tubos AF/AQ/Gás + Conexões)", "#17becf"),
        (sis_esg, "IfcSanitaryTerminal & IfcPipeFitting\n(TQ + Pluvial + Cx Sifonada)", "#bcbd22")
    ]:
        G.add_node(filho, nivel=4, cor=cor_f)
        G.add_edge(pai, filho)

    pos, niveis = {}, {}
    for n, data in G.nodes(data=True):
        niveis.setdefault(data.get('nivel', 0), []).append(n)
    for niv, lista_nos in niveis.items():
        larg = len(lista_nos)
        for i, n in enumerate(lista_nos):
            pos[n] = ((i - (larg - 1) / 2.0) * 3.0, -niv * 2.0)

    edge_x, edge_y = [], []
    for u, v in G.edges():
        edge_x.extend([pos[u][0], pos[v][0], None])
        edge_y.extend([pos[u][1], pos[v][1], None])

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode='lines', line=dict(width=2, color='#888'), hoverinfo='none'))
    fig.add_trace(go.Scatter(
        x=[pos[n][0] for n in G.nodes()], y=[pos[n][1] for n in G.nodes()], mode='markers+text',
        text=list(G.nodes()), textposition="bottom center",
        marker=dict(size=28, color=[G.nodes[n]['cor'] for n in G.nodes()], line=dict(width=2, color='white')), hoverinfo='text'
    ))
    fig.update_layout(
        title="Fluxograma Topológico IFC 4 (Esquema de Classes e Sistemas MEP)",
        showlegend=False, xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        plot_bgcolor="white", height=480, margin=dict(l=10, r=10, t=45, b=30)
    )
    return fig

# ==========================================
# 3.E MOTOR DE RECONHECIMENTO INTELIGENTE DE BLOCOS (DXF / IFC -> BIBLIOTECA)
# ==========================================
import unicodedata
import difflib

def normalizar_texto_bim(txt):
    """Remove acentos, caracteres especiais e padroniza para maiúsculas."""
    if not txt:
        return ""
    s = "".join(c for c in unicodedata.normalize("NFD", str(txt)) if unicodedata.category(c) != "Mn")
    return s.upper().replace("_", " ").replace("-", " ").strip()

def extrair_nome_real_bloco_dxf(doc, entidade_insert):
    """
    Recupera o nome real de blocos dinâmicos anônimos do AutoCAD (*U63, *U65, etc.)
    inspecionando atributos, descrição do bloco, textos internos e a Layer de origem.
    """
    nome_bruto = str(entidade_insert.dxf.name)
    layer_nome = str(entidade_insert.dxf.layer)

    if not nome_bruto.startswith("*U"):
        return nome_bruto

    textos_encontrados = []
    # 1. Verifica atributos diretos da entidade INSERT
    try:
        for att in entidade_insert.attribs:
            if att.dxf.text and len(str(att.dxf.text).strip()) > 1:
                textos_encontrados.append(str(att.dxf.text).strip())
    except Exception:
        pass

    # 2. Vasculha a definição interna do bloco no DXF
    try:
        if nome_bruto in doc.blocks:
            bloco_def = doc.blocks.get(nome_bruto)
            desc = getattr(bloco_def.block.dxf, "description", "")
            if desc:
                textos_encontrados.append(str(desc).strip())
            for sub_e in bloco_def:
                dxft = sub_e.dxftype()
                if dxft in ["TEXT", "MTEXT"]:
                    t_val = getattr(sub_e.dxf, "text", "")
                    if t_val and len(str(t_val).strip()) > 1:
                        textos_encontrados.append(str(t_val).strip())
                elif dxft == "ATTDEF":
                    t_tag = getattr(sub_e.dxf, "tag", "")
                    if t_tag and len(str(t_tag).strip()) > 1:
                        textos_encontrados.append(str(t_tag).strip())
                elif dxft == "INSERT" and not str(sub_e.dxf.name).startswith("*U"):
                    textos_encontrados.append(str(sub_e.dxf.name).strip())
    except Exception:
        pass

    if textos_encontrados:
        resumo_txt = " ".join(dict.fromkeys(textos_encontrados))[:35]
        return f"{nome_bruto} [{resumo_txt}]"
    return f"{nome_bruto} [{layer_nome}]"

def classificar_bloco_hidro_inteligente(nome_bloco, layer_bloco, opcoes_equip):
    """
    Associa automaticamente Nome_Bloco + Layer ao Eq. (Biblioteca), Função BIM e altura z_relativo.
    """
    alvo = normalizar_texto_bim(f"{nome_bloco} {layer_bloco}")
    nome_norm = normalizar_texto_bim(nome_bloco)
    opcoes_norm = {normalizar_texto_bim(op): op for op in opcoes_equip}

    def buscar_na_bib(termo_chave, fallback=None):
        t_norm = normalizar_texto_bim(termo_chave)
        for k_norm, op_real in opcoes_norm.items():
            if t_norm in k_norm:
                return op_real
        return fallback if fallback else (opcoes_equip[0] if opcoes_equip else "")

    # 1. Verifica correspondência direta ou quase exata entre Nome_Bloco e a Biblioteca
    if nome_norm in opcoes_norm:
        eq_direto = opcoes_norm[nome_norm]
        func_bim = "Prumada Esgoto" if "TUBO DE QUEDA" in nome_norm or "COLUNA DE VENT" in nome_norm else "Aparelho Hidráulico"
        z_rel = 0.0 if ("RALO" in nome_norm or "CAIXA" in nome_norm) else 0.5
        return func_bim, eq_direto, z_rel

    for k_norm, op_real in opcoes_norm.items():
        if len(nome_norm) >= 4 and (nome_norm in k_norm or k_norm in nome_norm):
            z_rel = 0.0 if ("RALO" in k_norm or "CAIXA" in k_norm) else 0.5
            return "Aparelho Hidráulico", op_real, z_rel

    # 2. Regras Inteligentes por Palavras-Chave de Engenharia Hidrossanitária
    regras_hidro = [
        # (Palavras-chave, Função BIM, Termo na Biblioteca, Altura z_relativo)
        (["RAMAL DE DESCARGA", "RAMAL DESCARGA", "RD "], "Ramal de Descarga", "Ramal de Descarga Esgoto 40mm (Lavatório/Ralo)", -0.10),
        (["RAMAL DE ESGOTO", "RAMAL ESGOTO", "RE ", "COLETOR ESGOTO"], "Ramal de Esgoto", "Ramal de Esgoto Coletor 100mm (NBR 8160)", -0.18),
        (["QUEDA AF", "TQ AF", "DESCIDA AF", "QUEDA AGUA FRIA"], "Tubo de Queda Água Fria", "Tubo de Queda Água Fria (TQ-AF 32mm)", 0.0),
        (["SUBIDA AF", "CS AF", "COLUNA SUBIDA AF", "SUBIDA AGUA FRIA", "RECALQUE"], "Coluna de Subida Água Fria", "Coluna de Subida Água Fria (CS-AF 32mm)", 0.0),
        (["QUEDA AQ", "TQ AQ", "DESCIDA AQ", "QUEDA AGUA QUENTE"], "Tubo de Queda Água Quente", "Tubo de Queda Água Quente (TQ-AQ 28mm)", 0.0),
        (["SUBIDA AQ", "CS AQ", "COLUNA SUBIDA AQ", "SUBIDA AGUA QUENTE"], "Coluna de Subida Água Quente", "Coluna de Subida Água Quente (CS-AQ 28mm)", 0.0),
        (["BOILER", "AQUECEDOR"], "Boiler / Aquecedor", "Boiler (Aquecimento de Água Central)", 1.5),
        (["CAIXA DE INSPECAO", "CX INSPECAO", "CI ", "DESTINO ESGOTO", "FOSSA"], "Caixa de Inspeção / Destino Esgoto", "Caixa de Inspeção", -0.5),
        (["CAIXA D", "RESERVATORIO SUP", "CX AGUA"], "Caixa d'Água", "Caixa d'Água (Reservatório Superior)", 0.0),
        (["CISTERNA", "RESERVATORIO INF"], "Aparelho Hidráulico", "Cisterna (Reservatório Inferior)", 0.0),
        (["PRUMADA AF", "COLUNA AF", "DESCIDA AF", "PRUMADA AGUA"], "Prumada Água Fria", "Saída de Água Fria 32mm", 2.2),
        (["TUBO DE QUEDA", "TUBO QUEDA", "PRUMADA ESG", "COLUNA ESG"], "Prumada Esgoto", "Tubo de Queda (TQ - Esgoto Primário)", 0.0),
        (["VENTILACAO", "COLUNA VENT"], "Prumada Esgoto", "Coluna de Ventilação", 0.0),
        (["RALO SIFONADO", "RS ", "CX SIFONADA 100"], "Aparelho Hidráulico", "Ralo Sifonado", 0.0),
        (["CAIXA SIFONADA", "CX SIF", "CS "], "Aparelho Hidráulico", "Caixa Sifonada 150x150x50mm", 0.0),
        (["RALO SECO", "RSE"], "Aparelho Hidráulico", "Ralo Seco (Chuveiro)", 0.0),
        (["RALO LINEAR", "RALO BOX"], "Aparelho Hidráulico", "Ralo Linear Inox (Box Banheiro)", 0.0),
        (["RALO VARANDA", "RALO SACADA"], "Aparelho Hidráulico", "Ralo de Varanda/Sacada", 0.0),
        (["CAIXA DE GORDURA", "CX GORDURA", "[CG]", " CG "], "Aparelho Hidráulico", "Caixa de Gordura", 0.0),
        (["CAIXA DE INSPECAO", "CX INSPECAO", "[CI]", " CI ", "DESTINO ESGOTO", "FOSSA"], "Caixa de Inspeção / Destino Esgoto", "Caixa de Inspeção", -0.5),
        (["CAIXA DE PASSAGEM", "CX PASSAGEM"], "Aparelho Hidráulico", "Caixa de Passagem", 0.0),
        (["BACIA", "VASO", "SANITARIO", "VS "], "Aparelho Hidráulico", "Bacia Sanitária (Caixa Acoplada) - Popular", 0.2),
        (["DUCHA HIG", "DH ", "BIDE"], "Aparelho Hidráulico", "Ducha Higiênica", 0.6),
        (["CHUVEIRO MIST", "DUCHA MIST"], "Aparelho Hidráulico", "Chuveiro Misturador (Água Fria + Quente)", 2.1),
        (["CHUVEIRO", "DUCHA", "CH "], "Aparelho Hidráulico", "Chuveiro Elétrico Padrão", 2.1),
        (["BANHEIRA", "HIDROMASSAGEM", "SPA"], "Aparelho Hidráulico", "Banheira Hidromassagem", 0.4),
        (["LAVATORIO", "LV ", "CUBA BANH", "BANCADA BANH"], "Aparelho Hidráulico", "Lavatório/Pia (Residencial)", 0.65),
        (["PIA GOURMET", "CUBA DUPLA", "TORNEIRA GOURMET"], "Aparelho Hidráulico", "Pia de Cozinha - Cuba Dupla Gourmet", 0.65),
        (["PIA", "COZINHA", "CUBA"], "Aparelho Hidráulico", "Pia de Cozinha (Residencial)", 0.9),
        (["LAVA LOUCA", "MLL"], "Aparelho Hidráulico", "Máquina de Lavar Louça", 0.6),
        (["LAVAR ROUPA", "MLR", "MAQUINA DE LAVAR", "LAVADORA"], "Aparelho Hidráulico", "Máquina de Lavar Roupa", 0.9),
        (["TANQUE", "TQ ROUPA", "TQ LAV"], "Aparelho Hidráulico", "Tanque de Lavar Roupa", 0.9),
        (["FILTRO", "PURIFICADOR"], "Aparelho Hidráulico", "Filtro/Purificador de Parede", 1.35),
        (["BEBEDOURO"], "Aparelho Hidráulico", "Bebedouro", 0.9),
        (["GELADEIRA", "SIDE BY SIDE"], "Aparelho Hidráulico", "Geladeira Side-by-Side (Filtro/Gelo)", 1.35),
        (["MICTORIO"], "Aparelho Hidráulico", "Mictório Cerâmico (c/ válvula)", 0.6),
        (["TORNEIRA QUINTAL", "JARDIM", "EXTERNA"], "Aparelho Hidráulico", "Torneira quintal", 0.6),
        (["REGISTRO DE PRESSAO", "REG PRESSAO", "RP "], "Aparelho Hidráulico", "Registro de Pressão 25mm (3/4)", 1.1),
        (["REGISTRO DE GAVETA", "REG GAVETA", "RG "], "Aparelho Hidráulico", "Registro de Gaveta 25mm (3/4)", 1.8),
        (["VRP", "REDUTORA DE PRESSAO"], "Aparelho Hidráulico", "Válvula Redutora de Pressão (VRP) 32mm", 1.5),
        (["RETENCAO"], "Aparelho Hidráulico", "Válvula de Retenção 25mm", 0.5),
        (["BOMBA", "PRESSURIZADORA", "RECALQUE"], "Aparelho Hidráulico", "Bomba Pressurizadora Residencial", 0.3),
        (["BOILER"], "Aparelho Hidráulico", "Boiler (Aquecimento de Água Central)", 1.8),
        (["AQUECEDOR"], "Aparelho Hidráulico", "Aquecedor de Passagem a Gás", 1.5),
        (["GAS", "GLP", "FOGAO"], "Aparelho Hidráulico", "Ponto de Gás (Fogão/Aquecedor)", 0.6),
        (["JOELHO 90", "J90", "COTOVELO"], "Aparelho Hidráulico", "Joelho 90° 25mm", 0.6),
        (["JOELHO 45", "J45"], "Aparelho Hidráulico", "Joelho 45° 25mm", 0.6),
        (["CURVA 90", "C90"], "Aparelho Hidráulico", "Curva 90° 25mm", 0.6),
        (["TE 90", "TE PASSAGEM", "TE "], "Aparelho Hidráulico", "Tê 90° (Passagem Direta) 25mm", 0.6),
        (["JUNCAO", "Y "], "Aparelho Hidráulico", "Junção Y Esgoto 50mm", 0.0),
        # Regras de Fallback pelo nome da Layer quando o bloco é anônimo (*U63, *U65...)
        (["AGUA QUENTE", "AQ"], "Aparelho Hidráulico", "Saída de Água Quente 22mm", 1.0),
        (["AGUA FRIA", "AF"], "Aparelho Hidráulico", "Saída de Água Fria 32mm", 0.6),
        (["ESGOTO", "ESG"], "Aparelho Hidráulico", "Ponto de Esgoto 50mm", 0.0),
    ]

    for palavras, func_bim, eq_padrao, z_rel in regras_hidro:
        if any(p in alvo for p in palavras):
            return func_bim, buscar_na_bib(eq_padrao), z_rel

    # 3. Busca aproximada por similaridade (Fuzzy Matching)
    similares = difflib.get_close_matches(nome_norm, list(opcoes_norm.keys()), n=1, cutoff=0.45)
    if similares:
        return "Aparelho Hidráulico", opcoes_norm[similares[0]], 0.5

    return "Aparelho Hidráulico", (opcoes_equip[0] if opcoes_equip else ""), 0.5

def classificar_bloco_eletrico_inteligente(nome_bloco, layer_bloco, pe_direito, tensao_padrao, opcoes_elet):
    """
    Associa automaticamente Nome_Bloco + Layer ao Tipo_BIM, Carga (Biblioteca), Tensão, Amperagem e Altura Z.
    """
    alvo = normalizar_texto_bim(f"{nome_bloco} {layer_bloco}")
    opcoes_norm = {normalizar_texto_bim(op): op for op in opcoes_elet}

    def buscar_el(termo_chave):
        t_norm = normalizar_texto_bim(termo_chave)
        for k_norm, op_real in opcoes_norm.items():
            if t_norm in k_norm:
                return op_real
        return opcoes_elet[0] if opcoes_elet else "Tomada Uso Geral (TUG)"

    if any(k in alvo for k in ["QUADRO", "QDG", "QDL", "QD "]):
        return "Quadro Geral", buscar_el("Tomada Uso Geral (TUG)"), 0, 0, "10A", tensao_padrao, 1.5

    if any(k in alvo for k in ["CHUVEIRO", "DUCHA ELETRICA", "TORNEIRA ELETRICA"]):
        return "Caixa 4x2", buscar_el("Chuveiro Elétrico 7500W"), 1, 0, "20A", 220, 2.1

    if any(k in alvo for k in ["COOKTOP", "INDUCAO", "FOGAO"]):
        return "Caixa 4x2", buscar_el("Cooktop Indução 7000W"), 1, 0, "20A", 220, 0.6

    if any(k in alvo for k in ["AR CONDICIONADO", "SPLIT", "EVAPORADORA", "AC "]):
        return "Caixa 4x2", buscar_el("Ar-Condicionado 12000 BTU"), 1, 0, "20A", 220, 2.2

    if any(k in alvo for k in ["FORNO", "MICROONDAS", "AIR FRYER", "COZINHA", "BANCADA", "SERVICO", "LAVANDERIA"]):
        return "Caixa 4x2", buscar_el("Tomada Cozinha/Serviço (TUG)"), 1, 0, "20A", tensao_padrao, 1.1

    if any(k in alvo for k in ["INTERRUPTOR", "INT ", "TECLA", "PARALELO", "3W", "4W"]):
        qtd_int = 2 if ("DUPLO" in alvo or "2S" in alvo) else (3 if ("TRIPLO" in alvo or "3S" in alvo) else 1)
        qtd_tom = 1 if ("CONJ" in alvo or "TOM" in alvo) else 0
        return "Caixa 4x2", buscar_el("Lâmpada LED 15W"), qtd_tom, qtd_int, "10A", tensao_padrao, 1.1

    if any(k in alvo for k in ["TOMADA", "TUG", "TUE", "CX ", "4X2", "4X4", "PONTO FORCA"]):
        tb = "Caixa 4x4" if "4X4" in alvo else "Caixa 4x2"
        z_r = 0.3 if "BAIXA" in alvo else (2.1 if "ALTA" in alvo else 0.6)
        qtd_t = 2 if ("DUPLA" in alvo or "2T" in alvo) else 1
        return tb, buscar_el("Tomada Uso Geral (TUG)"), qtd_t, 0, "10A", tensao_padrao, z_r

    if any(k in alvo for k in ["LUMINARIA", "LAMPADA", "LUZ", "SPOT", "PLAFON", "PENDENTE", "LED", "LUSTRE", "TETO", "ILUM"]):
        return "Luminária", buscar_el("Lâmpada LED 15W"), 0, 0, "10A", tensao_padrao, pe_direito

    return "Caixa 4x2", buscar_el("Tomada Uso Geral (TUG)"), 1, 0, "10A", tensao_padrao, 0.6

# ==========================================
# 3.F MOTOR DE ATUALIZAÇÃO DIFERENCIAL (SMART SYNC DXF / IFC)
# ==========================================
if "sync_version" not in st.session_state:
    st.session_state["sync_version"] = 0
if "memoria_edicoes_elet" not in st.session_state:
    st.session_state["memoria_edicoes_elet"] = []
if "memoria_edicoes_hidro" not in st.session_state:
    st.session_state["memoria_edicoes_hidro"] = []
if "resumo_ultimo_sync" not in st.session_state:
    st.session_state["resumo_ultimo_sync"] = ""

def salvar_edicoes_na_memoria(df_elet, df_hidro):
    """Salva continuamente na sessão todas as edições feitas pelo usuário nas tabelas."""
    if df_elet is not None and not df_elet.empty:
        st.session_state["memoria_edicoes_elet"] = df_elet.to_dict("records")
    if df_hidro is not None and not df_hidro.empty:
        st.session_state["memoria_edicoes_hidro"] = df_hidro.to_dict("records")

def mesclar_blocos_com_memoria(df_novo, disciplina="hidro"):
    """
    Compara os blocos recém-lidos do DXF/IFC com a memória de edições anteriores:
    - Preserva todas as escolhas manuais nos blocos inalterados ou levemente movidos;
    - Atualiza apenas coordenadas alteradas, adiciona blocos novos e remove os excluídos.
    """
    if df_novo is None or df_novo.empty:
        return df_novo, {"mantidos": 0, "movidos": 0, "novos": 0, "removidos": 0}

    chave_mem = "memoria_edicoes_hidro" if disciplina == "hidro" else "memoria_edicoes_elet"
    memoria = st.session_state.get(chave_mem, [])
    if not memoria:
        return df_novo, {"mantidos": 0, "movidos": 0, "novos": len(df_novo), "removidos": 0}

    campos_preservar = (
        ["Tipo_BIM", "Equipamento", "z_relativo"]
        if disciplina == "hidro"
        else ["Tipo_BIM", "Equipamento_Associado", "Qtd_Tomadas", "Amperagem_Tomadas", "Tensao_V", "Qtd_Interruptores", "Luminarias_Controladas", "z_relativo"]
    )

    usados_mem = set()
    df_mesclado = df_novo.copy()
    cont_mantidos, cont_movidos, cont_novos = 0, 0, 0

    # Passagem 1: Mesma posição exata (distância < 5cm) e mesmo Andar -> Inalterado (mesmo que o ID_CAD tenha mudado a ordem)
    indices_pareados = set()
    for idx, row_n in df_mesclado.iterrows():
        andar_n = str(row_n.get("Andar", ""))
        nome_n = str(row_n.get("Nome_Bloco", ""))
        xn, yn = float(row_n.get("x", 0.0)), float(row_n.get("y", 0.0))

        for m_idx, row_m in enumerate(memoria):
            if m_idx in usados_mem:
                continue
            if str(row_m.get("Andar", "")) == andar_n and str(row_m.get("Nome_Bloco", "")) == nome_n:
                xm, ym = float(row_m.get("x", 0.0)), float(row_m.get("y", 0.0))
                if math.hypot(xn - xm, yn - ym) <= 0.05:
                    for col_p in campos_preservar:
                        if col_p in row_m and col_p in df_mesclado.columns:
                            df_mesclado.at[idx, col_p] = row_m[col_p]
                    usados_mem.add(m_idx)
                    indices_pareados.add(idx)
                    cont_mantidos += 1
                    break

    # Passagem 2: Blocos que foram movidos no CAD (mesmo Nome_Bloco e Andar em um raio de até 2.0m)
    for idx, row_n in df_mesclado.iterrows():
        if idx in indices_pareados:
            continue
        andar_n = str(row_n.get("Andar", ""))
        nome_n = str(row_n.get("Nome_Bloco", ""))
        xn, yn = float(row_n.get("x", 0.0)), float(row_n.get("y", 0.0))

        candidatos = []
        for m_idx, row_m in enumerate(memoria):
            if m_idx in usados_mem:
                continue
            if str(row_m.get("Andar", "")) == andar_n and str(row_m.get("Nome_Bloco", "")) == nome_n:
                xm, ym = float(row_m.get("x", 0.0)), float(row_m.get("y", 0.0))
                d_mov = math.hypot(xn - xm, yn - ym)
                if d_mov <= 2.0:
                    candidatos.append((d_mov, m_idx, row_m))

        if candidatos:
            candidatos.sort(key=lambda x: x[0])
            _, m_idx_escolhido, row_m_esc = candidatos[0]
            for col_p in campos_preservar:
                if col_p in row_m_esc and col_p in df_mesclado.columns:
                    df_mesclado.at[idx, col_p] = row_m_esc[col_p]
            usados_mem.add(m_idx_escolhido)
            indices_pareados.add(idx)
            cont_movidos += 1
        else:
            cont_novos += 1

    cont_removidos = max(0, len(memoria) - len(usados_mem))
    stats = {"mantidos": cont_mantidos, "movidos": cont_movidos, "novos": cont_novos, "removidos": cont_removidos}
    return df_mesclado, stats

with st.sidebar:
    st.header("💾 Arquivo do Projeto")
    arquivo_projeto = st.file_uploader("Abrir Projeto Salvo (.bim)", type=["bim", "json"])
    if arquivo_projeto is not None:
        if st.button("📂 Carregar Dados do Arquivo", use_container_width=True):
            importar_projeto(arquivo_projeto)
            st.success("Projeto carregado com sucesso!")
            st.rerun()

    st.download_button(
        label="💾 Salvar Projeto Atual (.bim)", data=exportar_projeto(),
        file_name="meu_projeto.bim", mime="application/json", use_container_width=True, type="primary"
    )

    st.divider()
    st.header("🏢 Arquitetura e Pavimentos (DXF / IFC)")
    import hashlib
    arquivos_dxf = st.file_uploader(
        "Upload Plantas ou Maquetes (.dxf ou .ifc)",
        type=["dxf", "ifc"],
        accept_multiple_files=True,
        help="Após salvar alterações no AutoCAD/Blender, clique no 'X' do arquivo antigo acima e solte o arquivo recém-salvo aqui. Suas edições na tabela serão preservadas!"
    )

    if arquivos_dxf:
        # Calcula a assinatura digital (Hash) dos bytes dos arquivos para detectar automaticamente qualquer modificação salva no CAD
        hash_atual = hashlib.md5(b"".join([f.getvalue() for f in arquivos_dxf])).hexdigest()[:8]
        hash_anterior = st.session_state.get("hash_arquivo_cad", "")

        if hash_anterior and hash_atual != hash_anterior:
            st.session_state["sync_version"] = st.session_state.get("sync_version", 0) + 1
            st.session_state["disparou_sync"] = True
            st.toast("✨ Novo arquivo modificado detectado! Sincronizando alterações...", icon="🔄")
        st.session_state["hash_arquivo_cad"] = hash_atual

        st.caption(f"📄 Versão carregada na memória: `{hash_atual}` ({sum(len(f.getvalue()) for f in arquivos_dxf)/1024:.1f} KB)")

        if st.button("🔄 Atualizar Projeto Atual (DXF/IFC)", use_container_width=True, help="Reprocessa o arquivo atual preservando todas as edições feitas na tabela."):
            st.session_state["sync_version"] = st.session_state.get("sync_version", 0) + 1
            st.session_state["disparou_sync"] = True
            st.rerun()

        if st.session_state.get("resumo_ultimo_sync"):
            st.success(st.session_state["resumo_ultimo_sync"])
            
    st.divider()
    st.subheader("Configurações Globais & Roteamento")
    espessura_laje = st.number_input("Espessura da Laje (m)", min_value=0.1, max_value=1.5, value=0.15, step=0.05)
    altura_viga = st.number_input("Altura Média das Vigas (m)", min_value=0.15, max_value=1.20, value=0.40, step=0.05)
    incluir_shaft = st.toggle("Incluir Shaft vertical entre andares", value=True)
    rotear_em_cascata = st.toggle("Roteamento TUG em Cascata (Poupe Eletrodutos)", value=True)
    agrupar_tugs_circuito = st.toggle("Agrupar TUGs/Ilum. por Pavimento no QDG", value=True)

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
    pessoas = st.number_input("Pessoas", min_value=1, value=4)
    consumo_pc = st.number_input("Consumo (L/dia)", min_value=50, value=150)
    dias_reserva = st.number_input("Dias Reserva", min_value=1, value=2)
    vol_caixa = pessoas * consumo_pc * dias_reserva
    vol_comercial = next((v for v in [500, 1000, 1500, 2000, 2500, 3000, 5000, 10000] if v >= vol_caixa), vol_caixa)
    st.info(f"Volume Calc: **{vol_caixa} L** | Comercial: **{vol_comercial} L**")

    st.divider()
    if st.button("🔒 Bloquear / Sair do Sistema", use_container_width=True):
        st.session_state["autenticado"] = False
        st.rerun()
# ==============================================================================
# PARTE 9 DE 10: ABAS 1 E 2 (MODELAGEM BIM 3D DXF/IFC E CLASH DETECTION)
# ==============================================================================
tab_bim, tab_clash, tab_eletrica, tab_hidro, tab_pecas_ifc, tab_export = st.tabs([
    "🗺️ BIM 3D & Roteamento",
    "⚠️ Clash Detection",
    "⚡ Eng. Elétrica, Auditoria & QDG",
    "💧 Eng. Hidrossanitária, Pluvial & Gás",
    "📐 Peças CAD (32 Itens), Quantitativos & IFC",
    "📦 Config. & Bibliotecas"
])

with tab_bim:
    st.title("Modelagem e Roteamento Multidisciplinar Consciente de Estrutura (DXF & IFC)")
    
    if arquivos_dxf:
        todas_layers_set = set()
        layers_com_blocos = set()
        dxf_files_only = [f for f in arquivos_dxf if f.name.lower().endswith(".dxf")]

        if dxf_files_only:
            for dxf_f in dxf_files_only:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp_file:
                    tmp_file.write(dxf_f.getvalue())
                    temp_path = tmp_file.name
                doc_base = ezdxf.readfile(temp_path)
                msp_base = doc_base.modelspace()
                # Captura layers da tabela oficial E também layers aplicadas diretamente nos objetos e blocos
                for layer in doc_base.layers:
                    todas_layers_set.add(layer.dxf.name)
                for ent in msp_base:
                    if hasattr(ent.dxf, "layer"):
                        todas_layers_set.add(ent.dxf.layer)
                        if ent.dxftype() == "INSERT":
                            layers_com_blocos.add(ent.dxf.layer)
                os.unlink(temp_path)
            todas_layers = sorted(list(todas_layers_set))
        else:
            todas_layers = ["IFC_WALLS", "IFC_DOORS_WINDOWS", "IFC_STRUCTURE", "IFC_ELECTRICAL", "IFC_PLUMBING"]

        # Detecta se surgiram layers novas no arquivo atualizado
        layers_conhecidas = st.session_state.get("layers_conhecidas_dxf", set())
        layers_novas_detectadas = set(todas_layers) - layers_conhecidas if layers_conhecidas else set()
        st.session_state["layers_conhecidas_dxf"] = set(todas_layers)

        if layers_novas_detectadas:
            st.info(f"✨ **Novas layers detectadas no arquivo atualizado:** `{', '.join(sorted(layers_novas_detectadas))}`")

        # Pré-seleção inteligente de layers por palavras-chave + inclusão automática de novas layers com blocos
        def sugerir_layers(palavras, padrao_vazio=False):
            sug = [ly for ly in todas_layers if any(p in normalizar_texto_bim(ly) for p in palavras)]
            if not sug and not padrao_vazio and todas_layers:
                return [todas_layers[0]]
            return sug

        default_arq = sugerir_layers(["ALVENARIA", "PAREDE", "ARQ", "MURO"], padrao_vazio=False)
        default_esq = sugerir_layers(["ESQUADRIA", "PORTA", "JANELA"], padrao_vazio=True)
        default_est = sugerir_layers(["VIGA", "PILAR", "ESTRUTURA", "CONCRETO"], padrao_vazio=True)
        default_elet = sugerir_layers(["ELETRICA", "ELET", "LUZ", "TOMADA", "ILUM"], padrao_vazio=True)
        default_hidro = sugerir_layers(["HIDR", "AGUA", "ESGOTO", "SANIT", "TUBULACAO", "PLUVIAL", "GAS"], padrao_vazio=True)

        # Inclui automaticamente qualquer nova layer que contenha blocos (INSERT) e não seja esquadria/estrutura
        for ly_b in layers_com_blocos:
            if ly_b not in default_esq and ly_b not in default_est and ly_b not in default_elet and ly_b not in default_hidro:
                if any(k in normalizar_texto_bim(ly_b) for k in ["ELET", "LUZ", "TOM"]):
                    default_elet.append(ly_b)
                elif ly_b in layers_novas_detectadas:
                    default_hidro.append(ly_b)

        c1, c2, c3, c4, c5 = st.columns(5)
        layer_arq = c1.multiselect("Paredes:", todas_layers, default=default_arq)
        layer_esquadrias = c2.multiselect("Esquadrias (Portas/Janelas):", todas_layers, default=default_esq)
        layer_estrutural = c3.multiselect("Vigas/Pilares:", todas_layers, default=default_est)
        layer_elet = c4.multiselect("Blocos Elétricos:", todas_layers, default=default_elet)
        layer_hidro = c5.multiselect("Blocos Hidro/Gás/Bomba:", todas_layers, default=sorted(list(set(default_hidro))))

        st.divider()
        st.subheader("Configuração de Alturas (Tubulações, Portas e Janelas) e Escopo")
        col_h1, col_h2, col_h3 = st.columns(3)
        h_agua_fria = col_h1.number_input("Altura Tubulação Água Fria na Parede (m)", value=0.20, step=0.1)
        h_agua_quente = col_h2.number_input("Altura Tubulação Água Quente na Parede (m)", value=1.00, step=0.1)
        modo_visualizacao = col_h3.selectbox("Visualização e Escopo do Projeto:", ["Unificado (Elétrica + Hidráulica)", "Apenas Elétrica", "Apenas Hidrossanitário"])

        # NOVOS CONTROLES PADRÃO DE PEITORIL, SOLEIRA E ALTURA DE JANELAS E PORTAS
        ce_p1, ce_p2, ce_j1, ce_j2 = st.columns(4)
        soleira_padrao_porta = ce_p1.number_input("Soleira Padrão de Portas (m)", min_value=0.0, max_value=1.0, value=0.00, step=0.05)
        altura_padrao_porta = ce_p2.number_input("Altura Padrão de Portas (m)", min_value=1.5, max_value=4.0, value=2.10, step=0.05)
        peitoril_padrao_janela = ce_j1.number_input("Peitoril Padrão de Janelas (m)", min_value=0.0, max_value=3.0, value=1.00, step=0.05)
        altura_padrao_janela = ce_j2.number_input("Altura Padrão de Janelas (m)", min_value=0.3, max_value=3.5, value=1.10, step=0.05)

        blocos_elet, blocos_hidro, paredes_raw, elementos_arquitetonicos = [], [], [], []
        max_z_projeto = 0.0
        z_acumulado = 0.0

        for andar_idx, config in enumerate(config_andares):
            dxf_file = config["arquivo"]
            pe_direito_atual = config["pe_direito"]
            z_base = z_acumulado
            if z_base > max_z_projeto:
                max_z_projeto = z_base

            if dxf_file.name.lower().endswith(".dxf"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp_file:
                    tmp_file.write(dxf_file.getvalue())
                    temp_path = tmp_file.name
                doc = ezdxf.readfile(temp_path)
                msp = doc.modelspace()
                
                for le in layer_esquadrias:
                    for idx_esq, e in enumerate(msp.query(f'INSERT[layer=="{le}"]')):
                        nome_bloco_u = extrair_nome_real_bloco_dxf(doc, e).upper()
                        layer_u = le.upper()
                        tem_arco = False
                        xs_b, ys_b = [], []
                        cx_ins, cy_ins = float(e.dxf.insert.x), float(e.dxf.insert.y)
                        try:
                            for ve in e.virtual_entities():
                                if ve.dxftype() == 'ARC':
                                    tem_arco = True
                                elif ve.dxftype() == 'LINE':
                                    if math.hypot(ve.dxf.start.x - cx_ins, ve.dxf.start.y - cy_ins) <= 2.5 and math.hypot(ve.dxf.end.x - cx_ins, ve.dxf.end.y - cy_ins) <= 2.5:
                                        xs_b.extend([ve.dxf.start.x, ve.dxf.end.x])
                                        ys_b.extend([ve.dxf.start.y, ve.dxf.end.y])
                                elif ve.dxftype() == 'LWPOLYLINE':
                                    for pt_v in ve.get_points(format='xy'):
                                        if math.hypot(pt_v[0] - cx_ins, pt_v[1] - cy_ins) <= 2.5:
                                            xs_b.append(pt_v[0])
                                            ys_b.append(pt_v[1])
                        except Exception:
                            pass

                        eh_porta = (
                            tem_arco
                            or any(k in nome_bloco_u for k in ["PORTA", "PT", "P1", "P2", "P3", "MADEIRA", "GIRO"])
                            or any(k in layer_u for k in ["PORTA", "MADEIRA"])
                        )
                        if "JANELA" in nome_bloco_u or "JAN" in layer_u:
                            eh_porta = False

                        if xs_b and ys_b:
                            x_min_e, x_max_e = min(xs_b), max(xs_b)
                            y_min_e, y_max_e = min(ys_b), max(ys_b)
                            dx_e, dy_e = x_max_e - x_min_e, y_max_e - y_min_e
                            larg_real = round(max(0.60, min(2.40, max(dx_e, dy_e))), 2)
                            cx_e, cy_e = round((x_min_e + x_max_e) / 2.0, 4), round((y_min_e + y_max_e) / 2.0, 4)
                            if dx_e >= dy_e:
                                p1_vao = (cx_e - larg_real / 2.0, cy_e)
                                p2_vao = (cx_e + larg_real / 2.0, cy_e)
                            else:
                                p1_vao = (cx_e, cy_e - larg_real / 2.0)
                                p2_vao = (cx_e, cy_e + larg_real / 2.0)
                        else:
                            larg_real = 0.85 if eh_porta else 1.20
                            rot_rad = math.radians(getattr(e.dxf, 'rotation', 0.0))
                            cx_e, cy_e = round(cx_ins, 4), round(cy_ins, 4)
                            p1_vao = (cx_e - (larg_real / 2.0) * math.cos(rot_rad), cy_e - (larg_real / 2.0) * math.sin(rot_rad))
                            p2_vao = (cx_e + (larg_real / 2.0) * math.cos(rot_rad), cy_e + (larg_real / 2.0) * math.sin(rot_rad))

                        # Reconhece janela alta de banheiro (báscula) se o nome indicar
                        eh_bascula = any(k in nome_bloco_u for k in ["BASC", "BANH", "WC", "J_ALTA"])
                        peit_ini = soleira_padrao_porta if eh_porta else (1.60 if eh_bascula else peitoril_padrao_janela)
                        alt_ini = altura_padrao_porta if eh_porta else (0.60 if eh_bascula else altura_padrao_janela)

                        elementos_arquitetonicos.append({
                            "ID_CAD": f"{e.dxf.name}_P{andar_idx}_{idx_esq}",
                            "Nome_Bloco": extrair_nome_real_bloco_dxf(doc, e),
                            "Layer_CAD": le,
                            "Andar": f"Pav {config['ordem']}",
                            "Tipo": "Esquadria",
                            "Subtipo": "Porta" if eh_porta else "Janela",
                            "x": cx_e, "y": cy_e, "z_base": z_base,
                            "pe_direito": pe_direito_atual,
                            "p1_vao": p1_vao, "p2_vao": p2_vao,
                            "Largura": larg_real,
                            "Peitoril": peit_ini,
                            "Altura": alt_ini
                        })

                for le in layer_estrutural:
                    for e in msp.query(f'INSERT[layer=="{le}"]'):
                        elementos_arquitetonicos.append({
                            "ID_CAD": f"{e.dxf.name}_EST", "Tipo": "Pilar/Viga",
                            "x": e.dxf.insert.x, "y": e.dxf.insert.y, "z_base": z_base,
                            "pe_direito": pe_direito_atual,
                            "Largura": 0.40, "Altura_Viga": altura_viga
                        })

                for le in layer_elet:
                    for i, e in enumerate(msp.query(f'INSERT[layer=="{le}"]')):
                        nome_inteligente = extrair_nome_real_bloco_dxf(doc, e)
                        blocos_elet.append({
                            "ID_CAD": f"{e.dxf.name}_P{andar_idx}_{i}",
                            "Nome_Bloco": nome_inteligente,
                            "Layer_CAD": le,
                            "x": round(e.dxf.insert.x, 4),
                            "y": round(e.dxf.insert.y, 4),
                            "z_base": z_base,
                            "Andar": f"Pav {config['ordem']}",
                            "pe_direito": pe_direito_atual
                        })
                for lh in layer_hidro:
                    for i, e in enumerate(msp.query(f'INSERT[layer=="{lh}"]')):
                        nome_inteligente = extrair_nome_real_bloco_dxf(doc, e)
                        blocos_hidro.append({
                            "ID_CAD": f"{e.dxf.name}_P{andar_idx}_{i}",
                            "Nome_Bloco": nome_inteligente,
                            "Layer_CAD": lh,
                            "x": round(e.dxf.insert.x, 4),
                            "y": round(e.dxf.insert.y, 4),
                            "z_base": z_base,
                            "Andar": f"Pav {config['ordem']}",
                            "pe_direito": pe_direito_atual
                        })
                for e in msp.query('LINE LWPOLYLINE'):
                    if e.dxf.layer in layer_arq:
                        pts = []
                        if e.dxftype() == 'LINE':
                            pts = [((e.dxf.start.x, e.dxf.start.y, z_base), (e.dxf.end.x, e.dxf.end.y, z_base + pe_direito_atual))]
                        elif e.dxftype() == 'LWPOLYLINE':
                            pontos = list(e.get_points(format='xy'))
                            for i in range(len(pontos)-1):
                                pts.append(((pontos[i][0], pontos[i][1], z_base), (pontos[i+1][0], pontos[i+1][1], z_base + pe_direito_atual)))
                        paredes_raw.extend(pts)
                os.unlink(temp_path)
            
            z_acumulado += pe_direito_atual + espessura_laje

        # TABELA INTERATIVA PARA EDITAR PEITORIL, SOLEIRA, ALTURA E LARGURA DE CADA PORTA E JANELA
        esquadrias_lista = [el for el in elementos_arquitetonicos if el.get("Tipo") == "Esquadria"]
        if esquadrias_lista:
            with st.expander(f"🚪🪟 Editar Peitoril, Soleira e Alturas Individuais de Portas e Janelas ({len(esquadrias_lista)} vãos detectados)", expanded=False):
                st.caption("Ajuste abaixo se um vão é Porta ou Janela, seu Peitoril/Soleira (m) e sua Altura (m). As tubulações podem passar livremente abaixo do Peitoril e acima da Verga (Peitoril + Altura)!")
                df_esq_raw = pd.DataFrame(esquadrias_lista)
                # Restaura edições salvas anteriormente pelo usuário por coordenada (x, y)
                mem_esq = st.session_state.get("memoria_edicoes_esq", {})
                for idx_e, r_e in df_esq_raw.iterrows():
                    chave_pos = f"{r_e.get('Andar','')}_{round(float(r_e['x']),2)}_{round(float(r_e['y']),2)}"
                    if chave_pos in mem_esq:
                        df_esq_raw.at[idx_e, "Subtipo"] = mem_esq[chave_pos]["Subtipo"]
                        df_esq_raw.at[idx_e, "Peitoril"] = mem_esq[chave_pos]["Peitoril"]
                        df_esq_raw.at[idx_e, "Altura"] = mem_esq[chave_pos]["Altura"]
                        df_esq_raw.at[idx_e, "Largura"] = mem_esq[chave_pos]["Largura"]

                cols_exibir_esq = ["ID_CAD", "Nome_Bloco", "Layer_CAD", "Andar", "Subtipo", "Peitoril", "Altura", "Largura", "x", "y"]
                df_esq_editado = st.data_editor(
                    df_esq_raw[cols_exibir_esq],
                    column_config={
                        "Subtipo": st.column_config.SelectboxColumn("Tipo de Vão", options=["Porta", "Janela"]),
                        "Peitoril": st.column_config.NumberColumn("Peitoril / Soleira (m)", min_value=0.0, max_value=3.5, step=0.05),
                        "Altura": st.column_config.NumberColumn("Altura do Vão (m)", min_value=0.3, max_value=4.0, step=0.05),
                        "Largura": st.column_config.NumberColumn("Largura (m)", min_value=0.4, max_value=5.0, step=0.05)
                    },
                    use_container_width=True,
                    hide_index=True,
                    key=f"editor_esq_v{st.session_state.get('sync_version', 0)}"
                )

                # Salva as edições e atualiza elementos_arquitetonicos com os novos peitoris e alturas
                novo_mem_esq = {}
                map_esq_atualizado = {}
                for _, r_ed in df_esq_editado.iterrows():
                    chave_pos = f"{r_ed.get('Andar','')}_{round(float(r_ed['x']),2)}_{round(float(r_ed['y']),2)}"
                    novo_mem_esq[chave_pos] = {
                        "Subtipo": r_ed["Subtipo"],
                        "Peitoril": float(r_ed["Peitoril"]),
                        "Altura": float(r_ed["Altura"]),
                        "Largura": float(r_ed["Largura"])
                    }
                    map_esq_atualizado[r_ed["ID_CAD"]] = novo_mem_esq[chave_pos]
                st.session_state["memoria_edicoes_esq"] = novo_mem_esq

                for el_arq in elementos_arquitetonicos:
                    if el_arq.get("Tipo") == "Esquadria" and el_arq["ID_CAD"] in map_esq_atualizado:
                        dados_at = map_esq_atualizado[el_arq["ID_CAD"]]
                        el_arq["Subtipo"] = dados_at["Subtipo"]
                        el_arq["Peitoril"] = dados_at["Peitoril"]
                        el_arq["Altura"] = dados_at["Altura"]
                        el_arq["Largura"] = dados_at["Largura"]
        
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.subheader("⚡ Equipamentos Elétricos")
            df_be = pd.DataFrame(blocos_elet) if blocos_elet else pd.DataFrame(columns=["ID_CAD", "Nome_Bloco", "x", "y", "z_base", "Andar", "pe_direito", "Tipo_BIM", "z_relativo"])
            
            if not df_be.empty:
                opcoes_eq_elet = list(st.session_state.bib_eletrica['Equipamento'])
                tipos_bim_el, equips_el, qtd_tom_el, qtd_int_el, amp_el, tens_el, z_rel_el = [], [], [], [], [], [], []

                for _, r_el in df_be.iterrows():
                    tb_e, eq_e, qt_e, qi_e, am_e, tn_e, zr_e = classificar_bloco_eletrico_inteligente(
                        r_el['Nome_Bloco'], r_el.get('Layer_CAD', ''), r_el['pe_direito'], tensao_fase, opcoes_eq_elet
                    )
                    tipos_bim_el.append(tb_e)
                    equips_el.append(eq_e)
                    qtd_tom_el.append(qt_e)
                    qtd_int_el.append(qi_e)
                    amp_el.append(am_e)
                    tens_el.append(tn_e)
                    z_rel_el.append(zr_e)

                df_be['Tipo_BIM'] = tipos_bim_el
                df_be['Equipamento_Associado'] = equips_el
                df_be['Qtd_Tomadas'] = qtd_tom_el
                df_be['Amperagem_Tomadas'] = amp_el
                df_be['Tensao_V'] = tens_el
                df_be['Qtd_Interruptores'] = qtd_int_el
                df_be['Luminarias_Controladas'] = ""
                df_be['z_relativo'] = z_rel_el
                                
                # --- TABELA ELÉTRICA (FECHAMENTO CORRETO DE PARÊNTESES) ---
                df_be, stats_el = mesclar_blocos_com_memoria(df_be, disciplina="elet")

                df_editado_elet = st.data_editor(
                    df_be,
                    column_config={
                        "Tipo_BIM": st.column_config.SelectboxColumn(
                            "Tipo Físico",
                            options=["Quadro Geral", "Luminária", "Caixa 4x2", "Caixa 4x4"]
                        ),
                        "Equipamento_Associado": st.column_config.SelectboxColumn(
                            "Carga (Biblioteca)",
                            options=opcoes_eq_elet
                        ),
                        "Amperagem_Tomadas": st.column_config.SelectboxColumn(
                            "Amperagem",
                            options=["10A", "20A"]
                        ),
                        "Tensao_V": st.column_config.SelectboxColumn(
                            "Tensão (V)",
                            options=[127, 220]
                        ),
                        "Qtd_Tomadas": st.column_config.NumberColumn("Qtd Tomadas", min_value=0, max_value=4),
                        "Qtd_Interruptores": st.column_config.NumberColumn("Qtd Interruptores", min_value=0, max_value=6)
                    },
                    use_container_width=True,
                    hide_index=True,
                    key=f"editor_elet_v{st.session_state.get('sync_version', 0)}"
                )

                st.markdown("**🔗 Painel de Comandos (Interruptores Simples, Paralelos Three-Way e Four-Way)**")
                opcoes_luminarias = df_editado_elet[df_editado_elet['Tipo_BIM'] == 'Luminária']['ID_CAD'].tolist()
                for idx, row in df_editado_elet.iterrows():
                    if 'Caixa' in row['Tipo_BIM'] and row['Qtd_Interruptores'] > 0:
                        selecionadas = st.multiselect(f"🔌 Caixa {row['ID_CAD']} controla:", options=opcoes_luminarias, key=f"ms_{row['ID_CAD']}")
                        df_editado_elet.at[idx, 'Luminarias_Controladas'] = ",".join(selecionadas)
            else:
                st.warning("Nenhum bloco elétrico detectado nas layers selecionadas.")
                df_editado_elet = pd.DataFrame()

        with col_t2:
            st.subheader("💧 Equipamentos Hidráulicos, Pluviais e Gás")
            df_bh = pd.DataFrame(blocos_hidro) if blocos_hidro else pd.DataFrame(columns=["ID_CAD", "Nome_Bloco", "x", "y", "z_base", "Andar", "pe_direito", "Tipo_BIM", "Equipamento", "z_relativo"])
            
            if not df_bh.empty:
                opcoes_equip = list(st.session_state.bib_hidro['Equipamento'])
                tipos_bim_h, equips_h, z_rel_h = [], [], []

                # Classificação automática linha a linha pelo Nome_Bloco + Layer
                for _, r_h in df_bh.iterrows():
                    tb_h, eq_h, zr_h = classificar_bloco_hidro_inteligente(
                        r_h['Nome_Bloco'], r_h.get('Layer_CAD', ''), opcoes_equip
                    )
                    tipos_bim_h.append(tb_h)
                    equips_h.append(eq_h)
                    z_rel_h.append(zr_h)

                df_bh['Tipo_BIM'] = tipos_bim_h
                df_bh['Equipamento'] = equips_h
                df_bh['z_relativo'] = z_rel_h

                # Ferramenta rápida para mapear em lote blocos anônimos repetidos (*U63, *U65, etc.)
                nomes_unicos_blocos = sorted(df_bh['Nome_Bloco'].unique().tolist())
                with st.expander("🪄 Mapeamento em Lote por Nome_Bloco (Ideal para blocos *U63, *U65...)", expanded=False):
                    st.caption("Se um bloco anônimo do CAD repetir várias vezes, vincule-o abaixo para atualizar todas as linhas dele de uma só vez:")
                    dict_map_lote = st.session_state.get("mapa_blocos_hidro", {})
                    cm1, cm2, cm3 = st.columns([1.5, 2, 1])
                    bloco_alvo = cm1.selectbox("Bloco do CAD:", nomes_unicos_blocos, key="sel_blk_lote")
                    eq_alvo = cm2.selectbox("Associar ao Equipamento:", opcoes_equip, key="sel_eq_lote")
                    func_alvo = cm3.selectbox("Função BIM:", ["Aparelho Hidráulico", "Prumada Água Fria", "Prumada Esgoto", "Caixa d'Água"], key="sel_fn_lote")
                    if st.button("✅ Aplicar a todos os blocos deste tipo", use_container_width=True):
                        dict_map_lote[bloco_alvo] = (func_alvo, eq_alvo)
                        st.session_state["mapa_blocos_hidro"] = dict_map_lote

                    for blk_k, (fn_v, eq_v) in dict_map_lote.items():
                        mask_b = df_bh['Nome_Bloco'] == blk_k
                        df_bh.loc[mask_b, 'Tipo_BIM'] = fn_v
                        df_bh.loc[mask_b, 'Equipamento'] = eq_v
                
                # --- TABELA HIDRÁULICA (FECHAMENTO CORRETO DE PARÊNTESES) ---
                df_bh, stats_hd = mesclar_blocos_com_memoria(df_bh, disciplina="hidro")

                df_editado_hidro = st.data_editor(
                    df_bh,
                    column_config={
                        "Tipo_BIM": st.column_config.SelectboxColumn(
                            "Função BIM",
                            options=[
                                "Aparelho Hidráulico",
                                "Ramal de Descarga",
                                "Ramal de Esgoto",
                                "Tubo de Queda Água Fria",
                                "Coluna de Subida Água Fria",
                                "Prumada Água Fria",
                                "Boiler / Aquecedor",
                                "Tubo de Queda Água Quente",
                                "Coluna de Subida Água Quente",
                                "Prumada Esgoto",
                                "Caixa de Inspeção / Destino Esgoto",
                                "Caixa d'Água"
                            ]
                        ),
                        "Equipamento": st.column_config.SelectboxColumn(
                            "Eq. (Biblioteca)",
                            options=opcoes_equip
                        )
                    },
                    use_container_width=True,
                    hide_index=True,
                    key=f"editor_hidro_v{st.session_state.get('sync_version', 0)}"
                )

                salvar_edicoes_na_memoria(
                    df_editado_elet if 'df_editado_elet' in locals() else pd.DataFrame(),
                    df_editado_hidro
                )
                if st.session_state.get("disparou_sync"):
                    st.session_state["resumo_ultimo_sync"] = (
                        f"✅ Sync: {stats_hd['mantidos']} mantidos | "
                        f"{stats_hd['movidos']} reposicionados | "
                        f"{stats_hd['novos']} novos | "
                        f"{stats_hd['removidos']} removidos"
                    )
                    st.toast(st.session_state["resumo_ultimo_sync"], icon="🔄")
                    st.session_state["disparou_sync"] = False
                
                tem_caixa = not df_editado_hidro[df_editado_hidro['Tipo_BIM'] == 'Caixa d\'Água'].empty
                if tem_caixa:
                    st.markdown("**🚰 Parâmetros da Caixa d'Água 3D**")
                    c_cx1, c_cx2 = st.columns(2)
                    altura_caixa = c_cx1.number_input("Altura acima da última laje (m)", min_value=0.5, value=1.5, step=0.1)
                    num_barriletes = c_cx2.number_input("Nº de Barriletes", min_value=1, value=1, step=1)
                else:
                    altura_caixa = 1.5
                    num_barriletes = 1
            else:
                st.warning("Nenhum bloco hidrossanitário detectado nas layers selecionadas.")
                df_editado_hidro = pd.DataFrame()
                altura_caixa = 1.5
                num_barriletes = 1

        st.divider()
        col_btn_proc, col_tog1, col_tog2 = st.columns([2, 1, 1])
        with col_tog1:
            mostrar_tubos = st.toggle("Ver Tubos / Eletrodutos 3D", value=True)
        with col_tog2:
            mostrar_fios = st.toggle("Ver Rótulos de Fios 3D (F N T / 2R)", value=True)

        if col_btn_proc.button("🚀 Processar Rotas Multidisciplinares, Dimensionamento ABNT e Quantitativos", type="primary", use_container_width=True):
            with st.spinner("Mapeando vigas, pilares, múltiplas prumadas, cascata TUG e calculando malhas ABNT..."):
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
                    if b['Tipo_BIM'] == 'Caixa d\'Água':
                        b['z_base'] = z_cobertura

                st.session_state.contexto_bim = {
                    'paredes': paredes_raw, 'elementos_arquitetonicos': elementos_arquitetonicos,
                    'df_eletrica': df_editado_elet.to_dict('records') if not df_editado_elet.empty else [],
                    'df_hidro': df_h_processar, 'min_x': min_x, 'min_y': min_y, 'offset': offset,
                    'grid_w': grid_w, 'grid_h': grid_h, 'pe_direito': ultimo_pe_direito,
                    'max_z_cobertura': z_cobertura, 'altura_caixa': altura_caixa, 'num_barriletes': num_barriletes,
                    'h_agua_fria': h_agua_fria, 'h_agua_quente': h_agua_quente, 'altura_viga': altura_viga,
                    'incluir_shaft': incluir_shaft, 'rotear_em_cascata': rotear_em_cascata
                }

                ctx = st.session_state.contexto_bim
                linhas_hidro = rotear_hidro(ctx['df_hidro'], ctx) if modo_visualizacao != "Apenas Elétrica" else []
                linhas_elet = rotear_eletrica(ctx['df_eletrica'], ctx) if modo_visualizacao != "Apenas Hidrossanitário" else []
                st.session_state.linhas_3d_master = {'eletrica': linhas_elet, 'hidro': linhas_hidro, 'equipamentos_3d': pontos_gerais}
                st.session_state.colisoes_detectadas = []

                # Geração Inteligente do Quadro de Cargas (Agrupando TUGs/Iluminação por Pavimento ou Individual)
                novos_circuitos = []
                grupos_agrupados = {}
                for b_el in ctx['df_eletrica']:
                    if b_el['Tipo_BIM'] == 'Quadro Geral': continue
                    eq_nome = b_el.get('Equipamento_Associado', 'Tomada Uso Geral (TUG)')
                    filtro_el = st.session_state.bib_eletrica['Equipamento'] == eq_nome
                    if filtro_el.any():
                        row_bib = st.session_state.bib_eletrica.loc[filtro_el].iloc[0]
                        pot_unit, tensao_eq, fp_eq, tipo_eq, curva_eq, uso_dr = float(row_bib['Potência (W)']), int(b_el.get('Tensao_V', row_bib['Tensão (V)'])), float(row_bib['Fator de Potência']), str(row_bib['Tipo']), str(row_bib['Curva Disjuntor']), str(row_bib['Uso de DR'])
                    else:
                        pot_unit, tensao_eq, fp_eq, tipo_eq, curva_eq, uso_dr = 100.0, 127, 1.0, "TUG", "B", "Opcional"

                    if b_el.get('Amperagem_Tomadas') == '20A' and pot_unit == 100.0: pot_unit = 600.0
                    qtd_pts = max(1, int(b_el.get('Qtd_Tomadas', 1))) if 'Caixa' in b_el['Tipo_BIM'] else 1
                    pot_total = pot_unit * qtd_pts
                    rota_assoc = next((r for r in linhas_elet if r.get('id_origem') == b_el['ID_CAD']), None)
                    dist_circ = rota_assoc['comprimento_m'] if rota_assoc else 15.0
                    andar_str = b_el.get('Andar', 'Pav 0')

                    if agrupar_tugs_circuito and tipo_eq in ["Iluminação", "TUG"] and pot_total <= 1200:
                        chave_g = (andar_str, tipo_eq, tensao_eq, uso_dr)
                        if chave_g not in grupos_agrupados or (grupos_agrupados[chave_g]["pot"] + pot_total) > (1200 if tensao_eq == 127 else 2200):
                            grupos_agrupados[chave_g] = {"pot": pot_total, "qtd": qtd_pts, "dist": dist_circ, "fp": fp_eq, "curva": curva_eq, "eq": f"Circuito {tipo_eq} ({andar_str})"}
                            novos_circuitos.append({"_ref_dict": grupos_agrupados[chave_g], "andar": andar_str, "tipo": tipo_eq, "tensao": tensao_eq, "dr": uso_dr})
                        else:
                            grupos_agrupados[chave_g]["pot"] += pot_total
                            grupos_agrupados[chave_g]["qtd"] += qtd_pts
                            grupos_agrupados[chave_g]["dist"] = max(grupos_agrupados[chave_g]["dist"], dist_circ)
                    else:
                        novos_circuitos.append({
                            "_ref_dict": {"pot": pot_total, "qtd": qtd_pts, "dist": dist_circ, "fp": fp_eq, "curva": curva_eq, "eq": f"{eq_nome} ({b_el['ID_CAD']})"},
                            "andar": andar_str, "tipo": tipo_eq, "tensao": tensao_eq, "dr": uso_dr
                        })

                circuitos_finais = []
                for idx_c, item_c in enumerate(novos_circuitos):
                    d_ref = item_c["_ref_dict"]
                    dim_5410 = dimensionar_circuito_nbr5410(d_ref["pot"], item_c["tensao"], d_ref["fp"], "B1", 0.80, 1.00, d_ref["dist"], item_c["tipo"])
                    circuitos_finais.append({
                        "ID": f"C{idx_c+1}", "Ambiente": item_c["andar"], "Equipamento": d_ref["eq"],
                        "Qtd": d_ref["qtd"], "Potência Total (W)": d_ref["pot"], "Tensão (V)": item_c["tensao"],
                        "Fator de Potência": d_ref["fp"], "Método Inst.": "B1",
                        "Eletroduto (Ref)": f"Eletroduto {item_c['andar']} - {'Teto' if item_c['tipo']=='Iluminação' else 'Parede'}",
                        "FCA": 0.80, "FCT": 1.00, "Corrente (A)": dim_5410["Corrente_Ib"],
                        "Corrente Corrigida (A)": dim_5410["Corrente_Corr"], "Bitola (mm²)": dim_5410["Bitola"],
                        "Queda Tensão (%)": dim_5410["Queda_Tensao_Pct"], "Disjuntor (A)": dim_5410["Disjuntor"],
                        "Curva": d_ref["curva"], "Icc (A)": dim_5410["Icc_A"], "Distância (m)": d_ref["dist"],
                        "Fase": "R", "Grupo DR": "DR 1 (Áreas Molhadas)" if item_c["dr"] == "Obrigatório" else "DR 2 (Geral)",
                        "Eletroduto (mm)": dim_5410["Eletroduto_mm"], "Ocupação (%)": dim_5410["Ocupacao_Pct"]
                    })
                if circuitos_finais:
                    st.session_state.circuitos = balancear_fases_automatico(pd.DataFrame(circuitos_finais))

                novos_pontos_hidro = []
                z_res_mca = z_cobertura + altura_caixa
                for b_hd in ctx['df_hidro']:
                    if b_hd['Tipo_BIM'] not in ['Aparelho Hidráulico', 'Ramal de Descarga', 'Ramal de Esgoto']: continue
                    eq_h = b_hd['Equipamento']
                    filtro_h = st.session_state.bib_hidro['Equipamento'] == eq_h
                    if not filtro_h.any(): continue
                    row_h = st.session_state.bib_hidro.loc[filtro_h].iloc[0]
                    peso_h, uhc_h, af_mm, esg_mm, pressao_req_kpa = float(row_h['Peso']), float(row_h['UHC']), int(row_h['Agua_mm']), int(row_h['Esgoto_mm']), float(row_h['Pressao_kpa'])
                    rota_af = next((r for r in linhas_hidro if r.get('id_ap') == b_hd['ID_CAD'] and r.get('tipo') == 'Água Fria'), None)
                    comp_real_af = rota_af.get('comp_acumulado_total_m', calcular_comprimento_rota(rota_af['pontos'])) if rota_af else 8.0
                    j90_reais = rota_af.get('j90_acumulados', 2) if rota_af else 2
                    tes_reais = rota_af.get('tes_acumulados', 1) if rota_af else 1
                    vazao_ls, _, comp_eq, perda_mca = calcular_perda_carga_nbr5626(peso_h, max(20, af_mm), comp_real_af, qtd_joelhos90=j90_reais, qtd_tes=tes_reais)
                    z_ponto = b_hd['z_base'] + b_hd.get('z_relativo', 0.5)
                    pressao_estatica_mca = max(1.5, z_res_mca - z_ponto)
                    pressao_disp_mca = max(0.0, pressao_estatica_mca - perda_mca)
                    pressao_disp_kpa = round(pressao_disp_mca * 9.81, 1)

                    if pressao_disp_kpa < pressao_req_kpa: status_pressao = "⚠️ Pressurizar! (< Mín.)"
                    elif pressao_estatica_mca > 40.0: status_pressao = "⚠️ Instalar VRP (> 40 m.c.a.)"
                    else: status_pressao = "OK (NBR 5626)"

                    novos_pontos_hidro.append({
                        "ID": b_hd['ID_CAD'], "Andar": b_hd.get('Andar', 'Pav 0'), "Ambiente": b_hd.get('Andar', 'Banheiro/Cozinha'),
                        "Equipamento": eq_h, "z": round(z_ponto, 2), "Peso (NBR 5626)": peso_h, "Vazão (L/s)": vazao_ls,
                        "Tubo AF (mm)": af_mm, "L Real + Eq (m)": round(comp_real_af + comp_eq, 2), "Perda Carga (m.c.a.)": perda_mca,
                        "Pressão Estática (m.c.a.)": round(pressao_estatica_mca, 1), "Pressão Disp. (kPa)": pressao_disp_kpa,
                        "Pressão Mín. (kPa)": pressao_req_kpa, "Status Pressão": status_pressao,
                        "UHC": uhc_h, "Tubo Esgoto (mm)": esg_mm, "Declividade Esg. (%)": 1.0 if esg_mm >= 100 else (2.0 if esg_mm > 0 else 0.0)
                    })
                st.session_state.pontos_hidro = novos_pontos_hidro
                st.session_state.quantitativos_master = gerar_quantitativos_totais_bim(linhas_elet, linhas_hidro, st.session_state.circuitos, ctx['df_eletrica'], ctx['df_hidro'])
                st.success("✅ Roteamento 3D (DXF/IFC), Múltiplas Prumadas, Cascata TUG e Quantitativos concluídos!")

        if st.session_state.linhas_3d_master['eletrica'] or st.session_state.linhas_3d_master['hidro'] or paredes_raw:
            metragem_el = sum(calcular_comprimento_rota(r['pontos']) for r in st.session_state.linhas_3d_master['eletrica'])
            metragem_hd = sum(calcular_comprimento_rota(r['pontos']) for r in st.session_state.linhas_3d_master['hidro'])
            df_el_ctx = st.session_state.contexto_bim.get('df_eletrica', [])
            cb1, cb2, cb3, cb4 = st.columns(4)
            cb1.metric("Eletroduto Total", f"{metragem_el:.1f} m")
            cb2.metric("Tubulação Hidrossanitária", f"{metragem_hd:.1f} m")
            cb3.metric("Caixas 4x2 / 4x4", sum(1 for b in df_el_ctx if 'Caixa' in b.get('Tipo_BIM', '')))
            cb4.metric("Pontos de Iluminação", sum(1 for b in df_el_ctx if b.get('Tipo_BIM') == 'Luminária'))

            fig = go.Figure()

            # Filtra linhas espúrias (como margens de folha CAD distantes dos blocos) para focar 100% na edificação
            pts_ref_x = [b['x'] for b in (blocos_elet + blocos_hidro)]
            pts_ref_y = [b['y'] for b in (blocos_elet + blocos_hidro)]
            if pts_ref_x and pts_ref_y:
                lim_x_min, lim_x_max = min(pts_ref_x) - 12.0, max(pts_ref_x) + 12.0
                lim_y_min, lim_y_max = min(pts_ref_y) - 12.0, max(pts_ref_y) + 12.0
                paredes_filtradas = [
                    (p1, p2) for (p1, p2) in paredes_raw
                    if (lim_x_min <= p1[0] <= lim_x_max and lim_y_min <= p1[1] <= lim_y_max)
                    and (lim_x_min <= p2[0] <= lim_x_max and lim_y_min <= p2[1] <= lim_y_max)
                    and dist_2d(p1, p2) <= 25.0
                ]
                if not paredes_filtradas:
                    paredes_filtradas = paredes_raw
            else:
                paredes_filtradas = paredes_raw

            # 1. PAREDES 3D EM MODO RAIO-X (Faces 3D translúcidas + Arestas escuras nítidas no piso e topo)
            wx_base, wy_base, wz_base = [], [], []
            wx_topo, wy_topo, wz_topo = [], [], []
            mesh_x, mesh_y, mesh_z = [], [], []
            mesh_i, mesh_j, mesh_k = [], [], []

            for p1, p2 in paredes_filtradas:
                if dist_2d(p1, p2) < 0.05:
                    continue
                z_piso = p1[2]
                z_topo = p2[2] if p2[2] > z_piso else (z_piso + 3.0)

                # Planta baixa nítida no piso (chumbo escuro) para leitura imediata dos cômodos
                wx_base.extend([p1[0], p2[0], None])
                wy_base.extend([p1[1], p2[1], None])
                wz_base.extend([z_piso, z_piso, None])

                # Arestas superiores e verticais suaves (Wireframe 3D)
                wx_topo.extend([p1[0], p2[0], None, p1[0], p1[0], None, p2[0], p2[0], None])
                wy_topo.extend([p1[1], p2[1], None, p1[1], p1[1], None, p2[1], p2[1], None])
                wz_topo.extend([z_topo, z_topo, None, z_piso, z_topo, None, z_piso, z_topo, None])

                # Face 3D translúcida da parede (efeito vidro/raio-X)
                idx_v = len(mesh_x)
                mesh_x.extend([p1[0], p2[0], p2[0], p1[0]])
                mesh_y.extend([p1[1], p2[1], p2[1], p1[1]])
                mesh_z.extend([z_piso, z_piso, z_topo, z_topo])
                mesh_i.extend([idx_v, idx_v])
                mesh_j.extend([idx_v + 1, idx_v + 2])
                mesh_k.extend([idx_v + 2, idx_v + 3])

            if mesh_x:
                fig.add_trace(go.Mesh3d(
                    x=mesh_x, y=mesh_y, z=mesh_z,
                    i=mesh_i, j=mesh_j, k=mesh_k,
                    color='#94a3b8', opacity=0.18,
                    name='🏢 Paredes 3D (Faces Raio-X)',
                    legendgroup='paredes_3d', showlegend=True, hoverinfo='skip'
                ))
            if wx_base:
                fig.add_trace(go.Scatter3d(
                    x=wx_base, y=wy_base, z=wz_base, mode='lines',
                    line=dict(color='#1e293b', width=3.5),
                    name='📐 Contorno das Paredes (Base)',
                    legendgroup='paredes_base', showlegend=True, hoverinfo='skip'
                ))
            if wx_topo:
                fig.add_trace(go.Scatter3d(
                    x=wx_topo, y=wy_topo, z=wz_topo, mode='lines',
                    line=dict(color='rgba(71, 85, 105, 0.45)', width=1.5),
                    name='🏢 Paredes 3D (Wireframe Superior)',
                    legendgroup='paredes_wire', showlegend=True, hoverinfo='skip'
                ))

            # 2. VÃOS DE PORTAS, JANELAS E PILARES (Filtrados dentro do perímetro da edificação)
            px_porta, py_porta, pz_porta = [], [], []
            jx_jan, jy_jan, jz_jan = [], [], []
            ex_est, ey_est, ez_est = [], [], []

            for elem in elementos_arquitetonicos:
                if pts_ref_x and not (lim_x_min <= elem['x'] <= lim_x_max and lim_y_min <= elem['y'] <= lim_y_max):
                    continue
                if elem['Tipo'] == 'Pilar/Viga':
                    h_pilar = elem.get('pe_direito', 3.0)
                    ex_est.extend([elem['x'], elem['x'], None])
                    ey_est.extend([elem['y'], elem['y'], None])
                    ez_est.extend([elem['z_base'], elem['z_base'] + h_pilar, None])
                elif elem['Tipo'] == 'Esquadria':
                    z_piso_e = elem['z_base']
                    z_teto_e = z_piso_e + elem.get('pe_direito', 3.0)
                    z_inf = z_piso_e + elem.get('Peitoril', 0.0)
                    z_sup = min(z_teto_e, z_inf + elem.get('Altura', 2.10))
                    larg_v = min(2.40, elem.get('Largura', 0.90))
                    p1_v = elem.get('p1_vao', (elem['x'] - larg_v/2.0, elem['y']))
                    p2_v = elem.get('p2_vao', (elem['x'] + larg_v/2.0, elem['y']))

                    # 1. Desenha o quadro 3D do vão (Porta ou Janela) na altura exata configurada
                    quadro_x = [p1_v[0], p2_v[0], p2_v[0], p1_v[0], p1_v[0], None]
                    quadro_y = [p1_v[1], p2_v[1], p2_v[1], p1_v[1], p1_v[1], None]
                    quadro_z = [z_inf,   z_inf,   z_sup,   z_sup,   z_inf,   None]

                    if elem.get('Subtipo') == 'Porta':
                        px_porta.extend(quadro_x)
                        py_porta.extend(quadro_y)
                        pz_porta.extend(quadro_z)
                    else:
                        jx_jan.extend(quadro_x)
                        jy_jan.extend(quadro_y)
                        jz_jan.extend(quadro_z)

                    # 2. Preenche a parede 3D Raio-X ABAIXO DO PEITORIL (se Peitoril > 0)
                    if z_inf > z_piso_e + 0.05:
                        idx_v = len(mesh_x)
                        mesh_x.extend([p1_v[0], p2_v[0], p2_v[0], p1_v[0]])
                        mesh_y.extend([p1_v[1], p2_v[1], p2_v[1], p1_v[1]])
                        mesh_z.extend([z_piso_e, z_piso_e, z_inf, z_inf])
                        mesh_i.extend([idx_v, idx_v])
                        mesh_j.extend([idx_v + 1, idx_v + 2])
                        mesh_k.extend([idx_v + 2, idx_v + 3])

                    # 3. Preenche a parede 3D Raio-X ACIMA DA PORTA/JANELA (Verga até o teto)
                    if z_sup < z_teto_e - 0.05:
                        idx_v2 = len(mesh_x)
                        mesh_x.extend([p1_v[0], p2_v[0], p2_v[0], p1_v[0]])
                        mesh_y.extend([p1_v[1], p2_v[1], p2_v[1], p1_v[1]])
                        mesh_z.extend([z_sup, z_sup, z_teto_e, z_teto_e])
                        mesh_i.extend([idx_v2, idx_v2])
                        mesh_j.extend([idx_v2 + 1, idx_v2 + 2])
                        mesh_k.extend([idx_v2 + 2, idx_v2 + 3])

            if px_porta:
                fig.add_trace(go.Scatter3d(
                    x=px_porta, y=py_porta, z=pz_porta, mode='lines',
                    line=dict(color='#d97706', width=3),
                    name='🚪 Vãos de Porta (3D)', legendgroup='portas'
                ))
            if jx_jan:
                fig.add_trace(go.Scatter3d(
                    x=jx_jan, y=jy_jan, z=jz_jan, mode='lines',
                    line=dict(color='#0284c7', width=3),
                    name='🪟 Vãos de Janela (3D)', legendgroup='janelas'
                ))
            if ex_est:
                fig.add_trace(go.Scatter3d(
                    x=ex_est, y=ey_est, z=ez_est, mode='lines',
                    line=dict(color='#334155', width=6),
                    name='🧱 Pilares / Vigas (3D)', legendgroup='pilares'
                ))

            # 3. REDES ELÉTRICAS E HIDROSSANITÁRIAS COM LEGENDA AGRUPADA (SEM REPETIÇÕES!)
            grupos_legenda_usados = set()

            if modo_visualizacao in ["Unificado (Elétrica + Hidráulica)", "Apenas Elétrica"]:
                for linha in st.session_state.linhas_3d_master['eletrica']:
                    pts = linha['pontos']
                    fios_txt = linha.get('fios', 'F N T')
                    nome_grp = "⚡ Eletrodutos e Circuitos"
                    mostrar_leg = nome_grp not in grupos_legenda_usados
                    grupos_legenda_usados.add(nome_grp)
                    if mostrar_tubos:
                        fig.add_trace(go.Scatter3d(
                            x=[p[0] for p in pts], y=[p[1] for p in pts], z=[p[2] for p in pts],
                            mode='lines+markers', marker=dict(size=3),
                            line=dict(color=linha['cor'], width=5),
                            name=nome_grp, legendgroup='rede_eletrica', showlegend=mostrar_leg,
                            hovertext=f"Elétrica ({fios_txt}) - L={linha.get('comprimento_m',0)}m", hoverinfo="text"
                        ))
                    if mostrar_fios and len(pts) >= 2:
                        p_mid = pts[len(pts) // 2]
                        fig.add_trace(go.Scatter3d(
                            x=[p_mid[0]], y=[p_mid[1]], z=[p_mid[2] + 0.15],
                            mode='text', text=[fios_txt], textposition="top center",
                            textfont=dict(color="black", size=11, family="Arial Black"),
                            legendgroup='rede_eletrica', showlegend=False
                        ))

            if modo_visualizacao in ["Unificado (Elétrica + Hidráulica)", "Apenas Hidrossanitário"]:
                for linha in st.session_state.linhas_3d_master['hidro']:
                    pts = linha['pontos']
                    tipo_raw = str(linha.get('tipo', 'Hidro'))
                    dn_val = linha.get('diametro', 25)
                    if 'Água Fria' in tipo_raw or 'AF' in tipo_raw or 'Barrilete' in tipo_raw:
                        grp_id, nome_grp = 'hidro_af', '💧 Água Fria (Tubulação)'
                    elif 'Água Quente' in tipo_raw or 'AQ' in tipo_raw:
                        grp_id, nome_grp = 'hidro_aq', '🔥 Água Quente (Tubulação)'
                    elif 'Ventilação' in tipo_raw:
                        grp_id, nome_grp = 'hidro_vent', '🟢 Ventilação Sanitária'
                    else:
                        grp_id, nome_grp = 'hidro_esg', '🤎 Esgoto Sanitário e Descarga'

                    mostrar_leg = grp_id not in grupos_legenda_usados
                    grupos_legenda_usados.add(grp_id)
                    if mostrar_tubos:
                        fig.add_trace(go.Scatter3d(
                            x=[p[0] for p in pts], y=[p[1] for p in pts], z=[p[2] for p in pts],
                            mode='lines+markers', marker=dict(size=3),
                            line=dict(color=linha['cor'], width=6),
                            name=nome_grp, legendgroup=grp_id, showlegend=mostrar_leg,
                            hovertext=f"{tipo_raw} (DN {dn_val}mm)", hoverinfo="text"
                        ))

            if df_el_ctx:
                fig.add_trace(go.Scatter3d(
                    x=[b['x'] for b in df_el_ctx], y=[b['y'] for b in df_el_ctx], z=[b['z_base'] + b.get('z_relativo', 1.3) for b in df_el_ctx],
                    mode='markers',
                    hovertext=[f"{b['ID_CAD']} ({b.get('Nome_Bloco','')} | z: {b['z_base']+b.get('z_relativo',1.3):.2f}m)" for b in df_el_ctx],
                    hoverinfo="text",
                    marker=dict(size=6, color=['red' if 'Quadro' in b['Tipo_BIM'] else 'gold' if 'Luminária' in b['Tipo_BIM'] else 'green' for b in df_el_ctx]),
                    name="🔌 Pontos Elétricos"
                ))

            df_h_proc = st.session_state.contexto_bim.get('df_hidro', [])
            if df_h_proc:
                fig.add_trace(go.Scatter3d(
                    x=[b['x'] for b in df_h_proc], y=[b['y'] for b in df_h_proc], z=[b['z_base'] + b.get('z_relativo', 0.5) for b in df_h_proc],
                    mode='markers',
                    hovertext=[f"{b['Nome_Bloco']} -> {b['Equipamento']} ({b['Tipo_BIM']})" for b in df_h_proc],
                    hoverinfo="text",
                    marker=dict(size=5, color='#0ea5e9', symbol='circle'),
                    name="🚰 Pontos Hidrossanitários"
                ))
            cx_box = next((b for b in df_h_proc if b['Tipo_BIM'] == 'Caixa d\'Água'), None)
            if cx_box:
                fig.add_trace(go.Scatter3d(
                    x=[cx_box['x']], y=[cx_box['y']], z=[cx_box['z_base'] + st.session_state.contexto_bim.get('altura_caixa', 1.5)],
                    mode='markers', marker=dict(size=18, color='#1d4ed8', symbol='square'), name='🟦 Caixa d\'Água Superior'
                ))

            fig.update_layout(
                scene=dict(
                    aspectmode='data',
                    bgcolor='#f8fafc',
                    xaxis=dict(title='X (m)', backgroundcolor='#f1f5f9', gridcolor='#cbd5e1'),
                    yaxis=dict(title='Y (m)', backgroundcolor='#f1f5f9', gridcolor='#cbd5e1'),
                    zaxis=dict(title='Z (m)', backgroundcolor='#e2e8f0', gridcolor='#cbd5e1')
                ),
                legend=dict(
                    title=dict(text="Camadas 3D (Clique p/ Ocultar):", font=dict(color="#ffffff", size=13)),
                    bgcolor="rgba(0, 0, 0, 0.90)",
                    bordercolor="#475569",
                    borderwidth=1,
                    font=dict(color="#ffffff", size=12),
                    y=0.92,
                    yanchor="top"
                ),
                height=780, margin=dict(l=0, r=0, b=0, t=0)
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Suba os arquivos DXF ou IFC das plantas/maquetes na barra lateral para iniciar a coordenação.")

with tab_clash:
    st.subheader("Verificação de Interferências (Hard & Soft Clash) e Avoidance")
    if st.button("🔍 Rodar Verificação de Colisões", type="primary"):
        if st.session_state.linhas_3d_master['eletrica'] and st.session_state.linhas_3d_master['hidro']:
            st.session_state.colisoes_detectadas = checar_clash_detection(st.session_state.linhas_3d_master['eletrica'], st.session_state.linhas_3d_master['hidro'], 0.15)
            if not st.session_state.colisoes_detectadas: st.success("✅ O Projeto está limpo! Nenhuma interferência entre Elétrica e Hidráulica.")
        else: st.warning("Processe as rotas primeiro na aba BIM 3D.")
    if st.session_state.colisoes_detectadas:
        st.error(f"⚠️ Foram detectados {len(st.session_state.colisoes_detectadas)} pontos de colisão na malha 3D!")
        st.dataframe(pd.DataFrame(st.session_state.colisoes_detectadas), use_container_width=True)
        if st.button("🛡️ Evitar Colisões Automaticamente (Re-rotear Elétrica)", type="primary"):
            ctx = st.session_state.contexto_bim
            st.session_state.linhas_3d_master['eletrica'] = rotear_eletrica(ctx['df_eletrica'], ctx, evitar_linhas=st.session_state.linhas_3d_master['hidro'])
            st.session_state.colisoes_detectadas = []
            st.success("✅ Evasão concluída! Verifique o modelo 3D (aba anterior).")
            st.rerun()
# ==============================================================================
# PARTE 10 DE 10: ABAS 3, 4, 5 E 6 (ELÉTRICA, HIDRO/PLUVIAL/GÁS, PEÇAS E BIBLIOTECAS)
# ==============================================================================
with tab_eletrica:
    st.title("⚡ Engenharia Elétrica Executiva (NBR 5410 + PRODIST + V12)")

    with st.expander("📏 Validação Normativa 1: Auditoria de Pontos Mínimos por Área e Perímetro dos Cômodos (NBR 5410 - Item 9.5.2)", expanded=False):
        df_amb_edit = st.data_editor(
            st.session_state.auditoria_ambientes,
            column_config={
                "Tipo Cômodo (NBR 5410)": st.column_config.SelectboxColumn(
                    "Classificação NBR 5410",
                    options=["Sala / Dormitório", "Cozinha / Copa / Área de Serviço", "Banheiro", "Varanda / Garagem / Sótão"]
                ),
                "Área (m²)": st.column_config.NumberColumn("Área (m²)", min_value=1.0, step=0.5),
                "Perímetro (m)": st.column_config.NumberColumn("Perímetro (m)", min_value=2.0, step=0.5)
            },
            num_rows="dynamic", use_container_width=True
        )
        st.session_state.auditoria_ambientes = df_amb_edit
        if not df_amb_edit.empty:
            df_res_aud = pd.DataFrame([
                auditar_ambiente_nbr5410(r.get("Ambiente", f"Amb {i+1}"), r.get("Tipo Cômodo (NBR 5410)", "Sala / Dormitório"), float(r.get("Área (m²)", 10.0)), float(r.get("Perímetro (m)", 12.0)))
                for i, r in df_amb_edit.iterrows()
            ])
            st.dataframe(df_res_aud, use_container_width=True, hide_index=True)

    df_circ = st.session_state.circuitos
    if not df_circ.empty:
        pot_instalada = pd.to_numeric(df_circ['Potência Total (W)'], errors='coerce').fillna(0).sum()
        pot_it, pot_tue, demanda_est, fd_it, fd_tue = calcular_demanda_escalonada_prodist(df_circ)
        tensao_alim = 220 if ("Trifásico" in sistema_fornecimento or "Bifásico" in sistema_fornecimento) else tensao_fase
        fator_fases = 1.732 if "Trifásico" in sistema_fornecimento else 1.0
        corrente_geral = demanda_est / (tensao_alim * fator_fases) if tensao_alim > 0 else 0.0
        disj_geral = calcular_disjuntor(corrente_geral, 125)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Potência Instalada Total", f"{pot_instalada:.0f} W")
        m2.metric("Demanda PRODIST Calculada", f"{demanda_est:.0f} W", f"FD Ilum/TUG: {fd_it*100:.0f}% | TUE: {fd_tue*100:.0f}%")
        m3.metric("Corrente do Alimentador", f"{corrente_geral:.1f} A")
        m4.metric("Disjuntor Geral QDG", f"{disj_geral} A")

        st.divider()
        st.subheader("⚖️ Balanceamento de Fases (R, S, T) e Ramal Alimentador (Medidor → QDG)")
        c_r, c_s, c_t = 0.0, 0.0, 0.0
        for _, r_f in df_circ.iterrows():
            f_str, i_val = str(r_f.get('Fase', 'R')), float(r_f.get('Corrente (A)', 0.0))
            if '+' in f_str:
                for p in f_str.split('+'):
                    if p == 'R': c_r += i_val / 2.0
                    elif p == 'S': c_s += i_val / 2.0
                    elif p == 'T': c_t += i_val / 2.0
            else:
                if f_str == 'R': c_r += i_val
                elif f_str == 'S': c_s += i_val
                elif f_str == 'T': c_t += i_val

        cf1, cf2, cf3 = st.columns(3)
        cf1.metric("Corrente Fase R", f"{c_r:.1f} A")
        cf2.metric("Corrente Fase S", f"{c_s:.1f} A")
        cf3.metric("Corrente Fase T", f"{c_t:.1f} A")

        col_mat, col_temp, col_dist = st.columns(3)
        material_alim = col_mat.selectbox("Material do Cabo Alimentador", ["Cobre", "Alumínio"])
        temp_alim = col_temp.selectbox("Isolação Térmica", ["70°C (PVC)", "90°C (EPR/XLPE)"])
        dist_alim = col_dist.number_input("Distância Medidor → QDG (m)", min_value=1.0, value=20.0, step=1.0)

        condutividade = 56.0 if material_alim == "Cobre" else 35.0
        res_alim = dimensionar_circuito_nbr5410(demanda_est, tensao_alim, 0.95, "B1", 1.0, 1.0, dist_alim, "TUE", material_alim, temp_alim)
        bitola_alim = max(6.0, res_alim["Bitola"])
        queda_v_alim = (fator_fases * dist_alim * corrente_geral * 0.95) / (condutividade * bitola_alim)
        queda_perc_alim = (queda_v_alim / tensao_alim) * 100.0 if tensao_alim > 0 else 0.0

        if queda_perc_alim <= 2.0:
            st.success(f"🔌 **Ramal Alimentador Recomendado:** Cabo de {material_alim} **{bitola_alim} mm²** ({temp_alim}) | **Queda no Alimentador:** {queda_perc_alim:.2f}% (OK ≤ 2.0% NBR 5410)")
        else:
            st.error(f"⚠️ **Ramal Alimentador:** {bitola_alim} mm² apresenta queda de **{queda_perc_alim:.2f}%** (> 2.0% NBR 5410). Aumente a seção do cabo de entrada!")

    st.divider()
    st.subheader("📋 Quadro Geral de Cargas, Curto-Circuito (Icc) e FCA Automático por Eletroduto")
    if st.button("🚀 Recalcular Fatores (FCA Automático por Eletroduto + Icc + Balanceamento R/S/T)", type="primary", use_container_width=True):
        if not st.session_state.circuitos.empty:
            df_calc = st.session_state.circuitos.copy()
            if 'Eletroduto (Ref)' not in df_calc.columns:
                df_calc['Eletroduto (Ref)'] = 'Eletroduto Geral'
            contagem_tubos = df_calc['Eletroduto (Ref)'].value_counts().to_dict()

            for idx, r in df_calc.iterrows():
                qtd_no_tubo = contagem_tubos.get(r.get('Eletroduto (Ref)', 'Eletroduto Geral'), 1)
                fca_auto = obter_fca(qtd_no_tubo)
                res = dimensionar_circuito_nbr5410(
                    float(r.get("Potência Total (W)", 100)),
                    int(r.get("Tensão (V)", 127)),
                    float(r.get("Fator de Potência", 0.95)),
                    str(r.get("Método Inst.", "B1")),
                    fca_auto,
                    float(r.get("FCT", 1.00)),
                    float(r.get("Distância (m)", 15.0)),
                    "Iluminação" if "Lâmpada" in str(r.get("Equipamento", "")) else "TUG"
                )
                df_calc.at[idx, "FCA"] = fca_auto
                df_calc.at[idx, "Corrente (A)"] = res["Corrente_Ib"]
                df_calc.at[idx, "Corrente Corrigida (A)"] = res["Corrente_Corr"]
                df_calc.at[idx, "Bitola (mm²)"] = res["Bitola"]
                df_calc.at[idx, "Queda Tensão (%)"] = res["Queda_Tensao_Pct"]
                df_calc.at[idx, "Disjuntor (A)"] = res["Disjuntor"]
                df_calc.at[idx, "Icc (A)"] = res["Icc_A"]
                df_calc.at[idx, "Eletroduto (mm)"] = res["Eletroduto_mm"]
                df_calc.at[idx, "Ocupação (%)"] = res["Ocupacao_Pct"]

            st.session_state.circuitos = balancear_fases_automatico(df_calc)
            st.success("✅ Engenharia reprocessada com FCA automático por eletroduto, corrente de curto-circuito (Icc) e fases equilibradas!")
            st.rerun()

    df_circ_edit = st.data_editor(st.session_state.circuitos, num_rows="dynamic", use_container_width=True)
    st.session_state.circuitos = df_circ_edit

    if not st.session_state.circuitos.empty:
        st.divider()
        st.subheader("🎛️ Montagem Física Visual do QDG (Pré-Visualização Trilho DIN)")
        df_q = st.session_state.circuitos
        if 'Grupo DR' not in df_q.columns:
            df_q['Grupo DR'] = 'DR 1 (Geral)'
        grupos_dr_usados = df_q[df_q['Grupo DR'] != 'Nenhum']['Grupo DR'].unique()
        qtd_drs = len(grupos_dr_usados)
        modulos_protecao = 2 + (qtd_drs * 4) + 2
        total_ocupado = modulos_protecao + len(df_q)
        espaco_reserva = max(2, math.ceil(total_ocupado * 0.25))
        caixa_ideal = next((c for c in [12, 18, 24, 36, 48, 72, 100] if c >= (total_ocupado + espaco_reserva)), 100)

        st.info(f"📦 **Caixa Recomendada:** Quadro Embutir para **{caixa_ideal} Módulos DIN** (Ocupados: {total_ocupado} | Reserva Técnica NBR 5410: {espaco_reserva})")

        html_caixa = """
        <div style="background-color: #e0e0e0; padding: 20px; border-radius: 10px; border: 2px solid #9e9e9e; max-width: 850px; margin: auto;">
            <div style="background-color: #d5d5d5; padding: 10px; margin-bottom: 18px; display: flex; gap: 6px; flex-wrap: wrap; border-radius: 6px;">
                <div style="background-color: #f44336; color: white; padding: 14px 10px; border-radius: 5px; font-weight: bold; width: 65px; text-align: center; font-size: 12px;">GERAL<br>3P</div>
        """
        for dr_nome in grupos_dr_usados:
            html_caixa += f'<div style="background-color: #2196f3; color: white; padding: 14px 6px; border-radius: 5px; font-weight: bold; width: 115px; text-align: center; font-size: 11px;">{dr_nome}<br>IDR 4P 30mA</div>'
        html_caixa += '<div style="background-color: #ff9800; color: white; padding: 14px 10px; border-radius: 5px; font-weight: bold; width: 65px; text-align: center; font-size: 12px;">DPS<br>275V</div></div>'

        html_caixa += '<div style="background-color: #d5d5d5; padding: 10px; display: flex; gap: 6px; flex-wrap: wrap; border-radius: 6px;">'
        for _, row in df_q.iterrows():
            html_caixa += f'<div style="background-color: #4caf50; color: white; padding: 12px 5px; border-radius: 5px; font-weight: bold; width: 52px; text-align: center; font-size: 11px;">{row.get("ID", "?")}<br>{row.get("Disjuntor (A)", "-")}A<br><span style="color:#ffeb3b;font-size:10px;">{row.get("Fase","R")}</span></div>'
        for _ in range(espaco_reserva):
            html_caixa += '<div style="background-color: #9e9e9e; color: white; padding: 14px 5px; border-radius: 5px; font-weight: bold; width: 48px; text-align: center; font-size: 10px;">Reserva</div>'
        html_caixa += '</div></div>'
        st.markdown(html_caixa, unsafe_allow_html=True)

    st.divider()
    st.subheader("📄 Exportação de Memoriais, Diagramas e Planilha Excel")
    c_pdf1, c_pdf2, c_pdf3 = st.columns(3)
    with c_pdf1:
        if not st.session_state.circuitos.empty:
            caminho_unif = gerar_memorial_unifilar(st.session_state.circuitos, "Memorial_Unifilar_NBR5410.pdf")
            with open(caminho_unif, "rb") as f_pdf:
                st.download_button("📥 Baixar Memorial + Diagrama Unifilar (PDF)", data=f_pdf.read(), file_name="Memorial_Unifilar_NBR5410.pdf", mime="application/pdf", type="primary", use_container_width=True)
    with c_pdf2:
        if not st.session_state.circuitos.empty:
            caminho_qdg = gerar_pdf_qdg(st.session_state.circuitos, "Layout_QDG_DIN.pdf")
            with open(caminho_qdg, "rb") as f_qdg:
                st.download_button("📥 Baixar Layout Físico do QDG (PDF)", data=f_qdg.read(), file_name="Layout_QDG_DIN.pdf", mime="application/pdf", use_container_width=True)
    with c_pdf3:
        if not st.session_state.circuitos.empty:
            excel_bytes, excel_nome, excel_mime = gerar_arquivo_excel_completo()
            st.download_button("📊 Baixar Planilha Completa (.XLSX)", data=excel_bytes, file_name=excel_nome, mime=excel_mime, use_container_width=True)

# --- ABA 4: ENGENHARIA HIDROSSANITÁRIA (NBR 5626 & NBR 8160 + VALIDAÇÃO VRP 40 m.c.a.) ---
with tab_hidro:
    st.title("💧 Engenharia Hidrossanitária Executiva (NBR 5626 & NBR 8160)")
    st.subheader("📋 Verificação de Pressões (Mín. 10 kPa e Máx. Estática 40 m.c.a. c/ VRP), Perda de Carga e Declividades")

    df_h_display = pd.DataFrame(st.session_state.pontos_hidro) if st.session_state.pontos_hidro else pd.DataFrame(columns=[
        "ID", "Andar", "Ambiente", "Equipamento", "z", "Peso (NBR 5626)", "Vazão (L/s)",
        "Tubo AF (mm)", "L Real + Eq (m)", "Perda Carga (m.c.a.)", "Pressão Estática (m.c.a.)",
        "Pressão Disp. (kPa)", "Pressão Mín. (kPa)", "Status Pressão", "UHC", "Tubo Esgoto (mm)", "Declividade Esg. (%)"
    ])

    if not df_h_display.empty and "Status Pressão" in df_h_display.columns:
        qtd_ok = sum(df_h_display["Status Pressão"] == "OK (NBR 5626)")
        qtd_press = sum(df_h_display["Status Pressão"].str.contains("Pressurizar", na=False))
        qtd_vrp = sum(df_h_display["Status Pressão"].str.contains("VRP", na=False))
        ch1, ch2, ch3 = st.columns(3)
        ch1.metric("Pontos com Pressão Normal (NBR 5626)", f"{qtd_ok} pts")
        ch2.metric("Pontos Exigindo Pressurização (< Mín.)", f"{qtd_press} pts")
        ch3.metric("Pontos Exigindo VRP (> 40 m.c.a. Estática)", f"{qtd_vrp} pts")

    df_hidro_edit = st.data_editor(df_h_display, num_rows="dynamic", use_container_width=True)
    st.session_state.pontos_hidro = df_hidro_edit.to_dict('records')

    st.divider()
    st.subheader("📄 Exportação de Memorial Hidrossanitário e Lista de Materiais (PDF)")
    ch_pdf1, ch_pdf2 = st.columns(2)
    with ch_pdf1:
        if not df_hidro_edit.empty:
            dados_res = {"diario": pessoas * consumo_pc, "reserva": vol_caixa, "sugerido": vol_comercial}
            caminho_hid_pdf = gerar_memorial_hidraulico(df_hidro_edit, dados_res, "Memorial_Hidrossanitario_Executivo.pdf")
            with open(caminho_hid_pdf, "rb") as fh:
                st.download_button("📥 Baixar Memorial de Cálculo Hidrossanitário (PDF)", data=fh.read(), file_name="Memorial_Hidrossanitario_Executivo.pdf", mime="application/pdf", type="primary", use_container_width=True)
    with ch_pdf2:
        q_m = st.session_state.quantitativos_master
        if not q_m['agua_fria'].empty or not q_m['esgoto'].empty:
            caminho_mat_pdf = gerar_lista_materiais_pdf(q_m['agua_fria'], q_m['agua_quente'], q_m['esgoto'], "Quantitativo_Hidrossanitario.pdf")
            with open(caminho_mat_pdf, "rb") as fm:
                st.download_button("📥 Baixar Lista de Materiais Hidráulicos (PDF)", data=fm.read(), file_name="Quantitativo_Hidrossanitario.pdf", mime="application/pdf", use_container_width=True)

# --- ABA 5: DESENHOS TÉCNICOS DE PEÇAS (32 FAMÍLIAS), QUANTITATIVOS TOTAIS E IFC/DXF ---
with tab_pecas_ifc:
    st.title("📐 Desenhos Técnicos de Peças/Conexões (32 Famílias), Quantitativos Totais & Fluxograma IFC")

    st.subheader("1. Gerador de Desenho Técnico CAD de Todas as Peças e Conexões (Padrão ABNT)")
    cp1, cp2 = st.columns([2.5, 1])
    peca_sel = cp1.selectbox("Selecione a Peça, Conexão, Caixa, Válvula ou Dispositivo para Detalhamento Cotado:", CATALOGO_PECAS_CAD)
    dn_sel = cp2.selectbox("Diâmetro Nominal / Dimensão Base (mm):", [15, 20, 22, 25, 28, 32, 40, 50, 60, 75, 100, 150], index=3)
    fig_peca = gerar_desenho_tecnico_peca_plotly(peca_sel, dn_sel)
    st.plotly_chart(fig_peca, use_container_width=True)

    st.divider()
    st.subheader("2. Quantitativos Totais Extraídos da Geometria 3D (Bill of Materials)")
    q_m = st.session_state.quantitativos_master
    cq1, cq2 = st.columns(2)
    with cq1:
        st.markdown("**⚡ Quantitativo Total - Instalações Elétricas**")
        st.dataframe(q_m['eletrica'], use_container_width=True, hide_index=True)
        st.markdown("**🔥 Quantitativo Total - Água Quente (CPVC/PPR)**")
        st.dataframe(q_m['agua_quente'], use_container_width=True, hide_index=True)
    with cq2:
        st.markdown("**💧 Quantitativo Total - Água Fria (PVC Soldável)**")
        st.dataframe(q_m['agua_fria'], use_container_width=True, hide_index=True)
        st.markdown("**🤎 Quantitativo Total - Esgoto Sanitário e Ventilação**")
        st.dataframe(q_m['esgoto'], use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("3. Fluxograma Topológico IFC & Exportação de Malhas 3D (.DXF c/ Simbologia ABNT e .IFC)")
    st.markdown("O arquivo `.DXF` exportado já inclui a **Simbologia Unifilar ABNT (Fase, Neutro, Terra e Retorno)** desenhada automaticamente nos eletrodutos.")
    fig_ifc = gerar_fluxograma_ifc_plotly(
        st.session_state.linhas_3d_master['eletrica'],
        st.session_state.linhas_3d_master['hidro'],
        config_andares
    )
    st.plotly_chart(fig_ifc, use_container_width=True)

    paredes_export = st.session_state.contexto_bim.get('paredes', [])
    linhas_el_exp = st.session_state.linhas_3d_master['eletrica']
    linhas_hd_exp = st.session_state.linhas_3d_master['hidro']

    ce1, ce2, ce3 = st.columns(3)
    with ce1:
        st.markdown("**⚡ Projeto Individual de Elétrica**")
        st.download_button("📐 Baixar Malha Elétrica 3D + Símbolos ABNT (.DXF)", data=exportar_malha_para_dxf(linhas_el_exp, [], paredes_export, "ELETRICA"), file_name="Malha_Eletrica_3D_ABNT.dxf", use_container_width=True)
        st.download_button("🧱 Baixar Modelo IFC Elétrica (.IFC)", data=exportar_malha_para_ifc_step(linhas_el_exp, [], "ELETRICA"), file_name="Projeto_Eletrico_BIM.ifc", use_container_width=True)
    with ce2:
        st.markdown("**💧 Projeto Individual de Hidráulica**")
        st.download_button("📐 Baixar Malha Hidráulica 3D (.DXF)", data=exportar_malha_para_dxf([], linhas_hd_exp, paredes_export, "HIDRO"), file_name="Malha_Hidraulica_3D.dxf", use_container_width=True)
        st.download_button("🧱 Baixar Modelo IFC Hidráulica (.IFC)", data=exportar_malha_para_ifc_step([], linhas_hd_exp, "HIDRO"), file_name="Projeto_Hidraulico_BIM.ifc", use_container_width=True)
    with ce3:
        st.markdown("**🏢 Projeto Unificado Completo (Elétrica + Hidro)**")
        st.download_button("📐 Baixar Malha Unificada 3D (.DXF)", data=exportar_malha_para_dxf(linhas_el_exp, linhas_hd_exp, paredes_export, "UNIFICADO"), file_name="Malha_MEP_Unificada_3D.dxf", type="primary", use_container_width=True)
        st.download_button("🧱 Baixar Modelo IFC Unificado (.IFC)", data=exportar_malha_para_ifc_step(linhas_el_exp, linhas_hd_exp, "UNIFICADO"), file_name="Projeto_MEP_Unificado_BIM.ifc", type="primary", use_container_width=True)

# --- ABA 6: GERENCIADOR DE BIBLIOTECAS ---
with tab_export:
    st.title("📚 Gerenciamento de Bibliotecas BIM")
    st.markdown("As tabelas abaixo alimentam as opções e cálculos normativos em todo o sistema.")
    
    aba_elet, aba_hidro, aba_gas = st.tabs(["⚡ Elétrica (NBR 5410)", "💧 Instalações Hidrossanitárias (Água + Esgoto)", "🔥 Gás & Climatização (NBR 15526 / 16401)"])
    
    with aba_elet:
        st.session_state.bib_eletrica = st.data_editor(st.session_state.bib_eletrica, num_rows="dynamic", use_container_width=True)
    
    with aba_hidro:
        st.markdown("**Pesos (NBR 5626), Água Quente (CPVC/PPR) e UHCs (NBR 8160) unificados por equipamento**")
        st.session_state.bib_hidro = st.data_editor(st.session_state.bib_hidro, num_rows="dynamic", use_container_width=True)

    with aba_gas:
        st.markdown("**Parâmetros Normativos de Gás Combustível (GLP/GN - NBR 15526) e Climatização Split (NBR 16401)**")
        st.session_state.bib_gas_avac = st.data_editor(st.session_state.bib_gas_avac, num_rows="dynamic", use_container_width=True)

# === FIM DO ARQUIVO ===
