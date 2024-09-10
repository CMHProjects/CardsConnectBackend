from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3
import os
import json
import subprocess
import time

app = Flask(__name__)
CORS(app)

json_file = 'sim_data.json'
main_script = 'app/main.py'
db_file = 'data/sim_cards.db'

# Ensure the database table exists
def initialize_database():
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sim_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                iccid INTEGER UNIQUE,
                pin TEXT
            )
        ''')
        conn.commit()
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
    finally:
        if conn:
            conn.close()

initialize_database()

def is_json_empty_or_not_exist():
    return not os.path.exists(json_file) or os.stat(json_file).st_size == 0

def load_json_data():
    if is_json_empty_or_not_exist():
        return []
    with open(json_file, 'r') as f:
        return json.load(f)

def save_json_data(data):
    with open(json_file, 'w') as f:
        json.dump(data, f, indent=4)

def load_iccid_pin_data():
    """Load ICCID and PIN data dynamically from the database."""
    iccid_pin_data = {}
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT iccid, pin FROM sim_cards")
        rows = cursor.fetchall()
        for row in rows:
            iccid = str(row[0])  # ICCID is stored as a string
            pin = row[1]
            iccid_pin_data[iccid] = pin
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
    finally:
        if conn:
            conn.close()
    
    return iccid_pin_data

@app.route('/api/run_main_and_get_data')
def run_main_and_get_data():
    """Run the main script and fetch SIM data dynamically."""
    # Fetch fresh ICCID and PIN data from the database
    iccid_pin_data = load_iccid_pin_data()
    
    # Call the main script, which uses the ICCID and PIN data
    if is_json_empty_or_not_exist():
        try:
            subprocess.run(['python', main_script], check=True)
        except subprocess.CalledProcessError as e:
            return jsonify({'error': f'Error running {main_script}: {e}'}), 500
        while is_json_empty_or_not_exist():
            print(f"Waiting for {json_file} to be populated...")
            time.sleep(1)
    
    sim_data = load_json_data()

    # Unlock SIMs using the freshly loaded ICCID and PIN data
    for sim in sim_data:
        port = sim.get('port')
        # Assuming you have the logic to process the sim and unlock it using the ICCID and PIN
        if port and port in iccid_pin_data:
            # Example unlock logic: Replace with actual function to unlock SIM
            print(f"Unlocking SIM on port {port} with ICCID {sim['iccid']} using PIN.")
            # unlock_sim(port, iccid_pin_data[sim['iccid']])

    return jsonify(sim_data)

@app.route('/api/reset_data', methods=['POST'])
def reset_data():
    if os.path.exists(json_file):
        os.remove(json_file)
    return jsonify({'message': 'Data reset successfully.'})

@app.route('/api/delete_sms', methods=['POST'])
def delete_sms():
    data = request.get_json()
    port = data.get('port')
    if not port:
        return jsonify({'error': 'Port not specified'}), 400
    try:
        # Ensure --delete-sms is passed correctly
        result = subprocess.run(
            ['python', main_script, '--port', port, '--delete-sms'],
            capture_output=True, text=True, check=True
        )
        return jsonify({'message': f'All SMS deleted on port {port}.'})
    except subprocess.CalledProcessError as e:
        return jsonify({'error': f'Error deleting SMS on port {port}: {e.stderr}'}), 500

@app.route('/api/sms_count', methods=['POST'])
def get_sms_count():
    data = request.get_json()
    port = data.get('port')
    if not port:
        return jsonify({'error': 'Port not specified'}), 400
    try:
        result = subprocess.run(
            ['python', main_script, '--port', port, '--count-sms'],
            capture_output=True, text=True, check=True
        )
        response = json.loads(result.stdout.strip())
        return jsonify(response)
    except json.JSONDecodeError:
        return jsonify({'error': 'Failed to decode the SMS count response as JSON.'}), 500
    except subprocess.CalledProcessError as e:
        return jsonify({'error': f'Error getting SMS count for port {port}: {e.stderr}'}), 500

@app.route('/api/get_last_sms', methods=['POST'])
def get_last_sms():
    data = request.get_json()
    port = data.get('port')
    sim_data = load_json_data()
    try:
        # Run only for a specific port
        subprocess.run(['python', main_script, '--port', port], check=True)
    except subprocess.CalledProcessError as e:
        return jsonify({'error': f'Error running {main_script} for port {port}: {e}'}), 500
    updated_data = load_json_data()
    updated_port_data = next((item for item in updated_data if item['port'] == port), None)
    if updated_port_data:
        existing_port_data_index = next((index for (index, d) in enumerate(sim_data) if d['port'] == port), None)
        if existing_port_data_index is not None:
            sim_data[existing_port_data_index] = updated_port_data
        else:
            sim_data.append(updated_port_data)
    save_json_data(sim_data)
    if updated_port_data:
        return jsonify(updated_port_data)
    return jsonify({'message': 'No data found for this port.'})

@app.route('/api/add_sim', methods=['POST'])
def add_sim():
    data = request.get_json()
    iccid = data.get('iccid')
    pin = data.get('pin')
    if not iccid or not pin:
        return jsonify({'error': 'ICCID and PIN are required'}), 400
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO sim_cards (iccid, pin) VALUES (?, ?)', (iccid, pin))
        conn.commit()
        return jsonify({'message': 'SIM card added successfully.'})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'ICCID already exists'}), 400
    except sqlite3.Error as e:
        return jsonify({'error': f'SQLite error: {e}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/bulk_add_sim', methods=['POST'])
def bulk_add_sim():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if not file.filename.endswith(('.csv', '.xlsx')):
        return jsonify({'error': 'Invalid file format'}), 400
    
    try:
        import pandas as pd
        import sqlite3
        
        # Detect CSV or XLSX and process accordingly
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file, delimiter=';')
        elif file.filename.endswith('.xlsx'):
            df = pd.read_excel(file)
        
        # Connect to the SQLite database
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        for _, row in df.iterrows():
            try:
                # Ensure ICCID and PIN are valid integers
                iccid = int(row['ICCID'])
                pin = int(row['PIN'])
                
                # Insert SIM card data into the database
                cursor.execute('INSERT OR IGNORE INTO sim_cards (iccid, pin) VALUES (?, ?)', (iccid, pin))
            except ValueError:
                # Handle non-numeric values for ICCID or PIN
                return jsonify({'error': f'Invalid ICCID or PIN value at row {_ + 1}'}), 400
        
        # Commit the transaction
        conn.commit()
        
        return jsonify({'message': 'Bulk SIM cards added successfully.'})
    
    except Exception as e:
        return jsonify({'error': f'Error processing file: {str(e)}'}), 500
    
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    app.run(debug=True)
