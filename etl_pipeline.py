import os
import requests
import smtplib
import pandas as pd
import numpy as np
import math
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Configuración
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
HOY = datetime.today().strftime('%Y-%m-%d')

def obtener_partidos():
    url = "https://free-api-live-football-data.p.rapidapi.com/football-matches-by-date"
    querystring = {"date": HOY}
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "free-api-live-football-data.p.rapidapi.com"
    }
    try:
        response = requests.get(url, headers=headers, params=querystring)
        print(f"DEBUG: Status Code API: {response.status_code}")
        
        if response.status_code != 200:
            print(f"DEBUG: Error en API: {response.text}")
            return []
            
        datos = response.json().get("response", [])
        print(f"DEBUG: Datos crudos recibidos: {datos}")
        return datos
    except Exception as e:
        print(f"DEBUG: Error crítico: {e}")
        return []

def calcular_score_racha(form_str):
    if not form_str or pd.isna(form_str): return 50.0  
    puntos = {'W': 3, 'D': 1, 'L': 0}
    total_puntos = sum(puntos.get(char.upper(), 0) for char in str(form_str)[:5])
    return (total_puntos / 15) * 100

def calcular_marcador_poisson(prob_local, prob_visita):
    goles_esperados_total = 2.5 
    p_h, p_a = prob_local / 100, prob_visita / 100
    if (p_h + p_a) == 0: return "0-0"
    lambda_h = goles_esperados_total * (p_h / (p_h + p_a))
    lambda_a = goles_esperados_total * (p_a / (p_h + p_a))
    max_prob, mejor_marcador = 0, "0-0"
    for i in range(6):
        for j in range(6):
            prob = (math.exp(-lambda_h) * (lambda_h**i) / math.factorial(i)) * (math.exp(-lambda_a) * (lambda_a**j) / math.factorial(j))
            if prob > max_prob:
                max_prob, mejor_marcador = prob, f"{i}-{j}"
    return mejor_marcador

def transformar_y_guardar(partidos):
    if not partidos: return None
    df = pd.DataFrame(partidos)
    # Ajuste de extracción de cuotas según la estructura real que devuelva la API
    df['home_odds'] = df['odds'].apply(lambda x: x.get('home', 2.10))
    df['draw_odds'] = df['odds'].apply(lambda x: x.get('draw', 3.20))
    df['away_odds'] = df['odds'].apply(lambda x: x.get('away', 3.60))
    
    df['mkt_p_local'] = (1/df['home_odds']) / ((1/df['home_odds']) + (1/df['draw_odds']) + (1/df['away_odds']))
    df['mkt_p_empate'] = (1/df['draw_odds']) / ((1/df['home_odds']) + (1/df['draw_odds']) + (1/df['away_odds']))
    df['mkt_p_visita'] = (1/df['away_odds']) / ((1/df['home_odds']) + (1/df['draw_odds']) + (1/df['away_odds']))

    df['prob_local'] = (df['mkt_p_local'] * 100).round(1)
    df['prob_empate'] = (df['mkt_p_empate'] * 100).round(1)
    df['prob_visita'] = (df['mkt_p_visita'] * 100).round(1)
    df['marcador_predicho'] = df.apply(lambda row: calcular_marcador_poisson(row['prob_local'], row['prob_visita']), axis=1)

    return df

def enviar_correo(df):
    msg = MIMEMultipart()
    msg['From'], msg['To'], msg['Subject'] = GMAIL_USER, GMAIL_USER, f"Pronósticos Mundial - {HOY}"
    
    if df is None:
        html = "<h2>No se encontraron partidos hoy o la API falló. Revisa los logs de GitHub Actions.</h2>"
    else:
        html = "<table border='1'><tr><th>Partido</th><th>L</th><th>E</th><th>V</th><th>Marcador</th></tr>"
        for _, r in df.iterrows():
            html += f"<tr><td>{r['home_team']} vs {r['away_team']}</td><td>{r['prob_local']}%</td><td>{r['prob_empate']}%</td><td>{r['prob_visita']}%</td><td>{r['marcador_predicho']}</td></tr>"
        html += "</table>"
    
    msg.attach(MIMEText(html, 'html'))
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(GMAIL_USER, GMAIL_PASSWORD)
    server.send_message(msg)
    server.quit()

if __name__ == "__main__":
    partidos = obtener_partidos()
    df = transformar_y_guardar(partidos)
    enviar_correo(df)
