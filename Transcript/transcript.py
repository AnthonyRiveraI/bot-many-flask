import os
import requests
import openai
import re
import gspread
from google.oauth2.service_account import Credentials
from tema import tema_prompt

# Cargar variables de entorno
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
SHEETS_CREDENTIALS = os.getenv('SHEET_CREDENTIALS')
SHEET_NAME = os.getenv('SHEET_NAME')

# Inicializar cliente de OpenAI
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Configuración de las credenciales y alcance de Google Sheets y Drive
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

try:
    creds = Credentials.from_service_account_file(SHEETS_CREDENTIALS, scopes=scope)
except Exception as e:
    raise ValueError(f"Error loading Sheets credentials from path: {SHEETS_CREDENTIALS}, {e}")

sheets_client = gspread.authorize(creds)

def fetch_sheet_records():
    try:
        sheet = sheets_client.open(SHEET_NAME).sheet1
        records = sheet.get_all_records()
        if not records:
            print("No se encontraron registros.")
        else:
            print(f"Registros recuperados de Google Sheets: {records}")
        return records
    except Exception as e:
        print(f"Error al obtener registros de Google Sheets: {e}")
        return []

def fetch_openai_data(thread_id):
    url = f"https://api.openai.com/v1/threads/{thread_id}/messages"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
        "OpenAI-Beta": "assistants=v2"
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to fetch thread data: {response.status_code}, Response: {response.text}")
        return {}

def process_transcript(messages):
    if not messages:
        return ""

    # Ordenar los mensajes de más antiguo a más reciente
    sorted_messages = sorted(messages, key=lambda x: x['created_at'])
    transcript = "\n".join([f"{msg['role']}: {msg['content'][0]['text']['value']}" for msg in sorted_messages])
    return transcript

def count_user_messages(transcript):
    return len(re.findall(r'user:', transcript))

def classify_data(transcript, prompt_template):
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt_template.format(transcript=transcript)}],
        max_tokens=100,
        temperature=0.7
    )
    return response.choices[0].message.content.strip()

def update_sheet_batch(updates, sheet):
    try:
        sheet.batch_update(updates)
        print("Records updated successfully.")
    except Exception as e:
        print(f"Failed to update records: {e}")

def main():
    records = fetch_sheet_records()
    sheet = sheets_client.open(SHEET_NAME).sheet1
    updates = []

    for record in records:
        thread_id = record.get('Thread_id')
        if not thread_id:
            continue

        # Encontrar la fila correspondiente al Thread_id
        cell = sheet.find(thread_id)
        if not cell:
            continue
        row_number = cell.row

        data = fetch_openai_data(thread_id)
        messages = data.get('data', [])
        if not messages:
            updates.append({
                'range': f"E{row_number}:I{row_number}",  # Columnas E a I
                'values': [["Processed", "EMPTY", "EMPTY", "0", "EMPTY"]]
            })
            continue

        transcript = process_transcript(messages)
        if transcript:
            tema = classify_data(transcript, tema_prompt)
            user_messages_count = count_user_messages(transcript)

            lead_prompt = "Eres un analizador de leads. Se te proporciona la siguiente conversación, entre un usuario y un asistente de IA. Responde con 'Yes' o 'No' indicando si la conversación contiene un lead:\n\n{transcript}"
            lead = classify_data(transcript, lead_prompt)

            updates.append({
                'range': f"E{row_number}:I{row_number}",  # Columnas E a I
                'values': [["Processed", transcript, tema, user_messages_count, lead]]
            })
        else:
            updates.append({
                'range': f"E{row_number}:I{row_number}",  # Columnas E a I
                'values': [["EMPTY", "EMPTY", "EMPTY", "0", "EMPTY"]]
            })

    if updates:
        update_sheet_batch(updates, sheet)

if __name__ == '__main__':
    main()
