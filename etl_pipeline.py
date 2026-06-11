import os
import requests
import smtplib
import pandas as pd
import numpy as np
import math
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- CONFIGURACIÓN ---
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
HOY = datetime.today().strftime('%Y-%m-%d')

def obtener_partidos():
    """Extract: Llama a un endpoint de fixtures estándar."""
    # Cambiamos a /fixtures que es el estándar de la industria en RapidAPI
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
    querystring = {"date": HOY, "league": "1", "season": "2026"} # Ajusta la liga si es necesario
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "api-football-v1.p.rapidapi.com"
    }
    
    try:
        response = requests.get(url, headers=headers, params=querystring)
        print(f"DEBUG: Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"DEBUG: Error API: {response.text}")
            return None
            
        data = response.json()
        return data.get("response", [])
    except Exception as e:
        print(f"DEBUG: Error crítico: {e}")
        return None

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

def procesar_datos(partidos):
    if not partidos: return None
    
    # Adaptación a la estructura común de API-Football
    lista_procesada = []
    for p in partidos:
        lista_procesada.append({
            "home": p["teams"]["home"]["name"],
            "away": p["teams"]["away"]["name"],
            "prob_local": 45.0, # Placeholder hasta mapear odds reales
            "prob_empate": 25.0,
            "prob_visita": 30.0
        })
    df = pd.DataFrame(lista_procesada)
    df['marcador'] = df.apply(lambda r: calcular_marcador_poisson(r['prob_local'], r['prob_visita']), axis=1)
    return df

def enviar_correo(df):
    msg = MIMEMultipart()
    msg['From'], msg['To'], msg['Subject'] = GMAIL_USER, GMAIL_USER, f"Pronóstico Mundial - {HOY}"
    html = "<h3>Resultados del Proceso</h3>" + (df.to_html() if df is not None else "API sin datos hoy.")
    msg.attach(MIMEText(html, 'html'))
    
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(GMAIL_USER, GMAIL_PASSWORD)
    server.send_message(msg)
    server.quit()

if __name__ == "__main__":
    partidos = obtener_partidos()
    df = procesar_datos(partidos)
    enviar_correo(df)
