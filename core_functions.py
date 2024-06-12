# core_functions.py
import logging
import openai
import os
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import pytz
from googleapiclient.discovery import build
from packaging import version
from flask import request, abort
import time
import re
import json

# Cargar las variables de entorno desde el entorno
AIRTABLE_DB_URL = os.getenv('AIRTABLE_DB_URL')
AIRTABLE_API_KEY = f"Bearer {os.getenv('AIRTABLE_API_KEY')}"
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ASSISTANT_ID = os.getenv('ASSISTANT_ID')
CUSTOM_API_KEY = os.getenv('CUSTOM_API_KEY')
SHEET_CREDENTIALS = os.getenv('SHEET_CREDENTIALS')
SHEET_NAME = os.getenv('SHEET_NAME')
FOLDER_ID = os.getenv('FOLDER_ID')

# Initialize OpenAI client with v2 API header
if not OPENAI_API_KEY:
    raise ValueError("No OpenAI API key found in environment variables")
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Configuración de las credenciales y alcance de Google Sheets y Drive
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

if not SHEET_CREDENTIALS:
    raise ValueError(
        "No Sheets credentials path found in environment variables")

try:
    creds = Credentials.from_service_account_file(SHEET_CREDENTIALS,
                                                  scopes=scope)
except Exception as e:
    raise ValueError(
        f"Error loading Sheets credentials from path: {SHEET_CREDENTIALS}, {e}"
    )

sheets_client = gspread.authorize(creds)
drive_service = build('drive', 'v3', credentials=creds)


def check_openai_version():
    required_version = version.parse("1.1.1")
    current_version = version.parse(openai.__version__)
    if current_version < required_version:
        raise ValueError(
            f"Error: OpenAI version {openai.__version__} is less than the required version 1.1.1"
        )
    else:
        logging.info("OpenAI version is compatible.")


def check_api_key():
    api_key = request.headers.get('X-API-KEY')
    if api_key != CUSTOM_API_KEY:
        logging.info(f"Invalid API key: {api_key}")
        abort(401)


def get_folder_by_id():
    try:
        folder = drive_service.files().get(fileId=FOLDER_ID,
                                           fields='id, name').execute()
        logging.info(f"Folder '{folder['name']}' exists with ID: {FOLDER_ID}")
        return folder['name']
    except Exception as e:
        logging.error(f"Could not retrieve folder: {str(e)}")
        raise FileNotFoundError(f"Folder with ID '{FOLDER_ID}' not found.")


def open_spreadsheet_in_folder(spreadsheet_name):
    query = f"'{FOLDER_ID}' in parents and name='{spreadsheet_name}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
    results = drive_service.files().list(q=query, spaces='drive').execute()
    items = results.get('files', [])

    if not items:
        raise FileNotFoundError(
            f"Spreadsheet '{spreadsheet_name}' not found in folder '{FOLDER_ID}'"
        )

    spreadsheet_id = items[0]['id']
    return sheets_client.open_by_key(spreadsheet_id)


def add_thread_to_sheet(thread_id, platform, username, sheet):
    try:
        local_timezone = pytz.timezone('America/Mexico_City')
        current_time = datetime.now(local_timezone).strftime(
            '%Y-%m-%d %H:%M:%S')

        row = [thread_id, platform, username, current_time, "Arrived"]
        sheet.append_row(row)
        logging.info("Thread added to sheet successfully.")
    except Exception as e:
        logging.error(
            f"An error occurred while adding the thread to the sheet: {e}")


def add_thread_to_airtable(thread_id, platform, username):
    url = f"{AIRTABLE_DB_URL}"
    headers = {
        "Authorization": f"{AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }

    local_timezone = pytz.timezone('America/Mexico_City')
    current_time = datetime.now(local_timezone).strftime('%Y-%m-%d %H:%M:%S')

    data = {
        "records": [{
            "fields": {
                "Thread_id": thread_id,
                "Platform": platform,
                "Username": username,
                "Status": "Arrived",
            }
        }]
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            logging.info("Thread added to Airtable successfully.")
        else:
            logging.error(
                f"Failed to add thread to Airtable: HTTP Status Code {response.status_code}, Response: {response.text}"
            )
    except Exception as e:
        logging.error(
            f"An error occurred while adding the thread to Airtable: {e}")


def process_tool_calls(client, thread_id, run_id, tool_data):
    start_time = time.time()
    while time.time() - start_time < 8:
        run_status = client.beta.threads.runs.retrieve(thread_id=thread_id,
                                                       run_id=run_id)
        logging.info(f"Checking run status: {run_status.status}")

        if run_status.status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=thread_id)
            message_content = messages.data[0].content[0].text.value
            logging.info(f"Message content before cleaning: {message_content}")

            message_content = re.sub(r"【.*?†.*?】", '', message_content)
            message_content = re.sub(r'[^\S\r\n]+', ' ',
                                     message_content).strip()

            return {"response": message_content, "status": "completed"}

        elif run_status.status == 'requires_action':
            logging.info("Run requires action, handling...")
            for tool_call in run_status.required_action.submit_tool_outputs.tool_calls:
                function_name = tool_call.function.name

                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as e:
                    logging.error(
                        f"JSON decoding failed: {e.msg}. Input: {tool_call.function.arguments}"
                    )
                    arguments = {}

                if function_name in tool_data["function_map"]:
                    function_to_call = tool_data["function_map"][function_name]
                    output = function_to_call(arguments)
                    client.beta.threads.runs.submit_tool_outputs(
                        thread_id=thread_id,
                        run_id=run_id,
                        tool_outputs=[{
                            "tool_call_id": tool_call.id,
                            "output": json.dumps(output)
                        }])
                else:
                    logging.warning(
                        f"Function {function_name} not found in tool data.")
                    break

        elif run_status.status == 'failed':
            logging.error("Run failed")
            return {"response": "error", "status": "failed"}

        time.sleep(2)

    logging.info("Run timed out")
    return {"response": "timeout", "status": "timeout"}


def load_tools_from_directory(directory):
    tool_data = {"tool_configs": [], "function_map": {}}

    for filename in os.listdir(directory):
        if filename.endswith('.py'):
            module_name = filename[:-3]
            module_path = os.path.join(directory, filename)
            spec = importlib.util.spec_from_file_location(
                module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, 'tool_config'):
                tool_data["tool_configs"].append(module.tool_config)

            for attr in dir(module):
                attribute = getattr(module, attr)
                if callable(attribute) and not attr.startswith("__"):
                    tool_data["function_map"][attr] = attribute

    return tool_data


def get_assistant_id():
    assistant_id = os.getenv('ASSISTANT_ID')
    if not assistant_id:
        raise ValueError(
            "Assistant ID not found in environment variables. Please set ASSISTANT_ID."
        )
    logging.info("Loaded existing assistant ID from environment variable.")
    return assistant_id
