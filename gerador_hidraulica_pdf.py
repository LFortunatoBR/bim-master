from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import pandas as pd

def desenhar_detalhes_conexoes_hidro_pdf(c, x_ini, y_ini):
    """Desenha os cortes técnicos de Joelho 90°, Tê 90° e Caixa Sifonada no Memorial PDF."""
    c.setStrokeColor(colors.black)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x_ini, y_ini, "4. Desenho Técnico de Peças e Conexões Hidrossanitárias (Corte Cotado)")

    y_b = y_ini - 65
    # 1. Joelho 90° Soldável / Esgoto
    c.setLineWidth(1.2)
    c.setFillColorRGB(0.88, 0.94, 0.98)
    c.rect(x_ini, y_b, 20, 45, fill=1)
    c.rect(x_ini, y_b + 25, 45, 20, fill=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(x_ini - 5, y_b - 12, "Joelho 90° (Bolsas Soldáveis)")
    c.setFont("Helvetica", 6)
    c.drawString(x_ini - 5, y_b - 20, "Leq = 1.2m (DN 25mm)")

    # 2. Tê 90° de Derivação
    x_te = x_ini + 165
    c.setFillColorRGB(0.88, 0.94, 0.98)
    c.rect(x_te, y_b + 15, 60, 18, fill=1)
    c.rect(x_te + 21, y_b + 15, 18, 35, fill=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(x_te, y_b - 12, "Tê 90° Passagem/Derivação")
    c.setFont("Helvetica", 6)
    c.drawString(x_te, y_b - 20, "Leq Lat. = 2.4m (DN 25mm)")

    # 3. Caixa Sifonada c/ Fecho Hídrico >= 50mm (NBR 8160)
    x_cs = x_ini + 340
    c.setFillColorRGB(0.92, 0.96, 0.92)
    c.rect(x_cs, y_b, 50, 45, fill=1)
    c.setFillColorRGB(0.65, 0.85, 0.98)
    c.rect(x_cs + 2, y_b + 2, 46, 20, fill=1) # Fecho hídrico
    c.setLineWidth(2)
    c.line(x_cs + 34, y_b + 38, x_cs + 34, y_b + 10) # Septo sifão
    c.setLineWidth(1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(x_cs - 10, y_b - 12, "Caixa Sifonada 150x150x50mm")
    c.setFont("Helvetica", 6)
    c.drawString(x_cs - 10, y_b - 20, "Fecho Hídrico >= 50mm (NBR 8160)")

def gerar_memorial_hidraulico(df_pontos, dados_reservatorio, caminho_saida="Projeto_Hidraulico.pdf"):
    c = canvas.Canvas(caminho_saida, pagesize=A4)
    largura, altura = A4

    def nova_pagina(pag_num, primeira=False):
        if not primeira:
            c.showPage()
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, altura - 50, "Memorial de Cálculo Hidrossanitário - BIM Master")
        c.setFont("Helvetica", 10)
        c.drawString(50, altura - 70, f"Projeto Executivo NBR 5626 / NBR 8160 - Página {pag_num}")
        c.line(50, altura - 80, largura - 50, altura - 80)
        return altura - 120

    pag = 1
    y_atual = nova_pagina(pag, primeira=True)

    # --- 1. DADOS DO RESERVATÓRIO ---
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y_atual, "1. Dimensionamento do Reservatório e Demandas Globais")
    y_atual -= 25
    c.setFont("Helvetica", 10)
    c.drawString(50, y_atual, f"- Consumo Diário Estimado: {dados_reservatorio['diario']} Litros")
    c.drawString(50, y_atual - 15, f"- Volume de Reserva: {dados_reservatorio['reserva']} Litros")
    c.setFillColorRGB(0.13, 0.58, 0.95)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y_atual - 35, f"-> Reservatório Comercial: {dados_reservatorio['sugerido']} Litros")
    c.setFillColor(colors.black)
    y_atual -= 70

    # --- 2. DIAGRAMA TOPOLÓGICO HIERÁRQUICO ---
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y_atual, "2. Diagrama Topológico Hierárquico (Andares e Ambientes)")
    y_atual -= 30

    if not df_pontos.empty:
        grupos_col = ['Ambiente']
        if 'Andar' in df_pontos.columns:
            grupos_col = ['Andar', 'Ambiente']
            
        grupos = df_pontos.groupby(grupos_col)

        for nome_grupo, df_grupo in grupos:
            if y_atual < 150:
                pag += 1
                y_atual = nova_pagina(pag)
            
            c.setFillColorRGB(0.9, 0.9, 0.9)
            c.rect(50, y_atual - 15, 495, 20, fill=1, stroke=0)
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", 9)
            texto_titulo = f"LOCAL: {str(nome_grupo).replace('(', '').replace(')', '').replace(',', ' - ')}"
            c.drawString(60, y_atual - 8, texto_titulo)
            y_atual -= 30
            
            for idx, row in df_grupo.iterrows():
                cota_z = row.get('z', 'N/A')
                c.setFont("Helvetica-Bold", 8)
                c.drawString(70, y_atual, f"• {row['Equipamento']}")
                c.setFont("Helvetica", 7)
                if isinstance(cota_z, (int, float)):
                    c.drawString(280, y_atual, f"Cota Z: {cota_z:.2f}m")
                else:
                    c.drawString(280, y_atual, f"Cota Z: {cota_z}")
                p_disp = row.get('Pressão Disp. (kPa)', '-')
                c.drawString(360, y_atual, f"AF: {row['Tubo AF (mm)']}mm | Esg: {row['Tubo Esgoto (mm)']}mm | P.Disp: {p_disp} kPa")
                y_atual -= 15
            y_atual -= 10

    # --- 3. QUADRO RESUMO TABELADO (COM PERDA DE CARGA E PRESSÕES) ---
    if y_atual < 220:
        pag += 1
        y_atual = nova_pagina(pag)
        
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y_atual, "3. Quadro Resumo Executivo e Verificação de Pressões (NBR 5626 / NBR 8160)")
    
    colunas_pdf = [
        'Ambiente', 'Equipamento', 'Tubo AF (mm)', 'Vazão (L/s)',
        'Perda Carga (m.c.a.)', 'Pressão Disp. (kPa)', 'Tubo Esgoto (mm)', 'UHC'
    ]
    if not df_pontos.empty:
        cols_ok = [col for col in colunas_pdf if col in df_pontos.columns]
        df_resumo = df_pontos[cols_ok].copy().astype(str)
        
        styles = getSampleStyleSheet()
        estilo_celula = ParagraphStyle('TableCell', parent=styles['Normal'], fontSize=6.5, alignment=1, leading=8)
        
        dados_tabela = [[Paragraph(str(col), estilo_celula) for col in df_resumo.columns]]
        for row in df_resumo.values.tolist():
            dados_tabela.append([Paragraph(str(item), estilo_celula) for item in row])

        tabela = Table(dados_tabela, colWidths=[(largura-100)/len(df_resumo.columns)]*len(df_resumo.columns))
        tabela.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkslategray),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')
        ]))
        h_tab = tabela.wrap(largura, altura)[1]
        y_tab = y_atual - 20 - h_tab
        if y_tab < 140:
            c.showPage()
            pag += 1
            y_atual = nova_pagina(pag)
            y_tab = y_atual - 20 - h_tab
        tabela.drawOn(c, 50, y_tab)
        desenhar_detalhes_conexoes_hidro_pdf(c, 50, y_tab - 30)

    c.save()
    return caminho_saida

def gerar_lista_materiais_pdf(lista_af, lista_aq, lista_esg, caminho_saida="Lista_Materiais.pdf"):
    c = canvas.Canvas(caminho_saida, pagesize=A4)
    largura, altura = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, altura - 50, "Lista Executiva de Materiais - Projeto Hidrossanitário")
    c.line(50, altura - 60, largura - 50, altura - 60)
    
    styles = getSampleStyleSheet()
    estilo_celula = ParagraphStyle('TableCell', parent=styles['Normal'], fontSize=8.5, alignment=1, leading=10)
    y_atual = altura - 100

    def desenhar_tabela(titulo, df, y):
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, titulo)
        if df is None or df.empty: return y - 30
        header = [Paragraph(str(col), estilo_celula) for col in df.columns.tolist()]
        dados = [header] + [[Paragraph(str(val), estilo_celula) for val in row] for row in df.values.tolist()]
        tabela = Table(dados, colWidths=[(largura-100)*0.60, (largura-100)*0.15, (largura-100)*0.25])
        tabela.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkslategray),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white)
        ]))
        h_tabela = tabela.wrap(largura, altura)[1]
        
        if y - 20 - h_tabela < 50:
            c.showPage()
            y = altura - 50
            c.setFont("Helvetica-Bold", 12)
            c.drawString(50, y, titulo + " (Cont.)")
        
        tabela.drawOn(c, 50, y - 20 - h_tabela)
        return y - 40 - h_tabela

    y_atual = desenhar_tabela("1. Água Fria (PVC Soldável - NBR 5626)", lista_af, y_atual)
    y_atual = desenhar_tabela("2. Água Quente (CPVC / PPR - NBR 5626)", lista_aq, y_atual)
    y_atual = desenhar_tabela("3. Esgoto Sanitário e Ventilação (NBR 8160)", lista_esg, y_atual)
    c.save()
    return caminho_saida