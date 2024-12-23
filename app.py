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

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# MySQL Configurations
app.config["MYSQL_HOST"] = os.getenv("MYSQL_HOST")
app.config["MYSQL_USER"] = os.getenv("MYSQL_USER")
app.config["MYSQL_PASSWORD"] = os.getenv("MYSQL_PASSWORD")
app.config["MYSQL_DB"] = os.getenv("MYSQL_DB")
mysql = MySQL(app)

# Encryption Key
encryption_key = os.getenv("ENCRYPTION_KEY").encode()
cipher = Fernet(encryption_key)

# MQTT Subscriber Setup
MQTT_BROKER = "localhost"  # Since it's running on the same Raspberry Pi
MQTT_TOPIC = "heart_data" 

# Decorator to require login
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'loggedin' not in session:
            flash('Please log in to access this page.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# MQTT Callback Functions
def on_connect(client, userdata, flags, rc):
    logger.info(f"Connected with result code {rc}")
    # Subscribe to both topics
    client.subscribe([("heart_data", 0), ("mpu_data", 0)])  # Subscribing to both topics

def on_message(client, userdata, msg):
    # Use application context to handle database operations
    with app.app_context():
        try:
            # Parse the received message
            message = msg.payload.decode('utf-8')
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            logger.info(f"Raw MQTT Message Received: {message}")

            # If the message is from the heart_data topic
            if msg.topic == "heart_data":
                # Process and store heart data
                try:
                    # Example for processing heart rate data
                    filtered_red, filtered_ir = map(float, message.split(','))
                    # You can store these values in the database or use them as needed
                    logger.info(f"Heart data received: {filtered_red}, {filtered_ir}")
                except Exception as e:
                    logger.error(f"Error processing heart data: {e}")
            
            # If the message is from the mpu_data topic
            elif msg.topic == "mpu_data":
                # Process and store MPU data
                logger.info(f"MPU data received: {message}")
                # You can process the accelerometer and gyroscope data here as needed

        except Exception as general_error:
            logger.error(f"General MQTT Message Processing Error: {general_error}")

# MQTT Client Setup
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

def parse_sensor_data(message):
    """
    Parse the sensor data message into structured format
    Expected format: "Accelerometer: X=value, Y=value, Z=value | Gyroscope: X=value, Y=value, Z=value"
    """
    try:
        # Split accelerometer and gyroscope data
        accel_part, gyro_part = message.split(' | ')
        
        # Extract accelerometer values
        accel_x = float(accel_part.split('X=')[1].split(',')[0])
        accel_y = float(accel_part.split('Y=')[1].split(',')[0])
        accel_z = float(accel_part.split('Z=')[1])
        
        # Extract gyroscope values
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
    # Matplotlib configuration to reduce warnings
    import matplotlib
    matplotlib.use('Agg')
    matplotlib.pyplot.ioff()

    # Fetch recent gyroscope data from database
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(
        "SELECT encrypted_gyro_data FROM gyroscope_data ORDER BY event_time DESC LIMIT 5"
    )
    db_gyro_data = cursor.fetchall()
    
    # Prepare data for graphing
    gyro_x_data = []
    gyro_y_data = []
    gyro_z_data = []
    timestamps = []

    for entry in db_gyro_data:
        try:
            # Decrypt the data
            decrypted_data = cipher.decrypt(entry['encrypted_gyro_data']).decode()
            parsed_data = parse_sensor_data(decrypted_data)
            
            if parsed_data:
                gyro_x_data.append(parsed_data['gyroscope']['x'])
                gyro_y_data.append(parsed_data['gyroscope']['y'])
                gyro_z_data.append(parsed_data['gyroscope']['z'])
                timestamps.append(len(timestamps) + 1)  # Use sequential numbering
        except Exception as e:
            logger.error(f"Error processing graph data: {e}")

    # If no data, use dummy data
    if not gyro_x_data:
        timestamps = list(range(1, 6))
        gyro_x_data = [0, 0, 0, 0, 0]
        gyro_y_data = [0, 0, 0, 0, 0]
        gyro_z_data = [0, 0, 0, 0, 0]

    # Gyroscope Data Graph
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

    # Placeholder for heart rate (you might want to implement similar logic for heart rate)
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

# Route: Login
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

# Route: Register
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

# Route: Logout
@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# Route: Home
@app.route('/home')
@login_required
def home():
    return render_template('home.html')

# Route: Sensor Data
@app.route('/sensordata')
@login_required
def sensordata():
    logger.debug("sensordata route accessed")

    # Fetch recent heart rate data from the database
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    user_id = session.get('id', 1)

    cursor.execute(
        "SELECT id, event_time, encrypted_gyro_data FROM gyroscope_data WHERE user_id = %s ORDER BY event_time DESC LIMIT 10",
        (user_id,)
    )
    gyro_data = cursor.fetchall()

    # Decrypt gyroscope data
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

    # Generate Gyroscope Data Graph
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

    # Convert to image
    gyro_img = io.BytesIO()
    plt.savefig(gyro_img, format='png')
    gyro_img.seek(0)
    gyro_base64 = base64.b64encode(gyro_img.getvalue()).decode('utf-8')
    plt.close()

    # Fetch heart rate data from database
    cursor.execute(
        "SELECT id, reading_time, encrypted_heart_data FROM heart_readings WHERE user_id = %s ORDER BY reading_time DESC LIMIT 10",
        (user_id,)
    )
    heart_data = cursor.fetchall()

    # Decrypt the heart readings and check the latest heart rate value
    heart_times = []
    heart_values = []
    latest_heart_rate = None
    for entry in heart_data:
        decrypted_heart_data = cipher.decrypt(entry['encrypted_heart_data']).decode()
        heart_times.append(entry['reading_time'])
        heart_values.append(float(decrypted_heart_data))
        latest_heart_rate = float(decrypted_heart_data)  # Get the most recent heart rate value

    # Define threshold for heart rate alarm (e.g., 120 bpm)
    heart_rate_threshold = 170.0

    # Check if the latest heart rate exceeds the threshold to trigger the alarm
    alarm_heart_triggered = latest_heart_rate is not None and latest_heart_rate > heart_rate_threshold

    # Generate Heart Rate Graph
    plt.figure(figsize=(10, 5))
    plt.plot(heart_times, heart_values, marker='o', color='green')
    plt.title('Heart Rate Over Time')
    plt.xlabel('Time')
    plt.ylabel('Heart Rate (bpm)')
    plt.xticks(rotation=45)
    plt.tight_layout()

    # Convert to image
    heart_img = io.BytesIO()
    plt.savefig(heart_img, format='png')
    heart_img.seek(0)
    heart_base64 = base64.b64encode(heart_img.getvalue()).decode('utf-8')
    plt.close()

    # Fetch alarms for both MPU and Heart Rate
    cursor.execute("SELECT * FROM alarms WHERE user_id = %s ORDER BY alarm_time DESC LIMIT 2", (user_id,))
    alarms = cursor.fetchall()

    # Check if any of the alarms are triggered
    alarm_gyro_triggered = any(alarm['alarm_type'] == 'high gyro' for alarm in alarms)

    # Pass the flags to the template
    return render_template(
        'sensordata.html',
        heart_graph=heart_base64,
        gyro_graph=gyro_base64,
        alarms=alarms,
        alarm_gyro_triggered=alarm_gyro_triggered,
        alarm_heart_triggered=alarm_heart_triggered  # Pass the flag for heart rate alarm
    )
    
# Start MQTT Client in a separate thread
def start_mqtt_client():
    while True:
        try:
            logger.info("Attempting to connect to MQTT Broker")
            mqtt_client.connect(MQTT_BROKER, 1883, 60)
            logger.info("MQTT Client connected successfully")
            
            # Subscribe to both topics
            mqtt_client.subscribe([("heart_data", 0), ("mpu_data", 0)])  # Subscribe to both topics
            logger.info(f"Subscribed to topics: 'heart_data', 'mpu_data'")
            
            # Start the loop
            mqtt_client.loop_forever()
        except Exception as e:
            logger.error(f"MQTT Connection Error: {e}")
            logger.info("Attempting to reconnect in 5 seconds...")
            time.sleep(5)

# Start MQTT thread before running the app
mqtt_thread = threading.Thread(target=start_mqtt_client)
mqtt_thread.daemon = True
mqtt_thread.start()

# Run the Flask application
if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)