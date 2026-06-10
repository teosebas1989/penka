import os
import requests
import smtplib
import pandas as pd
import numpy as np
import math
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")

HOY = datetime.today().strftime('%Y-%m-%d')

def obtener_partidos():
    """Extract: Obtiene partidos y cuotas desde la API con logging de control."""
    url = "https://free-api-live-football-data.p.rapidapi.com/football-matches-by-date"
    querystring = {"date": HOY}
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "free-api-live-football-data.p.rapidapi.com"
    }
    try:
        response = requests.get(url, headers=headers, params=querystring)
        datos = response.json().get("response", [])
        
        # LOG DE CONTROL: Esto aparecerá en los logs de GitHub Actions
        print(f"--- [DEBUG] Datos recibidos de la API el {HOY}: {datos} ---")
        
        return datos
    except Exception as e:
        print(f"Error en extracción: {e}")
        return []

def calcular_score_racha(form_str):
    """Calcula el rendimiento reciente."""
    if not form_str or pd.isna(form_str): 
        return 50.0  
    
    puntos = {'W': 3, 'D': 1, 'L': 0}
    total_puntos = sum(puntos.get(char.upper(), 0) for char in str(form_str)[:5])
    max_posible = len(str(form_str)[:5]) * 3
    
    return (total_puntos / max_posible) * 100 if max_posible > 0 else 50.0

def calcular_marcador_poisson(prob_local, prob_visita):
    """Genera el marcador más probable usando Poisson."""
    goles_esperados_total = 2.5 
    p_h = prob_local / 100
    p_a = prob_visita / 100
    
    if (p_h + p_a) == 0: return "0-0"
    
    lambda_h = goles_esperados_total * (p_h / (p_h + p_a))
    lambda_a = goles_esperados_total * (p_a / (p_h + p_a))
    
    max_prob = 0
    mejor_marcador = "0-0"
    
    for i in range(6):
        for j in range(6):
            prob_i = (math.exp(-lambda_h) * (lambda_h**i)) / math.factorial(i)
            prob_j = (math.exp(-lambda_a) * (lambda_a**j)) / math.factorial(j)
            prob_cruzada = prob_i * prob_j
            
            if prob_cruzada > max_prob:
                max_prob = prob_cruzada
                mejor_marcador = f"{i}-{j}"
                
    return mejor_marcador

def transformar_y_guardar(partidos):
    """Transform & Load: Procesa métricas híbridas 80/20 y Poisson."""
    if not partidos:
        return ""

    df = pd.DataFrame(partidos)

    df['home_odds'] = df['odds'].apply(lambda x: x.get('home', 2.10) if isinstance(x, dict) else 2.10)
    df['draw_odds'] = df['odds'].apply(lambda x: x.get('draw', 3.20) if isinstance(x, dict) else 3.20)
    df['away_odds'] = df['odds'].apply(lambda x: x.get('away', 3.60) if isinstance(x, dict) else 3.60)
    
    df['form_local_str'] = df.get('home_team_form', 'WWDLW')
    df['form_visita_str'] = df.get('away_team_form', 'LDWLW')

    # PASO A: Mercado Puro
    df['raw_p_local'] = 1 / df['home_odds']
    df['raw_p_empate'] = 1 / df['draw_odds']
    df['raw_p_visita'] = 1 / df['away_odds']
    df['overround'] = df['raw_p_local'] + df['raw_p_empate'] + df['raw_p_visita']
    
    df['mkt_p_local'] = df['raw_p_local'] / df['overround']
    df['mkt_p_empate'] = df['raw_p_empate'] / df['overround']
    df['mkt_p_visita'] = df['raw_p_visita'] / df['overround']

    # PASO B: Racha Reciente
    df['score_form_local'] = df['form_local_str'].apply(calcular_score_racha)
    df['score_form_visita'] = df['form_visita_str'].apply(calcular_score_racha)
    df['diff_racha'] = (df['score_form_local'] - df['score_form_visita']) / 100
    
    df['racha_p_local'] = (0.35 + (df['diff_racha'] * 0.15)).clip(0, 1)
    df['racha_p_visita'] = (0.35 - (df['diff_racha'] * 0.15)).clip(0, 1)
    df['racha_p_empate'] = 0.30

    # PASO C: Combinación Híbrida 80/20
    df['probabilidad_local'] = ((df['mkt_p_local'] * 0.80) + (df['racha_p_local'] * 0.20)) * 100
    df['probabilidad_empate'] = ((df['mkt_p_empate'] * 0.80) + (df['racha_p_empate'] * 0.20)) * 100
    df['probabilidad_visitante'] = ((df['mkt_p_visita'] * 0.80) + (df['racha_p_visita'] * 0.20)) * 100

    df['probabilidad_local'] = df['probabilidad_local'].round(1)
    df['probabilidad_empate'] = df['probabilidad_empate'].round(1)
    df['probabilidad_visitante'] = df['probabilidad_visitante'].round(1)

    # PASO D: Motor de Poisson
    df['marcador_predicho'] = df.apply(lambda row: calcular_marcador_poisson(row['probabilidad_local'], row['probabilidad_visitante']), axis=1)

    # Carga a Supabase
    df['fecha_partido'] = HOY
    df_supabase = df[['fecha_partido', 'home_team', 'away_team', 'probabilidad_local', 'probabilidad_empate', 'probabilidad_visitante', 'marcador_predicho']].copy()
    df_supabase.columns = ['fecha_partido', 'equipo_local', 'equipo_visitante', 'probabilidad_local', 'probabilidad_empate', 'probabilidad_visitante', 'marcador_predicho']

    records = df_supabase.to_dict(orient='records')
    if records:
        endpoint = f"{SUPABASE_URL}/rest/v1/pronosticos_mundial"
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=minimal"}
        requests.post(endpoint, headers=headers, json=records)

    # Generar HTML
    html_filas = ""
    for _, row in df.iterrows():
        html_filas += f"""
        <tr>
            <td style='padding:10px; border-bottom:1px solid #ddd;'><b>{row['home_team']}</b> vs <b>{row['away_team']}</b></td>
            <td style='padding:10px; border-bottom:1px solid #ddd; text-align:center;'>{row['probabilidad_local']}%</td>
            <td style='padding:10px; border-bottom:1px solid #ddd; text-align:center;'>{row['probabilidad_empate']}%</td>
            <td style='padding:10px; border-bottom:1px solid #ddd; text-align:center;'>{row['probabilidad_visitante']}%</td>
            <td style='padding:10px; border-bottom:1px solid #ddd; text-align:center; font-weight:bold; color:#e74c3c;'>{row['marcador_predicho']}</td>
        </tr>
        """
    return html_filas

def enviar_correo(tabla_html):
    if not tabla_html: tabla_html = "<tr><td colspan='5' align='center'>Sin partidos hoy.</td></tr>"
    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER
    msg['Subject'] = f"🏆 Modelo Híbrido Penka (80/20) - {HOY}"

    html = f"""<div style="font-family:sans-serif; max-width:650px; margin:auto;">
        <h2 style="color:#2c3e50;">Predicciones Combinadas (80% Mercado | 20% Racha)</h2>
        <table style="width:100%; border-collapse:collapse; margin-top:20px;">
            <tr style="background-color:#2c3e50; color:white;"><th style="padding:10px; text-align:left;">Partido</th><th>Local</th><th>Empate</th><th>Visita</th><th>Marcador</th></tr>
            {tabla_html}
        </table>
    </div>"""
    msg.attach(MIMEText(html, 'html'))
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
    except Exception as e: print(f"Error de correo: {e}")

if __name__ == "__main__":
    partidos = obtener_partidos()
    if not partidos:
        partidos = [{"home_team": "México", "away_team": "Sudáfrica", "home_team_form": "WWDWW", "away_team_form": "LLDLL", "odds": {"home": 1.80, "draw": 3.40, "away": 4.50}}]
    filas = transformar_y_guardar(partidos)
    enviar_correo(filas)
