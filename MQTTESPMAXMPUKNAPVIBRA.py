import network
import time
import ntptime  
from machine import Pin, I2C
import threading
from umqtt.simple import MQTTClient
import mpulib

# MQTT Config
BROKER = "192.168.1.185"
CLIENT_ID = "esp32_combined_publisher"
TOPIC_MPU = "mpu_data"
TOPIC_MAX = "heart_data"

# I2C Bus for begge sensorer
i2c = I2C(0, scl=Pin(15), sda=Pin(2), freq=400000)  # MAX30102
i2c1 = I2C(1, scl=Pin(22), sda=Pin(21), freq=400000)  # MPU6050
mpu = mpulib.MPU6050(i2c1)

# MAX Configu
MAX30102_I2C_ADDRESS = 0x62
REG_FIFO_DATA = 0x07
REG_FIFO_WR_PTR = 0x04
REG_FIFO_RD_PTR = 0x06

WINDOW_SIZE = 10
red_buffer = []
ir_buffer = []

# Vibrationsmotor setup
vibration_motor = Pin(4, Pin.OUT)  # Vibrationsmotor på pin 4

# Wi-Fi 
def connect_wifi(ssid, password):
    station = network.WLAN(network.STA_IF)
    station.active(True)
    station.connect(ssid, password)
    while not station.isconnected():
        pass
    print("Wi-Fi connected:", station.ifconfig())

# MQTT Setup
def mqtt_connect():
    client = MQTTClient(CLIENT_ID, BROKER)
    client.connect()
    print("Connected to MQTT Broker")
    return client

# MAXSensor Funtioner
def write_register(reg, value):
    i2c.writeto_mem(MAX30102_I2C_ADDRESS, reg, bytes([value]))

def read_register(reg, nbytes=1):
    return i2c.readfrom_mem(MAX30102_I2C_ADDRESS, reg, nbytes)

def reset_fifo():
    write_register(REG_FIFO_WR_PTR, 0x00)  # rset write pointer
    write_register(REG_FIFO_RD_PTR, 0x00)  # reset read pointer

def init_max30102():
    print("Initializing sensor...")
    write_register(0x09, 0x40)  # reset
    time.sleep(0.1)
    write_register(0x02, 0xC0)  # Enable A_FULL and PPG_RDY interrupts
    write_register(0x03, 0x00)  # Disable other interrupts
    write_register(0x08, 0x00)  # FIFO config
    write_register(0x04, 0x00)  # FIFO write pointer = 0
    write_register(0x05, 0x00)  # Overflow counter = 0
    write_register(0x06, 0x00)  # FIFO read pointer = 0
    write_register(0x09, 0x03)  # Enable SpO2 mode
    write_register(0x0A, 0x27)  # SPO2 config
    write_register(0x0E, 0x24)  # LED1 pulse amplitude
    write_register(0x0F, 0x24)  # LED2 pulse amplitude
    print("Sensor initialized.")

def extract_led_data(fifo_data):
    red = (fifo_data[0] << 16) | (fifo_data[1] << 8) | fifo_data[2]
    ir = (fifo_data[3] << 16) | (fifo_data[4] << 8) | fifo_data[5]
    return red & 0x03FFFF, ir & 0x03FFFF

def moving_average(new_value, buffer, window_size):
    buffer.append(new_value)
    if len(buffer) > window_size:
        buffer.pop(0)
    return sum(buffer) / len(buffer)

# trykknap for Reset
button_pin = Pin(19, Pin.IN, Pin.PULL_UP)

def check_button_press():
    return not button_pin.value()

# Funktion til at aktivere vibrationsmotoren kl. 13
def vibrate_at_13():
    while True:
        # Tjek om klokken er 13:00
        current_time = time.localtime()  # hent lokal tid fra ESP32 RTC
        print(f"Tid: {current_time}")
        if current_time[3] == 13 and current_time[4] == 0:  # timer er 13:00
            print("Vibrating motor for 30 seconds")
            vibration_motor.value(1)  # Tænd motor
            time.sleep(30)  # Vent i 30 sekunder
            vibration_motor.value(0)  # Sluk motor
        time.sleep(60)  # check hver minut

# Main 
def main():
    connect_wifi("Inteno-7CAE", "TJVGYFNJAHGOIR")
    client = mqtt_connect()
    init_max30102()

    print("Starting combined data collection...")

    # Start tråden til overvågning af klokke
    vibration_thread = threading.Thread(target=vibrate_at_13)
    vibration_thread.daemon = True  # daemon tråd yesyesyes
    vibration_thread.start()

    while True:
        try:
            # Restart knbap
            if check_button_press():
                print("Button pressed - Resetting program...")
                main()

            # MPU
            values = mpu.get_values()
            mpu_message = f"Accelerometer: X={values['accel']['x']}, Y={values['accel']['y']}, Z={values['accel']['z']} | Gyroscope: X={values['gyro']['x']}, Y={values['gyro']['y']}, Z={values['gyro']['z']}"
            print(f"Sending MPU6050 Data: {mpu_message}")
            client.publish(TOPIC_MPU, mpu_message)

            # MAX
            fifo_data = read_register(REG_FIFO_DATA, 6)
            if fifo_data:
                red, ir = extract_led_data(fifo_data)
                filtered_red = moving_average(red, red_buffer, WINDOW_SIZE)
                filtered_ir = moving_average(ir, ir_buffer, WINDOW_SIZE)

                if red > 0 and ir > 0:  # valid data?
                    max_message = f"{filtered_red:.2f},{filtered_ir:.2f}"
                    print(f"Sending MAX30102 Data: {max_message}")
                    client.publish(TOPIC_MAX, max_message)
                else:
                    print("Invalid MAX30102 data, resetting FIFO...")
                    reset_fifo()
            else:
                print("Error reading MAX30102 FIFO data.")
                reset_fifo()

            time.sleep(0.25)  # 0.25 sekunder mellme hver

        except Exception as e:
            print(f"Error: {e}")
            client.connect()  # Reconnect MQTT ved afbrudt

if __name__ == "__main__":
    main()
