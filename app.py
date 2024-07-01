from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import requests
import json
import time
import os
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

app = Flask(__name__)
socketio = SocketIO(app)

usd_xml_api_url = "http://api.nbp.pl/api/exchangerates/rates/c/usd/?format=xml"
btc_json_api_url = "https://min-api.cryptocompare.com/data/generateAvg?fsym=BTC&tsym=USD&e=coinbase"
usd_output_file = "usd-currency.xml"
btc_output_file = "btc-currency.json"

# Infinite loop to continuously fetch and save data
btc_interval = 5

# Zmienna do śledzenia ostatniego czasu pobrania danych USD
last_usd_fetch_time = None

btc_prices = None
usd_rate = None


def fetch_and_save_btc_data(api_url, output_file):
    global btc_prices
    try:
        # Call API and get data
        response = requests.get(api_url)
        data = response.json()

        # Get only the "RAW" section
        raw_data = data.get("RAW")
        btc_data = raw_data['PRICE']
        if raw_data:
            current_time =  datetime.now()
            formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S")
            new_entry = {"timestamp": formatted_time, "data": raw_data}

            # If file exists, read existing data
            if os.path.exists(output_file):
                with open(output_file, 'r') as file:
                    existing_data = json.load(file)
            else:
                existing_data = []

            # Append new data
            existing_data.append(new_entry)

            # Keep only the latest 25 entries
            existing_data = existing_data[-25:]

            # Write updated data back to the file
            with open(output_file, 'w') as file:
                json.dump(existing_data, file, indent=4)
                print(f"Data has been saved to {output_file}.")

                # Extract timestamps and prices separately
                btc_timestamps = [entry["timestamp"] for entry in existing_data]
                btc_prices = [entry["data"]["PRICE"] for entry in existing_data]

                # Send both timestamps and prices to the client
                socketio.emit('btc_update', {'timestamps': btc_timestamps, 'prices': btc_prices})
        else:
            print("RAW section not found in the data.")

    except requests.exceptions.RequestException as e:
        # If there was an error during the API call, display the error message
        print(f"Error: {e}")
    except Exception as ex:
        # If another error occurred, display a general error message
        print(f"An error occurred: {ex}")


def fetch_and_save_usd_data(url, output_file):
    """
    Pobiera plik XML z podanego URL i dopisuje go do lokalnego pliku, jeśli istnieje.
    Jeśli plik nie istnieje, tworzy nowy plik.

    :param url: URL API, z którego pobierany jest plik XML
    :param output_file: Ścieżka do pliku, w którym zostanie zapisany pobrany XML
    """

    global usd_rate
    try:
        # Wysyłanie żądania GET do API
        response = requests.get(url)
        # Sprawdzenie, czy żądanie się powiodło
        response.raise_for_status()

        # Parsowanie odpowiedzi XML
        new_tree = ET.ElementTree(ET.fromstring(response.content))
        new_root = new_tree.getroot()

        if os.path.exists(output_file):
            # Jeśli plik istnieje, załaduj istniejący XML
            existing_tree = ET.parse(output_file)
            existing_root = existing_tree.getroot()

            # Dopisanie nowego XML do istniejącego
            for elem in new_root:
                existing_root.append(elem)

                # Ograniczenie liczby wpisów do 5
                entries_to_keep = existing_root.findall('.//Rate')[-5:]
                existing_root.clear()
                for entry in entries_to_keep:
                    existing_root.append(entry)

            # Zapisanie zaktualizowanego drzewa XML do pliku
            existing_tree.write(output_file, encoding='utf-8', xml_declaration=True)

            usd_rate = float(new_root.find('.//Rate/Bid').text)
            socketio.emit('usd_update', {'rate': usd_rate})
        else:
            # Jeśli plik nie istnieje, zapisz nowy plik XML
            new_tree.write(output_file, encoding='utf-8', xml_declaration=True)

        print(f"XML dopisany/zapisany do pliku: {output_file}")




    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
    except requests.exceptions.RequestException as req_err:
        print(f"Request error occurred: {req_err}")
    except ET.ParseError as parse_err:
        print(f"XML parsing error occurred: {parse_err}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


# Background process to update data periodically
def background_task():
    global btc_data, last_usd_fetch_time, usd_rate
    while True:
        # Fetch BTC data every 5 seconds
        fetch_and_save_btc_data(btc_json_api_url, btc_output_file)
        time.sleep(btc_interval)

        # Fetch USD data once a day
        current_time = datetime.now()
        if last_usd_fetch_time is None or (current_time - last_usd_fetch_time) >= timedelta(days=1):
            fetch_and_save_usd_data(usd_xml_api_url, usd_output_file)
            last_usd_fetch_time = current_time

# Start background task in a thread
import threading
thread = threading.Thread(target=background_task)
thread.daemon = True
thread.start()

@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    global btc_prices, usd_rate
    if btc_prices:
        emit('btc_update', {'prices': btc_prices})
    if usd_rate:
        emit('usd_update', {'rate': usd_rate})

if __name__ == '__main__':
    socketio.run(app, debug=True)