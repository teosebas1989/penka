import os
import requests
import smtplib
import pandas as pd
import numpy as np
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
    """Extract: Obtiene partidos y cuotas desde la API."""
    url = "https://free-api-live-football-data.p.rapidapi.com/football-matches-by-date"
    querystring = {"date": HOY}
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "free-api-live-football-data.p.rapidapi.com"
    }
    try:
        response = requests.get(url, headers=headers, params=querystring)
        return response.json().get("response", [])
    except Exception as e:
        print(f"Error en extracción: {e}")
        return []

def calcular_score_racha(form_str):
    """Función helper para transformar la racha (texto) a un score numérico (0-100)."""
    if not form_str or pd.isna(form_str): 
        return 50.0  # Neutro si no hay historial
    
    # Tomamos los últimos 5 partidos, asignamos 3 puntos por victoria (W) y 1 por empate (D)
    puntos = {'W': 3, 'D': 1, 'L': 0}
    total_puntos = sum(puntos.get(char.upper(), 0) for char in str(form_str)[:5])
    max_posible = len(str(form_str)[:5]) * 3
    
    return (total_puntos / max_posible) * 100 if max_posible > 0 else 50.0

def transformar_y_guardar(partidos):
    """Transform & Load: Procesa la matriz de pesos con Pandas y carga a Supabase."""
    if not partidos:
        return ""

    # 1. Crear DataFrame base
    df = pd.DataFrame(partidos)

    # Desestructurar diccionarios anidados de la API (Cuotas y Rachas) con fallbacks
    df['home_odds'] = df['odds'].apply(lambda x: x.get('home', 2.10) if isinstance(x, dict) else 2.10)
    df['draw_odds'] = df['odds'].apply(lambda x: x.get('draw', 3.20) if isinstance(x, dict) else 3.20)
    df['away_odds'] = df['odds'].apply(lambda x: x.get('away', 3.60) if isinstance(x, dict) else 3.60)
    
    df['form_local_str'] = df.get('home_team_form', 'WWDLW') # Mock default si la API no lo trae
    df['form_visita_str'] = df.get('away_team_form', 'LDWLW')

    # 2. PASO A: Probabilidades Normalizadas del Mercado (70% del peso)
    df['raw_p_local'] = 1 / df['home_odds']
    df['raw_p_empate'] = 1 / df['draw_odds']
    df['raw_p_visita'] = 1 / df['away_odds']
    
    df['overround'] = df['raw_p_local'] + df['raw_p_empate'] + df['raw_p_visita']
    
    df['mkt_p_local'] = df['raw_p_local'] / df['overround']
    df['mkt_p_empate'] = df['raw_p_empate'] / df['overround']
    df['mkt_p_visita'] = df['raw_p_visita'] / df['overround']

    # 3. PASO B: Probabilidades basadas en Rendimiento Reciente (30% del peso)
    df['score_form_local'] = df['form_local_str'].apply(calcular_score_racha)
    df['score_form_visita'] = df['form_visita_str'].apply(calcular_score_racha)
    
    # Calculamos la diferencia de rendimiento entre ambos equipos
    df['diff_racha'] = (df['score_form_local'] - df['score_form_visita']) / 100  # Rango entre -1 y 1
    
    # Distribuimos el impacto de la racha (el empate se mantiene base en 30%)
    df['racha_p_local'] = 0.35 + (df['diff_racha'] * 0.15)
    df['racha_p_visita'] = 0.35 - (df['diff_racha'] * 0.15)
    df['racha_p_empate'] = 0.30
    
    # Asegurar límites lógicos entre 0 y 1
    df['racha_p_local'] = df['racha_p_local'].clip(0, 1)
    df['racha_p_visita'] = df['racha_p_visita'].clip(0, 1)

    # 4. PASO C: Combinación del Modelo Híbrido (70% Mercado + 30% Racha)
    df['probabilidad_local'] = ((df['mkt_p_local'] * 0.70) + (df['racha_p_local'] * 0.30)) * 100
    df['probabilidad_empate'] = ((df['mkt_p_empate'] * 0.70) + (df['racha_p_empate'] * 0.30)) * 100
    df['probabilidad_visitante'] = ((df['mkt_p_visita'] * 0.70) + (df['racha_p_visita'] * 0.30)) * 100

    # Redondear y formatear
    df['probabilidad_local'] = df['probabilidad_local'].round(1)
    df['probabilidad_empate'] = df['probabilidad_empate'].round(1)
    df['probabilidad_visitante'] = df['probabilidad_visitante'].round(1)

    # 5. Carga masiva (Bulk Load) a Supabase
    df['fecha_partido'] = HOY  # <-- Aquí está la corrección clave para Pandas
    
    df_supabase = df[[
        'fecha_partido', 'home_team', 'away_team', 
        'probabilidad_local', 'probabilidad_empate', 'probabilidad_visitante'
    ]].copy()
    
    # Renombrar columnas para que coincidan exactamente con la base de datos
    df_supabase.columns = [
        'fecha_partido', 'equipo_local', 'equipo_visitante', 
        'probabilidad_local', 'probabilidad_empate', 'probabilidad_visitante'
    ]

    records = df_supabase.to_dict(orient='records')
    
    if records:
        endpoint = f"{SUPABASE_URL}/rest/v1/pronosticos_mundial"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        requests.post(endpoint, headers=headers, json=records)

    # 6. Generar las filas HTML para el correo usando Pandas
    html_filas = ""
    for _, row in df.iterrows():
        html_filas += f"""
        <tr>
            <td style='padding:8px; border-bottom:1px solid #eee;'><b>{row['home_team']}</b> vs <b>{row['away_team']}</b></td>
            <td style='padding:8px; border-bottom:1px solid #eee; text-align:center; color:#27ae60;'>{row['probabilidad_local']}%</td>
            <td style='padding:8px; border-bottom:1px solid #eee; text-align:center; color:#7f8c8d;'>{row['probabilidad_empate']}%</td>
            <td style='padding:8px; border-bottom:1px solid #eee; text-align:center; color:#2980b9;'>{row['probabilidad_visitante']}%</td>
        </tr>
        """
    return html_filas

def enviar_correo(tabla_html):
    """Notificar: Despacha la alerta por Gmail."""
    if not tabla_html:
        tabla_html = "<tr><td colspan='4' align='center'>Sin partidos hoy.</td></tr>"

    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER
    msg['Subject'] = f"📊 Modelo Híbrido Penka - {HOY}"

    html = f"""
    <div style="font-family:sans-serif; max-width:600px; margin:auto;">
        <h2 style="color:#2c3e50;">Predicciones Combinadas (70% Mercado | 30% Racha)</h2>
        <p>Este modelo ajusta las probabilidades del mercado según el rendimiento reciente en la cancha:</p>
        <table style="width:100%; border-collapse:collapse;">
            <tr style="background-color:#ecf0f1;">
                <th style="padding:10px; text-align:left;">Partido</th>
                <th>Local</th><th>Empate</th><th>Visita</th>
            </tr>
            {tabla_html}
        </table>
    </div>
    """
    msg.attach(MIMEText(html, 'html'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("Correo enviado correctamente.")
    except Exception as e:
        print(f"Error de correo: {e}")

if __name__ == "__main__":
    partidos = obtener_partidos()
    if not partidos:
        # Mock con datos de racha incluidos para la simulación inicial
        partidos = [{
            "home_team": "México", 
            "away_team": "Sudáfrica",
            "home_team_form": "WWDWW", # Racha excelente
            "away_team_form": "LLDLL", # Racha pésima
            "odds": {"home": 2.10, "draw": 3.20, "away": 3.60}
        }]
    
    filas = transformar_y_guardar(partidos)
    enviar_correo(filas)
