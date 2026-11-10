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
    "Tê (Direta)":     {20: 0.7, 22: 0.7, 25: 0.8, 32: 0.9, 40: 1.5, 50: 2.2, 60: 2.5},
    "Tê (Saída Lat.)": {20: 2.3, 22: 2.3, 25: 2.4, 32: 3.1, 40: 4.6, 50: 7.3, 60: 8.0},
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
    {"Equipamento": "Tê (Passagem Direta) 22mm", "Vazao_Ls": 0.00, "Peso": 0.7, "Agua_mm": 22, "AQ_mm": 22, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Tê (Passagem Direta) 25mm", "Vazao_Ls": 0.00, "Peso": 0.8, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
    {"Equipamento": "Tê (Passagem Direta) 32mm", "Vazao_Ls": 0.00, "Peso": 0.9, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
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
    {"Equipamento": "Tê Esgoto 40mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 40, "Vent_mm": 0},
    {"Equipamento": "Tê Esgoto 50mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 50, "Vent_mm": 0},
    {"Equipamento": "Tê Esgoto 75mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 75, "Vent_mm": 0},
    {"Equipamento": "Tê Esgoto 100mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 100, "Vent_mm": 0},
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
    """Injeta Tubulações de Passagem (AF, AQ e Esgoto), Tubos de Queda, Subida e Ramais na bib_hidro."""
    novos_itens = [
        # ---- TUBULAÇÕES DE PASSAGEM (PARA INDICAR CAMINHO E ALTURA ESPECÍFICA) ----
        {"Equipamento": "Tubulação Água Fria 25mm", "Vazao_Ls": 0.40, "Peso": 0.0, "Agua_mm": 25, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Tubulação Água Fria 20mm", "Vazao_Ls": 0.20, "Peso": 0.0, "Agua_mm": 20, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Tubulação Água Fria 32mm", "Vazao_Ls": 0.60, "Peso": 0.0, "Agua_mm": 32, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Tubulação Água Fria 40mm", "Vazao_Ls": 1.00, "Peso": 0.0, "Agua_mm": 40, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Tubulação Água Fria 50mm", "Vazao_Ls": 1.50, "Peso": 0.0, "Agua_mm": 50, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Tubulação Água Quente 22mm", "Vazao_Ls": 0.30, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 22, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Tubulação Água Quente 28mm", "Vazao_Ls": 0.50, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 28, "Pressao_kpa": 0, "UHC": 0, "Esgoto_mm": 0, "Vent_mm": 0},
        {"Equipamento": "Tubulação Esgoto 100mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 160, "Esgoto_mm": 100, "Vent_mm": 75},
        {"Equipamento": "Tubulação Esgoto 75mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 20, "Esgoto_mm": 75, "Vent_mm": 50},
        {"Equipamento": "Tubulação Esgoto 50mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 6, "Esgoto_mm": 50, "Vent_mm": 40},
        {"Equipamento": "Tubulação Esgoto 40mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 2, "Esgoto_mm": 40, "Vent_mm": 40},
        {"Equipamento": "Ponto de Esgoto 100mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 6, "Esgoto_mm": 100, "Vent_mm": 50},
        {"Equipamento": "Ponto de Esgoto 75mm", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 6, "Esgoto_mm": 75, "Vent_mm": 50},
        # ---- CAIXAS SIFONADAS E CAIXAS DE GORDURA NORMATIVAS (NBR 8160 - ITEM 5.1.5) ----
        {"Equipamento": "Ralo Sifonado 100x100x50mm (Fecho 50mm - Máx 6 UHC)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 6, "Esgoto_mm": 50, "Vent_mm": 40},
        {"Equipamento": "Caixa Sifonada 150x150x50mm (Fecho 50mm - Máx 15 UHC)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 15, "Esgoto_mm": 75, "Vent_mm": 50},
        {"Equipamento": "Caixa de Gordura Pequena (CGP 18L - 1 Cozinha - Saída 50/75mm)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 6, "Esgoto_mm": 75, "Vent_mm": 50},
        {"Equipamento": "Caixa de Gordura Simples (CGS 31L - 1 a 2 Cozinhas - Saída 75mm)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 12, "Esgoto_mm": 75, "Vent_mm": 50},
        {"Equipamento": "Caixa de Gordura Dupla (CGD 120L - 2 a 12 Cozinhas - Saída 100mm)", "Vazao_Ls": 0.00, "Peso": 0.0, "Agua_mm": 0, "AQ_mm": 0, "Pressao_kpa": 0, "UHC": 36, "Esgoto_mm": 100, "Vent_mm": 75},
        # ---- TUBOS DE QUEDA, SUBIDA E RAMAIS ----
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
        qtd_tes * COMPRIMENTO_EQUIVALENTE_CONEXOES["Tê (Saída Lat.)"][d_ref] +
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
    """Calcula a menor distância 2D entre um ponto (px, py) e o segmento (x1,y1)-(x2,y2)."""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))

def analisar_parede_hospedeira_e_verga(p1_vao, p2_vao, z_base, paredes_lista, max_ext=0.30):
    """
    Verifica se existe uma parede REAL da layer de Paredes colinear ao vão (p1_vao, p2_vao).
    - Se NÃO existir parede real no local, retorna encontrou_parede=False (não cria parede nem verga fantasma).
    - Se existir, alinha o vão exatamente nas duas faces da parede e calcula o avanço da
      Verga e Contraverga (até 30cm para cada lado, parando antes se a parede acabar ou dobrar).
    """
    vx, vy = p2_vao[0] - p1_vao[0], p2_vao[1] - p1_vao[1]
    comp_vao = math.hypot(vx, vy)
    if comp_vao < 0.20 or not paredes_lista:
        return p1_vao, p2_vao, p1_vao, p2_vao, (-0.075, 0.075), (0.0, 1.0), False

    ux, uy = vx / comp_vao, vy / comp_vao
    nx, ny = -uy, ux

    offsets_perp = []
    avan_esq, avan_dir = 0.0, 0.0
    encontrou_parede = False

    for seg in paredes_lista:
        w1, w2 = seg[0], seg[1]
        if abs(w1[2] - z_base) > 0.6:
            continue
        wx, wy = w2[0] - w1[0], w2[1] - w1[1]
        w_len = math.hypot(wx, wy)
        if w_len < 0.12:
            continue
        wux, wuy = wx / w_len, wy / w_len
        if abs(ux * wux + uy * wuy) < 0.88:
            continue

        # Distância perpendicular com sinal em relação a p1_vao
        d_perp = (w1[0] - p1_vao[0]) * nx + (w1[1] - p1_vao[1]) * ny
        if abs(d_perp) > 0.28:
            continue

        # Projeção longitudinal do segmento de parede ao longo do vão [0, comp_vao]
        s1 = (w1[0] - p1_vao[0]) * ux + (w1[1] - p1_vao[1]) * uy
        s2 = (w2[0] - p1_vao[0]) * ux + (w2[1] - p1_vao[1]) * uy
        s_min, s_max = min(s1, s2), max(s1, s2)

        # Só considera parede hospedeira se ela estiver encostada ou sobreposta ao vão (folga <= 25cm)
        if s_max < -0.25 or s_min > comp_vao + 0.25:
            continue

        encontrou_parede = True
        offsets_perp.append(d_perp)

        # Quanto a parede avança continuamente à esquerda de p1_vao (s < 0)
        if s_max >= -0.15 and s_min < 0.0:
            avan_esq = max(avan_esq, min(max_ext, abs(s_min)))
        # Quanto a parede avança continuamente à direita de p2_vao (s > comp_vao)
        if s_min <= comp_vao + 0.15 and s_max > comp_vao:
            avan_dir = max(avan_dir, min(max_ext, s_max - comp_vao))

    if not encontrou_parede:
        return p1_vao, p2_vao, p1_vao, p2_vao, (-0.075, 0.075), (nx, ny), False

    d_min = min(offsets_perp)
    d_max = max(offsets_perp)
    if abs(d_max - d_min) < 0.06:
        d_med = (d_min + d_max) / 2.0
        d_min, d_max = d_med - 0.075, d_med + 0.075
    else:
        d_med = (d_min + d_max) / 2.0
        d_min, d_max = d_min - d_med, d_max - d_med
        # Centraliza p1_vao e p2_vao exatamente no eixo central entre as duas faces da parede
        p1_vao = (p1_vao[0] + nx * d_med, p1_vao[1] + ny * d_med)
        p2_vao = (p2_vao[0] + nx * d_med, p2_vao[1] + ny * d_med)

    p1_ext = (p1_vao[0] - ux * avan_esq, p1_vao[1] - uy * avan_esq)
    p2_ext = (p2_vao[0] + ux * avan_dir, p2_vao[1] + uy * avan_dir)
    return p1_vao, p2_vao, p1_ext, p2_ext, (d_min, d_max), (nx, ny), True

def extrair_geometria_esquadria_dxf(entidade_insert, paredes_andar, z_base):
    """
    Extrai a posição, largura e orientação real de Portas e Janelas do DXF:
    - Para Portas (com ARC): usa o centro do arco (dobradiça) e o raio alinhado com a parede,
      ignorando a folha aberta a 90° para não criar parede perpendicular no meio do cômodo.
    - Para Janelas: alinha o eixo principal da janela com a parede colinear mais próxima.
    """
    linhas_internas = []
    arcos_internos = []

    def coletar_entidades(ent_pai, prof=0):
        if prof > 2:
            return
        try:
            for ve in ent_pai.virtual_entities():
                dxft = ve.dxftype()
                if dxft == 'LINE':
                    p1 = (float(ve.dxf.start.x), float(ve.dxf.start.y))
                    p2 = (float(ve.dxf.end.x), float(ve.dxf.end.y))
                    if dist_2d(p1, p2) >= 0.05:
                        linhas_internas.append((p1, p2))
                elif dxft == 'LWPOLYLINE':
                    pts = list(ve.get_points(format='xy'))
                    for i in range(len(pts) - 1):
                        p1, p2 = (float(pts[i][0]), float(pts[i][1])), (float(pts[i+1][0]), float(pts[i+1][1]))
                        if dist_2d(p1, p2) >= 0.05:
                            linhas_internas.append((p1, p2))
                    if ve.closed and len(pts) >= 3:
                        p1, p2 = (float(pts[-1][0]), float(pts[-1][1])), (float(pts[0][0]), float(pts[0][1]))
                        if dist_2d(p1, p2) >= 0.05:
                            linhas_internas.append((p1, p2))
                elif dxft == 'ARC':
                    r = float(ve.dxf.radius)
                    if 0.40 <= r <= 1.80:
                        c_arc = (float(ve.dxf.center.x), float(ve.dxf.center.y))
                        try:
                            sp = ve.start_point
                            ep = ve.end_point
                            a1, a2 = (float(sp.x), float(sp.y)), (float(ep.x), float(ep.y))
                        except Exception:
                            ang1 = math.radians(float(ve.dxf.start_angle))
                            ang2 = math.radians(float(ve.dxf.end_angle))
                            a1 = (c_arc[0] + r * math.cos(ang1), c_arc[1] + r * math.sin(ang1))
                            a2 = (c_arc[0] + r * math.cos(ang2), c_arc[1] + r * math.sin(ang2))
                        arcos_internos.append((c_arc, r, a1, a2))
                elif dxft == 'INSERT':
                    coletar_entidades(ve, prof + 1)
        except Exception:
            pass

    coletar_entidades(entidade_insert)
    tem_arco_porta = len(arcos_internos) > 0

    # CASO 1: Bloco de Porta com Arco de Giro (ARC)
    if tem_arco_porta:
        # Escolhe o maior arco de giro da porta
        c_arc, r_arc, a1, a2 = max(arcos_internos, key=lambda x: x[1])
        larg_porta = round(max(0.55, min(1.60, r_arc)), 2)

        # Testa qual dos dois raios do arco (c_arc -> a1 ou c_arc -> a2) está alinhado com a parede (e não com a folha aberta)
        _, _, _, _, _, _, ok1 = analisar_parede_hospedeira_e_verga(c_arc, a1, z_base, paredes_andar)
        _, _, _, _, _, _, ok2 = analisar_parede_hospedeira_e_verga(c_arc, a2, z_base, paredes_andar)

        if ok1 and not ok2:
            p1_v, p2_v = c_arc, a1
        elif ok2 and not ok1:
            p1_v, p2_v = c_arc, a2
        else:
            # A folha aberta tem várias linhas longas paralelas a ela; o vão na parede é o raio SEM linhas da folha!
            v1x, v1y = (a1[0] - c_arc[0]) / max(r_arc, 0.01), (a1[1] - c_arc[1]) / max(r_arc, 0.01)
            v2x, v2y = (a2[0] - c_arc[0]) / max(r_arc, 0.01), (a2[1] - c_arc[1]) / max(r_arc, 0.01)
            peso_folha_1, peso_folha_2 = 0.0, 0.0
            for l1, l2 in linhas_internas:
                comp_l = dist_2d(l1, l2)
                if comp_l >= 0.40:
                    lux, luy = (l2[0] - l1[0]) / comp_l, (l2[1] - l1[1]) / comp_l
                    if abs(lux * v1x + luy * v1y) > 0.90:
                        peso_folha_1 += comp_l
                    if abs(lux * v2x + luy * v2y) > 0.90:
                        peso_folha_2 += comp_l
            p1_v, p2_v = (c_arc, a2) if peso_folha_1 >= peso_folha_2 else (c_arc, a1)

        cx_f, cy_f = round((p1_v[0] + p2_v[0]) / 2.0, 4), round((p1_v[1] + p2_v[1]) / 2.0, 4)
        return True, cx_f, cy_f, p1_v, p2_v, larg_porta

    # CASO 2: Bloco de Janela (ou Porta sem arco) formado por linhas
    if linhas_internas:
        # Encontra a direção do segmento mais longo do bloco (direção longitudinal da janela)
        seg_principal = max(linhas_internas, key=lambda s: dist_2d(s[0], s[1]))
        comp_princ = dist_2d(seg_principal[0], seg_principal[1])
        ux, uy = (seg_principal[1][0] - seg_principal[0][0]) / comp_princ, (seg_principal[1][1] - seg_principal[0][1]) / comp_princ
        nx, ny = -uy, ux

        todos_pts = [pt for seg in linhas_internas for pt in seg]
        cx_m = sum(p[0] for p in todos_pts) / len(todos_pts)
        cy_m = sum(p[1] for p in todos_pts) / len(todos_pts)

        # Filtra pontos próximos ao centro para não esticar caso seja bloco agrupado
        pts_locais = [p for p in todos_pts if math.hypot(p[0] - cx_m, p[1] - cy_m) <= 2.0]
        if not pts_locais:
            pts_locais = todos_pts

        projs_u = [(p[0] - cx_m) * ux + (p[1] - cy_m) * uy for p in pts_locais]
        projs_n = [(p[0] - cx_m) * nx + (p[1] - cy_m) * ny for p in pts_locais]
        u_min, u_max = min(projs_u), max(projs_u)
        n_med = (min(projs_n) + max(projs_n)) / 2.0

        larg_jan = round(max(0.40, min(3.00, u_max - u_min)), 2)
        u_med = (u_min + u_max) / 2.0
        cx_f = round(cx_m + ux * u_med + nx * n_med, 4)
        cy_f = round(cy_m + uy * u_med + ny * n_med, 4)
        p1_v = (cx_f - ux * (larg_jan / 2.0), cy_f - uy * (larg_jan / 2.0))
        p2_v = (cx_f + ux * (larg_jan / 2.0), cy_f + uy * (larg_jan / 2.0))
        return False, cx_f, cy_f, p1_v, p2_v, larg_jan

    # Fallback caso o bloco seja apenas um ponto
    cx_ins, cy_ins = round(float(entidade_insert.dxf.insert.x), 4), round(float(entidade_insert.dxf.insert.y), 4)
    rot_rad = math.radians(getattr(entidade_insert.dxf, 'rotation', 0.0))
    larg_fb = 0.90
    p1_v = (cx_ins - (larg_fb / 2.0) * math.cos(rot_rad), cy_ins - (larg_fb / 2.0) * math.sin(rot_rad))
    p2_v = (cx_ins + (larg_fb / 2.0) * math.cos(rot_rad), cy_ins + (larg_fb / 2.0) * math.sin(rot_rad))
    return False, cx_ins, cy_ins, p1_v, p2_v, larg_fb

def liberar_vaos_esquadrias_na_matriz(matriz, elementos_arq, ctx):
    """Abre os vãos de portas e janelas na matriz 2D A* para permitir a passagem dos tubos."""
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
    Desvia as tubulações (Elétrica, Água Fria, Água Quente e Esgoto) respeitando:
    1. O vão da Porta ou Janela;
    2. A VERGA superior (10cm de altura acima do vão + até 30cm para cada lado na parede);
    3. A CONTRAVERGA inferior (10cm de altura abaixo do peitoril da janela + até 30cm para cada lado).
    """
    if not elementos_arq or len(linha_3d) < 2:
        return linha_3d

    elems_andar = [e for e in elementos_arq if abs(e.get('z_base', 0.0) - z_base) < 0.6 and not str(e.get('ID_CAD', '')).startswith('VAO_AUTO_')]
    if not elems_andar:
        return linha_3d

    paredes_ctx = st.session_state.contexto_bim.get('paredes', [])
    z_teto_livre = z_base + pe_direito - 0.06
    ALT_VERGA = 0.10
    nova_linha = [linha_3d[0]]

    for i in range(len(linha_3d) - 1):
        p_ini = linha_3d[i]
        p_fim = linha_3d[i + 1]
        comp_2d = dist_2d(p_ini, p_fim)

        if comp_2d < 0.08:
            nova_linha.append(p_fim)
            continue

        n_passos = max(2, int(comp_2d / 0.10) + 1)
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
                    _, _, p1_ext, p2_ext, _, _, tem_parede = analisar_parede_hospedeira_e_verga(p1_v, p2_v, z_base, paredes_ctx, max_ext=0.30)
                    if not tem_parede:
                        continue

                    dist_ext = distancia_ponto_segmento_2d(px, py, p1_ext[0], p1_ext[1], p2_ext[0], p2_ext[1])
                    if dist_ext <= 0.25:
                        peitoril = float(elem.get('Peitoril', 0.0))
                        altura_vao = float(elem.get('Altura', 2.10))
                        eh_janela = (elem.get('Subtipo') == 'Janela')

                        z_base_contraverga = z_base + max(0.0, peitoril - ALT_VERGA) if (eh_janela and peitoril >= 0.15) else (z_base + peitoril)
                        z_topo_verga = z_base + peitoril + altura_vao + ALT_VERGA

                        if (z_base_contraverga - 0.04) < pz < (z_topo_verga + 0.04):
                            z_acima_verga = min(z_teto_livre, z_topo_verga + 0.06)
                            z_abaixo_contraverga = max(z_base + 0.05, z_base_contraverga - 0.06)

                            if eh_janela and peitoril >= 0.25:
                                if abs(pz - z_abaixo_contraverga) <= abs(z_acima_verga - pz):
                                    z_ajustado = z_abaixo_contraverga
                                else:
                                    z_ajustado = z_acima_verga
                            else:
                                if peitoril >= 0.15 and pz <= z_base_contraverga + 0.08:
                                    z_ajustado = z_abaixo_contraverga
                                else:
                                    z_ajustado = z_acima_verga
                            break

                elif elem.get('Tipo') == 'Pilar/Viga':
                    if math.hypot(px - elem['x'], py - elem['y']) <= (elem.get('Largura', 0.40) / 2.0 + 0.15):
                        z_fundo_viga = z_base + pe_direito - h_viga - 0.05
                        if pz > z_fundo_viga:
                            z_ajustado = z_fundo_viga

            pt_novo = (round(px, 4), round(py, 4), round(z_ajustado, 4))
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

def dimensionar_tubo_agua_fria(soma_pesos):
    """Dimensiona o diâmetro comercial de Água Fria (mm) pela ABNT NBR 5626 (Q = 0.3 * sqrt(Peso))."""
    p = max(0.1, float(soma_pesos))
    vazao_ls = 0.30 * math.sqrt(p)
    # Diâmetros comerciais soldáveis (mm) e vazão máxima recomendada (L/s) respeitando V <= 3,0 m/s
    tabela_af = [
        (20, 0.35),
        (25, 0.65),
        (32, 1.15),
        (40, 1.80),
        (50, 3.00),
        (60, 4.50),
        (75, 7.50),
        (85, 10.50),
        (110, 18.00)
    ]
    for dn, q_max in tabela_af:
        if vazao_ls <= q_max:
            return dn
    return 110


def dimensionar_tubo_esgoto(soma_uhc):
    """Dimensiona o diâmetro nominal de Esgoto (mm) pela ABNT NBR 8160 com base nas UHCs acumuladas."""
    u = float(soma_uhc)
    if u <= 2.0:
        return 40
    elif u <= 6.0:
        return 50
    elif u <= 20.0:
        return 75
    elif u <= 160.0:
        return 100
    return 150


def contar_conexoes_na_rota(pontos_3d):
    """Conta automaticamente joelhos de 90°, joelhos de 45° e tês ao longo dos vértices de uma rota 3D."""
    if not pontos_3d or len(pontos_3d) < 3:
        return 1, 0, 1
    j90, j45 = 0, 0
    for i in range(1, len(pontos_3d) - 1):
        p0, p1, p2 = pontos_3d[i - 1], pontos_3d[i], pontos_3d[i + 1]
        v1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
        v2 = (p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2])
        n1 = math.sqrt(v1[0]**2 + v1[1]**2 + v1[2]**2)
        n2 = math.sqrt(v2[0]**2 + v2[1]**2 + v2[2]**2)
        if n1 > 1e-3 and n2 > 1e-3:
            cos_ang = (v1[0]*v2[0] + v1[1]*v2[1] + v1[2]*v2[2]) / (n1 * n2)
            cos_ang = max(-1.0, min(1.0, cos_ang))
            ang_graus = math.degrees(math.acos(cos_ang))
            if ang_graus >= 65.0:
                j90 += 1
            elif ang_graus >= 20.0:
                j45 += 1
    return max(1, j90), j45, 1


def liberar_caixa(matriz, cx, cy, grid_w, grid_h, raio=2):
    """Desbloqueia a vizinhança de um ponto na matriz 2D do A* para permitir saída/chegada na parede."""
    for dy in range(-raio, raio + 1):
        for dx in range(-raio, raio + 1):
            nx, ny = cx + dx, cy + dy
            if 0 <= ny < grid_h and 0 <= nx < grid_w:
                matriz[ny][nx] = 1


def bloquear_caixa_estrutural(matriz, cx, cy, grid_w, grid_h, raio=2):
    """Bloqueia a área de um pilar estrutural na matriz 2D para que a tubulação contorne o pilar."""
    for dy in range(-raio, raio + 1):
        for dx in range(-raio, raio + 1):
            nx, ny = cx + dx, cy + dy
            if 0 <= ny < grid_h and 0 <= nx < grid_w:
                matriz[ny][nx] = 0


def liberar_vaos_esquadrias_na_matriz(matriz, elementos_arq, ctx):
    """Libera os vãos de portas e janelas na matriz 2D para que os tubos atravessem desviando da verga/contraverga no 3D."""
    if not elementos_arq:
        return
    for elem in elementos_arq:
        if elem.get('Tipo') == 'Esquadria' and elem.get('tem_parede_real', True):
            larg = float(elem.get('Largura', 0.90))
            p1_v = elem.get('p1_vao', (elem['x'] - larg / 2.0, elem['y']))
            p2_v = elem.get('p2_vao', (elem['x'] + larg / 2.0, elem['y']))
            x0 = escalar_coord(p1_v[0] - ctx['min_x'] + ctx['offset'])
            y0 = escalar_coord(p1_v[1] - ctx['min_y'] + ctx['offset'])
            x1 = escalar_coord(p2_v[0] - ctx['min_x'] + ctx['offset'])
            y1 = escalar_coord(p2_v[1] - ctx['min_y'] + ctx['offset'])
            for px, py in algoritmo_bresenham(x0, y0, x1, y1):
                liberar_caixa(matriz, px, py, ctx['grid_w'], ctx['grid_h'], raio=1)

def obter_override_topologico_ponto(id_cad, todos_blocos, diam_padrao):
    """
    Retorna (bloco_alvo_manual, diametro_final, nome_conexao_manual, tem_link_manual)
    dando prioridade absoluta ao que o usuário configurou no Inspetor 2D/3D.
    """
    ov = st.session_state.get("overrides_topologia_bim", {}).get(str(id_cad), {})
    id_dest_manual = str(ov.get("Conectado_A", "Automático (Menor Rota ABNT)")).strip()
    bloco_alvo_manual = None
    tem_link_manual = False
    if id_dest_manual and id_dest_manual != "Automático (Menor Rota ABNT)":
        bloco_alvo_manual = next((b for b in todos_blocos if str(b.get("ID_CAD")) == id_dest_manual), None)
        if bloco_alvo_manual is not None and str(bloco_alvo_manual.get("ID_CAD")) != str(id_cad):
            tem_link_manual = True
    dn_manual = int(ov.get("DN_Manual_mm", 0))
    diam_final = dn_manual if dn_manual > 0 else diam_padrao
    return bloco_alvo_manual, diam_final, ov.get("Conexao_No", ""), tem_link_manual


def rotear_hidro(df_bh, ctx):
    """
    Motor Hidrossanitário 3D/2D (NBR 5626 e NBR 8160) Subordinado à Configuração Manual do Usuário:
    1. Toda ligação manual definida no Inspetor 2D tem prioridade absoluta (inclusive entre Caixas de Inspeção, Conexões e Caixas);
    2. O roteamento automático se readequa à árvore manual, evitando ciclos e acumulando Pesos e UHCs a jusante;
    3. Garante fallback geométrico direto caso o A* encontre obstáculo externo, nunca deixando uma ligação manual sem tubo.
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
        if elem.get('Tipo') == 'Pilar/Viga' and 'PILAR' in str(elem.get('ID_CAD', '')).upper():
            px, py = escalar_coord(elem['x'] - ctx['min_x'] + ctx['offset']), escalar_coord(elem['y'] - ctx['min_y'] + ctx['offset'])
            bloquear_caixa_estrutural(matriz, px, py, ctx['grid_w'], ctx['grid_h'], raio=2)

    liberar_vaos_esquadrias_na_matriz(matriz, elementos_arq, ctx)

    h_af = ctx.get('h_agua_fria', 0.20)
    h_aq = ctx.get('h_agua_quente', 1.00)
    h_viga = ctx.get('altura_viga', 0.40)
    z_subsolo_af = -0.25

    def rota_a_star_2d(orig, dest, permitir_diagonal=False, forcar_direto_se_falhar=True):
        ox = max(0, min(ctx['grid_w'] - 1, escalar_coord(orig['x'] - ctx['min_x'] + ctx['offset'])))
        oy = max(0, min(ctx['grid_h'] - 1, escalar_coord(orig['y'] - ctx['min_y'] + ctx['offset'])))
        dx = max(0, min(ctx['grid_w'] - 1, escalar_coord(dest['x'] - ctx['min_x'] + ctx['offset'])))
        dy = max(0, min(ctx['grid_h'] - 1, escalar_coord(dest['y'] - ctx['min_y'] + ctx['offset'])))
        liberar_caixa(matriz, ox, oy, ctx['grid_w'], ctx['grid_h'], raio=2)
        liberar_caixa(matriz, dx, dy, ctx['grid_w'], ctx['grid_h'], raio=2)
        grid = Grid(matrix=matriz)
        mov = DiagonalMovement.always if permitir_diagonal else DiagonalMovement.never
        finder = AStarFinder(diagonal_movement=mov)
        caminho, _ = finder.find_path(grid.node(ox, oy), grid.node(dx, dy), grid)
        pts = [(desescalar_coord(p.x) + ctx['min_x'] - ctx['offset'], desescalar_coord(p.y) + ctx['min_y'] - ctx['offset']) for p in caminho]
        if not pts and forcar_direto_se_falhar:
            return [(orig['x'], orig['y']), (dest['x'], dest['y'])]
        return pts

    mapa_blocos = {str(b['ID_CAD']): b for b in df_bh}

    # Classificação dos blocos por função BIM
    caixas_agua = [b for b in df_bh if b['Tipo_BIM'] == "Caixa d'Água"]
    prumadas_af = [b for b in df_bh if b['Tipo_BIM'] in ['Prumada Água Fria', 'Tubo de Queda Água Fria', 'Coluna de Subida Água Fria']]
    conexoes_af = [b for b in df_bh if b['Tipo_BIM'] == 'Conexões Hidráulicas AF']
    boilers = [b for b in df_bh if b['Tipo_BIM'] == 'Boiler / Aquecedor']
    prumadas_aq = [b for b in df_bh if b['Tipo_BIM'] in ['Tubo de Queda Água Quente', 'Coluna de Subida Água Quente']]
    conexoes_aq = [b for b in df_bh if b['Tipo_BIM'] == 'Conexões Hidráulicas AQ']
    prumadas_esg = [b for b in df_bh if b['Tipo_BIM'] == 'Prumada Esgoto']
    caixas_inspecao = [b for b in df_bh if b['Tipo_BIM'] == 'Caixa de Inspeção / Destino Esgoto']
    ramais_esgoto = [b for b in df_bh if b['Tipo_BIM'] == 'Ramal de Esgoto']
    caixas_sifonadas = [b for b in df_bh if b['Tipo_BIM'] == 'Caixa Sifonada / Ralo Sifonado' or "SIFONAD" in normalizar_texto_bim(b.get('Equipamento', ''))]
    caixas_gordura = [b for b in df_bh if b['Tipo_BIM'] == 'Caixa de Gordura' or "GORDURA" in normalizar_texto_bim(b.get('Equipamento', ''))]

    ids_esgoto_natos = {
        str(b['ID_CAD']) for b in df_bh
        if b['Tipo_BIM'] in [
            'Caixa de Inspeção / Destino Esgoto', 'Caixa de Gordura',
            'Caixa Sifonada / Ralo Sifonado', 'Ramal de Esgoto',
            'Ramal de Descarga', 'Conexões Tubulação Esgoto', 'Prumada Esgoto'
        ]
    }

    # =========================================================================
    # ETAPAS 1 A 3: ÁGUA FRIA (RESERVATÓRIO, COLUNAS, CONEXÕES AF E APARELHOS)
    # =========================================================================
    peso_total_edificacao = sum(
        float(st.session_state.bib_hidro.loc[st.session_state.bib_hidro['Equipamento'] == b['Equipamento'], 'Peso'].values[0])
        for b in df_bh
        if b['Tipo_BIM'] == 'Aparelho Hidráulico' and (st.session_state.bib_hidro['Equipamento'] == b['Equipamento']).any()
    )
    dn_barrilete = max(32, dimensionar_tubo_agua_fria(peso_total_edificacao))

    if caixas_agua and prumadas_af:
        cx_sup = caixas_agua[0]
        z_fundo_cx = ctx.get('max_z_cobertura', 3.0) + ctx.get('altura_caixa', 1.50)
        z_barrilete = ctx.get('max_z_cobertura', 3.0) + 0.25
        for prum in prumadas_af:
            _, dn_p_af, _, _ = obter_override_topologico_ponto(prum['ID_CAD'], df_bh, dn_barrilete)
            pts_b = rota_a_star_2d(cx_sup, prum, permitir_diagonal=False)
            linha_b = [(cx_sup['x'], cx_sup['y'], z_fundo_cx), (cx_sup['x'], cx_sup['y'], z_barrilete)]
            for px, py in pts_b:
                linha_b.append((px, py, z_barrilete))
            linha_b.extend([(prum['x'], prum['y'], z_barrilete), (prum['x'], prum['y'], 0.0)])
            linhas_processadas.append({
                'pontos': linha_b, 'cor': '#1d4ed8',
                'tipo': f"Barrilete / Coluna AF ({prum['ID_CAD']})", 'diametro': dn_p_af
            })

    # Grafo de Água Fria (Aparelhos com Agua_mm > 0 + Conexões AF) subordinado ao Manual
    nos_af = []
    for b in df_bh:
        if b['Tipo_BIM'] == 'Conexões Hidráulicas AF':
            nos_af.append(b)
        elif b['Tipo_BIM'] == 'Aparelho Hidráulico':
            f_eq = st.session_state.bib_hidro['Equipamento'] == b['Equipamento']
            af_mm = int(st.session_state.bib_hidro.loc[f_eq, 'Agua_mm'].values[0]) if f_eq.any() else 0
            alvo_m, _, _, tem_m = obter_override_topologico_ponto(b['ID_CAD'], df_bh, max(20, af_mm))
            # Se tem ligação manual para um nó de esgoto, a ligação manual será tratada na Etapa 5 (Esgoto)
            if af_mm > 0:
                nos_af.append(b)

    alvos_base_af = prumadas_af if prumadas_af else caixas_agua
    for no_a in nos_af:
        f_eq = st.session_state.bib_hidro['Equipamento'] == no_a['Equipamento']
        af_mm_base = int(st.session_state.bib_hidro.loc[f_eq, 'Agua_mm'].values[0]) if f_eq.any() else 25
        af_mm_base = max(20, af_mm_base)

        alvo_man_af, dn_af_uso, peca_man_af, tem_man_af = obter_override_topologico_ponto(no_a['ID_CAD'], df_bh, af_mm_base)
        alvo_af = None
        tag_manual_af = ""

        # Só usa o alvo manual na Água Fria se o alvo manual NÃO for uma peça exclusiva de esgoto
        if tem_man_af and str(alvo_man_af['ID_CAD']) not in ids_esgoto_natos:
            alvo_af = alvo_man_af
            tag_manual_af = " [MANUAL]"
        else:
            # Roteamento Automático de Água Fria (conecta na conexão AF mais próxima ou na prumada/caixa d'água)
            con_andar = [c for c in conexoes_af if str(c['ID_CAD']) != str(no_a['ID_CAD']) and abs(c['z_base'] - no_a['z_base']) < 0.6]
            if no_a['Tipo_BIM'] == 'Aparelho Hidráulico' and con_andar:
                cand_af = con_andar + alvos_base_af
            else:
                cand_af = [a for a in alvos_base_af if str(a['ID_CAD']) != str(no_a['ID_CAD'])]
            if cand_af:
                alvo_af = min(cand_af, key=lambda p: dist_2d((no_a['x'], no_a['y']), (p['x'], p['y'])))

        if alvo_af is not None and str(alvo_af['ID_CAD']) != str(no_a['ID_CAD']):
            pts_2d_af = rota_a_star_2d(no_a, alvo_af, permitir_diagonal=False)
            z_orig = no_a['z_base'] + float(no_a.get('z_relativo', h_af))
            z_dest = alvo_af['z_base'] + float(alvo_af.get('z_relativo', h_af))

            # Se a origem ou o destino for uma Conexão AF (Curva, Joelho, Tê, Registro) ou estiverem na mesma cota,
            # a tubulação corre na altura real do bloco editado em vez de cair para 0.20m!
            if abs(z_orig - z_dest) <= 0.25:
                z_cam = z_orig
            elif no_a['Tipo_BIM'] == 'Conexões Hidráulicas AF':
                z_cam = z_orig
            elif alvo_af['Tipo_BIM'] == 'Conexões Hidráulicas AF':
                z_cam = z_dest
            else:
                z_cam = no_a['z_base'] + h_af

            linha_af = [(no_a['x'], no_a['y'], z_orig), (no_a['x'], no_a['y'], z_cam)]
            for px, py in pts_2d_af:
                linha_af.append((px, py, z_cam))
            linha_af.extend([(alvo_af['x'], alvo_af['y'], z_cam), (alvo_af['x'], alvo_af['y'], z_dest)])
            linha_af = aplicar_desvios_estruturais_e_vaos_3d(linha_af, elementos_arq, no_a['z_base'], no_a.get('pe_direito', 3.0), h_viga)
            j90_c, j45_c, tes_c = contar_conexoes_na_rota(linha_af)
            linhas_processadas.append({
                'pontos': linha_af, 'cor': '#0284c7',
                'tipo': f"Água Fria ({no_a['Nome_Bloco']} -> {alvo_af['Nome_Bloco']}){tag_manual_af}",
                'diametro': dn_af_uso, 'id_ap': no_a['ID_CAD'],
                'comp_acumulado_total_m': calcular_comprimento_rota(linha_af),
                'j90_acumulados': j90_c, 'tes_acumulados': max(1, tes_c)
            })

    # =========================================================================
    # ETAPA 4: ÁGUA QUENTE (CPVC / PPR - BOILER, CONEXÕES AQ E APARELHOS AQ)
    # =========================================================================
    alvos_base_aq = boilers + prumadas_aq + conexoes_aq
    for b_aq in df_bh:
        if b_aq['Tipo_BIM'] not in ['Aparelho Hidráulico', 'Conexões Hidráulicas AQ']:
            continue
        f_eq = st.session_state.bib_hidro['Equipamento'] == b_aq['Equipamento']
        aq_mm = int(st.session_state.bib_hidro.loc[f_eq, 'AQ_mm'].values[0]) if (f_eq.any() and 'AQ_mm' in st.session_state.bib_hidro.columns) else 0
        if aq_mm <= 0 and b_aq['Tipo_BIM'] != 'Conexões Hidráulicas AQ':
            continue
        aq_mm = max(22, aq_mm)
        alvo_man_aq, dn_aq_uso, _, tem_man_aq = obter_override_topologico_ponto(b_aq['ID_CAD'], df_bh, aq_mm)
        alvo_aq = alvo_man_aq if (tem_man_aq and str(alvo_man_aq['ID_CAD']) not in ids_esgoto_natos) else None
        if alvo_aq is None:
            cand_aq = [a for a in alvos_base_aq if str(a['ID_CAD']) != str(b_aq['ID_CAD'])]
            if cand_aq:
                alvo_aq = min(cand_aq, key=lambda p: dist_2d((b_aq['x'], b_aq['y']), (p['x'], p['y'])))
        if alvo_aq is not None:
            pts_2d_aq = rota_a_star_2d(b_aq, alvo_aq, permitir_diagonal=False)
            z_cam_aq = b_aq['z_base'] + h_aq
            linha_aq = [(b_aq['x'], b_aq['y'], b_aq['z_base'] + float(b_aq.get('z_relativo', h_aq))), (b_aq['x'], b_aq['y'], z_cam_aq)]
            for px, py in pts_2d_aq:
                linha_aq.append((px, py, z_cam_aq))
            linha_aq.extend([(alvo_aq['x'], alvo_aq['y'], z_cam_aq), (alvo_aq['x'], alvo_aq['y'], alvo_aq['z_base'] + float(alvo_aq.get('z_relativo', h_aq)))])
            linha_aq = aplicar_desvios_estruturais_e_vaos_3d(linha_aq, elementos_arq, b_aq['z_base'], b_aq.get('pe_direito', 3.0), h_viga)
            linhas_processadas.append({
                'pontos': linha_aq, 'cor': '#dc2626',
                'tipo': f"Água Quente ({b_aq['Nome_Bloco']} -> {alvo_aq['Nome_Bloco']})",
                'diametro': dn_aq_uso, 'id_ap': b_aq['ID_CAD']
            })

    # =========================================================================
    # ETAPA 5: ÁRVORE DE ESGOTO SANITÁRIO SUBORDINADA À TOPOLOGIA MANUAL (NBR 8160)
    # =========================================================================
    # 5.0. Tubos de Queda verticais e Colunas de Ventilação
    if prumadas_esg:
        z_topo_vent = ctx.get('max_z_cobertura', 3.0) + 0.30
        for prum_e in prumadas_esg:
            linhas_processadas.append({
                'pontos': [(prum_e['x'], prum_e['y'], z_topo_vent), (prum_e['x'], prum_e['y'], z_subsolo_af - 0.10)],
                'cor': '#5c3a21', 'tipo': f"Tubo de Queda Esgoto ({prum_e['ID_CAD']})", 'diametro': 100
            })
            linhas_processadas.append({
                'pontos': [(prum_e['x'] + 0.15, prum_e['y'], z_topo_vent), (prum_e['x'] + 0.15, prum_e['y'], 0.0)],
                'cor': '#2ca02c', 'tipo': f"Coluna de Ventilação ({prum_e['ID_CAD']})", 'diametro': 50
            })

    # 5.1. Coleta TODOS os nós que participam do esgoto (Aparelhos c/ esgoto, Conexões Esgoto, Ralos Sifonados, Caixas de Gordura, Ramais, TQs e Caixas de Inspeção)
    nos_esgoto = []
    uhc_proprio_no = {}
    dn_min_no = {}

    for b in df_bh:
        id_b = str(b['ID_CAD'])
        tb = b['Tipo_BIM']
        f_eq = st.session_state.bib_hidro['Equipamento'] == b['Equipamento']
        uhc_val = float(st.session_state.bib_hidro.loc[f_eq, 'UHC'].values[0]) if f_eq.any() else 0.0
        esg_mm = int(st.session_state.bib_hidro.loc[f_eq, 'Esgoto_mm'].values[0]) if f_eq.any() else 0
        alvo_m, dn_m, _, tem_m = obter_override_topologico_ponto(id_b, df_bh, max(40, esg_mm))

        participa_esg = False
        if tb in [
            'Caixa de Inspeção / Destino Esgoto', 'Caixa de Gordura',
            'Caixa Sifonada / Ralo Sifonado', 'Ramal de Esgoto',
            'Ramal de Descarga', 'Conexões Tubulação Esgoto', 'Prumada Esgoto'
        ]:
            participa_esg = True
        elif tb == 'Aparelho Hidráulico' and (esg_mm > 0 or (tem_m and str(alvo_m['ID_CAD']) in ids_esgoto_natos)):
            participa_esg = True

        if participa_esg:
            nos_esgoto.append(b)
            # Apenas aparelhos geram UHC na origem; caixas/conexões somam o UHC que recebem a montante
            uhc_proprio_no[id_b] = uhc_val if tb in ['Aparelho Hidráulico', 'Ramal de Descarga'] else 0.0
            if tb in ['Caixa de Inspeção / Destino Esgoto', 'Prumada Esgoto']:
                dn_min_no[id_b] = max(100, esg_mm)
            elif tb == 'Caixa de Gordura':
                dn_min_no[id_b] = max(75, esg_mm)
            elif tb in ['Caixa Sifonada / Ralo Sifonado', 'Ramal de Esgoto']:
                dn_min_no[id_b] = max(50, esg_mm)
            else:
                dn_min_no[id_b] = max(40, esg_mm)

    # 5.2. PASSO A: Registra PRIMEIRO todas as Ligações Manuais definidas pelo usuário no Inspetor 2D!
    pai_esgoto = {}       # {id_origem: bloco_destino}
    eh_link_manual = {}   # {id_origem: True/False}

    for b in nos_esgoto:
        id_b = str(b['ID_CAD'])
        alvo_m, _, _, tem_m = obter_override_topologico_ponto(id_b, df_bh, dn_min_no.get(id_b, 50))
        if tem_m and alvo_m is not None:
            pai_esgoto[id_b] = alvo_m
            eh_link_manual[id_b] = True

    def forma_ciclo_esgoto(id_origem, id_candidato_destino):
        """Impede que uma ligação automática aponte para um nó que já deságua em id_origem (evita loop infinito)."""
        atual = str(id_candidato_destino)
        visitados = set()
        while atual in pai_esgoto and pai_esgoto[atual] is not None:
            if atual == str(id_origem) or atual in visitados:
                return True
            visitados.add(atual)
            atual = str(pai_esgoto[atual]['ID_CAD'])
        return atual == str(id_origem)

    # Nós que já possuem rota manual configurada pelo usuário (atuam como atratores/coletores ativos!)
    ids_manualmente_conectados = set(pai_esgoto.keys())

    # 5.3. PASSO B: Roteamento Automático Subordinado (Apenas para os nós que NÃO têm ligação manual)
    conexoes_esg_lista = [b for b in nos_esgoto if b['Tipo_BIM'] == 'Conexões Tubulação Esgoto']
    alvos_finais_esg = prumadas_esg + caixas_inspecao

    for b in nos_esgoto:
        id_b = str(b['ID_CAD'])
        if id_b in pai_esgoto:
            # JÁ CONFIGURADO MANUALMENTE PELO USUÁRIO -> Intocável!
            continue

        tb = b['Tipo_BIM']
        eq_norm = normalizar_texto_bim(b.get('Equipamento', ''))

        # Caixa de Inspeção sem ligação manual é o destino final (não cria saída automática a menos que o usuário mande)
        if tb == 'Caixa de Inspeção / Destino Esgoto':
            continue

        opcoes_cand = []
        if tb == 'Prumada Esgoto':
            opcoes_cand = [ci for ci in caixas_inspecao if not forma_ciclo_esgoto(id_b, ci['ID_CAD'])]

        elif tb == 'Caixa de Gordura':
            # Caixa de Gordura vai para a Caixa de Inspeção mais próxima (ou conexão de 75/100mm que leve à CI)
            con_prim = [c for c in conexoes_esg_lista if dn_min_no.get(str(c['ID_CAD']), 40) >= 75 and str(c['ID_CAD']) in ids_manualmente_conectados]
            opcoes_cand = caixas_inspecao + con_prim + prumadas_esg

        elif tb == 'Caixa Sifonada / Ralo Sifonado':
            # Saída de Ralo Sifonado (DN 50/75mm) procura Conexões de Esgoto (>=50mm), Ramais de Esgoto, TQ ou Caixa de Inspeção
            con_prim = [
                c for c in conexoes_esg_lista
                if dn_min_no.get(str(c['ID_CAD']), 40) >= 50
                and dist_2d((b['x'], b['y']), (c['x'], c['y'])) <= 5.0
            ]
            opcoes_cand = con_prim + ramais_esgoto + alvos_finais_esg

        elif tb in ['Ramal de Esgoto', 'Conexões Tubulação Esgoto']:
            dn_atual = dn_min_no.get(id_b, 50)
            if dn_atual <= 40 and caixas_sifonadas:
                # Conexão secundária de 40mm procura Ralo Sifonado próximo
                opcoes_cand = [cs for cs in caixas_sifonadas if dist_2d((b['x'], b['y']), (cs['x'], cs['y'])) <= 6.0]
            if not opcoes_cand:
                # Procura outra conexão já configurada manualmente mais próxima do destino ou vai para Ramal/TQ/CI
                con_jusante = [
                    c for c in conexoes_esg_lista
                    if str(c['ID_CAD']) != id_b
                    and dn_min_no.get(str(c['ID_CAD']), 40) >= dn_atual
                    and str(c['ID_CAD']) in ids_manualmente_conectados
                    and dist_2d((b['x'], b['y']), (c['x'], c['y'])) <= 4.5
                ]
                opcoes_cand = con_jusante + ramais_esgoto + alvos_finais_esg

        elif tb in ['Aparelho Hidráulico', 'Ramal de Descarga']:
            eh_bacia = ("BACIA" in eq_norm or "VASO" in eq_norm or "SANITARIO" in eq_norm or dn_min_no.get(id_b, 40) >= 100)
            eh_cozinha = any(k in eq_norm for k in ["PIA", "COZINHA", "LAVA LOUCA", "GOURMET"])

            if eh_cozinha and caixas_gordura:
                opcoes_cand = caixas_gordura
                dn_min_no[id_b] = max(50, dn_min_no.get(id_b, 50))
            elif not eh_bacia and not eh_cozinha and caixas_sifonadas:
                cs_prox = [cs for cs in caixas_sifonadas if abs(cs['z_base'] - b['z_base']) < 0.6 and dist_2d((b['x'], b['y']), (cs['x'], cs['y'])) <= 6.5]
                opcoes_cand = cs_prox if cs_prox else (ramais_esgoto + alvos_finais_esg)
            else:
                # Bacia sanitária procura conexão de 100mm próxima (ex: Tê 100mm), Ramal de Esgoto, TQ ou Caixa de Inspeção
                con_100 = [
                    c for c in conexoes_esg_lista
                    if dn_min_no.get(str(c['ID_CAD']), 40) >= 100
                    and dist_2d((b['x'], b['y']), (c['x'], c['y'])) <= 3.5
                ]
                opcoes_cand = con_100 + ramais_esgoto + alvos_finais_esg

        # Filtra candidatos válidos que não sejam o próprio nó e não gerem loop fechado
        opcoes_validas = [
            cand for cand in opcoes_cand
            if str(cand['ID_CAD']) != id_b and not forma_ciclo_esgoto(id_b, cand['ID_CAD'])
        ]
        if opcoes_validas:
            # Prioriza nós que você já conectou manualmente se estiverem próximos, ou o mais próximo geometricamente
            escolhido = min(
                opcoes_validas,
                key=lambda c: dist_2d((b['x'], b['y']), (c['x'], c['y'])) * (0.80 if str(c['ID_CAD']) in ids_manualmente_conectados else 1.0)
            )
            pai_esgoto[id_b] = escolhido
            eh_link_manual[id_b] = False

    # 5.4. PASSO C: Propagação Topológica de UHCs (Montante -> Jusante) pela Árvore Manual + Automática
    uhc_acumulado_no = {str(b['ID_CAD']): uhc_proprio_no.get(str(b['ID_CAD']), 0.0) for b in nos_esgoto}
    for b in nos_esgoto:
        id_orig = str(b['ID_CAD'])
        uhc_add = uhc_proprio_no.get(id_orig, 0.0)
        if b['Tipo_BIM'] == 'Caixa Sifonada / Ralo Sifonado' and uhc_add == 0.0:
            uhc_add = 2.0
        elif b['Tipo_BIM'] == 'Caixa de Gordura' and uhc_add == 0.0:
            uhc_add = 6.0

        if uhc_add > 0:
            atual = id_orig
            visitados = set()
            while atual in pai_esgoto and pai_esgoto[atual] is not None:
                prox_id = str(pai_esgoto[atual]['ID_CAD'])
                if prox_id in visitados:
                    break
                visitados.add(prox_id)
                uhc_acumulado_no[prox_id] = uhc_acumulado_no.get(prox_id, 0.0) + uhc_add
                atual = prox_id

    # 5.5. PASSO D: Geração das Tubulações 3D/2D de Esgoto com Respeito Estrito ao Diâmetro e Destino Manual
    for b in nos_esgoto:
        id_b = str(b['ID_CAD'])
        if id_b not in pai_esgoto or pai_esgoto[id_b] is None:
            continue

        alvo_esg = pai_esgoto[id_b]
        foi_manual = eh_link_manual.get(id_b, False)
        uhc_trecho = max(2.0, uhc_acumulado_no.get(id_b, 2.0))
        dn_normativo = max(dn_min_no.get(id_b, 40), dimensionar_tubo_esgoto(uhc_trecho))

        # Se o usuário definiu DN_Manual_mm > 0 no Inspetor (ex: 100mm), usa o valor do usuário!
        _, diam_final_esg, peca_no_esg, _ = obter_override_topologico_ponto(id_b, df_bh, dn_normativo)
        declividade_esg = 0.01 if diam_final_esg >= 100 else 0.02

        # Para ligações entre Caixas de Inspeção ou ligações manuais diretas, permite diagonal 45° e fallback direto
        pts_2d_esg = rota_a_star_2d(b, alvo_esg, permitir_diagonal=True, forcar_direto_se_falhar=True)
        if pts_2d_esg:
            tb = b['Tipo_BIM']
            z_ini = b['z_base'] + float(b.get('z_relativo', -0.15))
            if z_ini >= b['z_base']:
                z_ini_tubo = b['z_base'] - (0.30 if tb == 'Caixa de Gordura' else (0.14 if 'Sifonad' in tb else 0.12))
                linha_esg = [(b['x'], b['y'], z_ini), (b['x'], b['y'], z_ini_tubo)]
            else:
                z_ini_tubo = z_ini
                linha_esg = [(b['x'], b['y'], z_ini_tubo)]

            dist_ac = 0.0
            pt_ant = (b['x'], b['y'])
            for px_e, py_e in pts_2d_esg:
                dist_ac += dist_2d(pt_ant, (px_e, py_e))
                linha_esg.append((px_e, py_e, round(z_ini_tubo - (dist_ac * declividade_esg), 4)))
                pt_ant = (px_e, py_e)
            linha_esg.append((alvo_esg['x'], alvo_esg['y'], round(z_ini_tubo - (dist_ac * declividade_esg), 4)))

            cor_esg = '#2563eb' if foi_manual else ('#3d2514' if tb == 'Caixa de Inspeção / Destino Esgoto' else ('#5c3a21' if tb == 'Caixa de Gordura' else ('#8b4513' if 'Sifonad' in tb else 'brown')))
            tag_m = " [MANUAL]" if foi_manual else ""
            linhas_processadas.append({
                'pontos': linha_esg,
                'cor': '#7c2d12' if foi_manual else cor_esg,
                'tipo': f"Esgoto ({b['Nome_Bloco']} -> {alvo_esg['Nome_Bloco']}){tag_m}",
                'diametro': diam_final_esg,
                'declividade_pct': declividade_esg * 100,
                'equipamento': b.get('Equipamento', ''),
                'id_ap': b['ID_CAD'],
                'prumada_ref': alvo_esg['ID_CAD'],
                'uhc_acumulado_no': uhc_trecho,
                'manual': foi_manual
            })

    return linhas_processadas

def rotear_eletrica(df_be, ctx, evitar_linhas=None):
    """
    Motor Elétrico 3D/2D Subordinado às Ligações Manuais do Inspetor:
    - Qualquer ponto elétrico com Conectado_A manual liga-se diretamente ao alvo escolhido;
    - Os demais pontos se readequam automaticamente em cascata ou rumo ao QDG.
    """
    linhas_processadas = []
    if not df_be:
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
        if elem.get('Tipo') == 'Pilar/Viga' and 'PILAR' in str(elem.get('ID_CAD', '')).upper():
            px, py = escalar_coord(elem['x'] - ctx['min_x'] + ctx['offset']), escalar_coord(elem['y'] - ctx['min_y'] + ctx['offset'])
            bloquear_caixa_estrutural(matriz, px, py, ctx['grid_w'], ctx['grid_h'], raio=2)

    liberar_vaos_esquadrias_na_matriz(matriz, elementos_arq, ctx)

    if evitar_linhas:
        for l_hid in evitar_linhas:
            for pt_h in l_hid.get('pontos', []):
                hx = escalar_coord(pt_h[0] - ctx['min_x'] + ctx['offset'])
                hy = escalar_coord(pt_h[1] - ctx['min_y'] + ctx['offset'])
                if 0 <= hy < ctx['grid_h'] and 0 <= hx < ctx['grid_w']:
                    matriz[hy][hx] = 0

    h_viga = ctx.get('altura_viga', 0.40)
    rotear_cascata = ctx.get('rotear_em_cascata', True)

    def rota_a_star_elet(orig, dest):
        ox = max(0, min(ctx['grid_w'] - 1, escalar_coord(orig['x'] - ctx['min_x'] + ctx['offset'])))
        oy = max(0, min(ctx['grid_h'] - 1, escalar_coord(orig['y'] - ctx['min_y'] + ctx['offset'])))
        dx = max(0, min(ctx['grid_w'] - 1, escalar_coord(dest['x'] - ctx['min_x'] + ctx['offset'])))
        dy = max(0, min(ctx['grid_h'] - 1, escalar_coord(dest['y'] - ctx['min_y'] + ctx['offset'])))
        liberar_caixa(matriz, ox, oy, ctx['grid_w'], ctx['grid_h'], raio=2)
        liberar_caixa(matriz, dx, dy, ctx['grid_w'], ctx['grid_h'], raio=2)
        grid = Grid(matrix=matriz)
        finder = AStarFinder(diagonal_movement=DiagonalMovement.never)
        caminho, _ = finder.find_path(grid.node(ox, oy), grid.node(dx, dy), grid)
        pts = [(desescalar_coord(p.x) + ctx['min_x'] - ctx['offset'], desescalar_coord(p.y) + ctx['min_y'] - ctx['offset']) for p in caminho]
        return pts if pts else [(orig['x'], orig['y']), (dest['x'], dest['y'])]

    quadros = [b for b in df_be if b.get('Tipo_BIM') == 'Quadro Geral']
    if not quadros:
        quadros = [df_be[0]]

    caixas_passagem = [b for b in df_be if b.get('Tipo_BIM') in ['Caixa de Passagem', 'Conexão / Eletroduto']]
    luminarias = [b for b in df_be if b.get('Tipo_BIM') == 'Luminária']
    caixas_tom_int = [b for b in df_be if b.get('Tipo_BIM') in ['Caixa 4x2', 'Caixa 4x4']]

    # 1. CAIXAS DE PASSAGEM E CONEXÕES DE ELETRODUTO
    for cp in caixas_passagem:
        alvo_man, dn_cp, _, tem_m = obter_override_topologico_ponto(cp['ID_CAD'], df_be, 25)
        qdg_alvo = alvo_man if tem_m else min(quadros, key=lambda q: abs(q['z_base'] - cp['z_base']) * 4 + dist_2d((cp['x'], cp['y']), (q['x'], q['y'])))
        if qdg_alvo['ID_CAD'] == cp['ID_CAD']:
            continue
        pts_2d = rota_a_star_elet(cp, qdg_alvo)
        z_cp = cp['z_base'] + float(cp.get('z_relativo', 1.30))
        z_qdg = qdg_alvo['z_base'] + float(qdg_alvo.get('z_relativo', 1.50))
        linha_3d = [(cp['x'], cp['y'], z_cp)] + [(px, py, z_cp) for px, py in pts_2d] + [(qdg_alvo['x'], qdg_alvo['y'], z_cp), (qdg_alvo['x'], qdg_alvo['y'], z_qdg)]
        linha_3d = aplicar_desvios_estruturais_e_vaos_3d(linha_3d, elementos_arq, cp['z_base'], cp.get('pe_direito', 3.0), h_viga)
        linhas_processadas.append({
            'pontos': linha_3d, 'cor': '#ca8a04', 'fios': 'F N T', 'diametro': dn_cp,
            'comprimento_m': round(calcular_comprimento_rota(linha_3d), 2), 'id_origem': cp['ID_CAD'],
            'tipo': f"Eletroduto Passagem ({cp['ID_CAD']} -> {qdg_alvo['ID_CAD']})" + (" [MANUAL]" if tem_m else "")
        })

    # 2. LUMINÁRIAS
    for lum in luminarias:
        alvo_man, dn_lum, _, tem_m = obter_override_topologico_ponto(lum['ID_CAD'], df_be, 20)
        qdg_alvo = alvo_man if tem_m else min(quadros, key=lambda q: abs(q['z_base'] - lum['z_base']) * 4 + dist_2d((lum['x'], lum['y']), (q['x'], q['y'])))
        if qdg_alvo['ID_CAD'] == lum['ID_CAD']:
            continue
        pts_2d = rota_a_star_elet(lum, qdg_alvo)
        z_teto = lum['z_base'] + float(lum.get('z_relativo', lum.get('pe_direito', 3.0))) - 0.05
        z_qdg = qdg_alvo['z_base'] + float(qdg_alvo.get('z_relativo', 1.50))
        linha_3d = [(lum['x'], lum['y'], z_teto)] + [(px, py, z_teto) for px, py in pts_2d] + [(qdg_alvo['x'], qdg_alvo['y'], z_teto), (qdg_alvo['x'], qdg_alvo['y'], z_qdg)]
        linha_3d = aplicar_desvios_estruturais_e_vaos_3d(linha_3d, elementos_arq, lum['z_base'], lum.get('pe_direito', 3.0), h_viga)
        fios_lum = "F F T" if int(lum.get('Tensao_V', 127)) == 220 else "F N T"
        linhas_processadas.append({
            'pontos': linha_3d, 'cor': '#eab308', 'fios': fios_lum, 'diametro': dn_lum,
            'comprimento_m': round(calcular_comprimento_rota(linha_3d), 2), 'id_origem': lum['ID_CAD'],
            'tipo': f"Eletroduto Iluminação ({lum['ID_CAD']} -> {qdg_alvo['ID_CAD']})" + (" [MANUAL]" if tem_m else "")
        })

    # 3. TOMADAS E INTERRUPTORES (SUBORDINADOS AO VÍNCULO MANUAL)
    nos_alimentados = list(quadros) + list(caixas_passagem)
    caixas_ordenadas = sorted(caixas_tom_int, key=lambda c: min(dist_2d((c['x'], c['y']), (q['x'], q['y'])) for q in quadros))

    for cx in caixas_ordenadas:
        alvo_man, dn_el_uso, _, tem_m = obter_override_topologico_ponto(cx['ID_CAD'], df_be, 25)
        if tem_m or int(cx.get('Qtd_Tomadas', 0)) > 0 or int(cx.get('Qtd_Interruptores', 0)) == 0:
            eq_ass = str(cx.get('Equipamento_Associado', ''))
            eh_tue = (int(cx.get('Tensao_V', 127)) == 220 and cx.get('Amperagem_Tomadas') == '20A') or any(k in eq_ass.upper() for k in ["CHUVEIRO", "AR-CONDICIONADO", "SPLIT", "HIDROMASSAGEM", "BOILER", "COOKTOP", "FORNO", "TORNEIRA"])

            if tem_m and alvo_man is not None:
                alvo_el = alvo_man
            else:
                opcoes_dest = (list(quadros) + list(caixas_passagem)) if (eh_tue or not rotear_cascata) else [n for n in nos_alimentados if abs(n['z_base'] - cx['z_base']) < 0.6 and n['ID_CAD'] != cx['ID_CAD']]
                if not opcoes_dest:
                    opcoes_dest = [q for q in quadros if q['ID_CAD'] != cx['ID_CAD']]
                alvo_el = min(opcoes_dest, key=lambda n: dist_2d((cx['x'], cx['y']), (n['x'], n['y']))) if opcoes_dest else cx

            if alvo_el['ID_CAD'] != cx['ID_CAD']:
                pts_2d = rota_a_star_elet(cx, alvo_el)
                z_cx = cx['z_base'] + float(cx.get('z_relativo', 0.30))
                z_alvo = alvo_el['z_base'] + float(alvo_el.get('z_relativo', 1.30))
                z_travessia = z_cx if abs(z_cx - z_alvo) < 0.4 else min(max(z_cx, 0.35), 1.30)
                linha_3d = [(cx['x'], cx['y'], z_cx), (cx['x'], cx['y'], z_travessia)] + [(px, py, z_travessia) for px, py in pts_2d] + [(alvo_el['x'], alvo_el['y'], z_travessia), (alvo_el['x'], alvo_el['y'], z_alvo)]
                linha_3d = aplicar_desvios_estruturais_e_vaos_3d(linha_3d, elementos_arq, cx['z_base'], cx.get('pe_direito', 3.0), h_viga)
                fios_tom = "F F T" if int(cx.get('Tensao_V', 127)) == 220 else "F N T"
                linhas_processadas.append({
                    'pontos': linha_3d, 'cor': '#dc2626' if eh_tue else '#16a34a', 'fios': fios_tom,
                    'diametro': dn_el_uso, 'comprimento_m': round(calcular_comprimento_rota(linha_3d), 2),
                    'id_origem': cx['ID_CAD'],
                    'tipo': ('Eletroduto TUE' if eh_tue else 'Eletroduto Tomadas') + f" ({cx['ID_CAD']} -> {alvo_el['ID_CAD']})" + (" [MANUAL]" if tem_m else "")
                })
                if not eh_tue and cx not in nos_alimentados:
                    nos_alimentados.append(cx)

        if int(cx.get('Qtd_Interruptores', 0)) > 0 and not tem_m:
            lums_ctrl_str = str(cx.get('Luminarias_Controladas', '')).strip()
            lums_alvo = [l for l in luminarias if l['ID_CAD'] in lums_ctrl_str.split(",")] if lums_ctrl_str else []
            if not lums_alvo and luminarias:
                lums_andar = [l for l in luminarias if abs(l['z_base'] - cx['z_base']) < 0.6]
                if lums_andar:
                    lums_alvo = [min(lums_andar, key=lambda l: dist_2d((cx['x'], cx['y']), (l['x'], l['y'])))]
            qtd_i = int(cx.get('Qtd_Interruptores', 1))
            fios_ret = "F R1 R2" if ("PARALELO" in str(cx.get('Nome_Bloco', '')).upper() or qtd_i == 2) else ("F R1 R2 R3" if qtd_i >= 3 else "F R")
            for lum_dest in lums_alvo:
                pts_2d_r = rota_a_star_elet(cx, lum_dest)
                z_int = cx['z_base'] + float(cx.get('z_relativo', 1.20))
                z_lum = lum_dest['z_base'] + float(lum_dest.get('z_relativo', lum_dest.get('pe_direito', 3.0))) - 0.05
                linha_ret = [(cx['x'], cx['y'], z_int), (cx['x'], cx['y'], z_lum)] + [(px, py, z_lum) for px, py in pts_2d_r] + [(lum_dest['x'], lum_dest['y'], z_lum)]
                linha_ret = aplicar_desvios_estruturais_e_vaos_3d(linha_ret, elementos_arq, cx['z_base'], cx.get('pe_direito', 3.0), h_viga)
                linhas_processadas.append({
                    'pontos': linha_ret, 'cor': '#f59e0b', 'fios': fios_ret, 'diametro': dn_el_uso,
                    'comprimento_m': round(calcular_comprimento_rota(linha_ret), 2), 'id_origem': cx['ID_CAD'],
                    'tipo': f"Retorno Interruptor ({fios_ret})"
                })

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

        if 'Água Fria' in tipo or 'Barrilete' in tipo or 'AF' in tipo:
            add_item(bom_af, f"Tubo PVC Soldável Marrom DN {dn}mm", "m", round(comp_m * 1.05, 1))
            if joelhos_90 > 0: add_item(bom_af, f"Joelho 90° Soldável {dn}mm", "un", joelhos_90)
            if joelhos_45 > 0: add_item(bom_af, f"Joelho 45° Soldável {dn}mm", "un", joelhos_45)
            add_item(bom_af, f"Tê Soldável {dn}mm", "un", 1)
            add_item(bom_af, f"Luva Soldável {dn}mm", "un", luvas)
            if 'Barrilete' not in tipo:
                add_item(bom_af, f"Joelho 90° c/ Bucha de Latão {dn}mm x 1/2\"", "un", 1)
                add_item(bom_af, f"Registro de Pressão / Gaveta {dn}mm", "un", 1)
        elif 'Água Quente' in tipo or 'AQ' in tipo or 'Gás' in tipo:
            mat_nome = "Cobre/PEX Gás (NBR 15526)" if 'Gás' in tipo else "CPVC/PPR Água Quente"
            add_item(bom_aq, f"Tubo {mat_nome} DN {dn}mm", "m", round(comp_m * 1.05, 1))
            if joelhos_90 > 0: add_item(bom_aq, f"Joelho 90° {mat_nome} {dn}mm", "un", joelhos_90)
            if joelhos_45 > 0: add_item(bom_aq, f"Joelho 45° {mat_nome} {dn}mm", "un", joelhos_45)
            add_item(bom_aq, f"Tê {mat_nome} {dn}mm", "un", 1)
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
    "Tê de Passagem Direta / Derivação",
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
    if not txt:
        return ""
    s = "".join(c for c in unicodedata.normalize("NFD", str(txt)) if unicodedata.category(c) != "Mn")
    return s.upper().replace("_", " ").replace("-", " ").strip()

def extrair_handles_bloco_dinamico(obj_dxf):
    handles = []
    if obj_dxf is None:
        return handles
    try:
        if hasattr(obj_dxf, "xdata") and obj_dxf.xdata:
            for appid in obj_dxf.xdata.data.keys():
                for code, val in obj_dxf.get_xdata(appid):
                    if code in (1005, 340, 341, 330):
                        handles.append(str(val))
    except Exception:
        pass
    try:
        if hasattr(obj_dxf, "tags"):
            for tag in obj_dxf.tags:
                if tag.code in (1005, 340, 341, 330):
                    handles.append(str(tag.value))
    except Exception:
        pass
    return handles

def extrair_nome_real_bloco_dxf(doc, entidade_insert):
    nome_bruto = str(entidade_insert.dxf.name)
    layer_nome = str(entidade_insert.dxf.layer)

    if not nome_bruto.startswith("*U"):
        return nome_bruto

    handles_testar = []
    handles_testar.extend(extrair_handles_bloco_dinamico(entidade_insert))

    try:
        if entidade_insert.has_extension_dict:
            xdict = entidade_insert.get_extension_dict()
            for _, v_obj in xdict.items():
                handles_testar.extend(extrair_handles_bloco_dinamico(v_obj))
                if hasattr(v_obj, "items"):
                    for _, sub_obj in v_obj.items():
                        handles_testar.extend(extrair_handles_bloco_dinamico(sub_obj))
    except Exception:
        pass

    try:
        if nome_bruto in doc.block_records:
            blk_rec = doc.block_records.get(nome_bruto)
            handles_testar.extend(extrair_handles_bloco_dinamico(blk_rec))
            if blk_rec.has_extension_dict:
                xdict_br = blk_rec.get_extension_dict()
                for _, v_obj in xdict_br.items():
                    handles_testar.extend(extrair_handles_bloco_dinamico(v_obj))
                    if hasattr(v_obj, "items"):
                        for _, sub_obj in v_obj.items():
                            handles_testar.extend(extrair_handles_bloco_dinamico(sub_obj))
    except Exception:
        pass

    for h_cand in handles_testar:
        try:
            ent_ref = doc.entitydb.get(h_cand)
            if ent_ref is not None and ent_ref.dxftype() in ("BLOCK_RECORD", "BLOCK"):
                nome_original = str(ent_ref.dxf.name).strip()
                if nome_original and not nome_original.startswith("*"):
                    return f"{nome_original} ({nome_bruto})"
        except Exception:
            pass

    textos_encontrados = []
    try:
        for att in entidade_insert.attribs:
            if att.dxf.text and len(str(att.dxf.text).strip()) >= 1:
                textos_encontrados.append(str(att.dxf.text).strip())
    except Exception:
        pass

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
                    if t_val and len(str(t_val).strip()) >= 1:
                        textos_encontrados.append(str(t_val).strip())
                elif dxft == "INSERT" and not str(sub_e.dxf.name).startswith("*U"):
                    textos_encontrados.append(str(sub_e.dxf.name).strip())
    except Exception:
        pass

    if textos_encontrados:
        resumo_txt = " ".join(dict.fromkeys(textos_encontrados))[:35]
        return f"{resumo_txt} ({nome_bruto})"

    return f"{nome_bruto} [{layer_nome}]"

def classificar_bloco_hidro_inteligente(nome_bloco, layer_bloco, opcoes_equip):
    nome_sem_parenteses = str(nome_bloco).split("(")[0].split("[")[0].strip()
    nome_norm = normalizar_texto_bim(nome_sem_parenteses)
    layer_norm = normalizar_texto_bim(layer_bloco)
    alvo = f"{nome_norm} {layer_norm}".strip()
    palavras_alvo = set(alvo.split())
    opcoes_norm = {normalizar_texto_bim(op): op for op in opcoes_equip}

    eh_aq = any(k in alvo for k in ["AGUA QUENTE", "QUENTE", "AQ", "CPVC", "PPR"])
    eh_esg = any(k in alvo for k in ["ESGOTO", "ESG", "SANIT", "PLUVIAL"]) and not any(k in alvo for k in ["AGUA FRIA", "HIDRICO"])

    def buscar_na_bib(termo_exato):
        t_norm = normalizar_texto_bim(termo_exato)
        if t_norm in opcoes_norm:
            return opcoes_norm[t_norm]
        for k_norm, op_real in opcoes_norm.items():
            if t_norm in k_norm:
                return op_real
        return opcoes_equip[0] if opcoes_equip else ""

    eh_te = (nome_norm in ["TE", "T", "TE 90", "TE SOLDAVEL"] or "TE" in palavras_alvo or nome_norm.startswith("TE "))
    eh_curva = (nome_norm in ["CURVA", "C", "CURVA 90", "CURVA 45"] or "CURVA" in palavras_alvo)
    eh_joelho = (nome_norm in ["JOELHO", "J", "JOELHO 90", "JOELHO 45", "COTOVELO"] or "JOELHO" in palavras_alvo)
    eh_juncao = (nome_norm in ["JUNCAO", "Y", "JUNCAO Y", "JUNCAO 45"] or "JUNCAO" in palavras_alvo)

    dn_explicito = None
    for dn_cand in ["100", "75", "50", "40", "32", "28", "25", "22", "20"]:
        if f"{dn_cand}MM" in nome_norm.replace(" ", "") or f" {dn_cand} " in f" {nome_norm} ":
            dn_explicito = dn_cand
            break

    if eh_te:
        if eh_esg:
            dn_uso = dn_explicito if dn_explicito in ["40", "50", "75", "100"] else "50"
            return "Conexões Tubulação Esgoto", buscar_na_bib(f"Tê Esgoto {dn_uso}mm"), 0.0
        elif eh_aq:
            return "Conexões Hidráulicas AQ", buscar_na_bib("Tê (Passagem Direta) 22mm"), 0.6
        else:
            dn_uso = dn_explicito if dn_explicito in ["22", "25", "32"] else "25"
            return "Conexões Hidráulicas AF", buscar_na_bib(f"Tê (Passagem Direta) {dn_uso}mm"), 0.6

    if eh_curva:
        if eh_esg:
            dn_uso = dn_explicito if dn_explicito in ["40", "50", "75", "100"] else "50"
            return "Conexões Tubulação Esgoto", buscar_na_bib(f"Curva 90° Esgoto {dn_uso}mm"), 0.0
        elif eh_aq:
            return "Conexões Hidráulicas AQ", buscar_na_bib("Curva 90° 22mm"), 0.6
        else:
            dn_uso = dn_explicito if dn_explicito in ["22", "25", "32"] else "25"
            return "Conexões Hidráulicas AF", buscar_na_bib(f"Curva 90° {dn_uso}mm"), 0.6

    if eh_joelho:
        grau = "45°" if "45" in nome_norm else "90°"
        if eh_esg:
            dn_uso = dn_explicito if dn_explicito in ["40", "50", "75", "100"] else "50"
            return "Conexões Tubulação Esgoto", buscar_na_bib(f"Joelho {grau} Esgoto {dn_uso}mm"), 0.0
        elif eh_aq:
            return "Conexões Hidráulicas AQ", buscar_na_bib(f"Joelho {grau} 22mm"), 0.6
        else:
            dn_uso = dn_explicito if dn_explicito in ["22", "25", "32"] else "25"
            return "Conexões Hidráulicas AF", buscar_na_bib(f"Joelho {grau} {dn_uso}mm"), 0.6

    if eh_juncao:
        if eh_aq:
            return "Conexões Hidráulicas AQ", buscar_na_bib("Junção Y 22mm"), 0.6
        elif "AGUA FRIA" in alvo or "AF" in palavras_alvo:
            dn_uso = dn_explicito if dn_explicito in ["22", "25", "32"] else "25"
            return "Conexões Hidráulicas AF", buscar_na_bib(f"Junção Y {dn_uso}mm"), 0.6
        else:
            dn_uso = dn_explicito if dn_explicito in ["40", "50", "75", "100"] else "50"
            return "Conexões Tubulação Esgoto", buscar_na_bib(f"Junção Y Esgoto {dn_uso}mm"), 0.0

    if any(k in nome_norm for k in ["TUBULACAO", "TUBO"]) and not any(k in nome_norm for k in ["QUEDA", "SUBIDA"]):
        if eh_aq:
            dn_uso = "28" if "28" in nome_norm else "22"
            return "Conexões Hidráulicas AQ", buscar_na_bib(f"Tubulação Água Quente {dn_uso}mm"), 1.0
        elif eh_esg:
            dn_uso = dn_explicito if dn_explicito in ["40", "50", "75", "100"] else "50"
            return "Conexões Tubulação Esgoto", buscar_na_bib(f"Tubulação Esgoto {dn_uso}mm"), -0.15
        else:
            dn_uso = dn_explicito if dn_explicito in ["20", "25", "32", "40", "50"] else "25"
            return "Conexões Hidráulicas AF", buscar_na_bib(f"Tubulação Água Fria {dn_uso}mm"), 0.2

    altura_cx_padrao = float(st.session_state.get("altura_caixa_3d", 1.50))

    regras_hidro = [
        (["CAIXA DE INSPECAO", "CX INSPECAO", "INSPECAO", "CI", "DESTINO ESGOTO", "FOSSA"], "Caixa de Inspeção / Destino Esgoto", "Caixa de Inspeção", -0.50),
        (["CAIXA DE GORDURA DUPLA", "CGD"], "Caixa de Gordura", "Caixa de Gordura Dupla (CGD 120L - 2 a 12 Cozinhas - Saída 100mm)", -0.35),
        (["CAIXA DE GORDURA", "CX GORDURA", "GORDURA", "CG", "CGS", "CGP"], "Caixa de Gordura", "Caixa de Gordura Simples (CGS 31L - 1 a 2 Cozinhas - Saída 75mm)", -0.30),
        (["CAIXA SIFONADA", "CX SIF", "CS", "150X150"], "Caixa Sifonada / Ralo Sifonado", "Caixa Sifonada 150x150x50mm", 0.00),
        (["RALO SIFONADO", "RS", "CX SIFONADA 100"], "Caixa Sifonada / Ralo Sifonado", "Ralo Sifonado", 0.00),
        (["CAIXA DE PASSAGEM", "CX PASSAGEM", "CP"], "Ramal de Esgoto", "Caixa de Passagem", 0.00),
        (["CAIXA D'AGUA", "CAIXA DAGUA", "CAIXA D AGUA", "RESERVATORIO SUP", "CX AGUA", "CX DAGUA"], "Caixa d'Água", "Caixa d'Água (Reservatório Superior)", altura_cx_padrao),
        (["CISTERNA", "RESERVATORIO INF"], "CAIXA D AGUA", "Cisterna (Reservatório Inferior)", 0.00),
        (["RAMAL DE DESCARGA", "RAMAL DESCARGA", "RD"], "Ramal de Descarga", "Ramal de Descarga Esgoto 40mm (Lavatório/Ralo)", -0.10),
        (["RAMAL DE ESGOTO", "RAMAL ESGOTO", "RE", "COLETOR ESGOTO"], "Ramal de Esgoto", "Ramal de Esgoto Coletor 100mm (NBR 8160)", -0.18),
        (["QUEDA AF", "TQ AF", "DESCIDA AF", "QUEDA AGUA FRIA"], "Tubo de Queda Água Fria", "Tubo de Queda Água Fria (TQ-AF 32mm)", 0.00),
        (["SUBIDA AF", "CS AF", "COLUNA SUBIDA AF", "SUBIDA AGUA FRIA", "RECALQUE"], "Coluna de Subida Água Fria", "Coluna de Subida Água Fria (CS-AF 32mm)", 0.00),
        (["QUEDA AQ", "TQ AQ", "DESCIDA AQ", "QUEDA AGUA QUENTE"], "Tubo de Queda Água Quente", "Tubo de Queda Água Quente (TQ-AQ 28mm)", 0.00),
        (["SUBIDA AQ", "CS AQ", "COLUNA SUBIDA AQ", "SUBIDA AGUA QUENTE"], "Coluna de Subida Água Quente", "Coluna de Subida Água Quente (CS-AQ 28mm)", 0.00),
        (["PRUMADA AF", "COLUNA AF", "PRUMADA AGUA"], "Prumada Água Fria", "Saída de Água Fria 32mm", 2.20),
        (["TUBO DE QUEDA", "TUBO QUEDA", "PRUMADA ESG", "COLUNA ESG", "TQ"], "Prumada Esgoto", "Tubo de Queda (TQ - Esgoto Primário)", 0.00),
        (["VENTILACAO", "COLUNA VENT", "CV"], "Prumada Esgoto", "Coluna de Ventilação", 0.00),
        (["RALO SECO", "RSE"], "Ramal de Descarga", "Ralo Seco (Chuveiro)", 0.00),
        (["RALO LINEAR", "RALO BOX"], "Ramal de Descarga", "Ralo Linear Inox (Box Banheiro)", 0.00),
        (["RALO VARANDA", "RALO SACADA"], "Ramal de Descarga", "Ralo de Varanda/Sacada", 0.00),
        (["BACIA", "VASO", "SANITARIO", "BS", "VS"], "Aparelho Hidráulico", "Bacia Sanitária (Caixa Acoplada) - Popular", 0.20),
        (["DUCHA HIG", "DH", "BIDE"], "Aparelho Hidráulico", "Ducha Higiênica", 0.60),
        (["CHUVEIRO MIST", "DUCHA MIST"], "Aparelho Hidráulico", "Chuveiro Misturador (Água Fria + Quente)", 2.10),
        (["CHUVEIRO", "DUCHA", "CH"], "Aparelho Hidráulico", "Chuveiro Elétrico Padrão", 2.10),
        (["BANHEIRA", "HIDROMASSAGEM", "SPA"], "Aparelho Hidráulico", "Banheira Hidromassagem", 0.40),
        (["LAVATORIO", "LV", "CUBA BANH", "BANCADA BANH"], "Aparelho Hidráulico", "Lavatório/Pia (Residencial)", 0.60),
        (["PIA GOURMET", "CUBA DUPLA", "TORNEIRA GOURMET"], "Aparelho Hidráulico", "Pia de Cozinha - Cuba Dupla Gourmet", 0.90),
        (["PIA", "COZINHA", "CUBA"], "Aparelho Hidráulico", "Pia de Cozinha (Residencial)", 0.90),
        (["LAVA LOUCA", "MLL"], "Aparelho Hidráulico", "Máquina de Lavar Louça", 0.60),
        (["LAVAR ROUPA", "MLR", "MAQUINA DE LAVAR", "LAVADORA"], "Aparelho Hidráulico", "Máquina de Lavar Roupa", 0.90),
        (["TANQUE", "TQ ROUPA", "TQ LAV"], "Aparelho Hidráulico", "Tanque de Lavar Roupa", 0.65),
        (["FILTRO", "PURIFICADOR"], "Aparelho Hidráulico", "Filtro/Purificador de Parede", 1.35),
        (["BEBEDOURO"], "Aparelho Hidráulico", "Bebedouro", 0.90),
        (["GELADEIRA", "SIDE BY SIDE"], "Aparelho Hidráulico", "Geladeira Side-by-Side (Filtro/Gelo)", 1.35),
        (["MICTORIO"], "Aparelho Hidráulico", "Mictório Cerâmico (c/ válvula)", 0.60),
        (["TORNEIRA QUINTAL", "JARDIM", "EXTERNA"], "Aparelho Hidráulico", "Torneira quintal", 0.60),
        (["REGISTRO DE PRESSAO", "REG PRESSAO", "RP"], "Conexões Hidráulicas AF", "Registro de Pressão 25mm (3/4)", 1.10),
        (["REGISTRO DE GAVETA", "REG GAVETA", "RG"], "Conexões Hidráulicas AF", "Registro de Gaveta 25mm (3/4)", 1.80),
        (["VRP", "REDUTORA DE PRESSAO"], "Conexões Hidráulicas AF", "Válvula Redutora de Pressão (VRP) 32mm", 1.50),
        (["RETENCAO"], "Conexões Hidráulicas AF", "Válvula de Retenção 25mm", 0.50),
        (["BOMBA", "PRESSURIZADORA"], "Aparelho Hidráulico", "Bomba Pressurizadora Residencial", 0.30),
        (["BOILER", "AQUECEDOR"], "Boiler / Aquecedor", "Boiler (Aquecimento de Água Central)", 1.50),
        (["GAS", "GLP", "FOGAO"], "Aparelho Hidráulico", "Ponto de Gás (Fogão/Aquecedor)", 0.60),
        (["AGUA QUENTE 28", "AQ 28"], "Conexões Hidráulicas AQ", "Tubulação Água Quente 28mm", 1.00),
        (["AGUA QUENTE", "AQ"], "Conexões Hidráulicas AQ", "Tubulação Água Quente 22mm", 1.00),
        (["AGUA FRIA 50", "AF 50"], "Conexões Hidráulicas AF", "Tubulação Água Fria 50mm", 0.20),
        (["AGUA FRIA 40", "AF 40"], "Conexões Hidráulicas AF", "Tubulação Água Fria 40mm", 0.20),
        (["AGUA FRIA 32", "AF 32"], "Conexões Hidráulicas AF", "Tubulação Água Fria 32mm", 0.20),
        (["AGUA FRIA 20", "AF 20"], "Conexões Hidráulicas AF", "Tubulação Água Fria 20mm", 0.20),
        (["AGUA FRIA", "AF"], "Conexões Hidráulicas AF", "Tubulação Água Fria 25mm", 0.20),
        (["ESGOTO 100", "ESG 100", "TUBO 100", "TUBULACAO 100", "PRIMARIO", "SUBCOLETOR"], "Conexões Tubulação Esgoto", "Tubulação Esgoto 100mm", -0.20),
        (["ESGOTO 75", "ESG 75", "TUBO 75", "TUBULACAO 75"], "Conexões Tubulação Esgoto", "Tubulação Esgoto 75mm", -0.18),
        (["ESGOTO 40", "ESG 40", "TUBO 40", "TUBULACAO 40", "SECUNDARIO"], "Conexões Tubulação Esgoto", "Tubulação Esgoto 40mm", -0.10),
        (["ESGOTO 50", "ESG 50", "TUBO 50", "TUBULACAO 50"], "Conexões Tubulação Esgoto", "Tubulação Esgoto 50mm", -0.15),
        (["ESGOTO", "ESG"], "Conexões Tubulação Esgoto", "Tubulação Esgoto 100mm", -0.15),
    ]

    for palavras, func_bim, eq_padrao, z_rel in regras_hidro:
        for p in palavras:
            if (len(p) <= 2 and p in palavras_alvo) or (len(p) > 2 and p in alvo):
                return func_bim, buscar_na_bib(eq_padrao), z_rel

    similares = difflib.get_close_matches(nome_norm, list(opcoes_norm.keys()), n=1, cutoff=0.50)
    if similares:
        eq_sim = opcoes_norm[similares[0]]
        if any(k in eq_sim.upper() for k in ["CURVA", "JOELHO", "TÊ", "JUNÇÃO"]):
            if eh_aq:
                return "Conexões Hidráulicas AQ", buscar_na_bib(eq_sim.replace("32mm", "22mm").replace("25mm", "22mm")), 0.6
            elif not eh_esg:
                return "Conexões Hidráulicas AF", buscar_na_bib(eq_sim.replace("32mm", "25mm").replace("22mm", "25mm")), 0.6
        return "Aparelho Hidráulico", eq_sim, 0.5

    return "Aparelho Hidráulico", (opcoes_equip[0] if opcoes_equip else ""), 0.5

def garantir_itens_extras_na_bib_eletrica():
    """Garante na bib_eletrica as opções de Eletrodutos 25mm, Conexões, Caixas de Passagem e TUEs 220V."""
    novos_elet = [
        {"Equipamento": "Sem Carga (Apenas Interruptor / Passagem / Conexão)", "Potência (W)": 0, "Tensão (V)": 127, "Fator de Potência": 1.00, "Tipo": "Passagem", "Curva Disjuntor": "B", "Uso de DR": "Opcional"},
        {"Equipamento": "Eletroduto Corrugado/Rígido 25mm (Passagem)", "Potência (W)": 0, "Tensão (V)": 127, "Fator de Potência": 1.00, "Tipo": "Passagem", "Curva Disjuntor": "B", "Uso de DR": "Opcional"},
        {"Equipamento": "Curva / Joelho 90° Eletroduto 25mm", "Potência (W)": 0, "Tensão (V)": 127, "Fator de Potência": 1.00, "Tipo": "Passagem", "Curva Disjuntor": "B", "Uso de DR": "Opcional"},
        {"Equipamento": "Caixa de Passagem Elétrica 4x2 / 4x4 / Octogonal", "Potência (W)": 0, "Tensão (V)": 127, "Fator de Potência": 1.00, "Tipo": "Passagem", "Curva Disjuntor": "B", "Uso de DR": "Opcional"},
        {"Equipamento": "Tomada Uso Geral (TUG)", "Potência (W)": 100, "Tensão (V)": 127, "Fator de Potência": 0.95, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Opcional"},
        {"Equipamento": "Tomada Bancada Cozinha / Área de Serviço (600W)", "Potência (W)": 600, "Tensão (V)": 127, "Fator de Potência": 0.95, "Tipo": "TUG", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
        {"Equipamento": "Lâmpada / Painel LED (Iluminação)", "Potência (W)": 100, "Tensão (V)": 127, "Fator de Potência": 0.95, "Tipo": "Iluminação", "Curva Disjuntor": "B", "Uso de DR": "Opcional"},
        {"Equipamento": "Chuveiro Elétrico (220V)", "Potência (W)": 6800, "Tensão (V)": 220, "Fator de Potência": 1.00, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
        {"Equipamento": "Ar-Condicionado Split Inverter (220V)", "Potência (W)": 1500, "Tensão (V)": 220, "Fator de Potência": 0.92, "Tipo": "TUE", "Curva Disjuntor": "C", "Uso de DR": "Opcional"},
        {"Equipamento": "Bomba Hidromassagem / Spa (220V)", "Potência (W)": 1500, "Tensão (V)": 220, "Fator de Potência": 0.85, "Tipo": "TUE", "Curva Disjuntor": "C", "Uso de DR": "Obrigatório"},
        {"Equipamento": "Aquecedor de Água / Boiler Elétrico (220V)", "Potência (W)": 3000, "Tensão (V)": 220, "Fator de Potência": 1.00, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
        {"Equipamento": "Toalheiro Térmico Elétrico (220V)", "Potência (W)": 150, "Tensão (V)": 220, "Fator de Potência": 1.00, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
        {"Equipamento": "Cooktop de Indução / Forno Elétrico (220V)", "Potência (W)": 4500, "Tensão (V)": 220, "Fator de Potência": 0.98, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
        {"Equipamento": "Torneira Elétrica / Lava-Louça (220V)", "Potência (W)": 3500, "Tensão (V)": 220, "Fator de Potência": 1.00, "Tipo": "TUE", "Curva Disjuntor": "B", "Uso de DR": "Obrigatório"},
        {"Equipamento": "Bomba de Recalque / Piscina (220V)", "Potência (W)": 1100, "Tensão (V)": 220, "Fator de Potência": 0.85, "Tipo": "TUE", "Curva Disjuntor": "C", "Uso de DR": "Obrigatório"},
    ]
    if 'bib_eletrica' in st.session_state:
        existentes = set(st.session_state.bib_eletrica['Equipamento'].values)
        faltantes = [item for item in novos_elet if item["Equipamento"] not in existentes]
        if faltantes:
            st.session_state.bib_eletrica = pd.concat([st.session_state.bib_eletrica, pd.DataFrame(faltantes)], ignore_index=True)

garantir_itens_extras_na_bib_eletrica()


def classificar_bloco_eletrico_inteligente(nome_bloco, layer_bloco, pe_direito, tensao_padrao, opcoes_eq_elet):
    """
    Associa automaticamente Nome_Bloco + Layer à Função Física BIM, Carga da Biblioteca,
    Qtd de Tomadas, Qtd de Interruptores, Amperagem (10A/20A), Tensão (127V/220V) e altura z_relativo.
    """
    nome_limpo = str(nome_bloco).split("(")[0].split("[")[0].strip()
    nome_norm = normalizar_texto_bim(nome_limpo)
    layer_norm = normalizar_texto_bim(layer_bloco)
    alvo = f"{nome_norm} {layer_norm}".strip()
    palavras_alvo = set(alvo.split())
    opcoes_norm = {normalizar_texto_bim(op): op for op in opcoes_eq_elet}

    def buscar_eq_el(termo):
        t_n = normalizar_texto_bim(termo)
        if t_n in opcoes_norm:
            return opcoes_norm[t_n]
        for k_n, op_r in opcoes_norm.items():
            if t_n in k_n:
                return op_r
        return opcoes_eq_elet[0] if opcoes_eq_elet else "Tomada Uso Geral (TUG)"

    # 1. QUADRO DE DISTRIBUIÇÃO (QDG / QDC)
    if any(k in alvo for k in ["QUADRO", "QDG", "QDC", "QDL", "DISJUNTOR GERAL", "CENTRO DE CARGAS"]):
        return "Quadro Geral", buscar_eq_el("Sem Carga"), 0, 0, "10A", 220, 1.50

    # 2. CONEXÕES DE ELETRODUTO, CURVAS, LUVAS E TRECHOS DE PASSAGEM (BASE 25mm)
    eh_curva_el = any(k in palavras_alvo for k in ["CURVA", "JOELHO", "COTOVELO", "LUVA", "BUCHA", "CONDULETE"])
    eh_eletroduto = any(k in alvo for k in ["ELETRODUTO", "CONDUITE", "TUBULACAO ELETRICA"])
    if eh_curva_el or eh_eletroduto:
        z_con = round(float(pe_direito) - 0.05, 2) if "TETO" in alvo or "LAJE" in alvo else (0.05 if "PISO" in alvo else 1.30)
        eq_c = buscar_eq_el("Curva / Joelho 90° Eletroduto 25mm" if eh_curva_el else "Eletroduto Corrugado/Rígido 25mm")
        return "Conexão / Eletroduto", eq_c, 0, 0, "10A", tensao_padrao, z_con

    # 3. CAIXAS DE PASSAGEM (PAREDE, PISO OU OCTOGONAL DE TETO)
    if any(k in alvo for k in ["CAIXA DE PASSAGEM", "CX PASSAGEM", "OCTOGONAL", "PASSAGEM"]):
        z_cp = round(float(pe_direito) - 0.05, 2) if ("OCTOGONAL" in alvo or "TETO" in alvo) else (0.05 if "PISO" in alvo else 0.30)
        return "Caixa de Passagem", buscar_eq_el("Caixa de Passagem Elétrica"), 0, 0, "10A", tensao_padrao, z_cp

    # 4. ILUMINAÇÃO (TETO E ARANDELAS DE PAREDE)
    if any(k in alvo for k in ["ARANDELA", "BALIZADOR"]):
        z_ar = 0.40 if "BALIZADOR" in alvo else 2.00
        return "Luminária", buscar_eq_el("Lâmpada"), 0, 0, "10A", tensao_padrao, z_ar

    if any(k in alvo for k in ["LUMINARIA", "LAMPADA", "PLAFON", "SPOT", "PAINEL LED", "PENDENTE", "FITA LED", "REFLETOR", "ILUMINACAO", "LUZ", "PONTO DE LUZ"]):
        return "Luminária", buscar_eq_el("Lâmpada"), 0, 0, "10A", tensao_padrao, round(float(pe_direito), 2)

    # 5. INTERRUPTORES (SIMPLES, DUPLOS, TRIPLOS, PARALELOS THREE-WAY / FOUR-WAY E CONJUGADOS)
    tem_int = any(k in alvo for k in ["INTERRUPTOR", "TECLA", "PARALELO", "THREE WAY", "3 WAY", "FOUR WAY", "4 WAY"]) or any(k in palavras_alvo for k in ["INT", "S", "S1", "S2", "S3", "SP", "S4W"])
    tem_tom = any(k in alvo for k in ["TOMADA", "TUG", "TUE", "2P+T", "CONJUGAD"]) or any(k in palavras_alvo for k in ["TOM", "TB", "TM", "TA"])

    if tem_int and not tem_tom:
        qtd_sec = 3 if any(k in alvo for k in ["TRIPLO", "3 SECOES", "3 TECLAS", "S3"]) else (2 if any(k in alvo for k in ["DUPLO", "2 SECOES", "2 TECLAS", "S2"]) else 1)
        caixa_t = "Caixa 4x4" if qtd_sec >= 3 else "Caixa 4x2"
        return caixa_t, buscar_eq_el("Sem Carga"), 0, qtd_sec, "10A", tensao_padrao, 1.20

    if tem_int and tem_tom:
        qtd_sec = 2 if any(k in alvo for k in ["DUPLO", "2 SECOES", "S2"]) else 1
        return "Caixa 4x2", buscar_eq_el("Tomada Uso Geral"), 1, qtd_sec, "10A", tensao_padrao, 1.20

    # 6. EQUIPAMENTOS ESPECÍFICOS DE POTÊNCIA (TUEs - PRIORIDADE 220V E 20A)
    regras_tue = [
        (["CHUVEIRO", "DUCHA ELETRICA"], "Chuveiro Elétrico", 220, "20A", 2.20),
        (["AR CONDICIONADO", "SPLIT", "EVAPORADORA", "CONDENSADORA", "AC "], "Ar-Condicionado", 220, "20A", 2.20),
        (["HIDROMASSAGEM", "BANHEIRA", "SPA", "JACUZZI"], "Bomba Hidromassagem", 220, "20A", 0.40),
        (["BOILER", "AQUECEDOR"], "Aquecedor de Água", 220, "20A", 1.50),
        (["TOALHEIRO"], "Toalheiro Térmico", 220, "10A", 1.10),
        (["COOKTOP", "FORNO", "FOGAO ELETRICO", "INDUCAO"], "Cooktop", 220, "20A", 0.60),
        (["TORNEIRA ELETRICA", "LAVA LOUCA", "MLL"], "Torneira Elétrica", 220, "20A", 0.60),
        (["MICROONDAS", "MICRO-ONDAS"], "Micro-ondas", 220, "20A", 1.30),
        (["MAQUINA DE LAVAR", "LAVADORA", "SECADORA", "MLR"], "Máquina de Lavar", 220, "20A", 0.90),
        (["BOMBA", "RECALQUE", "PRESSURIZADORA", "PISCINA"], "Bomba", 220, "20A", 0.40),
        (["COIFA", "EXAUSTOR", "DEPURADOR"], "Tomada Bancada", 220, "20A", 2.00),
        (["GELADEIRA", "REFRIGERADOR", "FREEZER"], "Geladeira", tensao_padrao, "10A", 0.60),
    ]
    for k_list, eq_busca, v_tue, amp_tue, z_tue in regras_tue:
        if any(k in alvo for k in k_list):
            return "Caixa 4x2", buscar_eq_el(eq_busca), 1, 0, amp_tue, v_tue, z_tue

    # 7. TOMADAS DE USO GERAL (TUGs - BAIXA 0.30m, MÉDIA 1.30m, ALTA 2.20m, DUPLA/TRIPLA)
    qtd_tom = 3 if any(k in alvo for k in ["TRIPLA", "3 TOMADAS", "3X"]) else (2 if any(k in alvo for k in ["DUPLA", "2 TOMADAS", "2X"]) else 1)
    caixa_tom = "Caixa 4x4" if qtd_tom >= 3 else "Caixa 4x2"

    eh_alta = any(k in alvo for k in ["ALTA", "2.20", "2,20", "2.10"]) or "TA" in palavras_alvo
    eh_media = any(k in alvo for k in ["MEDIA", "BANCADA", "1.30", "1,30", "1.20", "1.10"]) or "TM" in palavras_alvo
    eh_area_molhada = any(k in alvo for k in ["COZINHA", "COPA", "SERVICO", "LAVANDERIA", "BANHEIRO", "GOURMET"])

    z_tom = 2.20 if eh_alta else (1.30 if (eh_media or eh_area_molhada) else 0.30)
    amp_tom = "20A" if ("20A" in alvo or eh_area_molhada) else "10A"
    tens_tom = 220 if "220" in alvo else tensao_padrao
    eq_tom = buscar_eq_el("Tomada Bancada" if eh_area_molhada else "Tomada Uso Geral")

    return caixa_tom, eq_tom, qtd_tom, 0, amp_tom, tens_tom, z_tom

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
    if df_elet is not None and not df_elet.empty:
        st.session_state["memoria_edicoes_elet"] = df_elet.to_dict("records")
    if df_hidro is not None and not df_hidro.empty:
        st.session_state["memoria_edicoes_hidro"] = df_hidro.to_dict("records")

def mesclar_blocos_com_memoria(df_novo, disciplina="hidro"):
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
    arquivo_bim = st.file_uploader("Abrir Projeto Salvo (.bim)", type=["bim", "json"])
    if arquivo_bim and st.button("📁 Carregar Dados do Arquivo", use_container_width=True):
        dados_bim = json.load(arquivo_bim)
        st.session_state.circuitos = pd.DataFrame(dados_bim.get("circuitos", []))
        st.session_state.pontos_hidro = dados_bim.get("pontos_hidro", [])
        st.session_state.linhas_3d_master = dados_bim.get("linhas_3d_master", {'eletrica': [], 'hidro': []})
        st.session_state.contexto_bim = dados_bim.get("contexto_bim", {})
        if "bib_eletrica" in dados_bim:
            st.session_state.bib_eletrica = pd.DataFrame(dados_bim["bib_eletrica"])
            garantir_itens_extras_na_bib_eletrica()
        if "bib_hidro" in dados_bim:
            st.session_state.bib_hidro = pd.DataFrame(dados_bim["bib_hidro"])
            garantir_tubos_queda_subida_na_biblioteca()
        if "bib_gas_avac" in dados_bim:
            st.session_state.bib_gas_avac = pd.DataFrame(dados_bim["bib_gas_avac"])
        if "quantitativos_master" in dados_bim:
            qm = dados_bim["quantitativos_master"]
            st.session_state.quantitativos_master = {k: pd.DataFrame(v) for k, v in qm.items()}

        ctx_salvo = st.session_state.contexto_bim
        st.session_state["memoria_edicoes_elet"] = dados_bim.get("memoria_edicoes_elet", ctx_salvo.get("df_elet", ctx_salvo.get("df_eletrica", [])))
        st.session_state["memoria_edicoes_hidro"] = dados_bim.get("memoria_edicoes_hidro", ctx_salvo.get("df_hidro", []))
        st.session_state["memoria_edicoes_esq_v2"] = dados_bim.get("memoria_edicoes_esq_v2", dados_bim.get("memoria_edicoes_esq", {}))
        st.session_state["mapa_blocos_hidro"] = dados_bim.get("mapa_blocos_hidro", {})
        st.session_state["mapa_blocos_elet"] = dados_bim.get("mapa_blocos_elet", {})
        st.session_state["altura_caixa_3d"] = float(dados_bim.get("altura_caixa_3d", ctx_salvo.get("altura_caixa", 1.50)))

        # Restaura as layers salvas no arquivo .bim e força a atualização visual dos 5 multiselects
        layers_do_bim = dados_bim.get("layers_selecionadas", ctx_salvo.get("layers_selecionadas", {}))
        if layers_do_bim:
            st.session_state["layers_selecionadas_mem"] = layers_do_bim
            st.session_state.contexto_bim["layers_selecionadas"] = layers_do_bim

        st.session_state["projeto_bim_ativo"] = True
        st.session_state["sync_version"] = st.session_state.get("sync_version", 0) + 1
        st.session_state["versao_widgets_layer"] = st.session_state.get("versao_widgets_layer", 0) + 1
        st.cache_data.clear()
        st.success("✅ Projeto .BIM e seleção de layers restaurados com sucesso!")
        st.rerun()

    pacote_bim = {
        "circuitos": st.session_state.circuitos.to_dict(orient="records") if not st.session_state.circuitos.empty else [],
        "pontos_hidro": st.session_state.pontos_hidro,
        "linhas_3d_master": st.session_state.linhas_3d_master,
        "contexto_bim": st.session_state.contexto_bim,
        "bib_eletrica": st.session_state.bib_eletrica.to_dict(orient="records"),
        "bib_hidro": st.session_state.bib_hidro.to_dict(orient="records"),
        "bib_gas_avac": st.session_state.bib_gas_avac.to_dict(orient="records"),
        "quantitativos_master": {k: v.to_dict(orient="records") for k, v in st.session_state.quantitativos_master.items()},
        "memoria_edicoes_elet": st.session_state.get("memoria_edicoes_elet", []),
        "memoria_edicoes_hidro": st.session_state.get("memoria_edicoes_hidro", []),
        "memoria_edicoes_esq_v2": st.session_state.get("memoria_edicoes_esq_v2", {}),
        "mapa_blocos_hidro": st.session_state.get("mapa_blocos_hidro", {}),
        "mapa_blocos_elet": st.session_state.get("mapa_blocos_elet", {}),
        "altura_caixa_3d": st.session_state.get("altura_caixa_3d", 1.50),
        "layers_selecionadas": st.session_state.get("layers_selecionadas_mem", st.session_state.contexto_bim.get("layers_selecionadas", {}))
    }
    st.download_button(
        "💾 Salvar Projeto Atual (.bim)",
        data=json.dumps(pacote_bim, indent=2),
        file_name="meu_projeto.bim",
        mime="application/json",
        type="primary",
        use_container_width=True
    )
    st.divider()

    st.header("🏢 Arquitetura e Pavimentos (DXF / IFC)")
    arquivos_dxf = st.file_uploader(
        "Upload Plantas ou Maquetes (.dxf ou .ifc)",
        type=["dxf", "ifc"],
        accept_multiple_files=True,
        help="Suba um ou mais arquivos DXF/IFC. Ao substituir o arquivo por uma versão editada, as layers e blocos serão relidos automaticamente."
    )
    config_andares = []
    if arquivos_dxf:
        import hashlib
        bytes_concat = b"".join([f.getvalue() for f in arquivos_dxf])
        hash_atual = hashlib.md5(bytes_concat).hexdigest()[:8]
        kb_total = len(bytes_concat) / 1024.0
        st.caption(f"📄 Versão carregada na memória: `{hash_atual}` ({kb_total:.1f} KB)")

        # Se o conteúdo binário do DXF mudou no upload, força automaticamente a releitura das layers!
        if st.session_state.get("ultimo_hash_sidebar") != hash_atual:
            st.session_state["ultimo_hash_sidebar"] = hash_atual
            st.session_state["forcar_releitura_layers_dxf"] = True
            st.session_state["versao_widgets_layer"] = st.session_state.get("versao_widgets_layer", 0) + 1
            st.session_state["sync_version"] = st.session_state.get("sync_version", 0) + 1
            st.session_state["disparou_sync"] = True
            st.cache_data.clear()

        if st.button("🔄 Atualizar Projeto Atual (DXF/IFC)", use_container_width=True):
            st.session_state["forcar_releitura_layers_dxf"] = True
            st.session_state["layers_conhecidas_dxf"] = set()
            st.session_state["versao_widgets_layer"] = st.session_state.get("versao_widgets_layer", 0) + 1
            st.session_state["sync_version"] = st.session_state.get("sync_version", 0) + 1
            st.session_state["disparou_sync"] = True
            st.cache_data.clear()
            st.toast("🔄 Layers e blocos relidos diretamente do arquivo DXF/IFC!", icon="✅")
            st.rerun()

        if st.session_state.get("resumo_ultimo_sync"):
            st.caption(st.session_state["resumo_ultimo_sync"])

        st.markdown("**Configuração de Pavimentos:**")
        for idx, arq in enumerate(arquivos_dxf):
            # Limpa caracteres especiais do nome do ficheiro para usar de forma segura na chave
            safe_name = "".join([c if c.isalnum() else "_" for c in arq.name])
            with st.expander(f"Pavimento {idx}: {arq.name}", expanded=(idx == 0)):
                ordem_pav = st.number_input(
                    f"Andar (0=Térreo) ({arq.name})", 
                    min_value=0, 
                    max_value=30, 
                    value=idx, 
                    step=1, 
                    key=f"ord_pav_{idx}_{safe_name}"
                )
                pd_pav = st.number_input(
                    f"Pé-Direito (m) ({arq.name})", 
                    min_value=2.0, 
                    max_value=6.0, 
                    value=3.00, 
                    step=0.10, 
                    key=f"pd_pav_{idx}_{safe_name}"
                )
                config_andares.append({"ordem": ordem_pav, "pe_direito": pd_pav, "arquivo": arq})
        config_andares = sorted(config_andares, key=lambda x: x["ordem"])
            
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
import ezdxf.path

def renderizar_tela_2d_ramificada_e_inspetor(paredes_filtradas, df_editado_elet, df_editado_hidro, ctx):
    """
    Tela Gráfica 2D Interativa com Anti-Sobreposição de Textos, Ligação Rápida em Sequência (2 Cliques)
    e Sincronização Direta com o Inspetor.
    """
    st.subheader("🕸️ Topologia Ramificada 2D Interativa & Inspetor de Conexões / Eixo Z (Clique no Ponto)")
    st.caption("Clique em um bloco na planta 2D para selecioná-lo. Para ligar dois pontos rapidamente, ative o 'Modo Ligação Rápida' abaixo e clique no ponto de origem e depois no destino.")

    if "overrides_topologia_bim" not in st.session_state:
        st.session_state["overrides_topologia_bim"] = ctx.get("overrides_topologia_bim", {})
    overrides = st.session_state["overrides_topologia_bim"]

    with st.expander("⚡💧🔥 Configurar Pontos de Entrada da Rua (Medidor Concessionária, Hidrômetro e Abrigo de Gás)", expanded=False):
        ce_r1, ce_r2, ce_r3, ce_r4 = st.columns(4)
        x_rua = ce_r1.number_input("Coord. X Entrada da Rua (m)", value=float(ctx.get("min_x", 0.0)), step=0.5, key="x_ent_rua")
        y_rua = ce_r2.number_input("Coord. Y Entrada da Rua (m)", value=float(ctx.get("min_y", 0.0)), step=0.5, key="y_ent_rua")
        dn_alim_agua = ce_r3.selectbox("Ramal Predial Água (Rua → Caixa/Cisterna)", [20, 25, 32, 40, 50], index=1, key="dn_rua_af")
        dn_alim_elet = ce_r4.selectbox("Eletroduto Entrada (Medidor Rua → QDG)", [25, 32, 40, 50, 60, 75], index=2, key="dn_rua_el")

    todos_nos = []
    if not df_editado_elet.empty:
        for _, r in df_editado_elet.iterrows():
            id_c = str(r["ID_CAD"])
            ov = overrides.get(id_c, {})
            todos_nos.append({
                "ID_CAD": id_c, "Disciplina": "Elétrica", "Nome": str(r.get("Nome_Bloco", id_c)),
                "Funcao": str(r.get("Tipo_BIM", "Caixa 4x2")), "Equipamento": str(r.get("Equipamento_Associado", "")),
                "x": float(r["x"]), "y": float(r["y"]), "z_base": float(r.get("z_base", 0.0)),
                "z_relativo": float(ov.get("z_relativo", r.get("z_relativo", 1.30))),
                "Conectado_A": ov.get("Conectado_A", "Automático (Menor Rota ABNT)"),
                "DN_Manual_mm": int(ov.get("DN_Manual_mm", 25)),
                "Conexao_No": ov.get("Conexao_No", "Curva 90° Eletroduto / Caixa")
            })
    if not df_editado_hidro.empty:
        for _, r in df_editado_hidro.iterrows():
            id_c = str(r["ID_CAD"])
            ov = overrides.get(id_c, {})
            eq_str = str(r.get("Equipamento", ""))
            disc = "Gás" if ("GAS" in normalizar_texto_bim(eq_str) or "FOGAO" in normalizar_texto_bim(eq_str)) else "Hidrossanitário"
            todos_nos.append({
                "ID_CAD": id_c, "Disciplina": disc, "Nome": str(r.get("Nome_Bloco", id_c)),
                "Funcao": str(r.get("Tipo_BIM", "Aparelho Hidráulico")), "Equipamento": eq_str,
                "x": float(r["x"]), "y": float(r["y"]), "z_base": float(r.get("z_base", 0.0)),
                "z_relativo": float(ov.get("z_relativo", r.get("z_relativo", 0.50))),
                "Conectado_A": ov.get("Conectado_A", "Automático (Menor Rota ABNT)"),
                "DN_Manual_mm": int(ov.get("DN_Manual_mm", 0)),
                "Conexao_No": ov.get("Conexao_No", "Joelho 90° Soldável / Tê")
            })

    if not todos_nos:
        st.info("Selecione as layers de blocos elétricos ou hidrossanitários acima para habilitar o mapa ramificado 2D.")
        return

    ids_disponiveis = [n["ID_CAD"] for n in todos_nos]

    # Ajuste dinâmico de posições dos textos para evitar sobreposição visual (Efeito Leque)
    posicoes_calculadas = {}
    ocupadas = []
    for n in sorted(todos_nos, key=lambda item: (item["x"], item["y"])):
        bx, by = n["x"], n["y"]
        offset_y = 0.22
        offset_x = 0.0
        for ox, oy in ocupadas:
            if abs(bx - ox) < 0.65 and abs(by - oy) < 0.35:
                offset_y += 0.30
                offset_x += 0.15
        ocupadas.append((bx + offset_x, by + offset_y))
        posicoes_calculadas[n["ID_CAD"]] = (bx + offset_x, by + offset_y)

    filtro_rede_2d = st.radio(
        "Filtrar Visualização na Planta Ramificada 2D:",
        ["Todas as Redes", "⚡ Apenas Elétrica (Rua → QDG → Circuitos)", "💧 Apenas Água Fria/Quente (Rua → Caixa → Pontos)", "🤎 Apenas Esgoto (Aparelhos → CS/CG → CI)", "🔥 Apenas Gás (GLP/GN)"],
        horizontal=True
    )

    fig_2d = go.Figure()

    # 1. Paredes 2D
    wx_2d, wy_2d = [], []
    for p1, p2 in paredes_filtradas:
        wx_2d.extend([p1[0], p2[0], None])
        wy_2d.extend([p1[1], p2[1], None])
    if wx_2d:
        fig_2d.add_trace(go.Scatter(
            x=wx_2d, y=wy_2d, mode="lines",
            line=dict(color="#94a3b8", width=2),
            name="Paredes (Planta 2D)", hoverinfo="skip"
        ))

    # 2. Ramais de Entrada
    qdgs = [n for n in todos_nos if n["Funcao"] == "Quadro Geral"]
    cxs_agua = [n for n in todos_nos if n["Funcao"] == "Caixa d'Água"]
    if qdgs and filtro_rede_2d in ["Todas as Redes", "⚡ Apenas Elétrica (Rua → QDG → Circuitos)"]:
        q0 = qdgs[0]
        fig_2d.add_trace(go.Scatter(
            x=[x_rua, q0["x"]], y=[y_rua, q0["y"]], mode="lines+markers+text",
            line=dict(color="#dc2626", width=3.5, dash="dashdot"),
            marker=dict(size=10, symbol="diamond", color="#dc2626"),
            text=["⚡ MEDIDOR RUA", f"QDG (Ø{dn_alim_elet}mm)"], textposition="top center",
            name=f"Entrada Energia Rua (Ø{dn_alim_elet}mm)", hoverinfo="skip"
        ))
    if cxs_agua and filtro_rede_2d in ["Todas as Redes", "💧 Apenas Água Fria/Quente (Rua → Caixa → Pontos)"]:
        c0 = cxs_agua[0]
        fig_2d.add_trace(go.Scatter(
            x=[x_rua, c0["x"]], y=[y_rua - 0.5, c0["y"]], mode="lines+markers+text",
            line=dict(color="#0284c7", width=3.5, dash="dot"),
            marker=dict(size=10, symbol="square", color="#0284c7"),
            text=["💧 HIDRÔMETRO RUA", f"Alimentador (Ø{dn_alim_agua}mm)"], textposition="bottom center",
            name=f"Alimentador Predial Rua (Ø{dn_alim_agua}mm)", hoverinfo="skip"
        ))

    # 3. Tubulações Calculadas
    linhas_m = st.session_state.get("linhas_3d_master", {})
    if filtro_rede_2d in ["Todas as Redes", "⚡ Apenas Elétrica (Rua → QDG → Circuitos)"]:
        for l_el in linhas_m.get("eletrica", []):
            pts = l_el.get("pontos", [])
            if len(pts) >= 2:
                dn_e = l_el.get("diametro", 25)
                fios_e = l_el.get("fios", "F N T")
                fig_2d.add_trace(go.Scatter(
                    x=[p[0] for p in pts], y=[p[1] for p in pts], mode="lines",
                    line=dict(color=l_el.get("cor", "#eab308"), width=2.5),
                    name="Ramal Elétrico", showlegend=False,
                    hovertext=f"{l_el.get('tipo','Eletroduto')} | Ø{dn_e}mm | {fios_e}", hoverinfo="text"
                ))

    if filtro_rede_2d != "⚡ Apenas Elétrica (Rua → QDG → Circuitos)":
        for l_hd in linhas_m.get("hidro", []):
            pts = l_hd.get("pontos", [])
            t_h = str(l_hd.get("tipo", ""))
            if filtro_rede_2d == "💧 Apenas Água Fria/Quente (Rua → Caixa → Pontos)" and ("Esgoto" in t_h or "Descarga" in t_h):
                continue
            if filtro_rede_2d == "🤎 Apenas Esgoto (Aparelhos → CS/CG → CI)" and ("Água" in t_h or "Barrilete" in t_h):
                continue
            if len(pts) >= 2:
                dn_h = l_hd.get("diametro", 25)
                pm = pts[len(pts) // 2]
                fig_2d.add_trace(go.Scatter(
                    x=[p[0] for p in pts], y=[p[1] for p in pts], mode="lines",
                    line=dict(color=l_hd.get("cor", "#0284c7"), width=3),
                    name="Ramal Hidro", showlegend=False,
                    hovertext=f"{t_h} | DN {dn_h}mm", hoverinfo="text"
                ))
                fig_2d.add_trace(go.Scatter(
                    x=[pm[0]], y=[pm[1]], mode="text",
                    text=[f"Ø{dn_h}mm"], textfont=dict(size=9, color="#0f172a"),
                    showlegend=False, hoverinfo="skip"
                ))

            # 4. Nós Clicáveis + Textos Deslocados (Anti-Sobreposição)
    cores_nos = []
    hover_nos = []
    textos_2d = []
    tx_x, tx_y = [], []
    for n in todos_nos:
        cor_n = "#eab308" if n["Disciplina"] == "Elétrica" else ("#f97316" if n["Disciplina"] == "Gás" else ("#8b4513" if "Caixa" in n["Funcao"] or "Esgoto" in n["Funcao"] else "#0ea5e9"))
        cores_nos.append(cor_n)
        hover_nos.append(
            f"<b>{n['ID_CAD']}</b> ({n['Nome']})<br>Função: {n['Funcao']}<br>Eq: {n['Equipamento']}"
            f"<br>Altura z_relativo: {n['z_relativo']:.2f}m<br>Ligado a: {n['Conectado_A']}"
            f"<br>Conexão: {n['Conexao_No']} | DN Manual: {n['DN_Manual_mm'] if n['DN_Manual_mm']>0 else 'Auto'}mm"
        )
        px_t, py_t = posicoes_calculadas[n["ID_CAD"]]
        tx_x.append(px_t)
        tx_y.append(py_t)
        textos_2d.append(n["ID_CAD"])

    # Camada dos Pontos (Marcadores)
    fig_2d.add_trace(go.Scatter(
        x=[n["x"] for n in todos_nos],
        y=[n["y"] for n in todos_nos],
        mode="markers",
        customdata=[n["ID_CAD"] for n in todos_nos],
        hovertext=hover_nos,
        hoverinfo="text",
        marker=dict(size=14, color=cores_nos, line=dict(width=2, color="#0f172a")),
        selected=dict(marker=dict(size=18, color="#dc2626", opacity=1.0)),
        unselected=dict(marker=dict(opacity=0.85)),
        name="🎯 Blocos (Marcadores)"
    ))

    # Camada dos Textos Separados (Permite clicar no nome do bloco sem sobreposição)
    fig_2d.add_trace(go.Scatter(
        x=tx_x, y=tx_y,
        mode="text",
        text=textos_2d,
        textfont=dict(size=10, color="#0f172a", family="Arial Black"),
        customdata=[n["ID_CAD"] for n in todos_nos],
        hoverinfo="skip",
        name="📝 Rótulos"
    ))

    fig_2d.update_layout(
        height=580,
        plot_bgcolor="#f8fafc",
        xaxis=dict(title="X (m)", gridcolor="#e2e8f0", zeroline=False),
        yaxis=dict(title="Y (m)", gridcolor="#e2e8f0", zeroline=False, scaleanchor="x", scaleratio=1),
        margin=dict(l=10, r=10, t=10, b=10),
        clickmode="event+select",
        dragmode="pan"
    )

    col_graf2d, col_insp = st.columns([2.2, 1.2])
    with col_graf2d:
        evento_clique = st.plotly_chart(
            fig_2d,
            use_container_width=True,
            on_select="rerun",
            selection_mode="points",
            key="grafico_2d_interativo_bim"
        )

    # Captura infalível do ponto clicado no Gráfico 2D
    if evento_clique and hasattr(evento_clique, "selection") and evento_clique.selection.get("points"):
        pts_clicados = evento_clique.selection["points"]
        if pts_clicados:
            pt_sel = pts_clicados[-1]
            id_detectado = None
            cd = pt_sel.get("customdata")
            if cd is not None:
                id_cand = str(cd[0]) if isinstance(cd, (list, tuple)) and len(cd) > 0 else str(cd)
                if id_cand in ids_disponiveis:
                    id_detectado = id_cand

            if id_detectado is None and "x" in pt_sel and "y" in pt_sel:
                px_c, py_c = float(pt_sel["x"]), float(pt_sel["y"])
                no_mais_prox = min(todos_nos, key=lambda n: math.hypot(n["x"] - px_c, n["y"] - py_c))
                if math.hypot(no_mais_prox["x"] - px_c, no_mais_prox["y"] - py_c) <= 0.65:
                    id_detectado = no_mais_prox["ID_CAD"]

            if id_detectado and st.session_state.get("ultimo_clique_2d_assinatura") != f"{id_detectado}_{pt_sel.get('x')}_{pt_sel.get('y')}":
                st.session_state["ultimo_clique_2d_assinatura"] = f"{id_detectado}_{pt_sel.get('x')}_{pt_sel.get('y')}"
                
                # Se o modo de ligação rápida estiver ativo, faz a ligação automática entre o ponto anterior e este!
                if st.session_state.get("modo_ligacao_rapida_ativo", False):
                    ponto_origem_ant = st.session_state.get("origem_ligacao_rapida")
                    if ponto_origem_ant and ponto_origem_ant != id_detectado:
                        overrides[ponto_origem_ant] = overrides.get(ponto_origem_ant, {})
                        overrides[ponto_origem_ant]["Conectado_A"] = id_detectado
                        st.session_state["overrides_topologia_bim"] = overrides
                        st.session_state.contexto_bim["overrides_topologia_bim"] = overrides
                        salvar_edicoes_na_memoria(df_editado_elet, df_editado_hidro)

                        # Reprocessa rotas
                        ctx_at = st.session_state.contexto_bim
                        ctx_at['df_eletrica'] = df_editado_elet.to_dict('records') if not df_editado_elet.empty else []
                        ctx_at['df_hidro'] = df_editado_hidro.to_dict('records') if not df_editado_hidro.empty else []
                        if ctx_at.get('grid_w') and ctx_at.get('grid_h'):
                            novas_linhas_hd = rotear_hidro(ctx_at['df_hidro'], ctx_at)
                            novas_linhas_el = rotear_eletrica(ctx_at['df_eletrica'], ctx_at)
                            st.session_state.linhas_3d_master['hidro'] = novas_linhas_hd
                            st.session_state.linhas_3d_master['eletrica'] = novas_linhas_el
                            st.session_state.quantitativos_master = gerar_quantitativos_totais_bim(
                                novas_linhas_el, novas_linhas_hd, st.session_state.circuitos, ctx_at['df_eletrica'], ctx_at['df_hidro']
                            )

                        st.toast(f"🔗 Ligação rápida criada com sucesso: {ponto_origem_ant} ➔ {id_detectado}!", icon="⚡")
                        st.session_state["modo_ligacao_rapida_ativo"] = False
                        st.session_state["origem_ligacao_rapida"] = None
                    else:
                        st.session_state["origem_ligacao_rapida"] = id_detectado
                        st.toast(f"📍 Ponto de origem definido: `{id_detectado}`. Agora clique no ponto de destino!", icon="🎯")

                st.session_state["no_selecionado_bim"] = id_detectado
                st.session_state["sel_insp_no"] = id_detectado

    if st.session_state.get("sel_insp_no") not in ids_disponiveis:
        id_ini = st.session_state.get("no_selecionado_bim", ids_disponiveis[0])
        st.session_state["sel_insp_no"] = id_ini if id_ini in ids_disponiveis else ids_disponiveis[0]

    with col_insp:
        st.markdown("### 🛠️ Inspetor do Ponto Selecionado")

        # Botão de Ligação Rápida Sequencial (2 Cliques)
        modo_rapido = st.toggle("🔗 Modo Ligação Rápida (1º Clique Origem, 2º Clique Destino)", value=st.session_state.get("modo_ligacao_rapida_ativo", False), key="toggle_ligacao_rapida")
        st.session_state["modo_ligacao_rapida_ativo"] = modo_rapido
        if modo_rapido:
            orig_Atual = st.session_state.get("origem_ligacao_rapida")
            if orig_Atual:
                st.warning(f"📍 Origem ativa: **`{orig_Atual}`**. Clique no ponto de destino no mapa 2D.")
            else:
                st.info("ℹ️ Clique primeiro no ponto de **Origem** no mapa 2D e depois no ponto de **Destino**.")

        id_escolhido = st.selectbox(
            "🎯 Bloco Ativo (Clique no 2D ou escolha):",
            ids_disponiveis,
            key="sel_insp_no"
        )
        st.session_state["no_selecionado_bim"] = id_escolhido
        no_atual = next(n for n in todos_nos if n["ID_CAD"] == id_escolhido)

        st.info(f"**Bloco CAD:** `{no_atual['Nome']}`\n\n**Disciplina:** {no_atual['Disciplina']} | **Função:** {no_atual['Funcao']}\n\n**Coord. 2D:** X={no_atual['x']:.2f}m, Y={no_atual['y']:.2f}m")

        novo_z_rel = st.number_input(
            "📏 Altura Relativa ao Piso — Eixo Z (m):",
            min_value=-1.50, max_value=6.00, value=float(no_atual["z_relativo"]), step=0.05,
            key=f"insp_z_{id_escolhido}"
        )

        opcoes_destino = ["Automático (Menor Rota ABNT)"] + [i for i in ids_disponiveis if i != id_escolhido]
        dest_atual = no_atual["Conectado_A"] if no_atual["Conectado_A"] in opcoes_destino else "Automático (Menor Rota ABNT)"
        novo_conectado_a = st.selectbox(
            "🔗 Ligar Diretamente ao Ponto (Jusante / Pai):",
            opcoes_destino, index=opcoes_destino.index(dest_atual),
            help="Define manualmente para qual ponto este bloco enviará ou receberá sua tubulação/eletroduto.",
            key=f"insp_dest_{id_escolhido}"
        )

        opcoes_peca_no = [
            "Joelho 90° Soldável / Tê",
            "Joelho 45° (Suavizado)",
            "Curva Longa 90° (Baixa Perda)",
            "Tê 90° Passagem Direta",
            "Tê de Redução Soldável",
            "Junção Simples 45° (Y - Esgoto)",
            "Curva 90° Eletroduto / Caixa",
            "Caixa de Passagem / Octogonal"
        ]
        peca_atual = no_atual["Conexao_No"] if no_atual["Conexao_No"] in opcoes_peca_no else opcoes_peca_no[0]
        nova_conexao_no = st.selectbox(
            "🔩 Conexão Principal neste Ponto:",
            opcoes_peca_no, index=opcoes_peca_no.index(peca_atual),
            key=f"insp_peca_{id_escolhido}"
        )

        opcoes_dn = [0, 15, 20, 22, 25, 28, 32, 40, 50, 60, 75, 100, 150]
        dn_at = no_atual["DN_Manual_mm"] if no_atual["DN_Manual_mm"] in opcoes_dn else 0
        novo_dn_manual = st.selectbox(
            "⭕ Diâmetro da Tubulação/Conduíte deste Trecho (mm) [0 = Auto ABNT]:",
            opcoes_dn, index=opcoes_dn.index(dn_at),
            key=f"insp_dn_{id_escolhido}"
        )

        col_ap1, col_ap2 = st.columns([2, 1])
        if col_ap1.button("💾 Aplicar ao Ponto e Atualizar 3D/2D", type="primary", use_container_width=True):
            overrides[id_escolhido] = {
                "z_relativo": float(novo_z_rel),
                "Conectado_A": novo_conectado_a,
                "Conexao_No": nova_conexao_no,
                "DN_Manual_mm": int(novo_dn_manual)
            }
            st.session_state["overrides_topologia_bim"] = overrides
            st.session_state.contexto_bim["overrides_topologia_bim"] = overrides

            if no_atual["Disciplina"] == "Elétrica" and not df_editado_elet.empty:
                df_editado_elet.loc[df_editado_elet["ID_CAD"] == id_escolhido, "z_relativo"] = float(novo_z_rel)
            elif not df_editado_hidro.empty:
                df_editado_hidro.loc[df_editado_hidro["ID_CAD"] == id_escolhido, "z_relativo"] = float(novo_z_rel)

            salvar_edicoes_na_memoria(df_editado_elet, df_editado_hidro)

            ctx_at = st.session_state.contexto_bim
            ctx_at['df_eletrica'] = df_editado_elet.to_dict('records') if not df_editado_elet.empty else []
            ctx_at['df_hidro'] = df_editado_hidro.to_dict('records') if not df_editado_hidro.empty else []
            if ctx_at.get('grid_w') and ctx_at.get('grid_h'):
                novas_linhas_hd = rotear_hidro(ctx_at['df_hidro'], ctx_at)
                novas_linhas_el = rotear_eletrica(ctx_at['df_eletrica'], ctx_at)
                st.session_state.linhas_3d_master['hidro'] = novas_linhas_hd
                st.session_state.linhas_3d_master['eletrica'] = novas_linhas_el
                st.session_state.quantitativos_master = gerar_quantitativos_totais_bim(
                    novas_linhas_el, novas_linhas_hd, st.session_state.circuitos, ctx_at['df_eletrica'], ctx_at['df_hidro']
                )

            st.session_state["sync_version"] = st.session_state.get("sync_version", 0) + 1
            st.toast(f"✅ Ligação manual aplicada: {id_escolhido} ➔ {novo_conectado_a} (Ø{novo_dn_manual if novo_dn_manual>0 else 'Auto'}mm)!", icon="🔗")
            st.rerun()

        if col_ap2.button("🗑️ Resetar Nó", use_container_width=True):
            if id_escolhido in overrides:
                del overrides[id_escolhido]
                st.session_state["overrides_topologia_bim"] = overrides
                st.rerun()

        links_ativos = [
            f"• `{k}` ➔ `{v.get('Conectado_A')}` (Ø{v.get('DN_Manual_mm') if v.get('DN_Manual_mm',0)>0 else 'Auto'}mm | z={v.get('z_relativo',0):.2f}m)"
            for k, v in overrides.items()
            if v.get("Conectado_A") and v.get("Conectado_A") != "Automático (Menor Rota ABNT)"
        ]
        if links_ativos:
            st.markdown("**🔒 Ligações Manuais Ativas (Prioridade Absoluta):**")
            st.caption("\n".join(links_ativos))

def extrair_segmentos_entidade_dxf(ent, modo="parede"):
    """
    Extrai segmentos 2D [((x1, y1), (x2, y2)), ...] de entidades do AutoCAD:
    Suporta LINE, LWPOLYLINE (aberta/fechada), POLYLINE (2D/3D), MLINE, ARC, CIRCLE, ELLIPSE e SPLINE.
    """
    segs = []
    if ent is None:
        return segs
    dxft = ent.dxftype()

    try:
        if dxft == 'LINE':
            p1 = (float(ent.dxf.start.x), float(ent.dxf.start.y))
            p2 = (float(ent.dxf.end.x), float(ent.dxf.end.y))
            if dist_2d(p1, p2) > 1e-4:
                segs.append((p1, p2))

        elif dxft == 'MLINE':
            pts_ml = []
            try:
                for v in ent.vertices:
                    loc = getattr(v, 'location', None)
                    if loc is not None:
                        pts_ml.append((float(loc.x), float(loc.y)))
            except Exception:
                pass

            if modo == "esquadria" and len(pts_ml) >= 2:
                for i in range(len(pts_ml) - 1):
                    if dist_2d(pts_ml[i], pts_ml[i + 1]) > 1e-4:
                        segs.append((pts_ml[i], pts_ml[i + 1]))
            else:
                segs_virt = []
                for ve in ent.virtual_entities():
                    segs_virt.extend(extrair_segmentos_entidade_dxf(ve, modo="parede"))
                if modo == "esquadria" and segs_virt:
                    maior_s = max(segs_virt, key=lambda s: dist_2d(s[0], s[1]))
                    segs.append(maior_s)
                elif segs_virt:
                    segs.extend(segs_virt)
                elif len(pts_ml) >= 2:
                    for i in range(len(pts_ml) - 1):
                        segs.append((pts_ml[i], pts_ml[i + 1]))

        elif dxft == 'LWPOLYLINE':
            pontos = list(ent.get_points(format='xy'))
            if len(pontos) >= 2:
                for i in range(len(pontos) - 1):
                    p1 = (float(pontos[i][0]), float(pontos[i][1]))
                    p2 = (float(pontos[i + 1][0]), float(pontos[i + 1][1]))
                    if dist_2d(p1, p2) > 1e-4:
                        segs.append((p1, p2))
                if getattr(ent, 'closed', False) and len(pontos) > 2:
                    p_ult = (float(pontos[-1][0]), float(pontos[-1][1]))
                    p_pri = (float(pontos[0][0]), float(pontos[0][1]))
                    if dist_2d(p_ult, p_pri) > 1e-4:
                        segs.append((p_ult, p_pri))

        elif dxft == 'POLYLINE':
            pts_pl = []
            for v in ent.vertices:
                loc = v.dxf.location
                pts_pl.append((float(loc.x), float(loc.y)))
            if len(pts_pl) >= 2:
                for i in range(len(pts_pl) - 1):
                    if dist_2d(pts_pl[i], pts_pl[i + 1]) > 1e-4:
                        segs.append((pts_pl[i], pts_pl[i + 1]))
                if getattr(ent, 'is_closed', False) and len(pts_pl) > 2:
                    if dist_2d(pts_pl[-1], pts_pl[0]) > 1e-4:
                        segs.append((pts_pl[-1], pts_pl[0]))

        elif dxft == 'ARC' and modo == "parede":
            cx, cy = float(ent.dxf.center.x), float(ent.dxf.center.y)
            r = float(ent.dxf.radius)
            if r > 1e-3:
                ang_ini = float(ent.dxf.start_angle)
                ang_fim = float(ent.dxf.end_angle)
                if ang_fim < ang_ini:
                    ang_fim += 360.0
                n_div = max(6, min(24, int((ang_fim - ang_ini) / 12.0) + 1))
                pts_arc = [
                    (cx + r * math.cos(math.radians(ang_ini + (ang_fim - ang_ini) * k / n_div)),
                     cy + r * math.sin(math.radians(ang_ini + (ang_fim - ang_ini) * k / n_div)))
                    for k in range(n_div + 1)
                ]
                for i in range(len(pts_arc) - 1):
                    segs.append((pts_arc[i], pts_arc[i + 1]))

        elif dxft == 'CIRCLE' and modo == "parede":
            cx, cy = float(ent.dxf.center.x), float(ent.dxf.center.y)
            r = float(ent.dxf.radius)
            if r > 1e-3:
                n_div = 16
                pts_cir = [
                    (cx + r * math.cos(2.0 * math.pi * k / n_div),
                     cy + r * math.sin(2.0 * math.pi * k / n_div))
                    for k in range(n_div + 1)
                ]
                for i in range(len(pts_cir) - 1):
                    segs.append((pts_cir[i], pts_cir[i + 1]))

        elif dxft in ('ELLIPSE', 'SPLINE') and modo == "parede":
            caminho_p = ezdxf.path.make_path(ent)
            pts_fl = [(float(v.x), float(v.y)) for v in caminho_p.flattening(0.08)]
            for i in range(len(pts_fl) - 1):
                if dist_2d(pts_fl[i], pts_fl[i + 1]) > 1e-4:
                    segs.append((pts_fl[i], pts_fl[i + 1]))

        elif dxft == 'INSERT' and modo == "parede":
            for ve in ent.virtual_entities():
                segs.extend(extrair_segmentos_entidade_dxf(ve, modo="parede"))
    except Exception:
        pass

    return segs


def verificar_parede_continua_no_trecho(pa, pb, z_base, paredes_lista):
    """
    Retorna True se houver uma parede sólida contínua (layer_arq) bloqueando o meio do segmento (pa, pb).
    Isso impede que uma porta ou janela seja criada sobre uma parede cega onde a folha da porta encosta!
    """
    vx, vy = pb[0] - pa[0], pb[1] - pa[1]
    comp = math.hypot(vx, vy)
    if comp < 0.20:
        return False
    ux, uy = vx / comp, vy / comp
    nx, ny = -uy, ux
    mx, my = (pa[0] + pb[0]) / 2.0, (pa[1] + pb[1]) / 2.0

    linhas_paralelas_no_meio = 0
    for w1, w2 in paredes_lista:
        if abs(w1[2] - z_base) > 0.6:
            continue
        w_len = dist_2d(w1, w2)
        if w_len < comp * 0.65:
            continue
        wux, wuy = (w2[0] - w1[0]) / w_len, (w2[1] - w1[1]) / w_len
        if abs(ux * wux + uy * wuy) >= 0.90:
            dist_perp = abs((w1[0] - mx) * nx + (w1[1] - my) * ny)
            if dist_perp <= 0.22:
                s1 = (w1[0] - pa[0]) * ux + (w1[1] - pa[1]) * uy
                s2 = (w2[0] - pa[0]) * ux + (w2[1] - pa[1]) * uy
                s_min, s_max = min(s1, s2), max(s1, s2)
                # Verifica se a linha de parede atravessa o terço central do vão [0.25*comp, 0.75*comp]
                if s_min <= comp * 0.25 and s_max >= comp * 0.75:
                    linhas_paralelas_no_meio += 1

    # Se as 2 faces da alvenaria atravessam continuamente o trecho, é parede cega (não é vão!)
    return linhas_paralelas_no_meio >= 2


def centralizar_segmento_na_espessura_da_parede(p1_in, p2_in, z_base, paredes_lista, exigir_abertura=False):
    """
    Mantém o comprimento e orientação exatos do segmento (p1_in, p2_in),
    ajustando apenas poucos centímetros na normal para centralizar no eixo da parede real (layer_arq).
    Retorna (p1_central, p2_central, larg_exata, offset_norm, ok_parede).
    """
    vx, vy = p2_in[0] - p1_in[0], p2_in[1] - p1_in[1]
    comp = math.hypot(vx, vy)
    if comp < 0.38 or comp > 3.80 or not paredes_lista:
        return None, None, comp, (0.0, 0.075), False

    ux, uy = vx / comp, vy / comp
    nx, ny = -uy, ux

    if exigir_abertura and verificar_parede_continua_no_trecho(p1_in, p2_in, z_base, paredes_lista):
        return None, None, comp, (0.0, 0.075), False

    # 1. Procura batentes transversais (bonecas de 8cm a 30cm) nas extremidades p1_in ou p2_in
    deslocamentos_n = []
    espessuras = []
    tem_apoio_esq = False
    tem_apoio_dir = False

    for w1, w2 in paredes_lista:
        if abs(w1[2] - z_base) > 0.6:
            continue
        w_len = dist_2d(w1, w2)
        if w_len < 0.06:
            continue
        wux, wuy = (w2[0] - w1[0]) / w_len, (w2[1] - w1[1]) / w_len
        alinhamento = abs(ux * wux + uy * wuy)

        # Batente perpendicular ao vão na ponta p1_in ou p2_in
        if alinhamento <= 0.25 and 0.08 <= w_len <= 0.32:
            bmx, bmy = (w1[0] + w2[0]) / 2.0, (w1[1] + w2[1]) / 2.0
            d1 = math.hypot(bmx - p1_in[0], bmy - p1_in[1])
            d2 = math.hypot(bmx - p2_in[0], bmy - p2_in[1])
            if d1 <= 0.24:
                tem_apoio_esq = True
                deslocamentos_n.append((bmx - p1_in[0]) * nx + (bmy - p1_in[1]) * ny)
                espessuras.append(w_len)
            if d2 <= 0.24:
                tem_apoio_dir = True
                deslocamentos_n.append((bmx - p2_in[0]) * nx + (bmy - p2_in[1]) * ny)
                espessuras.append(w_len)

        # Parede colinear que chega até p1_in ou p2_in
        elif alinhamento >= 0.88:
            dist_n = ((w1[0] - p1_in[0]) * nx + (w1[1] - p1_in[1]) * ny)
            if abs(dist_n) <= 0.24:
                s1 = (w1[0] - p1_in[0]) * ux + (w1[1] - p1_in[1]) * uy
                s2 = (w2[0] - p1_in[0]) * ux + (w2[1] - p1_in[1]) * uy
                s_min, s_max = min(s1, s2), max(s1, s2)
                if s_max >= -0.15 and s_min <= 0.15:
                    tem_apoio_esq = True
                    deslocamentos_n.append(dist_n)
                if s_min <= comp + 0.15 and s_max >= comp - 0.15:
                    tem_apoio_dir = True
                    deslocamentos_n.append(dist_n)

    # Só valida como vão se houver parede real apoiando os lados do vão!
    if not (tem_apoio_esq and tem_apoio_dir):
        return None, None, comp, (0.0, 0.075), False

    if deslocamentos_n:
        d_medio = (min(deslocamentos_n) + max(deslocamentos_n)) / 2.0
        if abs(d_medio) > 0.18:
            d_medio = 0.0
    else:
        d_medio = 0.0

    esp_uso = sum(espessuras) / len(espessuras) if espessuras else 0.15
    esp_uso = max(0.12, min(0.25, esp_uso))
    p1_c = (p1_in[0] + d_medio * nx, p1_in[1] + d_medio * ny)
    p2_c = (p2_in[0] + d_medio * nx, p2_in[1] + d_medio * ny)
    offset_norm = (nx * (esp_uso / 2.0), ny * (esp_uso / 2.0))
    return p1_c, p2_c, round(comp, 3), offset_norm, True


def extrair_vao_porta_por_arco_dxf(arc_ent, z_base, paredes_lista, segs_folhas_porta):
    """
    A partir de um arco de giro de porta (ARC de ~90°), identifica qual dos dois raios perpendiculares
    (C -> E1 ou C -> E2) é o VÃO REAL na parede e qual é apenas a folha da porta aberta.
    """
    try:
        cx, cy = float(arc_ent.dxf.center.x), float(arc_ent.dxf.center.y)
        r = float(arc_ent.dxf.radius)
        if not (0.50 <= r <= 1.30):
            return None
        ang1 = float(arc_ent.dxf.start_angle)
        ang2 = float(arc_ent.dxf.end_angle)
        span = (ang2 - ang1) % 360.0
        if not (55.0 <= span <= 115.0):
            return None

        e1 = (cx + r * math.cos(math.radians(ang1)), cy + r * math.sin(math.radians(ang1)))
        e2 = (cx + r * math.cos(math.radians(ang2)), cy + r * math.sin(math.radians(ang2)))
        candidatos = [((cx, cy), e1), ((cx, cy), e2)]

        melhor_cand = None
        melhor_score = -999.0

        for p_ini, p_fim in candidatos:
            # Verifica se este raio coincide com as linhas da folha da porta aberta
            vx, vy = p_fim[0] - p_ini[0], p_fim[1] - p_ini[1]
            comp_c = math.hypot(vx, vy)
            ux, uy = vx / comp_c, vy / comp_c
            mx, my = (p_ini[0] + p_fim[0]) / 2.0, (p_ini[1] + p_fim[1]) / 2.0

            tem_folha_em_cima = False
            for f1, f2 in segs_folhas_porta:
                f_len = dist_2d(f1, f2)
                if 0.45 <= f_len <= 1.35:
                    fux, fuy = (f2[0] - f1[0]) / f_len, (f2[1] - f1[1]) / f_len
                    if abs(ux * fux + uy * fuy) >= 0.90:
                        if distancia_ponto_segmento_2d(mx, my, f1[0], f1[1], f2[0], f2[1]) <= 0.14:
                            tem_folha_em_cima = True
                            break

            # O vão real da porta NÃO tem a folha desenhada sobre ele e precisa estar aberto na parede!
            p1_c, p2_c, larg_c, off_c, ok_w = centralizar_segmento_na_espessura_da_parede(
                p_ini, p_fim, z_base, paredes_lista, exigir_abertura=True
            )
            if not ok_w:
                continue

            score = 100.0 - (80.0 if tem_folha_em_cima else 0.0)
            if score > melhor_score:
                melhor_score = score
                melhor_cand = (p1_c, p2_c, larg_c, off_c)

        return melhor_cand
    except Exception:
        return None


def calcular_extensao_verga_na_parede(p1_vao, p2_vao, z_base, paredes_lista, max_ext=0.30, offset_padrao=(0.0, 0.075)):
    """
    Calcula o avanço real da Verga e Contraverga para cada lado do vão (máximo de 30cm para cada lado),
    medindo exclusivamente o segmento de parede que encosta no batente e parando na quina se < 30cm.
    """
    vx, vy = p2_vao[0] - p1_vao[0], p2_vao[1] - p1_vao[1]
    comp_vao = math.hypot(vx, vy)
    if comp_vao < 1e-4:
        return p1_vao, p2_vao, 0.0, 0.0, offset_padrao
    ux, uy = vx / comp_vao, vy / comp_vao
    nx, ny = -uy, ux

    esp_padrao = math.hypot(offset_padrao[0], offset_padrao[1])
    if esp_padrao < 0.04 or esp_padrao > 0.15:
        esp_padrao = 0.075
    offset_correto = (nx * esp_padrao, ny * esp_padrao)

    avan_esq, avan_dir = 0.0, 0.0
    for seg in paredes_lista:
        w1, w2 = seg[0], seg[1]
        if abs(w1[2] - z_base) > 0.6:
            continue
        wx, wy = w2[0] - w1[0], w2[1] - w1[1]
        w_len = math.hypot(wx, wy)
        if w_len < 0.06:
            continue
        wux, wuy = wx / w_len, wy / w_len
        if abs(ux * wux + uy * wuy) >= 0.90:
            dist_perp = abs((w1[0] - p1_vao[0]) * nx + (w1[1] - p1_vao[1]) * ny)
            if dist_perp <= 0.22:
                s1 = (w1[0] - p1_vao[0]) * ux + (w1[1] - p1_vao[1]) * uy
                s2 = (w2[0] - p1_vao[0]) * ux + (w2[1] - p1_vao[1]) * uy
                s_min, s_max = min(s1, s2), max(s1, s2)
                # Parede colada ao batente esquerdo (s = 0) indo para s < 0
                if -0.06 <= s_max <= 0.08 and s_min < -0.02:
                    avan_esq = max(avan_esq, min(max_ext, abs(s_min)))
                # Parede colada ao batente direito (s = comp_vao) indo para s > comp_vao
                if (comp_vao - 0.08) <= s_min <= (comp_vao + 0.06) and s_max > (comp_vao + 0.02):
                    avan_dir = max(avan_dir, min(max_ext, s_max - comp_vao))

    p1_ext = (p1_vao[0] - ux * avan_esq, p1_vao[1] - uy * avan_esq)
    p2_ext = (p2_vao[0] + ux * avan_dir, p2_vao[1] + uy * avan_dir)
    return p1_ext, p2_ext, round(avan_esq, 3), round(avan_dir, 3), offset_correto


def aplicar_desvios_estruturais_e_vaos_3d(linha_3d, elementos_arq, z_base, pe_direito, h_viga=0.40):
    """
    Desvia tubulações de Elétrica, Água Fria, Água Quente e Esgoto:
    - Passa por cima da Verga (Topo do Vão + 10cm de Verga) em Portas e Janelas;
    - Ou passa por baixo da Contraverga (Peitoril - 10cm de Contraverga) nas Janelas;
    - Respeita a extensão real (até +30cm para cada lado) da Verga e Contraverga.
    """
    if not elementos_arq or len(linha_3d) < 2:
        return linha_3d

    elems_andar = [e for e in elementos_arq if abs(e.get('z_base', 0.0) - z_base) < 0.6 and e.get('tem_parede_real', True)]
    if not elems_andar:
        return linha_3d

    paredes_ctx = st.session_state.contexto_bim.get('paredes', [])
    z_teto_livre = z_base + pe_direito - 0.06
    ALT_VERGA = 0.10
    nova_linha = [linha_3d[0]]

    for i in range(len(linha_3d) - 1):
        p_ini = linha_3d[i]
        p_fim = linha_3d[i + 1]
        comp_2d = dist_2d(p_ini, p_fim)

        if comp_2d < 0.08:
            nova_linha.append(p_fim)
            continue

        n_passos = max(2, int(comp_2d / 0.10) + 1)
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
                    off_n = elem.get('offset_norm', (0.0, 0.075))
                    p1_ext, p2_ext, _, _, _ = calcular_extensao_verga_na_parede(p1_v, p2_v, z_base, paredes_ctx, max_ext=0.30, offset_padrao=off_n)

                    if distancia_ponto_segmento_2d(px, py, p1_ext[0], p1_ext[1], p2_ext[0], p2_ext[1]) <= 0.22:
                        peitoril = float(elem.get('Peitoril', 0.0))
                        altura_vao = float(elem.get('Altura', 2.10))
                        eh_janela = (elem.get('Subtipo') == 'Janela')

                        z_base_contraverga = z_base + max(0.0, peitoril - ALT_VERGA) if (eh_janela and peitoril >= 0.15) else (z_base + peitoril)
                        z_topo_verga = z_base + peitoril + altura_vao + ALT_VERGA

                        if (z_base_contraverga - 0.04) < pz < (z_topo_verga + 0.04):
                            z_acima_verga = min(z_teto_livre, z_topo_verga + 0.06)
                            z_abaixo_contraverga = max(z_base + 0.05, z_base_contraverga - 0.06)

                            if eh_janela and peitoril >= 0.25:
                                z_ajustado = z_abaixo_contraverga if abs(pz - z_abaixo_contraverga) <= abs(z_acima_verga - pz) else z_acima_verga
                            else:
                                z_ajustado = z_abaixo_contraverga if (peitoril >= 0.15 and pz <= z_base_contraverga + 0.08) else z_acima_verga
                            break

                elif elem.get('Tipo') == 'Pilar/Viga':
                    if math.hypot(px - elem['x'], py - elem['y']) <= (elem.get('Largura', 0.40) / 2.0 + 0.15):
                        z_fundo_viga = z_base + pe_direito - h_viga - 0.05
                        if pz > z_fundo_viga:
                            z_ajustado = z_fundo_viga

            pt_novo = (round(px, 4), round(py, 4), round(z_ajustado, 4))
            if len(nova_linha) >= 2 and abs(nova_linha[-1][2] - pt_novo[2]) < 0.005 and abs(nova_linha[-2][2] - pt_novo[2]) < 0.005:
                if abs(dist_2d(nova_linha[-2], nova_linha[-1]) + dist_2d(nova_linha[-1], pt_novo) - dist_2d(nova_linha[-2], pt_novo)) < 0.005:
                    nova_linha[-1] = pt_novo
                else:
                    nova_linha.append(pt_novo)
            else:
                nova_linha.append(pt_novo)

    return nova_linha


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

    tem_projeto_bim = bool(
        st.session_state.get("projeto_bim_ativo")
        or st.session_state.contexto_bim.get("paredes")
        or st.session_state.contexto_bim.get("df_hidro")
        or st.session_state.get("memoria_edicoes_hidro")
    )

    if arquivos_dxf or tem_projeto_bim:
        ctx_mem = st.session_state.contexto_bim
        layers_salvas_bim = ctx_mem.get("layers_selecionadas", st.session_state.get("layers_selecionadas_mem", {}))

        if arquivos_dxf:
            todas_layers_set = set()
            layers_com_blocos = set()
            dxf_files_only = [f for f in arquivos_dxf if f.name.lower().endswith(".dxf")]

            # Calcula assinatura única (MD5) do conteúdo real dos arquivos DXF para detectar edições no mesmo arquivo
            import hashlib
            hash_dxf_atual = hashlib.md5(b"".join([f.getvalue() for f in arquivos_dxf])).hexdigest()
            hash_dxf_anterior = st.session_state.get("hash_dxf_anterior", "")

            if dxf_files_only:
                for dxf_f in dxf_files_only:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp_file:
                        tmp_file.write(dxf_f.getvalue())
                        temp_path = tmp_file.name
                    doc_base = ezdxf.readfile(temp_path)
                    msp_base = doc_base.modelspace()
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

            layers_conhecidas = st.session_state.get("layers_conhecidas_dxf", set())
            layers_novas_detectadas = (set(todas_layers) - layers_conhecidas) if (layers_conhecidas and hash_dxf_atual != hash_dxf_anterior) else set()
            st.session_state["layers_conhecidas_dxf"] = set(todas_layers)
            st.session_state["hash_dxf_anterior"] = hash_dxf_atual

            if layers_novas_detectadas:
                st.info(f"✨ **Arquivo DXF atualizado! Novas layers detectadas:** `{', '.join(sorted(layers_novas_detectadas))}`")

            def sugerir_layers(palavras_inc, palavras_exc=None, padrao_vazio=False):
                palavras_exc = palavras_exc or []
                sug = []
                for ly in todas_layers:
                    ly_n = normalizar_texto_bim(ly)
                    if any(p in ly_n for p in palavras_inc) and not any(ex in ly_n for ex in palavras_exc):
                        sug.append(ly)
                if not sug and not padrao_vazio and todas_layers:
                    return [todas_layers[0]]
                return sug

            # Sugestões limpas (Exclui ARQ_ESQUADRIA de Paredes e exclui COTA/TEXTO dos blocos MEP)
            sug_arq = sugerir_layers(
                ["ALVENARIA", "PAREDE", "MURO", "ARQ"],
                palavras_exc=["ESQUADRIA", "PORTA", "JANELA", "COTA", "TEXT", "PISO", "FORRO", "TELHA", "PROJ", "MOBIL", " VEGET"],
                padrao_vazio=False
            )
            sug_esq = sugerir_layers(
                ["ESQUADRIA", "PORTA", "JANELA"],
                palavras_exc=["COTA", "TEXT"],
                padrao_vazio=True
            )
            sug_est = sugerir_layers(
                ["VIGA", "PILAR", "ESTRUTURA", "CONCRETO"],
                palavras_exc=["COTA", "TEXT"],
                padrao_vazio=True
            )
            sug_elet = sugerir_layers(
                ["ELETRICA", "ELET", "LUZ", "TOMADA", "ILUM", "QUADRO"],
                palavras_exc=["COTA", "TEXT", "DIM", "LEGENDA"],
                padrao_vazio=True
            )
            sug_hidro = sugerir_layers(
                ["HIDR", "AGUA", "ESGOTO", "SANIT", "TUBULACAO", "PLUVIAL", "GAS", "EQUIPAMENTOS HIDRICOS", "CONEXOES"],
                palavras_exc=["COTA", "TEXT", "DIM", "LEGENDA"],
                padrao_vazio=True
            )

            # Se houver escolhas salvas pelo usuário (no .bim ou na sessão), respeita-as e adiciona apenas layers novas do DXF!
            forcar_releitura = st.session_state.get("forcar_releitura_layers_dxf", False)

            def mesclar_salvas_com_novas(chave_cat, sugestao_base):
                # Filtra apenas layers que realmente existem no DXF recém-carregado
                salvas = [ly for ly in layers_salvas_bim.get(chave_cat, []) if ly in todas_layers]
                # Remove automaticamente ARQ_ESQUADRIA de Paredes e COTA de Hidro caso estivessem gravadas de sessões antigas
                if chave_cat == "arq":
                    salvas = [ly for ly in salvas if not any(ex in normalizar_texto_bim(ly) for ex in ["ESQUADRIA", "PORTA", "JANELA", "COTA"])]
                elif chave_cat in ("hidro", "elet"):
                    salvas = [ly for ly in salvas if not any(ex in normalizar_texto_bim(ly) for ex in ["COTA", "TEXT", "DIM"])]

                if forcar_releitura:
                    # Quando clicou em Atualizar Projeto Atual (DXF/IFC), incorpora todas as layers válidas detectadas no DXF
                    return sorted(list(set(salvas + sugestao_base)))
                if chave_cat in layers_salvas_bim and salvas:
                    novas_da_cat = [ly for ly in layers_novas_detectadas if ly in sugestao_base and ly not in salvas]
                    return sorted(list(set(salvas + novas_da_cat)))
                return sugestao_base

            default_arq = mesclar_salvas_com_novas("arq", sug_arq)
            default_esq = mesclar_salvas_com_novas("esq", sug_esq)
            default_est = mesclar_salvas_com_novas("est", sug_est)
            default_elet = mesclar_salvas_com_novas("elet", sug_elet)
            default_hidro = mesclar_salvas_com_novas("hidro", sug_hidro)

            if forcar_releitura:
                st.session_state["forcar_releitura_layers_dxf"] = False

            col_ly_info, col_ly_btn = st.columns([4, 1.2])
            if col_ly_btn.button("🔄 Resetar Layers p/ Sugestão Limpa", use_container_width=True):
                st.session_state["layers_selecionadas_mem"] = {
                    "arq": sug_arq, "esq": sug_esq, "est": sug_est, "elet": sug_elet, "hidro": sug_hidro
                }
                st.session_state.contexto_bim["layers_selecionadas"] = st.session_state["layers_selecionadas_mem"]
                st.session_state["versao_widgets_layer"] = st.session_state.get("versao_widgets_layer", 0) + 1
                st.rerun()

            v_ly = st.session_state.get("versao_widgets_layer", 0)
            c1, c2, c3, c4, c5 = st.columns(5)
            layer_arq = c1.multiselect("Paredes:", todas_layers, default=default_arq, key=f"ms_ly_arq_{v_ly}")
            layer_esquadrias = c2.multiselect("Esquadrias (Portas/Janelas):", todas_layers, default=default_esq, key=f"ms_ly_esq_{v_ly}")
            layer_estrutural = c3.multiselect("Vigas/Pilares:", todas_layers, default=default_est, key=f"ms_ly_est_{v_ly}")
            layer_elet = c4.multiselect("Blocos Elétricos:", todas_layers, default=default_elet, key=f"ms_ly_elet_{v_ly}")
            layer_hidro = c5.multiselect("Blocos Hidro/Gás/Bomba:", todas_layers, default=default_hidro, key=f"ms_ly_hidro_{v_ly}")

            # Salva imediatamente as escolhas atuais do usuário na sessão e no contexto_bim (para o arquivo .bim)
            escolhas_atuais_ly = {
                "arq": layer_arq,
                "esq": layer_esquadrias,
                "est": layer_estrutural,
                "elet": layer_elet,
                "hidro": layer_hidro
            }
            st.session_state["layers_selecionadas_mem"] = escolhas_atuais_ly
            st.session_state.contexto_bim["layers_selecionadas"] = escolhas_atuais_ly
        else:
            st.success("📂 **Projeto carregado do arquivo `.bim`!** Todas as layers, tabelas, paredes e tubulações 3D estão ativas abaixo. *(Quando subir o arquivo `.dxf`, suas layers salvas no `.bim` serão mantidas automaticamente).*")

        st.divider()
        st.subheader("Configuração de Alturas (Tubulações, Portas e Janelas) e Escopo")
        ctx_mem = st.session_state.contexto_bim
        col_h1, col_h2, col_h3 = st.columns(3)
        h_agua_fria = col_h1.number_input("Altura Tubulação Água Fria na Parede (m)", value=float(ctx_mem.get("h_agua_fria", 0.20)), step=0.1)
        h_agua_quente = col_h2.number_input("Altura Tubulação Água Quente na Parede (m)", value=float(ctx_mem.get("h_agua_quente", 1.00)), step=0.1)
        modo_visualizacao = col_h3.selectbox("Visualização e Escopo do Projeto:", ["Unificado (Elétrica + Hidráulica)", "Apenas Elétrica", "Apenas Hidrossanitário"])

        ce_p1, ce_p2, ce_j1, ce_j2 = st.columns(4)
        soleira_padrao_porta = ce_p1.number_input("Soleira Padrão de Portas (m)", min_value=0.0, max_value=1.0, value=0.00, step=0.05)
        altura_padrao_porta = ce_p2.number_input("Altura Padrão de Portas (m)", min_value=1.5, max_value=4.0, value=2.10, step=0.05)
        peitoril_padrao_janela = ce_j1.number_input("Peitoril Padrão de Janelas (m)", min_value=0.0, max_value=3.0, value=0.80, step=0.05)
        altura_padrao_janela = ce_j2.number_input("Altura Padrão de Janelas (m)", min_value=0.3, max_value=3.5, value=1.45, step=0.05)

        blocos_elet, blocos_hidro, paredes_raw, elementos_arquitetonicos = [], [], [], []
        max_z_projeto = 0.0
        z_acumulado = 0.0

        # MODO A: Se carregou apenas o .bim, valida cada vão salvo para descartar vãos sobre paredes cegas ou folhas de porta
        if not arquivos_dxf:
            paredes_raw = ctx_mem.get("paredes", [])
            for el in ctx_mem.get("elementos_arquitetonicos", []):
                if str(el.get("ID_CAD", "")).startswith("VAO_AUTO_"):
                    continue
                if el.get("Tipo") == "Esquadria":
                    p1_h, p2_h = el.get("p1_vao"), el.get("p2_vao")
                    if p1_h and p2_h:
                        p1_a, p2_a, larg_a, off_a, ok_w = centralizar_segmento_na_espessura_da_parede(
                            p1_h, p2_h, el.get("z_base", 0.0), paredes_raw, exigir_abertura=True
                        )
                        if ok_w:
                            el["p1_vao"], el["p2_vao"], el["Largura"], el["offset_norm"], el["tem_parede_real"] = p1_a, p2_a, larg_a, off_a, True
                            el["x"], el["y"] = round((p1_a[0] + p2_a[0]) / 2.0, 4), round((p1_a[1] + p2_a[1]) / 2.0, 4)
                            elementos_arquitetonicos.append(el)
                else:
                    elementos_arquitetonicos.append(el)

            blocos_elet = st.session_state.get("memoria_edicoes_elet", ctx_mem.get("df_elet", []))
            blocos_hidro = st.session_state.get("memoria_edicoes_hidro", ctx_mem.get("df_hidro", []))
            max_z_projeto = max(0.0, float(ctx_mem.get("max_z_cobertura", 3.0)) - 3.0)

        # MODO B: Leitura de .DXF / .IFC com separação rigorosa entre Janelas (MLine/Line) e Portas (Arco 90° + Vão Aberto)
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

                # 1º) Lê todas as PAREDES do andar (layer_arq)
                paredes_andar = []
                for la in layer_arq:
                    for e_w in msp.query(f'*[layer=="{la}"]'):
                        segs_w = extrair_segmentos_entidade_dxf(e_w, modo="parede")
                        for (x1, y1), (x2, y2) in segs_w:
                            paredes_andar.append(((x1, y1, z_base), (x2, y2, z_base + pe_direito_atual)))
                paredes_raw.extend(paredes_andar)

                # 2º) Coleta todos os segmentos e arcos das layers de Esquadrias
                arcos_portas_dxf = []
                segs_folhas_porta = []
                candidatos_janela = []

                for le in layer_esquadrias:
                    le_u = le.upper()
                    eh_layer_porta = any(k in le_u for k in ["PORTA", "MADEIRA"]) and not any(k in le_u for k in ["JANELA", "JAN"])
                    eh_layer_janela = any(k in le_u for k in ["JANELA", "JAN"])

                    for idx_ent, ent in enumerate(msp.query(f'*[layer=="{le}"]')):
                        dxft = ent.dxftype()
                        if dxft == 'INSERT':
                            nome_b = extrair_nome_real_bloco_dxf(doc, ent)
                            nome_b_u = nome_b.upper()
                            arcos_bloco = []
                            segs_bloco = []
                            try:
                                for ve in ent.virtual_entities():
                                    if ve.dxftype() == 'ARC':
                                        arcos_bloco.append(ve)
                                    else:
                                        segs_bloco.extend(extrair_segmentos_entidade_dxf(ve, modo="esquadria"))
                            except Exception:
                                pass

                            eh_p_bloco = bool(arcos_bloco) or eh_layer_porta or any(k in nome_b_u for k in ["PORTA", "PT", "MADEIRA", "GIRO"])
                            if eh_layer_janela or "JANELA" in nome_b_u:
                                eh_p_bloco = False

                            if eh_p_bloco:
                                segs_folhas_porta.extend(segs_bloco)
                                for arc_v in arcos_bloco:
                                    arcos_portas_dxf.append((arc_v, nome_b, le))
                            else:
                                if segs_bloco:
                                    maior_seg = max(segs_bloco, key=lambda s: dist_2d(s[0], s[1]))
                                    candidatos_janela.append((maior_seg[0], maior_seg[1], nome_b, le))
                        elif dxft == 'ARC':
                            arcos_portas_dxf.append((ent, f"Porta ({le})", le))
                        elif dxft == 'MLINE' and not eh_layer_porta:
                            for s1, s2 in extrair_segmentos_entidade_dxf(ent, modo="esquadria"):
                                candidatos_janela.append((s1, s2, f"Janela MLine ({le})", le))
                        elif dxft in ('LINE', 'LWPOLYLINE', 'POLYLINE'):
                            segs_e = extrair_segmentos_entidade_dxf(ent, modo="esquadria")
                            if eh_layer_porta:
                                # Na layer de porta, linhas retas são folhas da porta aberta ou batentes (nunca o vão!)
                                segs_folhas_porta.extend(segs_e)
                            else:
                                for s1, s2 in segs_e:
                                    candidatos_janela.append((s1, s2, f"Janela ({le})", le))

                # Também busca arcos de 90° em outras layers (ex: arco cinza de porta) que toquem folhas de porta da layer_esquadrias
                if segs_folhas_porta:
                    for arc_geral in msp.query('ARC'):
                        if arc_geral.dxf.layer not in layer_esquadrias:
                            r_g = float(arc_geral.dxf.radius)
                            if 0.50 <= r_g <= 1.30:
                                c_gx, c_gy = float(arc_geral.dxf.center.x), float(arc_geral.dxf.center.y)
                                if any(min(math.hypot(c_gx - f1[0], c_gy - f1[1]), math.hypot(c_gx - f2[0], c_gy - f2[1])) <= 0.20 for f1, f2 in segs_folhas_porta):
                                    arcos_portas_dxf.append((arc_geral, "Porta", layer_esquadrias[0] if layer_esquadrias else arc_geral.dxf.layer))

                vaos_registrados = []

                def vao_ja_existe(p1_n, p2_n):
                    mx_n, my_n = (p1_n[0] + p2_n[0]) / 2.0, (p1_n[1] + p2_n[1]) / 2.0
                    for v_p1, v_p2 in vaos_registrados:
                        vmx, vmy = (v_p1[0] + v_p2[0]) / 2.0, (v_p1[1] + v_p2[1]) / 2.0
                        if math.hypot(mx_n - vmx, my_n - vmy) <= 0.45:
                            return True
                        if distancia_ponto_segmento_2d(mx_n, my_n, v_p1[0], v_p1[1], v_p2[0], v_p2[1]) <= 0.25:
                            return True
                    return False

                # 2.A: Processa todas as PORTAS a partir do arco de 90° e da abertura real na parede
                for idx_p, (arc_e, nome_p, ly_p) in enumerate(arcos_portas_dxf):
                    res_porta = extrair_vao_porta_por_arco_dxf(arc_e, z_base, paredes_andar, segs_folhas_porta)
                    if res_porta is not None:
                        p1_v, p2_v, larg_r, off_n = res_porta
                        if not vao_ja_existe(p1_v, p2_v):
                            vaos_registrados.append((p1_v, p2_v))
                            cx_f, cy_f = round((p1_v[0] + p2_v[0]) / 2.0, 4), round((p1_v[1] + p2_v[1]) / 2.0, 4)
                            elementos_arquitetonicos.append({
                                "ID_CAD": f"PORTA_P{andar_idx}_{idx_p}",
                                "Nome_Bloco": nome_p,
                                "Layer_CAD": ly_p,
                                "Andar": f"Pav {config['ordem']}",
                                "Tipo": "Esquadria",
                                "Subtipo": "Porta",
                                "x": cx_f, "y": cy_f, "z_base": z_base,
                                "pe_direito": pe_direito_atual,
                                "p1_vao": p1_v, "p2_vao": p2_v,
                                "offset_norm": off_n,
                                "tem_parede_real": True,
                                "Largura": larg_r,
                                "Peitoril": soleira_padrao_porta,
                                "Altura": altura_padrao_porta
                            })

                # 2.B: Processa todas as JANELAS mantendo o comprimento exato desenhado no CAD
                # Ordena do maior para o menor segmento para priorizar a linha principal da janela e fundir linhas paralelas
                candidatos_janela.sort(key=lambda item: dist_2d(item[0], item[1]), reverse=True)
                for idx_j, (s1, s2, nome_j, ly_j) in enumerate(candidatos_janela):
                    comp_j = dist_2d(s1, s2)
                    if not (0.40 <= comp_j <= 3.20):
                        continue
                    p1_v, p2_v, larg_r, off_n, ok_w = centralizar_segmento_na_espessura_da_parede(
                        s1, s2, z_base, paredes_andar, exigir_abertura=False
                    )
                    if ok_w and not vao_ja_existe(p1_v, p2_v):
                        vaos_registrados.append((p1_v, p2_v))
                        cx_f, cy_f = round((p1_v[0] + p2_v[0]) / 2.0, 4), round((p1_v[1] + p2_v[1]) / 2.0, 4)
                        eh_bascula = any(k in nome_j.upper() for k in ["BASC", "BANH", "WC", "J_ALTA"])
                        elementos_arquitetonicos.append({
                            "ID_CAD": f"JANELA_P{andar_idx}_{idx_j}",
                            "Nome_Bloco": nome_j,
                            "Layer_CAD": ly_j,
                            "Andar": f"Pav {config['ordem']}",
                            "Tipo": "Esquadria",
                            "Subtipo": "Janela",
                            "x": cx_f, "y": cy_f, "z_base": z_base,
                            "pe_direito": pe_direito_atual,
                            "p1_vao": p1_v, "p2_vao": p2_v,
                            "offset_norm": off_n,
                            "tem_parede_real": True,
                            "Largura": larg_r,
                            "Peitoril": 1.60 if eh_bascula else peitoril_padrao_janela,
                            "Altura": 0.60 if eh_bascula else altura_padrao_janela
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
                os.unlink(temp_path)

            z_acumulado += pe_direito_atual + espessura_laje

        assinatura_padroes = f"{soleira_padrao_porta}_{altura_padrao_porta}_{peitoril_padrao_janela}_{altura_padrao_janela}"
        padroes_mudaram = (st.session_state.get("assinatura_padroes_esq", "") != assinatura_padroes)
        st.session_state["assinatura_padroes_esq"] = assinatura_padroes

        esquadrias_lista = [el for el in elementos_arquitetonicos if el.get("Tipo") == "Esquadria" and el.get("tem_parede_real", True)]
        if esquadrias_lista:
            with st.expander(f"🚪🪟 Editar Peitoril, Soleira, Vergas e Alturas de Portas e Janelas ({len(esquadrias_lista)} vãos reais nas paredes)", expanded=False):
                st.caption("Vergas e Contravergas de 10cm de altura (+30cm para cada lado, limitadas pelas quinas da parede) são geradas exclusivamente sobre os vãos reais:")
                df_esq_raw = pd.DataFrame(esquadrias_lista)
                mem_esq = st.session_state.get("memoria_edicoes_esq_v2", {})

                for idx_e, r_e in df_esq_raw.iterrows():
                    chave_pos = f"{r_e.get('Andar','')}_{round(float(r_e['x']),2)}_{round(float(r_e['y']),2)}"
                    if chave_pos in mem_esq and not padroes_mudaram:
                        df_esq_raw.at[idx_e, "Subtipo"] = mem_esq[chave_pos]["Subtipo"]
                        df_esq_raw.at[idx_e, "Peitoril"] = mem_esq[chave_pos]["Peitoril"]
                        df_esq_raw.at[idx_e, "Altura"] = mem_esq[chave_pos]["Altura"]
                        df_esq_raw.at[idx_e, "Largura"] = mem_esq[chave_pos]["Largura"]
                    else:
                        eh_p = (r_e["Subtipo"] == "Porta")
                        df_esq_raw.at[idx_e, "Peitoril"] = soleira_padrao_porta if eh_p else peitoril_padrao_janela
                        df_esq_raw.at[idx_e, "Altura"] = altura_padrao_porta if eh_p else altura_padrao_janela

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
                    key=f"editor_esq_v2_{st.session_state.get('sync_version', 0)}_{assinatura_padroes}"
                )

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
                st.session_state["memoria_edicoes_esq_v2"] = novo_mem_esq

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
                garantir_itens_extras_na_bib_eletrica()
                opcoes_eq_elet = list(st.session_state.bib_eletrica['Equipamento'])
                opcoes_tipo_fisico_el = [
                    "Quadro Geral",
                    "Luminária",
                    "Caixa 4x2",
                    "Caixa 4x4",
                    "Caixa de Passagem",
                    "Conexão / Eletroduto"
                ]

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

                df_be, stats_el = mesclar_blocos_com_memoria(df_be, disciplina="elet")

                dict_map_elet = st.session_state.get("mapa_blocos_elet", {})
                for blk_e, d_el in dict_map_elet.items():
                    base_e = str(blk_e).split("(")[0].strip()
                    mask_e = (df_be['Nome_Bloco'] == blk_e) | (df_be['Nome_Bloco'].apply(lambda x: str(x).split("(")[0].strip() == base_e))
                    df_be.loc[mask_e, 'Tipo_BIM'] = d_el["tipo_bim"]
                    df_be.loc[mask_e, 'Equipamento_Associado'] = d_el["equip"]
                    df_be.loc[mask_e, 'Amperagem_Tomadas'] = d_el["amp"]
                    df_be.loc[mask_e, 'Tensao_V'] = d_el["tensao"]
                    df_be.loc[mask_e, 'z_relativo'] = d_el["z_rel"]

                nomes_unicos_elet = sorted(df_be['Nome_Bloco'].unique().tolist())
                with st.expander("🪄 Mapeamento em Lote por Nome_Bloco Elétrico (Ideal para blocos *U...)", expanded=False):
                    st.caption("Associe um bloco elétrico repetido do CAD para atualizar todas as linhas dele simultaneamente:")
                    ce_l1, ce_l2, ce_l3 = st.columns([1.5, 2, 1.3])
                    bloco_el_alvo = ce_l1.selectbox("Bloco Elétrico do CAD:", nomes_unicos_elet, key="sel_blk_elet_lote")
                    eq_el_alvo = ce_l2.selectbox("Carga (Biblioteca):", opcoes_eq_elet, key="sel_eq_elet_lote")
                    tipo_el_alvo = ce_l3.selectbox("Tipo Físico BIM:", opcoes_tipo_fisico_el, key="sel_tp_elet_lote")

                    ce_l4, ce_l5, ce_l6 = st.columns(3)
                    amp_el_alvo = ce_l4.selectbox("Amperagem:", ["10A", "20A"], key="sel_amp_elet_lote")
                    tens_el_alvo = ce_l5.selectbox("Tensão (V):", [127, 220], index=1 if tensao_fase == 220 else 0, key="sel_v_elet_lote")
                    z_el_alvo = ce_l6.number_input("Altura z_relativo (m):", min_value=0.0, max_value=4.5, value=1.30, step=0.10, key="sel_z_elet_lote")

                    if st.button("✅ Aplicar a todos os blocos elétricos deste tipo", use_container_width=True):
                        dict_map_elet[bloco_el_alvo] = {
                            "tipo_bim": tipo_el_alvo, "equip": eq_el_alvo,
                            "amp": amp_el_alvo, "tensao": int(tens_el_alvo), "z_rel": float(z_el_alvo)
                        }
                        st.session_state["mapa_blocos_elet"] = dict_map_elet
                        base_e = str(bloco_el_alvo).split("(")[0].strip()
                        mask_e = (df_be['Nome_Bloco'] == bloco_el_alvo) | (df_be['Nome_Bloco'].apply(lambda x: str(x).split("(")[0].strip() == base_e))
                        df_be.loc[mask_e, 'Tipo_BIM'] = tipo_el_alvo
                        df_be.loc[mask_e, 'Equipamento_Associado'] = eq_el_alvo
                        df_be.loc[mask_e, 'Amperagem_Tomadas'] = amp_el_alvo
                        df_be.loc[mask_e, 'Tensao_V'] = int(tens_el_alvo)
                        df_be.loc[mask_e, 'z_relativo'] = float(z_el_alvo)
                        salvar_edicoes_na_memoria(df_be, pd.DataFrame(st.session_state.get("memoria_edicoes_hidro", [])))
                        st.session_state["sync_version"] = st.session_state.get("sync_version", 0) + 1
                        st.rerun()

                for idx_el_z, r_el_z in df_be.iterrows():
                    id_ez = str(r_el_z['ID_CAD'])
                    if id_ez in st.session_state.get("overrides_topologia_bim", {}) and "z_relativo" in st.session_state["overrides_topologia_bim"][id_ez]:
                        df_be.at[idx_el_z, 'z_relativo'] = float(st.session_state["overrides_topologia_bim"][id_ez]["z_relativo"])
                df_editado_elet = st.data_editor(
                    df_be,
                    column_config={
                        "Tipo_BIM": st.column_config.SelectboxColumn("Tipo Físico", options=opcoes_tipo_fisico_el),
                        "Equipamento_Associado": st.column_config.SelectboxColumn("Carga (Biblioteca)", options=opcoes_eq_elet),
                        "Amperagem_Tomadas": st.column_config.SelectboxColumn("Amperagem", options=["10A", "20A"]),
                        "Tensao_V": st.column_config.SelectboxColumn("Tensão (V)", options=[127, 220]),
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
                    if 'Caixa' in str(row['Tipo_BIM']) and int(row.get('Qtd_Interruptores', 0)) > 0:
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
                opcoes_func_bim = [
                    "Aparelho Hidráulico",
                    "Caixa Sifonada / Ralo Sifonado",
                    "Caixa de Gordura",
                    "Conexões Hidráulicas AF",
                    "Conexões Hidráulicas AQ",
                    "Conexões Tubulação Esgoto",
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

                tipos_bim_h, equips_h, z_rel_h = [], [], []
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

                df_bh, stats_hd = mesclar_blocos_com_memoria(df_bh, disciplina="hidro")

                # 2. Auto-correção de função BIM (sem sobrescrever alturas z_relativo já editadas pelo usuário!)
                ov_z_mem = st.session_state.get("overrides_topologia_bim", {})
                z_lote_bloco = st.session_state.get("z_global_por_bloco", {})
                z_lote_equip = st.session_state.get("z_global_por_equip", {})

                for idx_fix, r_fix in df_bh.iterrows():
                    id_f = str(r_fix.get('ID_CAD', ''))
                    nb_raw = str(r_fix.get('Nome_Bloco', ''))
                    nb_norm = normalizar_texto_bim(f"{nb_raw} {r_fix.get('Equipamento', '')}")
                    if "GORDURA" in nb_norm or "[CG]" in nb_norm:
                        df_bh.at[idx_fix, 'Tipo_BIM'] = "Caixa de Gordura"
                        if "GORDURA" not in normalizar_texto_bim(r_fix.get('Equipamento', '')):
                            df_bh.at[idx_fix, 'Equipamento'] = "Caixa de Gordura"
                    elif "SIFONAD" in nb_norm:
                        df_bh.at[idx_fix, 'Tipo_BIM'] = "Caixa Sifonada / Ralo Sifonado"
                    elif ("INSPECAO" in nb_norm or "[CI]" in nb_norm) and r_fix.get('Tipo_BIM') != "Caixa de Inspeção / Destino Esgoto":
                        df_bh.at[idx_fix, 'Tipo_BIM'] = "Caixa de Inspeção / Destino Esgoto"
                        df_bh.at[idx_fix, 'Equipamento'] = "Caixa de Inspeção"

                    # Aplica alturas Z salvas globalmente (por Equipamento ou Nome_Bloco) ou individualmente no 3D/2D
                    eq_atual_f = str(df_bh.at[idx_fix, 'Equipamento'])
                    if eq_atual_f in z_lote_equip:
                        df_bh.at[idx_fix, 'z_relativo'] = float(z_lote_equip[eq_atual_f])
                    if nb_raw in z_lote_bloco:
                        df_bh.at[idx_fix, 'z_relativo'] = float(z_lote_bloco[nb_raw])
                    if id_f in ov_z_mem and "z_relativo" in ov_z_mem[id_f]:
                        df_bh.at[idx_fix, 'z_relativo'] = float(ov_z_mem[id_f]["z_relativo"])

                dict_map_lote = st.session_state.get("mapa_blocos_hidro", {})
                for blk_k, (fn_v, eq_v) in dict_map_lote.items():
                    base_k = str(blk_k).split("(")[0].strip()
                    mask_b = (df_bh['Nome_Bloco'] == blk_k) | (df_bh['Nome_Bloco'].apply(lambda x: str(x).split("(")[0].strip() == base_k))
                    df_bh.loc[mask_b, 'Tipo_BIM'] = fn_v
                    df_bh.loc[mask_b, 'Equipamento'] = eq_v

                nomes_unicos_blocos = sorted(df_bh['Nome_Bloco'].unique().tolist())
                with st.expander("🪄 Mapeamento em Lote por Nome_Bloco (Ideal para blocos *U63, *U65...)", expanded=False):
                    st.caption("Se um bloco do CAD repetir várias vezes, vincule-o abaixo para atualizar todas as linhas dele de uma só vez:")
                    cm1, cm2, cm3 = st.columns([1.5, 2, 1.5])
                    bloco_alvo = cm1.selectbox("Bloco do CAD:", nomes_unicos_blocos, key="sel_blk_lote")
                    eq_alvo = cm2.selectbox("Associar ao Equipamento:", opcoes_equip, key="sel_eq_lote")
                    func_alvo = cm3.selectbox("Função BIM:", opcoes_func_bim, key="sel_fn_lote")
                    if st.button("✅ Aplicar a todos os blocos deste tipo", use_container_width=True):
                        dict_map_lote[bloco_alvo] = (func_alvo, eq_alvo)
                        st.session_state["mapa_blocos_hidro"] = dict_map_lote
                        base_alvo = str(bloco_alvo).split("(")[0].strip()
                        mask_alvo = (df_bh['Nome_Bloco'] == bloco_alvo) | (df_bh['Nome_Bloco'].apply(lambda x: str(x).split("(")[0].strip() == base_alvo))
                        df_bh.loc[mask_alvo, 'Tipo_BIM'] = func_alvo
                        df_bh.loc[mask_alvo, 'Equipamento'] = eq_alvo
                        salvar_edicoes_na_memoria(df_editado_elet if 'df_editado_elet' in locals() else pd.DataFrame(), df_bh)
                        st.session_state["sync_version"] = st.session_state.get("sync_version", 0) + 1
                        st.rerun()

                altura_caixa_atual = float(st.session_state.get("altura_caixa_3d", 1.50))
                mask_cx_agua = (df_bh['Tipo_BIM'] == "Caixa d'Água") | (df_bh['Equipamento'].astype(str).str.contains("Caixa d'Água", na=False))
                if mask_cx_agua.any():
                    df_bh.loc[mask_cx_agua, 'z_relativo'] = altura_caixa_atual

                df_editado_hidro = st.data_editor(
                    df_bh,
                    column_config={
                        "Tipo_BIM": st.column_config.SelectboxColumn("Função BIM", options=opcoes_func_bim),
                        "Equipamento": st.column_config.SelectboxColumn("Eq. (Biblioteca)", options=opcoes_equip)
                    },
                    use_container_width=True,
                    hide_index=True,
                    key=f"editor_hidro_v{st.session_state.get('sync_version', 0)}"
                )

                tem_caixa = not df_editado_hidro[
                    (df_editado_hidro['Tipo_BIM'] == "Caixa d'Água") |
                    (df_editado_hidro['Equipamento'].astype(str).str.contains("Caixa d'Água", na=False))
                ].empty

                if tem_caixa:
                    st.markdown("**🚰 Parâmetros da Caixa d'Água 3D**")
                    c_cx1, c_cx2 = st.columns(2)
                    altura_caixa = c_cx1.number_input(
                        "Altura acima da última laje (m) → [z_relativo]",
                        min_value=0.2,
                        value=altura_caixa_atual,
                        step=0.1
                    )
                    num_barriletes = c_cx2.number_input("Nº de Barriletes", min_value=1, value=1, step=1)

                    if abs(altura_caixa - altura_caixa_atual) > 0.001:
                        st.session_state["altura_caixa_3d"] = float(altura_caixa)
                        mask_cx_ed = (df_editado_hidro['Tipo_BIM'] == "Caixa d'Água") | (df_editado_hidro['Equipamento'].astype(str).str.contains("Caixa d'Água", na=False))
                        df_editado_hidro.loc[mask_cx_ed, 'z_relativo'] = float(altura_caixa)
                        salvar_edicoes_na_memoria(df_editado_elet if 'df_editado_elet' in locals() else pd.DataFrame(), df_editado_hidro)
                        st.session_state["sync_version"] = st.session_state.get("sync_version", 0) + 1
                        st.rerun()
                else:
                    altura_caixa = altura_caixa_atual
                    num_barriletes = 1

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

        st.session_state.contexto_bim['paredes'] = paredes_raw
        st.session_state.contexto_bim['elementos_arquitetonicos'] = elementos_arquitetonicos
        st.session_state.contexto_bim['df_elet'] = df_editado_elet.to_dict('records') if not df_editado_elet.empty else []
        st.session_state.contexto_bim['df_hidro'] = df_editado_hidro.to_dict('records') if not df_editado_hidro.empty else []
        if col_btn_proc.button("🚀 Processar Rotas Multidisciplinares, Dimensionamento ABNT e Quantitativos", type="primary", use_container_width=True):
            with st.spinner("Mapeando vigas, pilares, vergas/contravergas (+30cm), múltiplas prumadas e calculando malhas ABNT..."):
                pontos_gerais = []
                if not df_editado_elet.empty:
                    pontos_gerais.extend(df_editado_elet.to_dict('records'))
                if not df_editado_hidro.empty:
                    pontos_gerais.extend(df_editado_hidro.to_dict('records'))

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
                    'incluir_shaft': incluir_shaft, 'rotear_em_cascata': rotear_em_cascata,
                    'layers_selecionadas': st.session_state.get("layers_selecionadas_mem", {})
                }

                ctx = st.session_state.contexto_bim
                linhas_hidro = rotear_hidro(ctx['df_hidro'], ctx) if modo_visualizacao != "Apenas Elétrica" else []
                linhas_elet = rotear_eletrica(ctx['df_eletrica'], ctx) if modo_visualizacao != "Apenas Hidrossanitário" else []
                st.session_state.linhas_3d_master = {'eletrica': linhas_elet, 'hidro': linhas_hidro, 'equipamentos_3d': pontos_gerais}
                st.session_state.colisoes_detectadas = []

                novos_circuitos = []
                grupos_agrupados = {}
                for b_el in ctx['df_eletrica']:
                    if b_el['Tipo_BIM'] in ['Quadro Geral', 'Caixa de Passagem', 'Conexão / Eletroduto'] or (int(b_el.get('Qtd_Tomadas', 0)) == 0 and b_el['Tipo_BIM'] != 'Luminária'): continue

                    eq_nome = b_el.get('Equipamento_Associado', 'Tomada Uso Geral (TUG)')
                    filtro_el = st.session_state.bib_eletrica['Equipamento'] == eq_nome
                    if filtro_el.any():
                        row_bib = st.session_state.bib_eletrica.loc[filtro_el].iloc[0]
                        pot_unit, tensao_eq, fp_eq, tipo_eq, curva_eq, uso_dr = float(row_bib['Potência (W)']), int(b_el.get('Tensao_V', row_bib['Tensão (V)'])), float(row_bib['Fator de Potência']), str(row_bib['Tipo']), str(row_bib['Curva Disjuntor']), str(row_bib['Uso de DR'])
                    else:
                        pot_unit, tensao_eq, fp_eq, tipo_eq, curva_eq, uso_dr = 100.0, 127, 1.0, "TUG", "B", "Opcional"

                    if b_el.get('Amperagem_Tomadas') == '20A' and pot_unit == 100.0:
                        pot_unit = 600.0
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
                    if b_hd['Tipo_BIM'] not in [
                        'Aparelho Hidráulico', 'Caixa Sifonada / Ralo Sifonado',
                        'Caixa de Gordura', 'Ramal de Descarga', 'Ramal de Esgoto'
                    ]:
                        continue
                    eq_h = b_hd['Equipamento']
                    filtro_h = st.session_state.bib_hidro['Equipamento'] == eq_h
                    if not filtro_h.any():
                        continue
                    row_h = st.session_state.bib_hidro.loc[filtro_h].iloc[0]
                    peso_h, uhc_h, af_mm, esg_mm, pressao_req_kpa = float(row_h['Peso']), float(row_h['UHC']), int(row_h['Agua_mm']), int(row_h['Esgoto_mm']), float(row_h['Pressao_kpa'])

                    # Se for Caixa de Gordura ou Caixa Sifonada, não consome Água Fria e exibe conformidade sanitária NBR 8160
                    if b_hd['Tipo_BIM'] in ['Caixa de Gordura', 'Caixa Sifonada / Ralo Sifonado', 'Ramal de Descarga', 'Ramal de Esgoto']:
                        rota_esg_no = next((r for r in linhas_hidro if r.get('id_ap') == b_hd['ID_CAD']), None)
                        comp_esg_m = calcular_comprimento_rota(rota_esg_no['pontos']) if rota_esg_no else 3.0
                        uhc_real = rota_esg_no.get('uhc_acumulado_no', uhc_h) if rota_esg_no else uhc_h
                        dn_esg_real = rota_esg_no.get('diametro', esg_mm) if rota_esg_no else esg_mm
                        z_ponto = b_hd['z_base'] + b_hd.get('z_relativo', 0.0)
                        if b_hd['Tipo_BIM'] == 'Caixa de Gordura':
                            status_pressao = "OK (Septo ≥20cm | Retenção NBR 8160)"
                        elif b_hd['Tipo_BIM'] == 'Caixa Sifonada / Ralo Sifonado':
                            status_pressao = "OK (Fecho Hídrico ≥50mm NBR 8160)"
                        else:
                            status_pressao = "OK (Escoamento Gravidade NBR 8160)"

                        novos_pontos_hidro.append({
                            "ID": b_hd['ID_CAD'], "Andar": b_hd.get('Andar', 'Pav 0'), "Ambiente": b_hd['Tipo_BIM'],
                            "Equipamento": eq_h, "z": round(z_ponto, 2), "Peso (NBR 5626)": 0.0, "Vazão (L/s)": 0.0,
                            "Tubo AF (mm)": 0, "L Real + Eq (m)": round(comp_esg_m, 2), "Perda Carga (m.c.a.)": 0.0,
                            "Pressão Estática (m.c.a.)": 0.0, "Pressão Disp. (kPa)": 0.0,
                            "Pressão Mín. (kPa)": 0.0, "Status Pressão": status_pressao,
                            "UHC": uhc_real, "Tubo Esgoto (mm)": dn_esg_real,
                            "Declividade Esg. (%)": 1.0 if dn_esg_real >= 100 else 2.0
                        })
                        continue
                    eq_h = b_hd['Equipamento']
                    filtro_h = st.session_state.bib_hidro['Equipamento'] == eq_h
                    if not filtro_h.any():
                        continue
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

                    if pressao_disp_kpa < pressao_req_kpa:
                        status_pressao = "⚠️ Pressurizar! (< Mín.)"
                    elif pressao_estatica_mca > 40.0:
                        status_pressao = "⚠️ Instalar VRP (> 40 m.c.a.)"
                    else:
                        status_pressao = "OK (NBR 5626)"

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
                st.success("✅ Roteamento 3D (DXF/IFC), Vergas/Contravergas (+30cm), Múltiplas Prumadas e Quantitativos concluídos!")

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

            # 1. PAREDES 3D EM MODO RAIO-X + FECHAMENTO ESTRITO NOS VÃOS REAIS + VERGAS E CONTRAVERGAS (+30cm)
            wx_base, wy_base, wz_base = [], [], []
            wx_topo, wy_topo, wz_topo = [], [], []
            mesh_x, mesh_y, mesh_z = [], [], []
            mesh_i, mesh_j, mesh_k = [], [], []

            vg_mesh_x, vg_mesh_y, vg_mesh_z = [], [], []
            vg_mesh_i, vg_mesh_j, vg_mesh_k = [], [], []
            vg_wire_x, vg_wire_y, vg_wire_z = [], [], []

            def adicionar_painel_vertical_3d(pa, pb, z0, z1, mx, my, mz, mi, mj, mk, wx_w=None, wy_w=None, wz_w=None):
                if z1 <= z0 + 0.01:
                    return
                iv = len(mx)
                mx.extend([pa[0], pb[0], pb[0], pa[0]])
                my.extend([pa[1], pb[1], pb[1], pa[1]])
                mz.extend([z0, z0, z1, z1])
                mi.extend([iv, iv])
                mj.extend([iv + 1, iv + 2])
                mk.extend([iv + 2, iv + 3])
                if wx_w is not None:
                    wx_w.extend([pa[0], pb[0], None, pa[0], pb[0], None, pa[0], pa[0], None, pb[0], pb[0], None])
                    wy_w.extend([pa[1], pb[1], None, pa[1], pb[1], None, pa[1], pa[1], None, pb[1], pb[1], None])
                    wz_w.extend([z0, z0, None, z1, z1, None, z0, z1, None, z0, z1, None])

            def adicionar_bloco_duplo_parede_3d(pa, pb, z0, z1, offset_n, mx, my, mz, mi, mj, mk, wx_w, wy_w, wz_w):
                if z1 <= z0 + 0.01:
                    return
                ox, oy = offset_n
                p1a, p2a = (pa[0] + ox, pa[1] + oy), (pb[0] + ox, pb[1] + oy)
                p1b, p2b = (pa[0] - ox, pa[1] - oy), (pb[0] - ox, pb[1] - oy)
                adicionar_painel_vertical_3d(p1a, p2a, z0, z1, mx, my, mz, mi, mj, mk, wx_w, wy_w, wz_w)
                adicionar_painel_vertical_3d(p1b, p2b, z0, z1, mx, my, mz, mi, mj, mk, wx_w, wy_w, wz_w)

            for p1, p2 in paredes_filtradas:
                if dist_2d(p1, p2) < 0.05:
                    continue
                z_piso = p1[2]
                z_topo = p2[2] if p2[2] > z_piso else (z_piso + 3.0)

                wx_base.extend([p1[0], p2[0], None])
                wy_base.extend([p1[1], p2[1], None])
                wz_base.extend([z_piso, z_piso, None])

                wx_topo.extend([p1[0], p2[0], None, p1[0], p1[0], None, p2[0], p2[0], None])
                wy_topo.extend([p1[1], p2[1], None, p1[1], p1[1], None, p2[1], p2[1], None])
                wz_topo.extend([z_topo, z_topo, None, z_piso, z_topo, None, z_piso, z_topo, None])

                adicionar_painel_vertical_3d(p1, p2, z_piso, z_topo, mesh_x, mesh_y, mesh_z, mesh_i, mesh_j, mesh_k)

            px_porta, py_porta, pz_porta = [], [], []
            jx_jan, jy_jan, jz_jan = [], [], []
            ex_est, ey_est, ez_est = [], [], []
            ALT_VERGA = 0.10

            for elem in elementos_arquitetonicos:
                if pts_ref_x and not (lim_x_min <= elem['x'] <= lim_x_max and lim_y_min <= elem['y'] <= lim_y_max):
                    continue
                if elem['Tipo'] == 'Pilar/Viga':
                    h_pilar = elem.get('pe_direito', 3.0)
                    ex_est.extend([elem['x'], elem['x'], None])
                    ey_est.extend([elem['y'], elem['y'], None])
                    ez_est.extend([elem['z_base'], elem['z_base'] + h_pilar, None])

                elif elem['Tipo'] == 'Esquadria':
                    # Só desenha paredes de peitoril/verga se o vão pertencer comprovadamente a uma parede real
                    if not elem.get('tem_parede_real', True):
                        continue
                    z_piso_e = float(elem.get('z_base', 0.0))
                    z_teto_e = z_piso_e + float(elem.get('pe_direito', 3.0))
                    peit_val = float(elem.get('Peitoril', 0.0))
                    alt_val = float(elem.get('Altura', 2.10))
                    z_inf = z_piso_e + peit_val
                    z_sup = min(z_teto_e, z_inf + alt_val)

                    p1_v = elem.get('p1_vao')
                    p2_v = elem.get('p2_vao')
                    if not p1_v or not p2_v:
                        continue
                    off_norm = elem.get('offset_norm', (0.0, 0.075))

                    p1_ext, p2_ext, _, _, offset_norm = calcular_extensao_verga_na_parede(
                        p1_v, p2_v, z_piso_e, paredes_filtradas, max_ext=0.30, offset_padrao=off_norm
                    )

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

                    # CONTRAVERGA (10cm abaixo do peitoril + até 30cm p/ cada lado) + PAREDE ABAIXO DA JANELA
                    if elem.get('Subtipo') == 'Janela' and peit_val >= 0.15:
                        z_base_cv = max(z_piso_e, z_inf - ALT_VERGA)
                        adicionar_bloco_duplo_parede_3d(
                            p1_ext, p2_ext, z_base_cv, z_inf, offset_norm,
                            vg_mesh_x, vg_mesh_y, vg_mesh_z, vg_mesh_i, vg_mesh_j, vg_mesh_k,
                            vg_wire_x, vg_wire_y, vg_wire_z
                        )
                        if z_base_cv > z_piso_e + 0.02:
                            adicionar_bloco_duplo_parede_3d(
                                p1_v, p2_v, z_piso_e, z_base_cv, offset_norm,
                                mesh_x, mesh_y, mesh_z, mesh_i, mesh_j, mesh_k,
                                wx_topo, wy_topo, wz_topo
                            )
                    elif z_inf > z_piso_e + 0.02:
                        adicionar_bloco_duplo_parede_3d(
                            p1_v, p2_v, z_piso_e, z_inf, offset_norm,
                            mesh_x, mesh_y, mesh_z, mesh_i, mesh_j, mesh_k,
                            wx_topo, wy_topo, wz_topo
                        )

                    # VERGA SUPERIOR (10cm acima de Portas e Janelas + até 30cm p/ cada lado) + PAREDE ACIMA DA VERGA
                    if z_sup < z_teto_e - 0.02:
                        z_topo_vg = min(z_teto_e, z_sup + ALT_VERGA)
                        adicionar_bloco_duplo_parede_3d(
                            p1_ext, p2_ext, z_sup, z_topo_vg, offset_norm,
                            vg_mesh_x, vg_mesh_y, vg_mesh_z, vg_mesh_i, vg_mesh_j, vg_mesh_k,
                            vg_wire_x, vg_wire_y, vg_wire_z
                        )
                        if z_teto_e > z_topo_vg + 0.02:
                            adicionar_bloco_duplo_parede_3d(
                                p1_v, p2_v, z_topo_vg, z_teto_e, offset_norm,
                                mesh_x, mesh_y, mesh_z, mesh_i, mesh_j, mesh_k,
                                wx_topo, wy_topo, wz_topo
                            )

            if mesh_x:
                fig.add_trace(go.Mesh3d(
                    x=mesh_x, y=mesh_y, z=mesh_z,
                    i=mesh_i, j=mesh_j, k=mesh_k,
                    color='#94a3b8', opacity=0.22,
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
                    line=dict(color='rgba(71, 85, 105, 0.50)', width=1.5),
                    name='🏢 Paredes 3D (Wireframe Superior)',
                    legendgroup='paredes_wire', showlegend=True, hoverinfo='skip'
                ))

            if vg_mesh_x:
                fig.add_trace(go.Mesh3d(
                    x=vg_mesh_x, y=vg_mesh_y, z=vg_mesh_z,
                    i=vg_mesh_i, j=vg_mesh_j, k=vg_mesh_k,
                    color='#475569', opacity=0.55,
                    name='🧱 Vergas e Contravergas (10cm | +30cm)',
                    legendgroup='vergas_3d', showlegend=True, hoverinfo='skip'
                ))
            if vg_wire_x:
                fig.add_trace(go.Scatter3d(
                    x=vg_wire_x, y=vg_wire_y, z=vg_wire_z, mode='lines',
                    line=dict(color='#334155', width=2.0),
                    name='🧱 Vergas e Contravergas (Arestas)',
                    legendgroup='vergas_3d', showlegend=False, hoverinfo='skip'
                ))

            if px_porta:
                fig.add_trace(go.Scatter3d(
                    x=px_porta, y=py_porta, z=pz_porta, mode='lines',
                    line=dict(color='#d97706', width=3.5),
                    name='🚪 Vãos de Porta (3D)', legendgroup='portas'
                ))
            if jx_jan:
                fig.add_trace(go.Scatter3d(
                    x=jx_jan, y=jy_jan, z=jz_jan, mode='lines',
                    line=dict(color='#0284c7', width=3.5),
                    name='🪟 Vãos de Janela (3D)', legendgroup='janelas'
                ))
            if ex_est:
                fig.add_trace(go.Scatter3d(
                    x=ex_est, y=ey_est, z=ez_est, mode='lines',
                    line=dict(color='#334155', width=6),
                    name='🧱 Pilares / Vigas (3D)', legendgroup='pilares'
                ))

            # 3. REDES ELÉTRICAS E HIDROSSANITÁRIAS COM CLIQUE ESQUERDO (POPUP EIXO Z) E SCROLL CENTRAL (ORBITAR)
            import streamlit.components.v1 as components

            # Processa imediatamente qualquer alteração de Altura Z enviada pelo Popup Flutuante 3D
            cmd_z3d = st.session_state.get("bridge_z3d_input", "")
            if cmd_z3d and cmd_z3d != st.session_state.get("ultimo_cmd_z3d_proc", ""):
                st.session_state["ultimo_cmd_z3d_proc"] = cmd_z3d
                partes_cmd = str(cmd_z3d).split("|")
                if len(partes_cmd) >= 3:
                    id_alvo_cmd = partes_cmd[0].strip()
                    try:
                        novo_z_cmd = round(float(partes_cmd[1].replace(",", ".")), 3)
                    except Exception:
                        novo_z_cmd = 0.50
                    escopo_cmd = partes_cmd[2].strip()  # 'PONTO', 'BLOCO' ou 'EQUIP'

                    todos_tmp = (df_editado_elet.to_dict('records') if not df_editado_elet.empty else []) + (df_editado_hidro.to_dict('records') if not df_editado_hidro.empty else [])
                    blk_ref_cmd = next((b for b in todos_tmp if str(b.get('ID_CAD')) == id_alvo_cmd), None)

                    if blk_ref_cmd is not None:
                        nome_b_cmd = str(blk_ref_cmd.get('Nome_Bloco', ''))
                        eq_b_cmd = str(blk_ref_cmd.get('Equipamento', blk_ref_cmd.get('Equipamento_Associado', '')))

                        if escopo_cmd == "BLOCO":
                            ids_afetar = {str(b['ID_CAD']) for b in todos_tmp if str(b.get('Nome_Bloco', '')) == nome_b_cmd}
                            st.session_state.setdefault("z_global_por_bloco", {})[nome_b_cmd] = novo_z_cmd
                        elif escopo_cmd == "EQUIP":
                            ids_afetar = {str(b['ID_CAD']) for b in todos_tmp if str(b.get('Equipamento', b.get('Equipamento_Associado', ''))) == eq_b_cmd}
                            st.session_state.setdefault("z_global_por_equip", {})[eq_b_cmd] = novo_z_cmd
                        else:
                            ids_afetar = {id_alvo_cmd}

                        # 1. Atualiza DataFrames da Aba 1
                        if not df_editado_elet.empty:
                            m_el = df_editado_elet['ID_CAD'].astype(str).isin(ids_afetar)
                            if m_el.any():
                                df_editado_elet.loc[m_el, 'z_relativo'] = novo_z_cmd
                        if not df_editado_hidro.empty:
                            m_hd = df_editado_hidro['ID_CAD'].astype(str).isin(ids_afetar)
                            if m_hd.any():
                                df_editado_hidro.loc[m_hd, 'z_relativo'] = novo_z_cmd

                        # 2. Atualiza Memória Smart Sync por coordenada
                        salvar_edicoes_na_memoria(df_editado_elet, df_editado_hidro)

                        # 3. Atualiza Overrides Topológicos (Gráfico 2D e Inspetor 2D)
                        ov_dict = st.session_state.get("overrides_topologia_bim", {})
                        for id_af in ids_afetar:
                            if id_af not in ov_dict:
                                ov_dict[id_af] = {"Conectado_A": "Automático (Menor Rota ABNT)", "Conexao_No": "Joelho 90° Soldável / Tê", "DN_Manual_mm": 0}
                            ov_dict[id_af]["z_relativo"] = novo_z_cmd
                            st.session_state[f"insp_z_{id_af}"] = novo_z_cmd
                        st.session_state["overrides_topologia_bim"] = ov_dict
                        st.session_state.contexto_bim["overrides_topologia_bim"] = ov_dict
                        st.session_state["no_selecionado_bim"] = id_alvo_cmd
                        st.session_state["sel_insp_no"] = id_alvo_cmd

                        # 4. Reprocessa Rotas 3D e 2D imediatamente com a nova altura
                        ctx_at = st.session_state.contexto_bim
                        ctx_at['df_elet'] = df_editado_elet.to_dict('records') if not df_editado_elet.empty else []
                        ctx_at['df_eletrica'] = ctx_at['df_elet']
                        ctx_at['df_hidro'] = df_editado_hidro.to_dict('records') if not df_editado_hidro.empty else []
                        if ctx_at.get('grid_w') and ctx_at.get('grid_h'):
                            novas_hd = rotear_hidro(ctx_at['df_hidro'], ctx_at) if modo_visualizacao != "Apenas Elétrica" else []
                            novas_el = rotear_eletrica(ctx_at['df_eletrica'], ctx_at) if modo_visualizacao != "Apenas Hidrossanitário" else []
                            st.session_state.linhas_3d_master['hidro'] = novas_hd
                            st.session_state.linhas_3d_master['eletrica'] = novas_el
                            st.session_state.quantitativos_master = gerar_quantitativos_totais_bim(
                                novas_el, novas_hd, st.session_state.circuitos, ctx_at['df_eletrica'], ctx_at['df_hidro']
                            )

                        # 5. Atualiza Tabela de Pressões Hidráulicas (Aba 4)
                        if st.session_state.get("pontos_hidro"):
                            z_res_mca = float(ctx_at.get("max_z_cobertura", 3.0)) + float(ctx_at.get("altura_caixa", 1.5))
                            for pt_h_row in st.session_state.pontos_hidro:
                                if str(pt_h_row.get("ID")) in ids_afetar:
                                    b_ref = next((b for b in ctx_at['df_hidro'] if str(b['ID_CAD']) == str(pt_h_row.get("ID"))), None)
                                    z_b = float(b_ref.get('z_base', 0.0)) if b_ref else 0.0
                                    novo_z_abs = round(z_b + novo_z_cmd, 2)
                                    pt_h_row["z"] = novo_z_abs
                                    if float(pt_h_row.get("Peso (NBR 5626)", 0.0)) > 0:
                                        p_est = max(1.5, z_res_mca - novo_z_abs)
                                        perda = float(pt_h_row.get("Perda Carga (m.c.a.)", 0.0))
                                        pt_h_row["Pressão Estática (m.c.a.)"] = round(p_est, 1)
                                        pt_h_row["Pressão Disp. (kPa)"] = round(max(0.0, p_est - perda) * 9.81, 1)

                        st.session_state["sync_version"] = st.session_state.get("sync_version", 0) + 1
                        st.cache_data.clear()
                        st.toast(f"✅ Altura Z = {novo_z_cmd:.2f}m aplicada em {len(ids_afetar)} ponto(s) em todo o projeto!", icon="📏")
                        st.rerun()

            grupos_legenda_usados = set()
            df_el_ctx = df_editado_elet.to_dict('records') if not df_editado_elet.empty else st.session_state.contexto_bim.get('df_eletrica', [])
            df_h_proc = df_editado_hidro.to_dict('records') if not df_editado_hidro.empty else st.session_state.contexto_bim.get('df_hidro', [])

            if modo_visualizacao in ["Unificado (Elétrica + Hidráulica)", "Apenas Elétrica"]:
                for linha in st.session_state.linhas_3d_master['eletrica']:
                    pts = linha['pontos']
                    fios_txt = linha.get('fios', 'F N T')
                    id_ref_el = str(linha.get('id_origem', ''))
                    nome_grp = "⚡ Eletrodutos e Circuitos"
                    mostrar_leg = nome_grp not in grupos_legenda_usados
                    grupos_legenda_usados.add(nome_grp)
                    if mostrar_tubos:
                        fig.add_trace(go.Scatter3d(
                            x=[p[0] for p in pts], y=[p[1] for p in pts], z=[p[2] for p in pts],
                            mode='lines+markers', marker=dict(size=3),
                            line=dict(color=linha['cor'], width=5),
                            customdata=[id_ref_el for _ in pts],
                            name=nome_grp, legendgroup='rede_eletrica', showlegend=mostrar_leg,
                            hovertext=f"Elétrica ({fios_txt}) | Bloco: {id_ref_el} | L={linha.get('comprimento_m',0)}m", hoverinfo="text"
                        ))
                    if mostrar_fios and len(pts) >= 2:
                        p_mid = pts[len(pts) // 2]
                        fig.add_trace(go.Scatter3d(
                            x=[p_mid[0]], y=[p_mid[1]], z=[p_mid[2] + 0.15],
                            mode='text', text=[fios_txt], textposition="top center",
                            textfont=dict(color="black", size=11, family="Arial Black"),
                            legendgroup='rede_eletrica', showlegend=False, hoverinfo='skip'
                        ))

            if modo_visualizacao in ["Unificado (Elétrica + Hidráulica)", "Apenas Hidrossanitário"]:
                for linha in st.session_state.linhas_3d_master['hidro']:
                    pts = linha['pontos']
                    tipo_raw = str(linha.get('tipo', 'Hidro'))
                    dn_val = linha.get('diametro', 25)
                    id_ref_hd = str(linha.get('id_ap', ''))
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
                            customdata=[id_ref_hd for _ in pts],
                            name=nome_grp, legendgroup=grp_id, showlegend=mostrar_leg,
                            hovertext=f"{tipo_raw} (DN {dn_val}mm) | Bloco: {id_ref_hd}", hoverinfo="text"
                        ))

            if df_el_ctx:
                fig.add_trace(go.Scatter3d(
                    x=[b['x'] for b in df_el_ctx],
                    y=[b['y'] for b in df_el_ctx],
                    z=[b['z_base'] + float(b.get('z_relativo', 1.3)) for b in df_el_ctx],
                    mode='markers',
                    customdata=[str(b['ID_CAD']) for b in df_el_ctx],
                    hovertext=[f"<b>{b['ID_CAD']}</b> | {b.get('Nome_Bloco','')}<br>Altura z_relativo: {float(b.get('z_relativo',1.3)):.2f}m<br>🖱️ Clique Esquerdo: Editar Altura Z" for b in df_el_ctx],
                    hoverinfo="text",
                    marker=dict(size=7, color=['red' if 'Quadro' in b['Tipo_BIM'] else 'gold' if 'Luminária' in b['Tipo_BIM'] else 'green' for b in df_el_ctx]),
                    name="🔌 Pontos Elétricos (Clique Esq. = Editar Z)"
                ))

            if df_h_proc:
                fig.add_trace(go.Scatter3d(
                    x=[b['x'] for b in df_h_proc],
                    y=[b['y'] for b in df_h_proc],
                    z=[b['z_base'] + float(b.get('z_relativo', 0.5)) for b in df_h_proc],
                    mode='markers',
                    customdata=[str(b['ID_CAD']) for b in df_h_proc],
                    hovertext=[f"<b>{b['ID_CAD']}</b> | {b['Nome_Bloco']}<br>Eq: {b['Equipamento']} ({b['Tipo_BIM']})<br>Altura z_relativo: {float(b.get('z_relativo',0.5)):.2f}m<br>🖱️ Clique Esquerdo: Editar Altura Z" for b in df_h_proc],
                    hoverinfo="text",
                    marker=dict(size=6, color='#0ea5e9', symbol='circle'),
                    name="🚰 Pontos Hidrossanitários (Clique Esq. = Editar Z)"
                ))

            cx_box = next((b for b in df_h_proc if b['Tipo_BIM'] == 'Caixa d\'Água'), None)
            if cx_box:
                fig.add_trace(go.Scatter3d(
                    x=[cx_box['x']], y=[cx_box['y']],
                    z=[cx_box['z_base'] + float(cx_box.get('z_relativo', st.session_state.contexto_bim.get('altura_caixa', 1.5)))],
                    mode='markers',
                    customdata=[str(cx_box['ID_CAD'])],
                    marker=dict(size=18, color='#1d4ed8', symbol='square'),
                    name='🟦 Caixa d\'Água Superior'
                ))

            fig.update_layout(
                scene=dict(
                    dragmode='turntable',
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

            st.caption("🖱️ **Controles do Mouse no 3D:** **Botão Central (Clique no Scroll + Arrastar)** = Orbitar Maquete | **Botão Direito + Arrastar** = Pan (Mover) | **Roda do Scroll** = Zoom | **Clique Esquerdo sobre um Bloco/Tubo** = Abre Caixa Flutuante de Edição do Eixo Z")
            st.plotly_chart(fig, use_container_width=True, key="grafico_3d_interativo_bim")

            # Ponte invisível de comunicação instantânea entre o Popup Flutuante 3D e o Python
            st.markdown(
                """
                <style>
                div[data-testid="stTextInput"]:has(input[aria-label="BRIDGE_Z3D_INPUT"]) {
                    opacity: 0.01 !important;
                    height: 1px !important;
                    width: 1px !important;
                    overflow: hidden !important;
                    position: fixed !important;
                    bottom: 0px !important;
                    right: 0px !important;
                    pointer-events: none !important;
                    z-index: -10 !important;
                }
                </style>
                """,
                unsafe_allow_html=True
            )
            st.text_input("BRIDGE_Z3D_INPUT", key="bridge_z3d_input", label_visibility="collapsed")

            # Empacota metadados de todos os blocos 3D para o Popup Flutuante exibir Nome, Equipamento, Contagens e Altura Z atual
            mapa_meta_3d = {}
            todos_b3d = df_el_ctx + df_h_proc
            for b in todos_b3d:
                id_b = str(b['ID_CAD'])
                nb_b = str(b.get('Nome_Bloco', id_b))
                eq_b = str(b.get('Equipamento', b.get('Equipamento_Associado', '')))
                mapa_meta_3d[id_b] = {
                    "id": id_b,
                    "nome": nb_b,
                    "equip": eq_b,
                    "funcao": str(b.get('Tipo_BIM', '')),
                    "x": round(float(b.get('x', 0.0)), 3),
                    "y": round(float(b.get('y', 0.0)), 3),
                    "z_base": round(float(b.get('z_base', 0.0)), 3),
                    "z_rel": round(float(b.get('z_relativo', 0.50)), 3),
                    "qtd_bloco": sum(1 for item in todos_b3d if str(item.get('Nome_Bloco', '')) == nb_b),
                    "qtd_equip": sum(1 for item in todos_b3d if str(item.get('Equipamento', item.get('Equipamento_Associado', ''))) == eq_b)
                }

            json_meta_3d = json.dumps(mapa_meta_3d)

            # Injeção do Controlador 3D: Botão do Meio (Scroll) = Orbitar | Clique Esquerdo = Abre Modal Flutuante de Altura Z
            components.html(
                f"""
                <script>
                (function() {{
                    const parentWin = window.parent;
                    const parentDoc = parentWin.document;
                    const blocosMeta = {json_meta_3d};
                    parentWin.__blocosMeta3D = blocosMeta;

                    // 1. Cria o Modal Flutuante de Edição de Altura (Eixo Z) sobre a tela 3D
                    let modalZ = parentDoc.getElementById('bim-modal-z3d');
                    if (!modalZ) {{
                        modalZ = parentDoc.createElement('div');
                        modalZ.id = 'bim-modal-z3d';
                        modalZ.style.cssText = 'display:none; position:fixed; top:50%; left:50%; transform:translate(-50%, -50%); width:420px; background:#0f172a; color:#f8fafc; border:2px solid #38bdf8; border-radius:12px; padding:20px; z-index:999999; box-shadow:0 20px 50px rgba(0,0,0,0.75); font-family:sans-serif;';
                        parentDoc.body.appendChild(modalZ);
                    }}

                    parentWin.__fecharModalZ3D = function() {{
                        modalZ.style.display = 'none';
                    }};

                    parentWin.__aplicarModalZ3D = function(idAlvo) {{
                        const valZ = parentDoc.getElementById('bim-input-z-val').value;
                        const radios = parentDoc.getElementsByName('bim_escopo_z3d');
                        let escopo = 'PONTO';
                        for (const r of radios) {{
                            if (r.checked) {{ escopo = r.value; break; }}
                        }}
                        const payload = idAlvo + '|' + valZ + '|' + escopo + '|' + Date.now();
                        const inputBridge = parentDoc.querySelector('input[aria-label="BRIDGE_Z3D_INPUT"]');
                        if (inputBridge) {{
                            const setter = Object.getOwnPropertyDescriptor(parentWin.HTMLInputElement.prototype, 'value').set;
                            inputBridge.focus();
                            setter.call(inputBridge, payload);
                            inputBridge.dispatchEvent(new parentWin.Event('input', {{ bubbles: true }}));
                            inputBridge.dispatchEvent(new parentWin.Event('change', {{ bubbles: true }}));
                            inputBridge.dispatchEvent(new parentWin.KeyboardEvent('keydown', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
                            inputBridge.blur();
                        }}
                        modalZ.style.display = 'none';
                    }};

                    function abrirModalZ3D(idCad) {{
                        const info = parentWin.__blocosMeta3D[idCad];
                        if (!info) return;
                        modalZ.innerHTML = `
                            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #334155; padding-bottom:10px; margin-bottom:12px;">
                                <span style="font-size:16px; font-weight:bold; color:#38bdf8;">📏 Editar Altura do Bloco (Eixo Z)</span>
                                <button onclick="window.__fecharModalZ3D()" style="background:transparent; border:none; color:#94a3b8; font-size:20px; cursor:pointer;">✖</button>
                            </div>
                            <div style="background:#1e293b; padding:10px 12px; border-radius:8px; font-size:13px; margin-bottom:14px; line-height:1.5;">
                                <div><b>ID no Projeto:</b> <code style="color:#fde047;">${{info.id}}</code></div>
                                <div><b>Bloco CAD:</b> ${{info.nome}}</div>
                                <div><b>Equipamento:</b> ${{info.equip}} (${{info.funcao}})</div>
                            </div>
                            <div style="margin-bottom:14px;">
                                <label style="display:block; font-size:13px; font-weight:bold; margin-bottom:6px; color:#e2e8f0;">Nova Altura Relativa ao Piso — Eixo Z (m):</label>
                                <div style="display:flex; gap:8px;">
                                    <button onclick="const el=document.getElementById('bim-input-z-val'); el.value=(parseFloat(el.value||0)-0.05).toFixed(2);" style="background:#334155; color:white; border:none; border-radius:6px; padding:8px 14px; cursor:pointer; font-weight:bold;">-0.05m</button>
                                    <input id="bim-input-z-val" type="number" step="0.05" value="${{info.z_rel}}" style="flex:1; background:#020617; color:#ffffff; border:1px solid #38bdf8; border-radius:6px; padding:8px 12px; font-size:16px; font-weight:bold; text-align:center;" />
                                    <button onclick="const el=document.getElementById('bim-input-z-val'); el.value=(parseFloat(el.value||0)+0.05).toFixed(2);" style="background:#334155; color:white; border:none; border-radius:6px; padding:8px 14px; cursor:pointer; font-weight:bold;">+0.05m</button>
                                </div>
                            </div>
                            <div style="margin-bottom:16px; font-size:13px; background:#1e293b; padding:10px 12px; border-radius:8px;">
                                <div style="font-weight:bold; margin-bottom:6px; color:#cbd5e1;">Aplicar esta altura em:</div>
                                <label style="display:block; margin-bottom:5px; cursor:pointer;">
                                    <input type="radio" name="bim_escopo_z3d" value="PONTO" checked /> 📍 Apenas neste ponto (<b>${{info.id}}</b>)
                                </label>
                                <label style="display:block; margin-bottom:5px; cursor:pointer;">
                                    <input type="radio" name="bim_escopo_z3d" value="BLOCO" /> 🧩 Todos os blocos <b>${{info.nome}}</b> (${{info.qtd_bloco}} locais)
                                </label>
                                <label style="display:block; cursor:pointer;">
                                    <input type="radio" name="bim_escopo_z3d" value="EQUIP" /> 🚰 Todos c/ equipamento <b>${{info.equip}}</b> (${{info.qtd_equip}} locais)
                                </label>
                            </div>
                            <div style="display:flex; gap:10px;">
                                <button onclick="window.__aplicarModalZ3D('${{info.id}}')" style="flex:2; background:#0284c7; color:white; border:none; border-radius:8px; padding:11px; font-size:14px; font-weight:bold; cursor:pointer;">💾 Salvar e Atualizar Tudo (3D, 2D e Tabelas)</button>
                                <button onclick="window.__fecharModalZ3D()" style="flex:0.8; background:#475569; color:white; border:none; border-radius:8px; padding:11px; font-size:13px; cursor:pointer;">Cancelar</button>
                            </div>
                        `;
                        modalZ.style.display = 'block';
                        setTimeout(() => {{
                            const inp = parentDoc.getElementById('bim-input-z-val');
                            if (inp) {{ inp.focus(); inp.select(); }}
                        }}, 40);
                    }}

                    // 2. Localiza o gráfico 3D do Plotly e configura:
                    //    - Botão do Meio (Scroll Click, button===1) => Orbitar
                    //    - Botão Esquerdo (button===0) => Não orbita; clica no ponto e abre o Modal de Eixo Z!
                    function configurarMouse3D() {{
                        const plots = parentDoc.querySelectorAll('.js-plotly-plot');
                        let plot3d = null;
                        for (const p of plots) {{
                            if (p.querySelector('.gl-container canvas')) {{
                                plot3d = p;
                                break;
                            }}
                        }}
                        if (!plot3d) {{
                            setTimeout(configurarMouse3D, 350);
                            return;
                        }}
                        if (plot3d.__mouse3dConfigurado) return;
                        plot3d.__mouse3dConfigurado = true;

                        const glContainer = plot3d.querySelector('.gl-container');
                        let ultimoHoverId = null;
                        let isMmbOrbiting = false;
                        let mmbCanvas = null;
                        let lmbDownPos = null;

                        function resolverIdDoPontoPlotly(pt) {{
                            if (!pt) return null;
                            if (pt.customdata) {{
                                const cd = Array.isArray(pt.customdata) ? String(pt.customdata[0]) : String(pt.customdata);
                                if (parentWin.__blocosMeta3D[cd]) return cd;
                            }}
                            if (typeof pt.x === 'number' && typeof pt.y === 'number') {{
                                let melhorId = null;
                                let menorDist = 1.5;
                                for (const [k, b] of Object.entries(parentWin.__blocosMeta3D)) {{
                                    const d = Math.hypot(b.x - pt.x, b.y - pt.y) + Math.abs((b.z_base + b.z_rel) - (pt.z || 0)) * 0.4;
                                    if (d < menorDist) {{
                                        menorDist = d;
                                        melhorId = k;
                                    }}
                                }}
                                return melhorId;
                            }}
                            return null;
                        }}

                        if (typeof plot3d.on === 'function') {{
                            plot3d.on('plotly_hover', function(data) {{
                                if (data && data.points && data.points.length > 0) {{
                                    const idH = resolverIdDoPontoPlotly(data.points[0]);
                                    if (idH) ultimoHoverId = idH;
                                }}
                            }});
                            plot3d.on('plotly_click', function(data) {{
                                if (isMmbOrbiting) return;
                                if (data && data.points && data.points.length > 0) {{
                                    const idC = resolverIdDoPontoPlotly(data.points[0]) || ultimoHoverId;
                                    if (idC) abrirModalZ3D(idC);
                                }}
                            }});
                        }}

                        // Intercepta Mousedown na cena 3D (Fase de Captura)
                        glContainer.addEventListener('mousedown', function(e) {{
                            if (e._isSyntheticMmb) return;

                            // BOTÃO CENTRAL DO MOUSE (Clique no Scroll, button === 1) => ORBITAR!
                            if (e.button === 1) {{
                                e.preventDefault();
                                e.stopPropagation();
                                e.stopImmediatePropagation();
                                isMmbOrbiting = true;
                                mmbCanvas = e.target;
                                if (plot3d._fullLayout && plot3d._fullLayout.scene && plot3d._fullLayout.scene._scene) {{
                                    plot3d._fullLayout.scene._scene.dragmode = 'turntable';
                                }}
                                const synDown = new parentWin.MouseEvent('mousedown', {{
                                    bubbles: true, cancelable: true, view: parentWin,
                                    clientX: e.clientX, clientY: e.clientY,
                                    screenX: e.screenX, screenY: e.screenY,
                                    button: 0, buttons: 1
                                }});
                                synDown._isSyntheticMmb = true;
                                mmbCanvas.dispatchEvent(synDown);
                                return;
                            }}

                            // BOTÃO ESQUERDO DO MOUSE (button === 0) => APENAS SELECIONAR BLOCO (Não orbitar)
                            if (e.button === 0) {{
                                lmbDownPos = {{ x: e.clientX, y: e.clientY, t: Date.now() }};
                            }}
                        }}, true);

                        // Intercepta Mousemove na janela para converter arrasto do Botão Central em Orbit e bloquear Orbit no Botão Esquerdo
                        parentWin.addEventListener('mousemove', function(e) {{
                            if (e._isSyntheticMmb) return;

                            if (isMmbOrbiting && mmbCanvas) {{
                                if ((e.buttons & 4) === 0) {{
                                    isMmbOrbiting = false;
                                    const synUp = new parentWin.MouseEvent('mouseup', {{
                                        bubbles: true, cancelable: true, view: parentWin,
                                        clientX: e.clientX, clientY: e.clientY,
                                        button: 0, buttons: 0
                                    }});
                                    synUp._isSyntheticMmb = true;
                                    mmbCanvas.dispatchEvent(synUp);
                                    return;
                                }}
                                e.preventDefault();
                                e.stopPropagation();
                                e.stopImmediatePropagation();
                                const synMove = new parentWin.MouseEvent('mousemove', {{
                                    bubbles: true, cancelable: true, view: parentWin,
                                    clientX: e.clientX, clientY: e.clientY,
                                    screenX: e.screenX, screenY: e.screenY,
                                    button: 0, buttons: 1
                                }});
                                synMove._isSyntheticMmb = true;
                                mmbCanvas.dispatchEvent(synMove);
                                return;
                            }}

                            // Se o usuário estiver segurando o botão esquerdo na maquete 3D, impede que ela orbite
                            if (lmbDownPos && (e.buttons & 1) === 1) {{
                                e.stopPropagation();
                                e.stopImmediatePropagation();
                            }}
                        }}, true);

                        parentWin.addEventListener('mouseup', function(e) {{
                            if (e._isSyntheticMmb) return;

                            if (isMmbOrbiting && e.button === 1) {{
                                e.preventDefault();
                                e.stopPropagation();
                                e.stopImmediatePropagation();
                                isMmbOrbiting = false;
                                if (mmbCanvas) {{
                                    const synUp = new parentWin.MouseEvent('mouseup', {{
                                        bubbles: true, cancelable: true, view: parentWin,
                                        clientX: e.clientX, clientY: e.clientY,
                                        button: 0, buttons: 0
                                    }});
                                    synUp._isSyntheticMmb = true;
                                    mmbCanvas.dispatchEvent(synUp);
                                }}
                                return;
                            }}

                            if (e.button === 0 && lmbDownPos) {{
                                const distClique = Math.hypot(e.clientX - lmbDownPos.x, e.clientY - lmbDownPos.y);
                                lmbDownPos = null;
                                // Fallback: se clicou com botão esquerdo sobre um ponto/tubo com tooltip ativo, abre o Modal Z!
                                if (distClique < 8 && ultimoHoverId) {{
                                    setTimeout(() => {{
                                        if (modalZ.style.display !== 'block' && ultimoHoverId) {{
                                            abrirModalZ3D(ultimoHoverId);
                                        }}
                                    }}, 60);
                                }}
                            }}
                        }}, true);

                        // Impede o ícone de auto-rolagem do navegador ao clicar com o scroll no 3D
                        glContainer.addEventListener('auxclick', function(e) {{
                            if (e.button === 1) {{
                                e.preventDefault();
                                e.stopPropagation();
                            }}
                        }}, true);
                    }}

                    configurarMouse3D();
                }})();
                </script>
                """,
                height=0
            )

            st.divider()
            renderizar_tela_2d_ramificada_e_inspetor(paredes_filtradas, df_editado_elet, df_editado_hidro, st.session_state.contexto_bim)
    else:
        st.info("Suba os arquivos DXF ou IFC das plantas/maquetes na barra lateral para iniciar a coordenação.")
        
        
with tab_clash:
    st.subheader("Verificação de Interferências (Hard & Soft Clash) e Avoidance")
    if st.button("🔍 Rodar Verificação de Colisões", type="primary"):
        if st.session_state.linhas_3d_master['eletrica'] and st.session_state.linhas_3d_master['hidro']:
            st.session_state.colisoes_detectadas = checar_clash_detection(st.session_state.linhas_3d_master['eletrica'], st.session_state.linhas_3d_master['hidro'], 0.15)
            if not st.session_state.colisoes_detectadas:
                st.success("✅ O Projeto está limpo! Nenhuma interferência entre Elétrica e Hidráulica.")
        else:
            st.warning("Processe as rotas primeiro na aba BIM 3D.")
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
# PARTE 10 DE 10: ABAS 3, 4, 5 E 6 (COM CACHE, IO.BYTESIO E PROTEÇÃO KEYERROR)
# ==============================================================================
import io

def _converter_saida_pdf_para_bytes(res_funcao, buffer_mem):
    """Garante retorno 100% em bytes na memória RAM (io.BytesIO), sem deixar arquivos no disco."""
    if isinstance(res_funcao, bytes):
        return res_funcao
    if isinstance(res_funcao, io.BytesIO):
        res_funcao.seek(0)
        return res_funcao.getvalue()
    if buffer_mem.tell() > 0:
        buffer_mem.seek(0)
        return buffer_mem.getvalue()
    if isinstance(res_funcao, str) and os.path.exists(res_funcao):
        with open(res_funcao, "rb") as f_tmp:
            dados_b = f_tmp.read()
        try:
            os.remove(res_funcao)
        except Exception:
            pass
        return dados_b
    return b""

@st.cache_data(show_spinner=False)
def obter_pdf_unifilar_memoria(df_circuitos):
    buf = io.BytesIO()
    res = gerar_memorial_unifilar(df_circuitos, buf)
    return _converter_saida_pdf_para_bytes(res, buf)

@st.cache_data(show_spinner=False)
def obter_pdf_qdg_memoria(df_circuitos):
    buf = io.BytesIO()
    res = gerar_pdf_qdg(df_circuitos, buf)
    return _converter_saida_pdf_para_bytes(res, buf)

@st.cache_data(show_spinner=False)
def obter_pdf_hidro_memoria(df_hidro, dados_res):
    buf = io.BytesIO()
    res = gerar_memorial_hidraulico(df_hidro, dados_res, buf)
    return _converter_saida_pdf_para_bytes(res, buf)

@st.cache_data(show_spinner=False)
def obter_pdf_materiais_memoria(df_af, df_aq, df_esg):
    buf = io.BytesIO()
    res = gerar_lista_materiais_pdf(df_af, df_aq, df_esg, buf)
    return _converter_saida_pdf_para_bytes(res, buf)

@st.cache_data(show_spinner=False)
def obter_dxf_cached(linhas_el, linhas_hd, paredes, escopo):
    return exportar_malha_para_dxf(linhas_el, linhas_hd, paredes, escopo)

@st.cache_data(show_spinner=False)
def obter_ifc_cached(linhas_el, linhas_hd, escopo):
    return exportar_malha_para_ifc_step(linhas_el, linhas_hd, escopo)


# --- ABA 3: ENGENHARIA ELÉTRICA EXECUTIVA (NBR 5410 + PRODIST) ---
with tab_eletrica:
    st.title("⚡ Engenharia Elétrica Executiva (NBR 5410 + PRODIST + V12)")

    with st.expander("📏 Validação Normativa 1: Auditoria de Pontos Mínimos por Área e Perímetro dos Cômodos (NBR 5410 - Item 9.5.2)", expanded=False):
        df_amb_edit = st.data_editor(
            st.session_state.get("auditoria_ambientes", pd.DataFrame()),
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
                auditar_ambiente_nbr5410(
                    r.get("Ambiente", f"Amb {i+1}"),
                    r.get("Tipo Cômodo (NBR 5410)", "Sala / Dormitório"),
                    float(r.get("Área (m²)", 10.0)),
                    float(r.get("Perímetro (m)", 12.0))
                )
                for i, r in df_amb_edit.iterrows()
            ])
            st.dataframe(df_res_aud, use_container_width=True, hide_index=True)

    df_circ = st.session_state.get("circuitos", pd.DataFrame())
    if not df_circ.empty:
        pot_instalada = pd.to_numeric(df_circ.get('Potência Total (W)', pd.Series(dtype=float)), errors='coerce').fillna(0).sum()
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
        if not st.session_state.get("circuitos", pd.DataFrame()).empty:
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
                df_calc.at[idx, "Ocupação (%)"] = res.get("Ocupação_Pct", res.get("Ocupacao_Pct", 0.0))

            st.session_state.circuitos = balancear_fases_automatico(df_calc)
            st.success("✅ Engenharia reprocessada com FCA automático por eletroduto, corrente de curto-circuito (Icc) e fases equilibradas!")
            st.rerun()

    df_circ_edit = st.data_editor(st.session_state.get("circuitos", pd.DataFrame()), num_rows="dynamic", use_container_width=True)
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
    st.subheader("📄 Exportação de Memoriais, Diagramas e Planilha Excel (Memória RAM + Cache)")
    c_pdf1, c_pdf2, c_pdf3 = st.columns(3)
    with c_pdf1:
        if not st.session_state.circuitos.empty:
            st.download_button(
                "📥 Baixar Memorial + Diagrama Unifilar (PDF)",
                data=obter_pdf_unifilar_memoria(st.session_state.circuitos),
                file_name="Memorial_Unifilar_NBR5410.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )
    with c_pdf2:
        if not st.session_state.circuitos.empty:
            st.download_button(
                "📥 Baixar Layout Físico do QDG (PDF)",
                data=obter_pdf_qdg_memoria(st.session_state.circuitos),
                file_name="Layout_QDG_DIN.pdf",
                mime="application/pdf",
                use_container_width=True
            )
    with c_pdf3:
        if not st.session_state.circuitos.empty:
            excel_bytes, excel_nome, excel_mime = gerar_arquivo_excel_completo()
            st.download_button(
                "📊 Baixar Planilha Completa (.XLSX)",
                data=excel_bytes,
                file_name=excel_nome,
                mime=excel_mime,
                use_container_width=True
            )

# --- ABA 4: ENGENHARIA HIDROSSANITÁRIA (NBR 5626 & NBR 8160 + VALIDAÇÃO VRP 40 m.c.a.) ---
with tab_hidro:
    st.title("💧 Engenharia Hidrossanitária Executiva (NBR 5626 & NBR 8160)")
    st.subheader("📋 Verificação de Pressões (Mín. 10 kPa e Máx. Estática 40 m.c.a. c/ VRP), Perda de Carga e Declividades")

    pts_hidro_atuais = st.session_state.get("pontos_hidro", [])
    df_h_display = pd.DataFrame(pts_hidro_atuais) if pts_hidro_atuais else pd.DataFrame(columns=[
        "ID", "Andar", "Ambiente", "Equipamento", "z", "Peso (NBR 5626)", "Vazão (L/s)",
        "Tubo AF (mm)", "L Real + Eq (m)", "Perda Carga (m.c.a.)", "Pressão Estática (m.c.a.)",
        "Pressão Disp. (kPa)", "Pressão Mín. (kPa)", "Status Pressão", "UHC", "Tubo Esgoto (mm)", "Declividade Esg. (%)"
    ])

    if not df_h_display.empty and "Status Pressão" in df_h_display.columns:
        qtd_ok = sum(df_h_display["Status Pressão"].astype(str).str.startswith("OK"))
        qtd_press = sum(df_h_display["Status Pressão"].astype(str).str.contains("Pressurizar", na=False))
        qtd_vrp = sum(df_h_display["Status Pressão"].astype(str).str.contains("VRP", na=False))
        ch1, ch2, ch3 = st.columns(3)
        ch1.metric("Pontos Normais (NBR 5626 / 8160)", f"{qtd_ok} pts")
        ch2.metric("Pontos Exigindo Pressurização (< Mín.)", f"{qtd_press} pts")
        ch3.metric("Pontos Exigindo VRP (> 40 m.c.a. Estática)", f"{qtd_vrp} pts")

    df_hidro_edit = st.data_editor(df_h_display, num_rows="dynamic", use_container_width=True)
    st.session_state.pontos_hidro = df_hidro_edit.to_dict('records')

    st.divider()
    st.subheader("📄 Exportação de Memorial Hidrossanitário e Lista de Materiais (Memória RAM + Cache)")
    ch_pdf1, ch_pdf2 = st.columns(2)
    with ch_pdf1:
        if not df_hidro_edit.empty:
            dados_res = {"diario": pessoas * consumo_pc, "reserva": vol_caixa, "sugerido": vol_comercial}
            st.download_button(
                "📥 Baixar Memorial de Cálculo Hidrossanitário (PDF)",
                data=obter_pdf_hidro_memoria(df_hidro_edit, dados_res),
                file_name="Memorial_Hidrossanitario_Executivo.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )
    with ch_pdf2:
        q_m = st.session_state.get("quantitativos_master", {})
        df_q_af = q_m.get("agua_fria", pd.DataFrame())
        df_q_aq = q_m.get("agua_quente", pd.DataFrame())
        df_q_esg = q_m.get("esgoto", pd.DataFrame())
        if not df_q_af.empty or not df_q_esg.empty:
            st.download_button(
                "📥 Baixar Lista de Materiais Hidráulicos (PDF)",
                data=obter_pdf_materiais_memoria(df_q_af, df_q_aq, df_q_esg),
                file_name="Quantitativo_Hidrossanitario.pdf",
                mime="application/pdf",
                use_container_width=True
            )

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
    q_m = st.session_state.get("quantitativos_master", {})
    df_q_el = q_m.get("eletrica", pd.DataFrame())
    df_q_af = q_m.get("agua_fria", pd.DataFrame())
    df_q_aq = q_m.get("agua_quente", pd.DataFrame())
    df_q_esg = q_m.get("esgoto", pd.DataFrame())

    cq1, cq2 = st.columns(2)
    with cq1:
        st.markdown("**⚡ Quantitativo Total - Instalações Elétricas**")
        st.dataframe(df_q_el, use_container_width=True, hide_index=True)
        st.markdown("**🔥 Quantitativo Total - Água Quente (CPVC/PPR)**")
        st.dataframe(df_q_aq, use_container_width=True, hide_index=True)
    with cq2:
        st.markdown("**💧 Quantitativo Total - Água Fria (PVC Soldável)**")
        st.dataframe(df_q_af, use_container_width=True, hide_index=True)
        st.markdown("**🤎 Quantitativo Total - Esgoto Sanitário e Ventilação**")
        st.dataframe(df_q_esg, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("3. Fluxograma Topológico IFC & Exportação de Malhas 3D (.DXF c/ Simbologia ABNT e .IFC)")
    st.markdown("O arquivo `.DXF` exportado já inclui a **Simbologia Unifilar ABNT (Fase, Neutro, Terra e Retorno)** desenhada automaticamente nos eletrodutos.")

    linhas_master = st.session_state.get("linhas_3d_master", {})
    linhas_el_exp = linhas_master.get("eletrica", [])
    linhas_hd_exp = linhas_master.get("hidro", [])
    paredes_export = st.session_state.get("contexto_bim", {}).get("paredes", [])

    fig_ifc = gerar_fluxograma_ifc_plotly(linhas_el_exp, linhas_hd_exp, config_andares)
    st.plotly_chart(fig_ifc, use_container_width=True)

    ce1, ce2, ce3 = st.columns(3)
    with ce1:
        st.markdown("**⚡ Projeto Individual de Elétrica**")
        st.download_button(
            "📐 Baixar Malha Elétrica 3D + Símbolos ABNT (.DXF)",
            data=obter_dxf_cached(linhas_el_exp, [], paredes_export, "ELETRICA"),
            file_name="Malha_Eletrica_3D_ABNT.dxf",
            use_container_width=True
        )
        st.download_button(
            "🧱 Baixar Modelo IFC Elétrica (.IFC)",
            data=obter_ifc_cached(linhas_el_exp, [], "ELETRICA"),
            file_name="Projeto_Eletrico_BIM.ifc",
            use_container_width=True
        )
    with ce2:
        st.markdown("**💧 Projeto Individual de Hidráulica**")
        st.download_button(
            "📐 Baixar Malha Hidráulica 3D (.DXF)",
            data=obter_dxf_cached([], linhas_hd_exp, paredes_export, "HIDRO"),
            file_name="Malha_Hidraulica_3D.dxf",
            use_container_width=True
        )
        st.download_button(
            "🧱 Baixar Modelo IFC Hidráulica (.IFC)",
            data=obter_ifc_cached([], linhas_hd_exp, "HIDRO"),
            file_name="Projeto_Hidraulico_BIM.ifc",
            use_container_width=True
        )
    with ce3:
        st.markdown("**🏢 Projeto Unificado Completo (Elétrica + Hidro)**")
        st.download_button(
            "📐 Baixar Malha Unificada 3D (.DXF)",
            data=obter_dxf_cached(linhas_el_exp, linhas_hd_exp, paredes_export, "UNIFICADO"),
            file_name="Malha_MEP_Unificada_3D.dxf",
            type="primary",
            use_container_width=True
        )
        st.download_button(
            "🧱 Baixar Modelo IFC Unificado (.IFC)",
            data=obter_ifc_cached(linhas_el_exp, linhas_hd_exp, "UNIFICADO"),
            file_name="Projeto_MEP_Unificado_BIM.ifc",
            type="primary",
            use_container_width=True
        )

# --- ABA 6: GERENCIADOR DE BIBLIOTECAS ---
with tab_export:
    st.title("📚 Gerenciamento de Bibliotecas BIM")
    st.markdown("As tabelas abaixo alimentam as opções e cálculos normativos em todo o sistema.")

    aba_elet, aba_hidro, aba_gas = st.tabs(["⚡ Elétrica (NBR 5410)", "💧 Instalações Hidrossanitárias (Água + Esgoto)", "🔥 Gás & Climatização (NBR 15526 / 16401)"])

    with aba_elet:
        st.session_state.bib_eletrica = st.data_editor(st.session_state.get("bib_eletrica", pd.DataFrame()), num_rows="dynamic", use_container_width=True)

    with aba_hidro:
        st.markdown("**Pesos (NBR 5626), Água Quente (CPVC/PPR) e UHCs (NBR 8160) unificados por equipamento**")
        st.session_state.bib_hidro = st.data_editor(st.session_state.get("bib_hidro", pd.DataFrame()), num_rows="dynamic", use_container_width=True)

    with aba_gas:
        st.markdown("**Parâmetros Normativos de Gás Combustível (GLP/GN - NBR 15526) e Climatização Split (NBR 16401)**")
        st.session_state.bib_gas_avac = st.data_editor(st.session_state.get("bib_gas_avac", pd.DataFrame()), num_rows="dynamic", use_container_width=True)

# === FIM DO ARQUIVO ===
