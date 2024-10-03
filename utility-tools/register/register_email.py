import os
import json
import gspread
from google.oauth2.service_account import Credentials

# Cargar variables de entorno
SHEETS_CREDENTIALS = os.getenv('SHEET_CREDENTIALS')
SHEET_NAME = os.getenv('SHEET_NAME')

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

# La configuración de la herramienta
tool_config = {
    "type": "function",
    "function": {
        "name": "register_email",
        "description": "Registers the user's email at the start of the conversation in Google Sheets.",
        "parameters": {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": "The email address of the user."
                }
            },
            "required": ["email"]
        }
    }
}

# La función de devolución de llamada
def register_email(arguments):
    """
    Registra el correo electrónico del usuario en Google Sheets.

    :param arguments: dict, contiene el correo electrónico del usuario.
    :return: str, mensaje de éxito o error.
    """
    email = arguments.get('email')
    if not email:
        return "Email is required."

    try:
        sheet = sheets_client.open(SHEET_NAME).sheet1
        # Encontrar la primera fila vacía en la columna J
        cell_list = sheet.col_values(10)
        empty_row = len(cell_list) + 1
        # Registrar el correo electrónico en la columna J
        sheet.update_cell(empty_row, 10, email)
        return "Email registered successfully."
    except Exception as e:
        return f"Failed to register email: {e}"
