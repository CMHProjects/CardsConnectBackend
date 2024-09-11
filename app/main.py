import argparse
import serial.tools.list_ports
import serial
import json
from datetime import datetime
import csv
import concurrent.futures
import sqlite3

# Database connection
db_file = 'data/sim_cards.db'  # Adjust as per your database file location
conn = sqlite3.connect(db_file)
cursor = conn.cursor()

# Function to send AT commands to a port and read the response


def send_at_command(port, baud_rate, command, timeout=1.5):
    try:
        with serial.Serial(port, baud_rate, timeout=timeout) as ser:
            ser.write(command)
            response = ser.readall()
        return response
    except serial.SerialException as e:
        print(f"Error communicating with port {port}: {e}")
        return None

# Function to detect available ports


def detect_ports():
    return [port.device for port in serial.tools.list_ports.comports()]


# Function to extract phone number from AT+CUSD response
def extract_phone_number(response):
    try:
        response_str = response.decode('utf-8')
        if 'CUSD:' in response_str:
            parts = response_str.split('"')
            if len(parts) >= 2:
                return parts[1]
    except Exception as e:
        print(f"Error extracting phone number: {e}")
    return None

# Function to extract ICCID from a raw response


def extract_iccid(response):
    try:
        parts = response.split(',')
        if len(parts) >= 3:
            iccid_with_quotes = parts[2]
            iccid = iccid_with_quotes.strip('"')[8:-2]  # Extract ICCID
            cleaned_iccid = ''.join(c for c in iccid if c.isdigit())[:10]

            # Rearrange ICCID 2 by 2
            rearranged_iccid = ''.join(
                cleaned_iccid[i:i+2][::-1] for i in range(0, len(cleaned_iccid), 2))

            return int(rearranged_iccid)  # Return ICCID as integer
    except (IndexError, ValueError) as e:
        print(f"Error parsing ICCID response: {e}")
    except Exception as e:
        print(f"Error rearranging ICCID: {e}")
    return None

# Function to decode an SMS message from a hexadecimal string


def decode_sms(hex_string):
    try:
        bytes_data = bytes.fromhex(hex_string)
        decoded_text = bytes_data.decode('utf-16-be')
        decoded_text = decoded_text.rstrip('\x00')
        decoded_text = decoded_text.replace('\n', '')
        return decoded_text
    except (UnicodeDecodeError, ValueError) as e:
        print(f"Error decoding SMS: {e}")
        return None

# Function to load ICCID and PIN data from a CSV file with semicolon delimiter


def load_iccid_pin_data():
    iccid_pin_data = {}
    try:
        cursor.execute("SELECT iccid, pin FROM sim_cards")
        rows = cursor.fetchall()
        for row in rows:
            iccid = row[0]
            pin = row[1]
            iccid_pin_data[iccid] = pin
    except Exception as e:
        print(f"Error loading ICCID and PIN data from database: {e}")
    return iccid_pin_data


def delete_all_sms(port, baud_rate):
    command = b'AT+CMGD=1,4\r'  # This command deletes all SMS from SIM storage
    response = send_at_command(port, baud_rate, command)
    if response and b'OK' in response:
        print(f"All SMS deleted from SIM on port {port}")
        return True
    else:
        print(f"Failed to delete SMS from SIM on port {port}")
        return False

# Function to count SMS stored in SIM


def count_sms_in_sim(port, baud_rate):
    command = b'AT+CPMS="SM"\r'  # Select SIM storage to read SMS count
    response = send_at_command(port, baud_rate, command)
    try:
        if response:
            response_str = response.decode('utf-8')
            # Parse response like +CPMS: <used>,<total>,<used>,<total>,<used>,<total>
            parts = response_str.split(',')
            used_sms = int(parts[0].split(':')[1].strip())
            total_sms = int(parts[1].strip())
            return used_sms, total_sms
    except (ValueError, IndexError, UnicodeDecodeError) as e:
        print(f"Error parsing SMS count response on port {port}: {e}")
    return None, None

# Function to check and unlock SIM card if needed


def check_and_unlock_sim(port, baud_rate, iccid_pin_data):
    status_response = send_at_command(port, baud_rate, b'AT+CPIN?\r')

    if not status_response:
        print(f"Failed to get SIM status on port {port}")
        return False

    try:
        status_decoded = status_response.decode(
            'utf-8', errors='ignore').strip()
        print(f"SIM status response on port {port}: {status_decoded}")

        if "+CPIN: SIM PIN" in status_decoded:
            iccid_response = send_at_command(
                port, baud_rate, b'AT+CRSM=176,12258,0,0,10\r')

            if iccid_response:
                iccid_decoded = iccid_response.decode(
                    'utf-8', errors='ignore').strip()
                extracted_iccid = extract_iccid(iccid_decoded)

                print(f"ICCID response on port {port}: {iccid_decoded}")
                print(f"Extracted ICCID on port {port}: {extracted_iccid}")

                if extracted_iccid:
                    decoded_iccid = extracted_iccid  # Use extracted ICCID for processing

                    if decoded_iccid in iccid_pin_data:
                        pin = iccid_pin_data[decoded_iccid]
                        unlock_command = f'AT+CPIN="{pin}"\r'.encode('utf-8')
                        unlock_response = send_at_command(
                            port, baud_rate, unlock_command)

                        if unlock_response and b'OK' in unlock_response:
                            print(f"SIM card on port {
                                  port} unlocked successfully.")
                            return True
                        else:
                            print(f"Failed to unlock SIM card on port {port}")
                    else:
                        print(f"No matching ICCID found for {
                              decoded_iccid} on port {port}")
                else:
                    print(f"Failed to extract ICCID on port {port}")
            else:
                print(f"Failed to get ICCID on port {port}")

        elif "+CPIN: READY" in status_decoded:
            return True

        else:
            print(f"Unexpected SIM status on port {port}: {status_decoded}")

    except UnicodeDecodeError as e:
        print(f"Error decoding SIM status response on port {port}: {e}")

    except Exception as e:
        print(f"An error occurred on port {port}: {e}")

    return False

# Function to process a single SIM card
# Function to process a single SIM card
# Send all commands for a full scan, or just "Get SMS" when a specific port is provided


def process_single_sim_card(port, baud_rate, iccid_pin_data, full_scan=True):
    port_data = {"port": port, "timestamp": datetime.now().isoformat(),
                 "responses": {}}

    print(f"Checking SIM card on port {port}...")

    if not check_and_unlock_sim(port, baud_rate, iccid_pin_data):
        print(f"Skipping port {port} due to SIM status issues.")
        return None

    if full_scan:
        # Full scan: Send all commands
        commands = {
            "Check SIM status": b'AT+CPIN?\r',
            "Get IMSI": b'AT+CIMI\r',
            "Set SMS text mode": b'AT+CMGF=1\r',
            "Get SMS": b'AT+CMGL="ALL"\r',
            "Send USSD": b'AT+CUSD=1,"*99#"\r',
            "Set Phonebook Storage to MSISDN": b'AT+CPBS="ON"\r',
            "Get Operator": b'AT+COPS?\r',
            "Get ICCID": b'AT+CRSM=176,12258,0,0,10\r',
        }
    else:
        # Fast scan: Only send "Get SMS" command
        commands = {
            "Get SMS": b'AT+CMGL="ALL"\r'
        }

    # Count SMS if it's a full scan
    if full_scan:
        used_sms, total_sms = count_sms_in_sim(port, baud_rate)
        if used_sms is not None and total_sms is not None:
            port_data["responses"]["SMS Count"] = {
                "used": used_sms, "total": total_sms}

    for desc, command in commands.items():
        print(f"  Sending command: {desc}")
        response = send_at_command(port, baud_rate, command)

        if response:
            print(f"  Received raw response on port {port}: {response}")
            try:
                decoded_response = response.decode(
                    'utf-8').strip().replace('\r\nOK', '')
                decoded_response = decoded_response.rstrip(
                    '\r\n')  # Remove trailing \r\n

                if desc == "Get SMS":
                    sms_texts = []
                    sms_messages = decoded_response.split('+CMGL:')
                    for sms in sms_messages[1:]:
                        lines = sms.split('\r\n')
                        if len(lines) >= 2:
                            sms_info = lines[0].split(',')
                            sender = sms_info[2].replace(
                                '"', '') if len(sms_info) > 2 else ''
                            timestamp = sms_info[4].replace(
                                '"', '') if len(sms_info) > 4 else ''
                            sms_content = lines[1].strip()
                            decoded_sms = decode_sms(sms_content)
                            if decoded_sms is None:
                                decoded_sms = sms_content
                            sms_texts.append({
                                "sender": sender,
                                "timestamp": timestamp,
                                "message": decoded_sms
                            })
                        else:
                            print(f"Invalid SMS format on port {port}: {sms}")
                    port_data["responses"][desc] = sms_texts

                else:
                    port_data["responses"][desc] = decoded_response.split('\r\n')[
                        0]

                if desc == "Get ICCID":
                    extracted_iccid = extract_iccid(decoded_response)
                    if extracted_iccid:
                        port_data["responses"]["ICCID"] = extracted_iccid

                if desc == "Send USSD" and "CUSD:" in decoded_response:
                    phone_number = extract_phone_number(response)
                    if phone_number:
                        port_data["responses"]["Phone Number (USSD)"] = phone_number

                if desc == "Get Phone Number" and "+CNUM:" in decoded_response:
                    lines = decoded_response.split('\r\n')
                    for line in lines:
                        if line.startswith("+CNUM:"):
                            parts = line.split(',')
                            if len(parts) >= 2:
                                phone_number = parts[1].replace('"', '')
                                port_data["responses"][desc] = phone_number

                if desc == "Get Operator" and "+COPS:" in decoded_response:
                    operator_code = decoded_response.split(
                        ',')[2].replace('"', '')
                    port_data["responses"][desc] = operator_code

                if desc == "Set Phonebook Storage to MSISDN" and "+CUSD:" in decoded_response:
                    parts = decoded_response.split('"')
                    if len(parts) >= 2 and parts[1].startswith('MSISDN:'):
                        msisdn = parts[1].split(':')[1].strip()
                        port_data["responses"]["MSISDN"] = msisdn

            except UnicodeDecodeError as e:
                hex_response = response.hex()
                port_data["responses"][desc] = hex_response
                print(f"  Could not decode response on port {
                      port}. Hex: {hex_response}. Error: {e}")
            except IndexError as e:
                print(f"  Error processing response on port {
                      port}: IndexError - {e}")
        else:
            port_data["responses"][desc] = None
            print(f"  No response received on port {port}")

    if "Set Phonebook Storage to MSISDN" in port_data["responses"]:
        del port_data["responses"]["Set Phonebook Storage to MSISDN"]
    if "Get ICCID" in port_data["responses"]:
        del port_data["responses"]["Get ICCID"]
    if "Send USSD" in port_data["responses"]:
        del port_data["responses"]["Send USSD"]

    return port_data

# Main function to process SIM cards, with the option for a full scan or fast scan (just SMS) on a specific port


def process_sim_cards(port=None, delete_sms=False):
    baud_rate = 115200
    active_ports = detect_ports()
    iccid_pin_data = load_iccid_pin_data()
    data = []

    # If a specific port is provided, do a fast scan; otherwise, do a full scan
    full_scan = not port

    if port:
        active_ports = [port]  # Process only the specified port if provided

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {executor.submit(process_single_sim_card, port, baud_rate,
                                   iccid_pin_data, full_scan): port for port in active_ports}
        for future in concurrent.futures.as_completed(futures):
            port_data = future.result()
            if port_data:
                data.append(port_data)

            if delete_sms:
                delete_all_sms(port, baud_rate)

    output_file = 'sim_data.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    print(f"Data saved to {output_file}")

# Function to parse command-line arguments


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Process SIM cards on specified port')
    parser.add_argument('--port', type=str, help='Specify a port to process')
    parser.add_argument('--delete-sms', action='store_true',
                        help='Delete all SMS messages from SIM storage')
    return parser.parse_args()


# Execute the main function with optional port argument
if __name__ == "__main__":
    args = parse_arguments()
    if args.port:
        process_sim_cards(port=args.port, delete_sms=args.delete_sms)
    else:
        process_sim_cards()
