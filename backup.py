from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit
import sqlite3
import re
from datetime import datetime
import logging

app = Flask(__name__)
app.secret_key = 'your_secret_key'
socketio = SocketIO(app)

# Initialize SQLite database
def init_db():
    with sqlite3.connect('messages.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_type TEXT,
                trans_id TEXT,
                trans_time TEXT,
                trans_amount REAL,
                business_short_code TEXT,
                bill_ref_number TEXT,
                invoice_number TEXT,
                org_account_balance TEXT,
                third_party_trans_id TEXT,
                msisdn TEXT,
                first_name TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                sender TEXT,
                content TEXT,
                timestamp TEXT,
                checked INTEGER DEFAULT 0,
                checked_by TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE,
                password TEXT,
                role TEXT
            )
        ''')
        conn.commit()

init_db()

# Function to save transaction data
def save_transaction_data(data):
    conn = sqlite3.connect('messages.db')
    cursor = conn.cursor()
    
    # Insert into transactions table
    cursor.execute('''
        INSERT INTO transactions (
            transaction_type, trans_id, trans_time, trans_amount, 
            business_short_code, bill_ref_number, invoice_number,
            org_account_balance, third_party_trans_id, msisdn,
            first_name
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data["TransactionType"], data["TransID"], data["TransTime"], float(data["TransAmount"]),
        data["BusinessShortCode"], data["BillRefNumber"], data["InvoiceNumber"],
        data["OrgAccountBalance"], data["ThirdPartyTransID"], data["MSISDN"],
        data["FirstName"]
    ))
    conn.commit()
    
    # Construct message for messages table
    message = (
        f"Transaction ID: {data['TransID']}\n"
        f"Transaction Time: {data['TransTime']}\n"
        f"Transaction Amount: {data['TransAmount']}\n"
        f"MSISDN: {data['MSISDN']}\n"
        f"First Name: {data['FirstName']}\n"
        f"Bill Reference Number: {data['BillRefNumber']}"
    )

    # Insert into messages table
    cursor.execute('INSERT INTO messages (sender, content, timestamp) VALUES (?, ?, ?)', ("MPESA", message, data['TransTime']))
    conn.commit()

    conn.close()

@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    role = session.get('role', 'user')
    return render_template('index.html', role=role)

@app.route('/checked_messages')
def checked_messages():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('checked_messages.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        with sqlite3.connect('messages.db') as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password))
            user = cursor.fetchone()

        if user:
            session['username'] = username
            session['role'] = user[2]
            return redirect(url_for('index'))
        else:
            return "Invalid credentials"

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('role', None)
    return redirect(url_for('login'))

@app.route('/messages_from_MPESA')
def messages_from_MPESA():
    if 'username' not in session:
        return jsonify({'status': 'failure', 'reason': 'Unauthorized'}), 401

    username = session['username'].upper()  # Assuming the username should be uppercase in the BillRefNumber
    role = session['role']

    with sqlite3.connect('messages.db') as conn:
        cursor = conn.cursor()
        if role == 'admin':
            cursor.execute('SELECT sender, content, timestamp, id FROM messages WHERE sender = "MPESA" AND checked = 0')
        else:
            cursor.execute('SELECT sender, content, timestamp, id FROM messages WHERE sender = "MPESA" AND checked = 0 AND content LIKE ?', (f'%{username}%',))
        messages = cursor.fetchall()

    return jsonify(messages)

@app.route('/search_messages')
def search_messages():
    if 'username' not in session:
        return jsonify({'status': 'failure', 'reason': 'Unauthorized'}), 401

    query = request.args.get('query', '').lower()
    checked = request.args.get('checked', 'false') == 'true'
    username = session['username'].upper()
    role = session['role']

    pattern = r'Ksh(\d+\.\d{2})'
    total_amount = 0
    messages = []

    with sqlite3.connect('messages.db') as conn:
        cursor = conn.cursor()
        if checked:
            if role == 'admin':
                cursor.execute('''
                    SELECT sender, content, timestamp, checked_by, id
                    FROM messages
                    WHERE sender = "MPESA" AND checked = 1 AND LOWER(checked_by) LIKE ?
                ''', ('%' + query + '%',))
            else:
                return jsonify({'status': 'failure', 'reason': 'Unauthorized'}), 403
        else:
            if role == 'admin':
                cursor.execute('''
                    SELECT sender, content, timestamp, id
                    FROM messages
                    WHERE sender = "MPESA" AND checked = 0 AND (LOWER(sender) LIKE ? OR LOWER(content) LIKE ?)
                ''', ('%' + query + '%', '%' + query + '%'))
            else:
                cursor.execute('''
                    SELECT sender, content, timestamp, id
                    FROM messages
                    WHERE sender = "MPESA" AND checked = 0 AND (LOWER(sender) LIKE ? OR LOWER(content) LIKE ?) AND content LIKE ?
                ''', ('%' + query + '%', '%' + query + '%', f'%{username}%'))
            rows = cursor.fetchall()

            for row in rows:
                messages.append(row)
                match = re.search(pattern, row[1])
                if match:
                    amount = float(match.group(1))
                    total_amount += amount

    return jsonify({'results': messages, 'total_amount': total_amount})

@app.route('/check_message', methods=['POST'])
def check_message():
    if 'username' not in session:
        return jsonify({'status': 'failure', 'reason': 'Unauthorized'}), 401

    data = request.get_json()
    message_id = data['id']
    username = session['username']
    
    pattern = r'Ksh(\d+\.\d{2})'

    with sqlite3.connect('messages.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE messages
            SET checked = 1, checked_by = ?
            WHERE id = ?
        ''', (username, message_id))
        conn.commit()

        cursor.execute('''
            SELECT content
            FROM messages
            WHERE id = ?
        ''', (message_id,))
        content = cursor.fetchone()[0]

        match = re.search(pattern, content)
        if match:
            amount = float(match.group(1))
        else:
            amount = 0

        cursor.execute('''
            SELECT SUM(CAST(SUBSTR(content, INSTR(content, 'Ksh') + 3, INSTR(SUBSTR(content, INSTR(content, 'Ksh') + 3), ' ')) AS FLOAT))
            FROM messages
            WHERE checked_by = ? AND checked = 1
        ''', (username,))
        total_checked_amount = cursor.fetchone()[0] or 0

    return jsonify({'status': 'success', 'total_checked_amount': total_checked_amount}), 200


@app.route('/checked_messages_by_user')
def checked_messages_by_user():
    if 'username' not in session:
        return jsonify({'status': 'failure', 'reason': 'Unauthorized'}), 401

    checked_by = request.args.get('checked_by', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    query = '''
        SELECT sender, content, timestamp, checked_by, id
        FROM messages
        WHERE sender = "MPESA" AND checked = 1 AND checked_by = ?
    '''
    
    params = [checked_by]

    if start_date and end_date:
        query += ' AND timestamp BETWEEN ? AND ?'
        params.extend([start_date, end_date])
    elif start_date:
        query += ' AND timestamp >= ?'
        params.append(start_date)
    elif end_date:
        query += ' AND timestamp <= ?'
        params.append(end_date)

    with sqlite3.connect('messages.db') as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        messages = cursor.fetchall()

    total_amount = 0.0
    for message in messages:
        match = re.search(r'Ksh\s?([\d,]+\.\d{2})', message[1])
        if match:
            amount = float(match.group(1).replace(',', ''))
            total_amount += amount

    return jsonify({'messages': messages, 'total_amount': total_amount})




@app.route('/uncheck_message', methods=['POST'])
def uncheck_message():
    if 'username' not in session:
        return jsonify({'status': 'failure', 'reason': 'Unauthorized'}), 401

    data = request.get_json()
    message_id = data['id']
    
    with sqlite3.connect('messages.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE messages
            SET checked = 0, checked_by = NULL
            WHERE id = ?
        ''', (message_id,))
        conn.commit()

    return jsonify({'status': 'success'})



@app.route('/transactions', methods=['POST'])
def transaction():
    data = request.json

    logging.info(f"Received transaction data: {data}")

    try:
        required_fields = [
            "TransactionType", "TransID", "TransTime", "TransAmount", "BusinessShortCode",
            "BillRefNumber", "InvoiceNumber", "OrgAccountBalance", "ThirdPartyTransID",
            "MSISDN", "FirstName"
        ]

        for field in required_fields:
            if field not in data:
                logging.error(f"Missing field: {field}")
                return jsonify({'status': 'failure', 'reason': f'Missing field: {field}'}), 400

        save_transaction_data(data)
        logging.info("Transaction data saved successfully")
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        logging.error(f"Error processing transaction: {e}")
        return jsonify({'status': 'failure', 'reason': 'Internal Server Error'}), 500

@app.route('/list_transactions', methods=['GET'])
def list_transactions():
    if 'username' not in session:
        return jsonify({'status': 'failure', 'reason': 'Unauthorized'}), 401

    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    query = 'SELECT * FROM transactions WHERE 1=1'
    params = []

    if start_date:
        query += ' AND trans_time >= ?'
        params.append(start_date)
    if end_date:
        query += ' AND trans_time <= ?'
        params.append(end_date)

    with sqlite3.connect('messages.db') as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        transactions = cursor.fetchall()

    return jsonify(transactions)

@app.route('/delete_transaction', methods=['POST'])
def delete_transaction():
    if 'username' not in session:
        return jsonify({'status': 'failure', 'reason': 'Unauthorized'}), 401

    data = request.get_json()
    trans_id = data['trans_id']

    with sqlite3.connect('messages.db') as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM transactions WHERE trans_id = ?', (trans_id,))
        conn.commit()

    return jsonify({'status': 'success'}), 200



@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@socketio.on('new_message')
def handle_new_message(data):
    print('New message received:', data)
    save_transaction_data(data)
    emit('update_messages', broadcast=True)

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    socketio.run(app, host='0.0.0.0', port=5000)
