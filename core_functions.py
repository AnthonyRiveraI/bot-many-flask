import importlib.util
import os
import requests
import logging
from packaging import version
import openai
import time
import json
import re


AIRTABLE_DB_URL = os.getenv('AIRTABLE_DB_URL')
AIRTABLE_API_KEY = f"Bearer {os.getenv('AIRTABLE_API_KEY')}"
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ASSISTANT_ID = os.getenv('ASSISTANT_ID')

if not OPENAI_API_KEY:
    raise ValueError("No OpenAI API key found in environment variables")
client = openai.OpenAI(api_key=OPENAI_API_KEY)

def check_openai_version():
    required_version = version.parse("1.1.1")
    current_version = version.parse(openai.__version__)
    if current_version < required_version:
        raise ValueError(f"Error: OpenAI version {openai.__version__} is less than the required version 1.1.1")
    else:
        logging.info("OpenAI version is compatible.")

def add_thread(thread_id, platform, username):
    url = f"{AIRTABLE_DB_URL}"
    headers = {
        "Authorization": AIRTABLE_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "records": [{
            "fields": {
                "Thread_id": thread_id,
                "Platform": platform,
                "Username": username
            }
        }]
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            print("Thread added to DB successfully.")
        else:
            print(f"Failed to add thread: HTTP Status Code {response.status_code}, Response: {response.text}")
    except Exception as e:
        print(f"An error occurred while adding the thread: {e}")

def process_run_status(thread_id, run_id, client, tool_data):
    start_time = time.time()
    while time.time() - start_time < 8:
        run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
        logging.info(f"Checking run status: {run_status.status}")

        if run_status.status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=thread_id)
            message_content = messages.data[0].content[0].text.value
            logging.info(f"Message content before cleaning: {message_content}")

            message_content = re.sub(r"【.*?†.*?】", '', message_content)
            message_content = re.sub(r'[^\S\r\n]+', ' ', message_content).strip()

            return {"response": message_content, "status": "completed"}

        elif run_status.status == 'requires_action':
            logging.info("Run requires action, handling...")
            for tool_call in run_status.required_action.submit_tool_outputs.tool_calls:
                function_name = tool_call.function.name

                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as e:
                    logging.error(f"JSON decoding failed: {e.msg}. Input: {tool_call.function.arguments}")
                    arguments = {}

                if function_name in tool_data["function_map"]:
                    function_to_call = tool_data["function_map"][function_name]
                    output = function_to_call(arguments)
                    client.beta.threads.runs.submit_tool_outputs(thread_id=thread_id, run_id=run_id, tool_outputs=[{
                        "tool_call_id": tool_call.id,
                        "output": json.dumps(output)
                    }])
                else:
                    logging.warning(f"Function {function_name} not found in tool data.")
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
            spec = importlib.util.spec_from_file_location(module_name, module_path)
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
        raise ValueError("Assistant ID not found in environment variables. Please set ASSISTANT_ID.")
    print("Loaded existing assistant ID from environment variable.")
    return assistant_id
