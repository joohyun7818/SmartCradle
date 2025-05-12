import cv2
from picamera2 import Picamera2
import time
import base64
import websocket  # pip install websocket-client
import threading
import json
import socket
import datetime
from PIL import Image, ImageDraw, ImageFont
import requests
import serial  # 추가
import numpy as np  # 추가
import qrcode

SERVER_URL = 'http://<EC2_PUBLIC_IP>:5000'
CRADLE_UUID = 'cradle-unique-id-example'
SERVER_WS_URL = f'ws://<EC2_PUBLIC_IP>:5000/ws/{CRADLE_UUID}'
FRAME_UPLOAD_INTERVAL = 0.1
QR_CODE_FILENAME = 'cradle_qrcode.png'

# MQTT 설정 (EC2 서버 IP로 변경 필요)
MQTT_BROKER_HOST = "<EC2_PUBLIC_IP>"
MQTT_BROKER_PORT = 1883
MQTT_TOPIC_TEMPERATURE = f"cradle/{CRADLE_UUID}/temperature"
MQTT_TOPIC_SERVO_STATUS = f"cradle/{CRADLE_UUID}/servo/status"

# 시리얼 통신 설정 (추가)
SERIAL_PORT = '/dev/ttyACM0'  # 실제 시리얼 포트
BAUDRATE = 9600
ser = None
try:
    ser = serial.Serial(SERIAL_PORT, BAUDRATE)
    print(f"시리얼 포트 {SERIAL_PORT} 연결 성공")
except serial.SerialException as e:
    print(f"시리얼 포트 {SERIAL_PORT} 연결 실패: {e}")

# MQTT 클라이언트 설정
mqtt_client = mqtt.Client()

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("MQTT Broker 연결 성공")
    else:
        print(f"MQTT Broker 연결 실패, rc={rc}")

mqtt_client.on_connect = on_connect

try:
    mqtt_client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 60)
    mqtt_client.loop_start()  # 백그라운드 스레드 시작
except Exception as e:
    print(f"MQTT 연결 오류: {e}")

picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(main={"size": (640, 480)}))
picam2.start()
time.sleep(2)

try:
    font = ImageFont.truetype('/home/jh/camTest/fonts/SCDream6.otf', 20)
except IOError:
    print("폰트 파일이 없습니다. 기본 폰트를 사용합니다.")
    font = ImageFont.load_default()

def generate_qr_code(uuid, filename):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(uuid)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
    img.save(filename)
    print(f"QR 코드가 {filename}으로 저장되었습니다.")

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        s.connect(('10.254.254.254', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def register_agent():
    agent_ip = get_ip()
    try:
        response = requests.post(f'{SERVER_URL}/register_agent', json={'uuid': CRADLE_UUID, 'ip': agent_ip})
        print(response.json())
    except Exception as e:
        print("서버 연결 실패:", e)

def send_frames_websocket():
    try:
        ws = websocket.create_connection(SERVER_WS_URL)
        print(f"웹 소켓 연결 성공: {SERVER_WS_URL}")
        while True:
            frame = picam2.capture_array()
            pil_image = Image.fromarray(frame)
            draw = ImageDraw.Draw(pil_image)
            nowDatetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            draw.text((10, 15), "raspiCam " + nowDatetime, font=font, fill=(255, 255, 255))
            frame = np.array(pil_image)

            _, img_encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
            base64_frame = base64.b64encode(img_encoded).decode('utf-8')
            try:
                ws.send(base64_frame)
            except websocket.WebSocketConnectionClosedException:
                print("웹 소켓 연결이 끊어졌습니다. 재연결 시도...")
                break
            except Exception as e:
                print(f"웹 소켓 전송 오류: {e}")
                break
            time.sleep(FRAME_UPLOAD_INTERVAL)
        if ws.connected:
            ws.close()
    except websocket.WebSocketException as e:
        print(f"웹 소켓 연결 또는 통신 오류: {e}")
    finally:
        print("웹 소켓 연결 종료")
        time.sleep(5) # 재연결 시도 간격
        threading.Thread(target=send_frames_websocket, daemon=True).start() # 자동 재연결 시도

# 체온 센서 값 및 MQTT 발행 (추가)
temperature = "N/A"
def read_temperature():
    global temperature
    while ser:
        try:
            if ser.in_waiting > 0:
                temp_data = ser.readline().decode('utf-8', errors='ignore').strip()
                temperature = temp_data
                payload = json.dumps({"temperature": temperature, "uuid": CRADLE_UUID})
                mqtt_client.publish(MQTT_TOPIC_TEMPERATURE, payload)
                print(f"Published temperature: {payload} to {MQTT_TOPIC_TEMPERATURE}")
        except serial.SerialException as e:
            print(f"시리얼 통신 오류 (온도): {e}")
            break
        except Exception as e:
            print(f"온도 읽기 오류: {e}")
        time.sleep(1)

def main():
    """메인 함수"""
    # 고유한 UUID 기반으로 QR 코드 생성 및 저장
    generate_qr_code(CRADLE_UUID, QR_CODE_FILENAME)

    # 에이전트 정보 등록
    register_agent()

    # 웹 소켓을 통해 프레임을 전송하는 스레드 시작
    frame_thread = threading.Thread(target=send_frames_websocket, daemon=True)
    frame_thread.start()

    # 체온 센서 값 읽기 및 MQTT 발행 시작 (별도 스레드)
    if ser:
        temperature_thread = threading.Thread(target=read_temperature)
        temperature_thread.daemon = True
        temperature_thread.start()

    # 메인 스레드는 계속 실행될 수 있도록 유지 (예: 다른 작업 수행 또는 종료 대기)
    while True:
        time.sleep(1)

if __name__ == '__main__':
    main()