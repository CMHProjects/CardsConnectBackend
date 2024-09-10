import csv
import sqlite3

def load_csv_to_database(csv_file, db_file):
    conn = None
    try:
        # Connect to SQLite 
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        # Create table if not exists
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sim_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                iccid INTEGER UNIQUE,
                pin TEXT
            )
        ''')
        conn.commit()

        # Load current ICCID data from database
        existing_iccids = set()
        cursor.execute('SELECT iccid FROM sim_cards')
        rows = cursor.fetchall()
        for row in rows:
            existing_iccids.add(row[0])

        # Read CSV file and insert new data into db
        with open(csv_file, 'r', newline='') as file:
            reader = csv.reader(file, delimiter=';')
            next(reader)  # Skip header if exists
            for row in reader:
                ICCID = int(row[0])
                PIN = row[1]
                if ICCID not in existing_iccids:
                    cursor.execute('INSERT OR IGNORE INTO sim_cards (iccid, pin) VALUES (?, ?)', (ICCID, PIN))
        
        conn.commit()
        print(f"Data successfully loaded from {csv_file} to {db_file} database.")

    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    csv_file = 'data/sim_cards.csv'
    db_file = 'data/sim_cards.db' 

    load_csv_to_database(csv_file, db_file)
