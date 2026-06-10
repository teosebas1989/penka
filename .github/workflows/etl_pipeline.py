import os
import requests
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 1. Credenciales seguras desde variables de entorno
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")

HOY = datetime.today().strftime('%Y-%m-%d')

def obtener_partidos():
    """Extrae los partidos y cuotas de la API."""
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

def transformar_y_guardar(partidos):
    """Calcula probabilidades puras (sin comisión) y guarda en BD."""
    datos_supabase = []
    html_filas = ""

    for partido in partidos:
        local = partido.get("home_team", "Local")
        visitante = partido.get("away_team", "Visitante")
        
        # Simulamos extracción de cuotas (ajustar según el JSON real de la API)
        odds = partido.get("odds", {"home": 2.10, "draw": 3.20, "away": 3.60})
        
        # 1. Cálculo de probabilidad implícita con margen de la casa
        imp_local = 1 / odds["home"]
        imp_empate = 1 / odds["draw"]
        imp_visitante = 1 / odds["away"]
        
        # 2. Normalización (eliminar el "vig" para que sumen 100% exacto)
        margen_total = imp_local + imp_empate + imp_visitante
        
        prob_local = round((imp_local / margen_total) * 100, 1)
        prob_empate = round((imp_empate / margen_total) * 100, 1)
        prob_visitante = round((imp_visitante / margen_total) * 100, 1)

        datos_supabase.append({
            "fecha_partido": HOY,
            "equipo_local": local,
            "equipo_visitante": visitante,
            "probabilidad_local": prob_local,
            "probabilidad_empate": prob_empate,
            "probabilidad_visitante": prob_visitante
        })

        html_filas += f"""
        <tr>
            <td style='padding:8px; border-bottom:1px solid #eee;'><b>{local}</b> vs <b>{visitante}</b></td>
            <td style='padding:8px; border-bottom:1px solid #eee; text-align:center; color:#27ae60;'>{prob_local}%</td>
            <td style='padding:8px; border-bottom:1px solid #eee; text-align:center; color:#7f8c8d;'>{prob_empate}%</td>
            <td style='padding:8px; border-bottom:1px solid #eee; text-align:center; color:#2980b9;'>{prob_visitante}%</td>
        </tr>
        """

    # Insertar en Supabase
    if datos_supabase:
        endpoint = f"{SUPABASE_URL}/rest/v1/pronosticos_mundial"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        requests.post(endpoint, headers=headers, json=datos_supabase)
        
    return html_filas

def enviar_correo(tabla_html):
    """Envía la alerta por Gmail."""
    if not tabla_html:
        tabla_html = "<tr><td colspan='4' align='center'>Sin partidos hoy.</td></tr>"

    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER
    msg['Subject'] = f"⚽ Pronósticos Penka Mundial - {HOY}"

    html = f"""
    <div style="font-family:sans-serif; max-width:600px; margin:auto;">
        <h2 style="color:#2c3e50;">Predicciones Normalizadas del Mercado</h2>
        <p>Datos purificados matemáticamente. Ingresa tu pronóstico:</p>
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
        print("Alerta enviada correctamente.")
    except Exception as e:
        print(f"Error de correo: {e}")

if __name__ == "__main__":
    partidos = obtener_partidos()
    # Mock para asegurar que corra la prueba si la API no devuelve data hoy
    if not partidos:
        partidos = [{"home_team": "México", "away_team": "Sudáfrica"}]
    
    filas = transformar_y_guardar(partidos)
    enviar_correo(filas)