from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import pandas as pd
import math

def desenhar_detalhes_tecnicos_eletrica_pdf(c, x_ini, y_ini):
    """Desenha os detalhes técnicos vetoriais cotados de Caixa 4x2, Disjuntor DIN e Eletroduto no PDF."""
    c.setStrokeColor(colors.black)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x_ini, y_ini, "3. Detalhamento Técnico de Peças e Conexões Elétricas (Padrão ABNT)")

    y_box = y_ini - 75
    # 1. Caixa 4x2" (100x50mm)
    c.setLineWidth(1.2)
    c.setFillColorRGB(0.95, 0.95, 0.95)
    c.rect(x_ini, y_box, 40, 60, fill=1)
    c.setDash(2, 2)
    c.circle(x_ini + 20, y_box + 45, 7, fill=0)
    c.circle(x_ini + 20, y_box + 15, 7, fill=0)
    c.setDash()
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(x_ini - 5, y_box - 12, "Caixa 4x2\" (100x50mm)")
    c.setFont("Helvetica", 6)
    c.drawString(x_ini - 5, y_box - 20, "Furos Ø 20/25mm c/ Bucha/Arruela")

    # 2. Disjuntor DIN + Barramento Pente
    x_dj = x_ini + 140
    c.setFillColorRGB(0.90, 0.93, 0.98)
    c.rect(x_dj, y_box, 25, 60, fill=1)
    c.setFillColorRGB(0.85, 0.2, 0.2)
    c.rect(x_dj + 4, y_box + 25, 17, 10, fill=1)
    c.setFillColor(colors.black)
    c.circle(x_dj + 12.5, y_box + 50, 3.5, fill=0)
    c.circle(x_dj + 12.5, y_box + 10, 3.5, fill=0)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(x_dj - 10, y_box - 12, "Disjuntor DIN (17.5mm/pólo)")
    c.setFont("Helvetica", 6)
    c.drawString(x_dj - 10, y_box - 20, "Fixação Trilho DIN 35mm")

    # 3. Seção de Eletroduto (Taxa de Ocupação <= 40% NBR 5410)
    x_el = x_ini + 310
    c.setFillColorRGB(0.95, 0.95, 0.95)
    c.circle(x_el + 30, y_box + 30, 26, fill=1)
    c.circle(x_el + 30, y_box + 30, 22, fill=1)
    # 3 Condutores (Fase, Neutro, Terra)
    c.setFillColorRGB(0.85, 0.1, 0.1)
    c.circle(x_el + 22, y_box + 24, 6, fill=1)
    c.setFillColorRGB(0.1, 0.4, 0.85)
    c.circle(x_el + 38, y_box + 24, 6, fill=1)
    c.setFillColorRGB(0.1, 0.7, 0.2)
    c.circle(x_el + 30, y_box + 37, 6, fill=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(x_el - 10, y_box - 12, "Corte Eletroduto (F+N+PE)")
    c.setFont("Helvetica", 6)
    c.drawString(x_el - 10, y_box - 20, "Área ocupada <= 40% (NBR 5410)")

def gerar_memorial_unifilar(df_circuitos, caminho_saida="Projeto_Executivo.pdf"):
    c = canvas.Canvas(caminho_saida, pagesize=A4)
    largura, altura = A4

    def nova_pagina(pag_num, primeira=False):
        if not primeira:
            c.showPage()
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, altura - 50, "Memorial de Cálculo e Diagrama Unifilar")
        c.setFont("Helvetica", 10)
        c.drawString(50, altura - 70, f"Projeto Executivo NBR 5410 - Página {pag_num}")
        c.line(50, altura - 80, largura - 50, altura - 80)
        return altura - 120

    if 'Grupo DR' not in df_circuitos.columns: df_circuitos['Grupo DR'] = 'DR 1 (Geral)'
    if 'Fase' not in df_circuitos.columns: df_circuitos['Fase'] = 'R'

    pag = 1
    y_atual = nova_pagina(pag, primeira=True)

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y_atual, "1. Diagrama Unifilar Topológico (Distribuição em Árvore)")
    y_atual -= 30

    # Tronco Principal
    x_tronco = 80
    c.setLineWidth(2)
    c.line(x_tronco, y_atual + 10, x_tronco, y_atual - 20)
    
    # Bloco Geral
    c.setFillColorRGB(0.95, 0.26, 0.21)
    c.rect(x_tronco - 25, y_atual - 40, 50, 20, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(x_tronco, y_atual - 34, "GERAL")
    
    y_atual -= 40
    grupos = df_circuitos.groupby('Grupo DR')
    
    for nome_dr, df_grupo in grupos:
        if y_atual < 180:
            c.setStrokeColor(colors.black)
            c.setLineWidth(2)
            c.line(x_tronco, y_atual, x_tronco, 50)
            pag += 1
            y_atual = nova_pagina(pag)
            c.setLineWidth(2)
            c.line(x_tronco, y_atual + 20, x_tronco, y_atual)
            
        y_linha_dr = y_atual - 40
        c.setStrokeColor(colors.black)
        c.setLineWidth(2)
        c.line(x_tronco, y_atual, x_tronco, y_linha_dr)
        c.line(x_tronco, y_linha_dr, x_tronco + 40, y_linha_dr)
        
        # Bloco DR
        c.setFillColorRGB(0.13, 0.58, 0.95)
        c.rect(x_tronco + 40, y_linha_dr - 15, 90, 30, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(x_tronco + 85, y_linha_dr + 2, "IDR (Fuga 30mA)")
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(x_tronco + 85, y_linha_dr - 10, str(nome_dr)[:18])
        
        x_sub_bar = x_tronco + 130
        c.setStrokeColor(colors.black)
        c.setLineWidth(2)
        c.line(x_sub_bar, y_linha_dr, x_sub_bar + 20, y_linha_dr)
        
        x_circ = x_sub_bar + 30
        y_sub_bar = y_linha_dr
        
        for idx, row in df_grupo.iterrows():
            if x_circ > largura - 40:
                c.setLineWidth(2)
                c.line(x_sub_bar + 20, y_sub_bar, x_circ - 20, y_sub_bar)
                y_sub_bar -= 80
                x_circ = x_sub_bar + 30
                
                if y_sub_bar < 80:
                    c.setLineWidth(2)
                    c.line(x_tronco, y_atual, x_tronco, 50)
                    pag += 1
                    y_atual = nova_pagina(pag)
                    y_sub_bar = y_atual - 40
                    c.setLineWidth(2)
                    c.line(x_tronco, y_atual + 20, x_tronco, y_sub_bar)
                    c.line(x_tronco, y_sub_bar, x_sub_bar + 20, y_sub_bar)
                else:
                    c.setLineWidth(2)
                    c.line(x_sub_bar + 20, y_sub_bar + 80, x_sub_bar + 20, y_sub_bar)
                    
            c.setStrokeColor(colors.black)
            c.setLineWidth(1)
            c.line(x_circ, y_sub_bar, x_circ, y_sub_bar - 20)
            
            c.setFillColorRGB(0.29, 0.68, 0.31)
            c.rect(x_circ - 15, y_sub_bar - 40, 30, 20, fill=1)
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 7)
            c.drawCentredString(x_circ, y_sub_bar - 28, str(row.get('ID', 'C?')))
            c.drawCentredString(x_circ, y_sub_bar - 36, str(row.get('Disjuntor (A)', '-')) + "A")
            
            c.setFillColor(colors.black)
            c.setFont("Helvetica", 6)
            c.drawCentredString(x_circ, y_sub_bar - 50, str(row.get('Bitola (mm²)', '-')) + "mm²")
            
            fase = str(row.get('Fase', 'R'))
            if 'R' in fase: c.setFillColorRGB(0.8, 0.0, 0.0)
            elif 'S' in fase: c.setFillColorRGB(0.0, 0.0, 0.8)
            else: c.setFillColorRGB(0.5, 0.3, 0.0)
            
            c.setFont("Helvetica-Bold", 7)
            c.drawCentredString(x_circ, y_sub_bar - 60, "F:" + fase)
            x_circ += 40
            
        c.setStrokeColor(colors.black)
        c.setLineWidth(2)
        c.line(x_sub_bar + 20, y_sub_bar, x_circ - 20, y_sub_bar)
        y_atual = y_sub_bar - 60

    c.setStrokeColor(colors.black)
    c.setLineWidth(2)
    c.line(x_tronco, y_atual + 60, x_tronco, y_atual + 20)

    # Página 2: Quadro de Cargas NBR 5410 + Detalhes Técnicos
    pag += 1
    y_atual = nova_pagina(pag)
    
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y_atual, "2. Quadro Executivo de Cargas e Dimensionamento NBR 5410")
    
    colunas_pdf = [
        'ID', 'Ambiente', 'Potência Total (W)', 'Tensão (V)', 'Corrente Proj. (A)',
        'Bitola (mm²)', 'Queda Tensão (%)', 'Disjuntor (A)', 'Eletroduto (mm)', 'Fase'
    ]
    cols_presentes = [col for col in colunas_pdf if col in df_circuitos.columns]
    df_resumo = df_circuitos[cols_presentes].copy().astype(str)
    
    styles = getSampleStyleSheet()
    estilo_celula = ParagraphStyle('TableCell', parent=styles['Normal'], fontSize=6.5, alignment=1, leading=8)
    
    dados_tabela = [[Paragraph(str(col), estilo_celula) for col in df_resumo.columns]]
    for row in df_resumo.values.tolist():
        dados_tabela.append([Paragraph(str(item), estilo_celula) for item in row])
    
    largura_disp = largura - 100
    qtd_cols = max(1, len(df_resumo.columns))
    col_w = largura_disp / qtd_cols
    
    tabela = Table(dados_tabela, colWidths=[col_w]*qtd_cols)
    tabela.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.darkslategray),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')
    ]))

    w, h = tabela.wrap(largura, altura)
    y_tab = y_atual - 20 - h
    if y_tab < 160:
        c.showPage()
        pag += 1
        y_atual = nova_pagina(pag)
        y_tab = y_atual - 20 - h
    
    tabela.drawOn(c, 50, y_tab)
    desenhar_detalhes_tecnicos_eletrica_pdf(c, 50, y_tab - 35)
    c.save()
    return caminho_saida

def gerar_pdf_qdg(df_circuitos, caminho_saida="Layout_QDG.pdf"):
    c = canvas.Canvas(caminho_saida, pagesize=A4)
    largura, altura = A4

    modulos_protecao = 8
    modulos_circuitos = len(df_circuitos)
    total_ocupado = modulos_protecao + modulos_circuitos
    espaco_reserva = math.ceil(total_ocupado * 0.25)
    if espaco_reserva < 2: espaco_reserva = 2

    caixas = [12, 18, 24, 36, 48, 72, 100]
    caixa_ideal = next((cx for cx in caixas if cx >= (total_ocupado + espaco_reserva)), "Especial >100")

    def desenhar_cabecalho_e_fundo(canvas_obj, alt, larg, primeira_pagina=True):
        if primeira_pagina:
            canvas_obj.setFont("Helvetica-Bold", 16)
            canvas_obj.drawString(50, alt - 50, "Layout Físico do Quadro de Distribuição (QDG)")
            canvas_obj.setFont("Helvetica", 10)
            canvas_obj.drawString(50, alt - 70, "Documento gerado automaticamente - Projeto Executivo NBR 5410")
            canvas_obj.line(50, alt - 80, larg - 50, alt - 80)
            canvas_obj.setFont("Helvetica-Bold", 12)
            canvas_obj.drawString(50, alt - 110, f"Caixa Recomendada: {caixa_ideal} Módulos DIN")
            canvas_obj.setFont("Helvetica", 10)
            canvas_obj.drawString(50, alt - 125, f"Ocupados: {total_ocupado} | Reserva Técnica (NBR 5410): {espaco_reserva}")
            y_inicio_caixa = alt - 150
        else:
            y_inicio_caixa = alt - 50

        canvas_obj.setStrokeColor(colors.gray)
        canvas_obj.setFillColorRGB(0.95, 0.95, 0.95)
        altura_fundo = y_inicio_caixa - 40
        canvas_obj.rect(40, 40, larg - 80, altura_fundo, fill=1)
        return y_inicio_caixa

    y_referencia = desenhar_cabecalho_e_fundo(c, altura, largura, primeira_pagina=True)
    y_atual = y_referencia - 60
    x_sup = 60
    
    c.setFillColorRGB(0.95, 0.26, 0.21)
    c.rect(x_sup, y_atual, 50, 40, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(x_sup + 25, y_atual + 22, "GERAL")
    c.drawCentredString(x_sup + 25, y_atual + 10, "3P 63A")
    x_sup += 55

    if 'Grupo DR' not in df_circuitos.columns: df_circuitos['Grupo DR'] = 'DR 1 (Geral)'
    grupos_dr_usados = df_circuitos[df_circuitos['Grupo DR'] != 'Nenhum']['Grupo DR'].unique()

    for dr in grupos_dr_usados:
        c.setFillColorRGB(0.13, 0.58, 0.95)
        c.rect(x_sup, y_atual, 100, 40, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(x_sup + 50, y_atual + 22, str(dr)[:18])
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(x_sup + 50, y_atual + 10, "IDR 4P 30mA")
        x_sup += 105

    c.setFillColorRGB(1.0, 0.59, 0.0)
    c.rect(x_sup, y_atual, 50, 40, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(x_sup + 25, y_atual + 22, "DPS")
    c.drawCentredString(x_sup + 25, y_atual + 10, "275V 20kA")

    y_atual -= 70
    x_atual = 60

    def checar_quebra_de_pagina(x_coord, y_coord, canvas_obj):
        if x_coord > largura - 100:
            y_coord -= 50
            x_coord = 60
            if y_coord < 60:
                canvas_obj.showPage()
                y_coord = desenhar_cabecalho_e_fundo(canvas_obj, altura, largura, primeira_pagina=False)
                y_coord -= 60
        return x_coord, y_coord

    for i, row in df_circuitos.iterrows():
        x_atual, y_atual = checar_quebra_de_pagina(x_atual, y_atual, c)
        nome = str(row.get('ID', f"C{i+1}"))
        disj = str(row.get('Disjuntor (A)', '-')) + "A"
        fase = str(row.get('Fase', '-'))

        c.setFillColorRGB(0.29, 0.68, 0.31)
        c.rect(x_atual, y_atual, 35, 40, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x_atual + 5, y_atual + 26, nome)
        c.drawString(x_atual + 5, y_atual + 15, disj)
        c.setFillColorRGB(1.0, 1.0, 0.0)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(x_atual + 17.5, y_atual + 3, fase)
        x_atual += 40

    for r in range(espaco_reserva):
        x_atual, y_atual = checar_quebra_de_pagina(x_atual, y_atual, c)
        c.setFillColorRGB(0.62, 0.62, 0.62)
        c.rect(x_atual, y_atual, 35, 40, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(x_atual + 8, y_atual + 18, "RES")
        x_atual += 40

    y_atual -= 60
    if y_atual < 80:
        c.showPage()
        y_atual = desenhar_cabecalho_e_fundo(c, altura, largura, primeira_pagina=False)
        y_atual -= 80

    c.setFillColorRGB(0.13, 0.58, 0.95)
    c.rect(60, y_atual, largura - 120, 15, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(largura / 2.0, y_atual + 4, "BARRAMENTO DE NEUTRO (N)")

    y_atual -= 25
    c.setFillColorRGB(0.29, 0.68, 0.31)
    c.rect(60, y_atual, largura - 120, 15, fill=1)
    c.setFillColor(colors.white)
    c.drawCentredString(largura / 2.0, y_atual + 4, "BARRAMENTO DE PROTEÇÃO / TERRA (PE)")

    c.save()
    return caminho_saida