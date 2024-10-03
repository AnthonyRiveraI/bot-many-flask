import gspread
from google.oauth2.service_account import Credentials
import os
import logging

# Configuración de la herramienta
tool_config = {
    "type": "function",
    "function": {
        "name": "get_data_info",
        "description": "Obtains information based on specified criteria from Google Sheets.",
        "parameters": {
            "type": "object",
            "properties": {
                "sheet_name": {
                    "type": "string",
                    "description": "The name of the sheet to query."
                },
                "query_type": {
                    "type": "string",
                    "description": "The type of query (e.g., 'specific', 'min', 'max', 'range', 'recommend')."
                },
                "item_name": {
                    "type": "string",
                    "description": "The name of the item to query. Required for 'specific' query type.",
                    "default": ""
                },
                "attribute": {
                    "type": "string",
                    "description": "The specific attribute to retrieve (e.g., 'price', 'quantity'). Required for all query types."
                },
                "min_value": {
                    "type": "number",
                    "description": "The minimum value range for 'range' and 'recommend' query types.",
                    "default": 0
                },
                "max_value": {
                    "type": "number",
                    "description": "The maximum value range for 'range' and 'recommend' query types.",
                    "default": 0
                }
            },
            "required": ["sheet_name", "query_type", "attribute"]
        }
    }
}

# La función de devolución de llamada
def get_data_info(arguments):
    """
    Obtains information based on specified criteria from Google Sheets.
    :param arguments: dict, Contains the type of query (query_type), the name of the item (item_name), and the specific attribute (attribute).
    :return: dict or str, Requested information or error message.
    """
    sheet_name = arguments.get('sheet_name')
    query_type = arguments.get('query_type')
    item_name = arguments.get('item_name', "").strip().lower()
    attribute = arguments.get('attribute').strip().lower()
    min_value = arguments.get('min_value', 0)
    max_value = arguments.get('max_value', float('inf'))

    # Ruta del archivo de credenciales
    credentials_path = "key.json"

    # Verificar que el archivo de credenciales existe
    if not os.path.exists(credentials_path):
        return f"Error: Credentials file not found at {credentials_path}"

    try:
        # Configuración de las credenciales y el cliente de Google Sheets
        logging.info("Configuring credentials")
        creds = Credentials.from_service_account_file(credentials_path, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        client = gspread.authorize(creds)
        logging.info("Credentials configured successfully")

        # Abrir la hoja de cálculo especificada
        spreadsheet = client.open_by_key("YOUR_SPREADSHEET_ID")
        sheet = spreadsheet.worksheet(sheet_name)
        logging.info(f"Spreadsheet '{sheet_name}' opened successfully")

        # Obtener todos los registros
        records = sheet.get_all_records()
        logging.info(f"Retrieved {len(records)} records from the sheet")

        if not records:
            return "Error: No data found in the sheet."

        # Debug: Listar las columnas disponibles
        columns = records[0].keys()
        logging.info(f"Available columns: {columns}")

        if attribute not in columns:
            return f"Attribute {attribute} not found in the sheet. Available attributes: {list(columns)}"

        # Manejo de diferentes tipos de consulta
        if query_type == 'specific':
            if not item_name:
                return "Error: item_name is required for 'specific' query type."
            item_info = next((record for record in records if item_name in record['ItemName'].lower()), None)
            if not item_info:
                return f"No item found with the name {item_name}."
            return {attribute: item_info[attribute]}

        elif query_type in ['min', 'max']:
            valid_records = []
            for record in records:
                try:
                    value = float(str(record.get(attribute, "")).replace(',', '').replace('.', ''))
                    valid_records.append((record['ItemName'], value))
                except ValueError:
                    continue

            if not valid_records:
                return f"No valid records found for attribute {attribute}"

            if query_type == 'min':
                min_item = min(valid_records, key=lambda x: x[1])
                return {f"item_with_min_{attribute}": min_item[0], attribute: min_item[1]}

            if query_type == 'max':
                max_item = max(valid_records, key=lambda x: x[1])
                return {f"item_with_max_{attribute}": max_item[0], attribute: max_item[1]}

        elif query_type == 'range':
            range_records = [record for record in records if min_value <= float(str(record.get(attribute, 0)).replace(',', '').replace('.', '')) <= max_value]
            if not range_records:
                return f"No items found in the {attribute} range {min_value} to {max_value}."
            return {"items_in_range": [{record['ItemName']: record[attribute]} for record in range_records]}

        elif query_type == 'recommend':
            recommend_records = [record for record in records if min_value <= float(str(record.get(attribute, 0)).replace(',', '').replace('.', '')) <= max_value]
            if not recommend_records:
                return f"No items found in the {attribute} range {min_value} to {max_value}."
            recommend_records.sort(key=lambda x: float(str(x.get(attribute, 0)).replace(',', '').replace('.', '')), reverse=True)
            return {"recommended_items": [{record['ItemName']: record[attribute]} for record in recommend_records]}

        else:
            return f"Invalid query_type: {query_type}. Allowed values are 'specific', 'min', 'max', 'range', 'recommend'."

    except gspread.exceptions.GSpreadException as gs_ex:
        logging.error(f"GSpread error: {gs_ex}")
        return f"GSpread error: {gs_ex}"
    except Exception as e:
        logging.error(f"Failed to retrieve data information: {e}")
        return f"Failed to retrieve data information: {e}"

# Asegúrate de incluir este script en tu directorio `tools`
