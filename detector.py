# -*- coding: utf-8 -*-
import sys
import time
import math
import threading
import queue
import importlib

import pydirectinput
import socketio
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

try:
    from character_detector import find_character_position
    from config_utils import run_minimap_configuration
except (ImportError, ModuleNotFoundError):
    print("오류: character_detector.py 또는 config_utils.py 파일을 찾을 수 없습니다.")
    sys.exit(1)

# --- 설정 ---
CONFIG_SERVER_PORT = 5001               # 이 개인용 서버가 사용할 포트
DETECTION_INTERVAL = 0.25             # 위치 탐색 주기 (초)
PROXIMITY_THRESHOLD = 35              # 이 거리(픽셀) 안으로 들어오면 버프 실행
BUFF_COOLDOWN = 10                    # 버프 재사용 대기시간 (초)

# --- 전역 변수 및 동기화 ---
state_lock = threading.Lock()
# --- 설정 및 상태 값 ---
MINIMAP_COORDS = None
SERVER_URL = 'http://127.0.0.1:5000' # 중계 서버 주소 (UI에서 설정 가능)
buff_keys = []
buff_logic_running = False
last_buff_time = 0
# --- 실시간 데이터 ---
all_player_positions = {} # 서버로부터 받은 모든 플레이어의 위치
my_latest_position = None # 내가 탐지한 나의 최신 위치
# --- 스레드 관리 ---
background_threads_started = False
stop_event = threading.Event()

# --- 키 입력 작업자 (별도 스레드) ---
execution_queue = queue.Queue()
def key_press_worker():
    while not stop_event.is_set():
        try:
            key = execution_queue.get(timeout=1)
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 버프 키 입력: '{key}'")
            pydirectinput.press(key)
            time.sleep(0.4)
            execution_queue.task_done()
        except queue.Empty:
            continue

# --- 근접 버프 로직 (별도 스레드) ---
def proximity_buff_thread():
    global last_buff_time
    while not stop_event.is_set():
        time.sleep(0.5)
        with state_lock:
            if not buff_logic_running or not my_latest_position or not buff_keys or not all_player_positions:
                continue
            current_time = time.time()
            if current_time - last_buff_time < BUFF_COOLDOWN:
                continue
            my_pos = my_latest_position
            # Make a local copy of positions to avoid holding the lock for long
            other_positions = [pos for sid, pos in all_player_positions.items() if sio.sid != sid]

        should_buff = False
        for other_pos in other_positions:
            distance = math.sqrt((my_pos[0] - other_pos[0])**2 + (my_pos[1] - other_pos[1])**2)
            if distance < PROXIMITY_THRESHOLD:
                should_buff = True
                break
        
        if should_buff:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 근접 플레이어 감지! 버프를 실행합니다.")
            for key in buff_keys:
                execution_queue.put(key)
            with state_lock:
                last_buff_time = time.time()

# --- 위치 탐지 및 서버 통신 로직 (별도 스레드) ---
sio = socketio.Client()

@sio.on('connect')
def on_connect(): print(f"성공: 중계 서버에 연결되었습니다 ({SERVER_URL})")
@sio.on('connect_error')
def on_connect_error(data): print(f"실패: 중계 서버에 연결할 수 없습니다 ({SERVER_URL})")
@sio.on('disconnect')
def on_disconnect(): print("연결 끊김: 중계 서버와의 연결이 끊어졌습니다.")

@sio.on('position_update_batch')
def on_position_update_batch(data):
    global all_player_positions
    with state_lock:
        all_player_positions = data

def position_detector_thread():
    global my_latest_position
    print(f"중계 서버에 연결을 시도합니다: {SERVER_URL} ...")
    try:
        sio.connect(SERVER_URL, transports=['websocket'])
    except socketio.exceptions.ConnectionError as e:
        print(f"중계 서버 연결 실패: {e}")
        return

    print("\n캐릭터 위치 탐색 및 전송을 시작합니다.")
    while sio.connected and not stop_event.is_set():
        position = find_character_position(MINIMAP_COORDS)
        if position:
            with state_lock:
                my_latest_position = position
            sio.emit('my_position', {'pos': position})
        time.sleep(DETECTION_INTERVAL)
    sio.disconnect()

# --- 개인 설정을 위한 Flask 서버 ---
app = Flask(__name__, template_folder='.')
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route('/')
def index():
    return render_template('control_panel.html')

def start_background_threads():
    global background_threads_started
    if not background_threads_started:
        print("백그라운드 작업 스레드를 시작합니다 (위치 탐지, 버프 로직 등)")
        stop_event.clear()
        threading.Thread(target=key_press_worker, daemon=True).start()
        threading.Thread(target=proximity_buff_thread, daemon=True).start()
        threading.Thread(target=position_detector_thread, daemon=True).start()
        background_threads_started = True

@app.route('/recalibrate', methods=['POST'])
def recalibrate():
    global MINIMAP_COORDS
    print("미니맵 재설정 요청을 받았습니다...")
    new_coords = run_minimap_configuration()
    if new_coords:
        MINIMAP_COORDS = new_coords
        # Save to file for next time
        with open("minimap_config.py", "w", encoding="utf-8") as f:
            f.write(f'MINIMAP_COORDS = {new_coords}')
        print(f"미니맵 설정 완료: {new_coords}")
        start_background_threads()
        return jsonify({"status": "success", "coords": new_coords})
    else:
        return jsonify({"status": "cancelled"})

@app.route('/update_buffs', methods=['POST'])
def update_buffs():
    global buff_keys, buff_logic_running, last_buff_time, SERVER_URL
    data = request.get_json()
    keys = data.get('keys', [])
    server_url_from_ui = data.get('server_url')
    
    with state_lock:
        buff_keys = keys
        buff_logic_running = True
        last_buff_time = 0 
        if server_url_from_ui and server_url_from_ui != SERVER_URL:
            SERVER_URL = server_url_from_ui
            print(f"[설정] 중계 서버 주소가 변경되었습니다: {SERVER_URL}")
            if sio.connected:
                sio.disconnect()
            # The detector thread will handle reconnection
    print(f"[설정] 버프 시작/업데이트. 키: {keys}")
    return jsonify({"status": "started", "keys": keys})

@app.route('/stop_buffs', methods=['POST'])
def stop_buffs():
    global buff_logic_running, buff_keys
    with state_lock:
        buff_logic_running = False
        buff_keys = []
    print("[설정] 버프 중지.")
    return jsonify({"status": "stopped"})

# --- 메인 실행 ---
def main():
    # Try to load existing config on start
    try:
        importlib.reload(minimap_config)
        if hasattr(minimap_config, 'MINIMAP_COORDS'):
            global MINIMAP_COORDS
            MINIMAP_COORDS = minimap_config.MINIMAP_COORDS
            print(f"기존 미니맵 설정을 로드했습니다: {MINIMAP_COORDS}")
            start_background_threads()
    except (ImportError, AttributeError):
        print("기존 미니맵 설정(`minimap_config.py`)을 찾을 수 없습니다. UI에서 설정해주세요.")
    
    print(f"--- 개인용 설정 UI 및 탐지기 클라이언트 ---")
    print(f"웹 브라우저에서 http://127.0.0.1:{CONFIG_SERVER_PORT} 로 접속하세요.")
    app.run(host='127.0.0.1', port=CONFIG_SERVER_PORT)

if __name__ == '__main__':
    # On Windows, pydirectinput requires this permission.
    try:
        pydirectinput.FAILSAFE = False
    except Exception as e:
        print(f"pydirectinput 설정 오류: {e}")

    main()
