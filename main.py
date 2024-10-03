# main.py
import logging
from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from core_functions import (add_thread_to_sheet,
                            client, process_tool_calls, get_assistant_id,
                            check_openai_version, load_tools_from_directory,
                            get_folder_by_id, open_spreadsheet_in_folder,
                            check_api_key, SHEET_NAME)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import time
import threading

# Configure logging
logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# Check OpenAI version compatibility
check_openai_version()

# Create Flask app
app = Flask(__name__)
CORS(app)

# Initialize all available tools
tool_data = load_tools_from_directory('tools')

# Get assistant ID from environment variables
assistant_id = get_assistant_id()

# Initialize Flask-Limiter with explicit in-memory storage configuration
limiter = Limiter(key_func=get_remote_address,
                  storage_uri="memory://",
                  app=app,
                  default_limits=["200 per minute"])

# Obtener la carpeta 'bot_sheets' por ID
folder_name = get_folder_by_id()

# Abrir la hoja de cálculo especificada en la variable de entorno 'SHEET_NAME'
try:
    spreadsheet = open_spreadsheet_in_folder(SHEET_NAME)
    sheet = spreadsheet.sheet1
except FileNotFoundError as e:
    logging.error(e)
    sheet = None  # Definir `sheet` como None si no se encuentra la hoja de cálculo


@app.route('/start', methods=['GET'])
# @limiter.limit("50 per day")  # Limitar a 50 conversaciones por día
def start_conversation():
    # check_api_key()
    platform = request.args.get('platform', 'Not Specified')
    username = request.args.get('username', 'Not Specified')

    logging.info(f"Starting a new conversation from platform: {platform}")

    thread = client.beta.threads.create()
    logging.info(f"New thread created with ID: {thread.id}")

    if sheet is not None:
        add_thread_to_sheet(thread.id, platform, username, sheet)
    else:
        logging.error("Sheet not defined. Cannot add thread to sheet.")
        return jsonify({"error": "Sheet not defined"}), 500

    # Añadir el hilo a Airtable
    # add_thread_to_airtable(thread.id, platform, username)

    return jsonify({"thread_id": thread.id})


@app.route('/chat', methods=['POST'])
# @limiter.limit("100 per day")  # Limitar a 100 mensajes por día
def chat():
    # check_api_key()
    data = request.json
    thread_id = data.get('thread_id')
    user_input = data.get('message', '')

    if not thread_id:
        logging.error("Error: Missing thread_id")
        return jsonify({"error": "Missing thread_id"}), 400

    logging.info(f"Received message: {user_input} for thread ID: {thread_id}")
    client.beta.threads.messages.create(thread_id=thread_id,
                                        role="user",
                                        content=user_input)
    run = client.beta.threads.runs.create(thread_id=thread_id,
                                          assistant_id=assistant_id)

    logging.info(f"Run ID: {run.id}")
    return jsonify({"run_id": run.id})


@app.route('/check', methods=['POST'])
# @limiter.limit("200 per day")
def check_run_status():
    # check_api_key()
    data = request.json
    thread_id = data.get('thread_id')
    run_id = data.get('run_id')
    if not thread_id or not run_id:
        logging.error("Error: Missing thread_id or run_id in /check")
        return jsonify({"error": "Missing thread_id or run_id"}), 400

    result = process_tool_calls(client, thread_id, run_id, tool_data)
    return jsonify(result)


@app.errorhandler(400)
def handle_400_error(e):
    logging.error(f"Bad Request: {e.description}")
    return jsonify(error="Bad Request", message=e.description), 400


@app.errorhandler(401)
def handle_401_error(e):
    logging.error(f"Unauthorized: {e.description}")
    return jsonify(error="Unauthorized", message=e.description), 401


@app.errorhandler(500)
def handle_500_error(e):
    logging.error(f"Internal Server Error: {e}")
    return jsonify(error="Internal Server Error",
                   message="An unexpected error occurred"), 500

def run_transcript_script():
    while True:
        try:
            logging.info("Ejecutando script de transcripción...")
            os.system('python Transcript/transcript.py')
            logging.info("Esperando 12 horas hasta la próxima ejecución...")
            time.sleep(12 * 3600)  # Esperar 12 horas antes de la próxima ejecución
        except Exception as e:
            logging.error(f"Error executing transcript script: {e}")


if __name__ == '__main__':
    threading.Thread(target=run_transcript_script, daemon=True).start()
    app.run(host='0.0.0.0', port=8080)
