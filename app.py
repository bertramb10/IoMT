from flask import Flask, request, redirect, url_for, session, render_template, flash, current_app
from flask_mysqldb import MySQL
from flask_bcrypt import Bcrypt
from cryptography.fernet import Fernet
import dotenv
import os
import MySQLdb.cursors
from functools import wraps
from datetime import datetime, timedelta
import time
import ssl
import paho.mqtt.client as mqtt
import json
import matplotlib.pyplot as plt
import io
import base64
import logging
import threading

dotenv.load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_APP_KEY")
bcrypt = Bcrypt(app)

# konfigurer logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# MySQL konfig
app.config["MYSQL_HOST"] = os.getenv("MYSQL_HOST")
app.config["MYSQL_USER"] = os.getenv("MYSQL_USER")
app.config["MYSQL_PASSWORD"] = os.getenv("MYSQL_PASSWORD")
app.config["MYSQL_DB"] = os.getenv("MYSQL_DB")
mysql = MySQL(app)

# encryption key
encryption_key = os.getenv("ENCRYPTION_KEY").encode()
cipher = Fernet(encryption_key)

# MQTT Subscriber Setup
MQTT_BROKER = "localhost"  # Since it's running on the same Raspberry Pi
MQTT_TOPIC = "heart_data" 

# require login
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'loggedin' not in session:
            flash('Please log in to access this page.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# MQTT Callback Funktioner
def on_connect(client, userdata, flags, rc):
    logger.info(f"Connected with result code {rc}")
    # Subscribe ttil beggetopics
    client.subscribe([("heart_data", 0), ("mpu_data", 0)])  

def on_message(client, userdata, msg):
    # brug app context til database håndtering
    with app.app_context():
        try:
            # afkod modtaget besked
            message = msg.payload.decode('utf-8')
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            logger.info(f"Raw MQTT Message Received: {message}")

            # besked på heart topic?
            if msg.topic == "heart_data":
                # gem data
                try:
                    filtered_red, filtered_ir = map(float, message.split(','))
                    logger.info(f"Heart data received: {filtered_red}, {filtered_ir}")
                except Exception as e:
                    logger.error(f"Error processing heart data: {e}")
            
            # besked fra mpu?
            elif msg.topic == "mpu_data":
                # gem data
                logger.info(f"MPU data received: {message}")
                

        except Exception as general_error:
            logger.error(f"General MQTT Message Processing Error: {general_error}")

# MQTT klient setup
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

def parse_sensor_data(message):
    """
    sæt sensordata in i dette format
    Expected format: "Accelerometer: X=value, Y=value, Z=value | Gyroscope: X=value, Y=value, Z=value"
    """
    try:
        # Split accelerometer and gyroscope data
        accel_part, gyro_part = message.split(' | ')
        
        # accelerometer values
        accel_x = float(accel_part.split('X=')[1].split(',')[0])
        accel_y = float(accel_part.split('Y=')[1].split(',')[0])
        accel_z = float(accel_part.split('Z=')[1])
        
        #gyroscope values
        gyro_x = float(gyro_part.split('X=')[1].split(',')[0])
        gyro_y = float(gyro_part.split('Y=')[1].split(',')[0])
        gyro_z = float(gyro_part.split('Z=')[1])
        
        return {
            'accelerometer': {'x': accel_x, 'y': accel_y, 'z': accel_z},
            'gyroscope': {'x': gyro_x, 'y': gyro_y, 'z': gyro_z}
        }
    except Exception as e:
        logger.error(f"Error parsing sensor data: {e}")
        return None

def create_graphs():
    # Matplotlib config
    import matplotlib
    matplotlib.use('Agg')
    matplotlib.pyplot.ioff()

    # tag seneste mplinger
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(
        "SELECT encrypted_gyro_data FROM gyroscope_data ORDER BY event_time DESC LIMIT 5"
    )
    db_gyro_data = cursor.fetchall()
    
    # opsæt data til grafer
    gyro_x_data = []
    gyro_y_data = []
    gyro_z_data = []
    timestamps = []

    for entry in db_gyro_data:
        try:
            # afkod data
            decrypted_data = cipher.decrypt(entry['encrypted_gyro_data']).decode()
            parsed_data = parse_sensor_data(decrypted_data)
            
            if parsed_data:
                gyro_x_data.append(parsed_data['gyroscope']['x'])
                gyro_y_data.append(parsed_data['gyroscope']['y'])
                gyro_z_data.append(parsed_data['gyroscope']['z'])
                timestamps.append(len(timestamps) + 1)  
        except Exception as e:
            logger.error(f"Error processing graph data: {e}")

    # gyroskop data grafen
    plt.figure(figsize=(10, 6))
    plt.plot(timestamps, gyro_x_data, label="GyroX", marker='o', color="red")
    plt.plot(timestamps, gyro_y_data, label="GyroY", marker='o', color="green")
    plt.plot(timestamps, gyro_z_data, label="GyroZ", marker='o', color="blue")
    plt.xlabel('Measurement Sequence')
    plt.ylabel('Gyroscope Data')
    plt.title('Gyroscope Data Over Time')
    plt.legend()
    plt.grid(True)
    
    gyro_buffer = io.BytesIO()
    plt.savefig(gyro_buffer, format='png')
    gyro_buffer.seek(0)
    gyro_image = base64.b64encode(gyro_buffer.getvalue()).decode('utf-8')
    plt.close()

    # hjerte grafen
    plt.figure(figsize=(10, 6))
    plt.plot([1, 2, 3, 4, 5], [70, 75, 80, 85, 90], label="Heart Rate", marker='o', color="purple")
    plt.xlabel('Measurement Sequence')
    plt.ylabel('Heart Rate (BPM)')
    plt.title('Heart Rate Over Time')
    plt.legend()
    plt.grid(True)
    
    heart_buffer = io.BytesIO()
    plt.savefig(heart_buffer, format='png')
    heart_buffer.seek(0)
    heart_image = base64.b64encode(heart_buffer.getvalue()).decode('utf-8')
    plt.close()

    return gyro_image, heart_image

def log_alarm(user_id, sensor_type, alarm_type, threshold):
    try:
        cursor = mysql.connection.cursor()
        alarm_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute(
            "INSERT INTO alarms (user_id, sensor_type, alarm_type, threshold, alarm_time) VALUES (%s, %s, %s, %s, %s)",
            (user_id, sensor_type, alarm_type, threshold, alarm_time)
        )
        mysql.connection.commit()
        logger.info(f"Alarm logged: {alarm_type} triggered for user {user_id}")
    except Exception as e:
        logger.error(f"Error logging alarm: {e}")

# Route Login
@app.route('/', methods=['GET', 'POST'])
def login():
    msg = ''
    if request.method == 'POST' and 'username' in request.form and 'password' in request.form:
        username = request.form['username']
        password = request.form['password']

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        account = cursor.fetchone()

        if account and bcrypt.check_password_hash(account['password_hash'], password):
            session['loggedin'] = True
            session['id'] = account['id']
            session['username'] = account['username']
            flash('Welcome, ' + username + '!', 'success')
            return redirect(url_for('home'))
        else:
            msg = 'Incorrect username or password'
    return render_template('login.html', msg=msg)

# Route Register
@app.route('/register', methods=['GET', 'POST'])
def register():
    msg = ''
    if request.method == 'POST' and 'username' in request.form and 'password' in request.form:
        username = request.form['username']
        password = request.form['password']

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        account = cursor.fetchone()

        if account:
            msg = 'Account already exists'
        elif not username or not password:
            msg = 'Please fill out the fields'
        else:
            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
            cursor.execute(
                'INSERT INTO users (username, password_hash) VALUES (%s, %s)',
                (username, hashed_password)
            )
            mysql.connection.commit()
            flash('You are now registered and can log in!', 'success')
            return redirect(url_for('login'))
    return render_template('register.html', msg=msg)

# Route Logout
@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# Route Home
@app.route('/home')
@login_required
def home():
    return render_template('home.html')

# Route Sensor Data
@app.route('/sensordata')
@login_required
def sensordata():
    logger.debug("sensordata route accessed")

    # tag sensete heartrate data
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    user_id = session.get('id', 1)

    cursor.execute(
        "SELECT id, event_time, encrypted_gyro_data FROM gyroscope_data WHERE user_id = %s ORDER BY event_time DESC LIMIT 10",
        (user_id,)
    )
    gyro_data = cursor.fetchall()

    # afkod gyroscop data
    gyro_times = []
    gyro_values_x = []
    gyro_values_y = []
    gyro_values_z = []
    for entry in gyro_data:
        decrypted_gyro_data = cipher.decrypt(entry['encrypted_gyro_data']).decode()
        gyro_times.append(entry['event_time'])
        x, y, z = map(float, decrypted_gyro_data.split(','))
        gyro_values_x.append(x)
        gyro_values_y.append(y)
        gyro_values_z.append(z)

    # Generer faktisk graf gyro
    plt.figure(figsize=(10, 5))
    plt.plot(gyro_times, gyro_values_x, marker='o', color='red', label='Gyro X')
    plt.plot(gyro_times, gyro_values_y, marker='o', color='blue', label='Gyro Y')
    plt.plot(gyro_times, gyro_values_z, marker='o', color='purple', label='Gyro Z')
    plt.title('Gyroscope Data Over Time')
    plt.xlabel('Time')
    plt.ylabel('Gyroscope Data')
    plt.xticks(rotation=45)
    plt.legend(loc='upper left')
    plt.tight_layout()

    # lav til IMG
    gyro_img = io.BytesIO()
    plt.savefig(gyro_img, format='png')
    gyro_img.seek(0)
    gyro_base64 = base64.b64encode(gyro_img.getvalue()).decode('utf-8')
    plt.close()

    # Hent heart data
    cursor.execute(
        "SELECT id, reading_time, encrypted_heart_data FROM heart_readings WHERE user_id = %s ORDER BY reading_time DESC LIMIT 10",
        (user_id,)
    )
    heart_data = cursor.fetchall()

    # afkod heart data 
    heart_times = []
    heart_values = []
    latest_heart_rate = None
    for entry in heart_data:
        decrypted_heart_data = cipher.decrypt(entry['encrypted_heart_data']).decode()
        heart_times.append(entry['reading_time'])
        heart_values.append(float(decrypted_heart_data))
        latest_heart_rate = float(decrypted_heart_data)  # seneste load

    # tærskel værdi for alarm
    heart_rate_threshold = 170.0

    # check om tærksel er overskredet
    alarm_heart_triggered = latest_heart_rate is not None and latest_heart_rate > heart_rate_threshold

    # hjertegrafen
    plt.figure(figsize=(10, 5))
    plt.plot(heart_times, heart_values, marker='o', color='green')
    plt.title('Heart Rate Over Time')
    plt.xlabel('Time')
    plt.ylabel('Heart Rate (bpm)')
    plt.xticks(rotation=45)
    plt.tight_layout()

    # lav til IMG
    heart_img = io.BytesIO()
    plt.savefig(heart_img, format='png')
    heart_img.seek(0)
    heart_base64 = base64.b64encode(heart_img.getvalue()).decode('utf-8')
    plt.close()

    # hen begge alarmer
    cursor.execute("SELECT * FROM alarms WHERE user_id = %s ORDER BY alarm_time DESC LIMIT 2", (user_id,))
    alarms = cursor.fetchall()

    # alarm triggered?
    alarm_gyro_triggered = any(alarm['alarm_type'] == 'high gyro' for alarm in alarms)

    # send flags til template
    return render_template(
        'sensordata.html',
        heart_graph=heart_base64,
        gyro_graph=gyro_base64,
        alarms=alarms,
        alarm_gyro_triggered=alarm_gyro_triggered,
        alarm_heart_triggered=alarm_heart_triggered  # flag til hjerte og gyro over
    )
    
# start mqqt client i separat tråd
def start_mqtt_client():
    while True:
        try:
            logger.info("Attempting to connect to MQTT Broker")
            mqtt_client.connect(MQTT_BROKER, 1883, 60)
            logger.info("MQTT Client connected successfully")
            
            # Subscribe til beggetopics
            mqtt_client.subscribe([("heart_data", 0), ("mpu_data", 0)])  
            logger.info(f"Subscribed to topics: 'heart_data', 'mpu_data'")
            
            # Start loop
            mqtt_client.loop_forever()
        except Exception as e:
            logger.error(f"MQTT Connection Error: {e}")
            logger.info("Attempting to reconnect in 5 seconds...")
            time.sleep(5)

# Start MQTT thread før app.py
mqtt_thread = threading.Thread(target=start_mqtt_client)
mqtt_thread.daemon = True
mqtt_thread.start()

# kør flask app
if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)