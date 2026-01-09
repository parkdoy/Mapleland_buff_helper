# -*- coding: utf-8 -*-
import sys
import time
import math
import threading
import queue

import pydirectinput
import socketio
from flask import Flask, request, jsonify
from flask_cors import CORS

try:
    from character_detector import find_character_position
    import minimap_config
except (ImportError, ModuleNotFoundError):
    print("오류: 필요한 파일을 가져올 수 없습니다.")
    print("이 프로그램을 실행하기 전에, 'python app.py'를 실행하여 웹 UI에서 미니맵 설정을 완료해야 합니다.")
    sys.exit(1)

# --- 설정 ---
SERVER_URL = 'http://127.0.0.1:5000'  # 메인 중계 서버 주소
CONFIG_PORT = 5001                    # 이 설정용 미니 서버가 사용할 포트
DETECTION_INTERVAL = 0.25             # 위치 탐색 주기 (초)
PROXIMITY_THRESHOLD = 35              # 이 거리(픽셀) 안으로 들어오면 버프 실행
BUFF_COOLDOWN = 10                    # 버프 재사용 대기시간 (초)

# --- 전역 변수 및 동기화 ---
state_lock = threading.Lock()
buff_keys = []
buff_logic_running = False
last_buff_time = 0
all_player_positions = {} # 서버로부터 받은 모든 플레이어의 위치
my_latest_position = None # 내가 탐지한 나의 최신 위치

# --- 키 입력 작업자 (별도 스레드) ---
execution_queue = queue.Queue()
def key_press_worker():
    while True:
        key = execution_queue.get()
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 버프 키 입력: '{key}'")
        pydirectinput.press(key)
        time.sleep(0.4)
        execution_queue.task_done()

# --- 근접 버프 로직 (별도 스레드) ---
def proximity_buff_thread():
    global last_buff_time
    while True:
        time.sleep(0.5) # 너무 자주 체크하지 않도록 함
        with state_lock:
            # 로직이 꺼져있거나, 내 위치/버프 키/다른 플레이어 정보가 없으면 실행 안 함
            if not buff_logic_running or not my_latest_position or not buff_keys or not all_player_positions:
                continue
            
            current_time = time.time()
            if current_time - last_buff_time < BUFF_COOLDOWN:
                continue

            # 로컬 복사본을 만들어 lock을 오래 잡고 있지 않도록 함
            my_pos = my_latest_position
            other_positions = list(all_player_positions.values())
        
        should_buff = False
        for other_pos in other_positions:
            distance = math.sqrt((my_pos[0] - other_pos[0])**2 + (my_pos[1] - other_pos[1])**2)
            if 0 < distance < PROXIMITY_THRESHOLD:
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
def on_connect():
    print(f"성공: 중계 서버에 연결되었습니다 ({SERVER_URL})")

@sio.on('connect_error')
def on_connect_error(data):
    print(f"실패: 중계 서버에 연결할 수 없습니다 ({SERVER_URL})")

@sio.on('disconnect')
def on_disconnect():
    print("연결 끊김: 중계 서버와의 연결이 끊어졌습니다.")

@sio.on('position_update_batch')
def on_position_update_batch(data):
    """서버로부터 전체 플레이어 위치 목록을 받음"""
    global all_player_positions
    with state_lock:
        # 내 SID는 서버에 의해 결정되므로, 여기서 내 위치는 제외하지 않음
        all_player_positions = data

def position_detector_thread():
    """주기적으로 내 위치를 탐지하여 중계 서버로 전송"""
    global my_latest_position
    
    print(f"중계 서버에 연결을 시도합니다: {SERVER_URL} ...")
    sio.connect(SERVER_URL, transports=['websocket'])

    print("\n캐릭터 위치 탐색 및 전송을 시작합니다.")
    while sio.connected:
        position = find_character_position(minimap_config.MINIMAP_COORDS)
        if position:
            with state_lock:
                my_latest_position = position
            sio.emit('my_position', {'pos': position})
        time.sleep(DETECTION_INTERVAL)

# --- 버프 설정을 위한 Flask 미니 서버 ---
config_app = Flask(__name__)
CORS(config_app)

@config_app.route('/update_buffs', methods=['POST'])
def update_buffs():
    global buff_keys, buff_logic_running, last_buff_time
    data = request.get_json()
    keys = data.get('keys', [])
    with state_lock:
        buff_keys = keys
        buff_logic_running = True
        last_buff_time = 0 # 쿨다운 초기화
    print(f"[설정] 버프 시작/업데이트. 키: {keys}")
    return jsonify({"status": "started", "keys": keys})

@config_app.route('/stop_buffs', methods=['POST'])
def stop_buffs():
    global buff_logic_running, buff_keys
    with state_lock:
        buff_logic_running = False
        buff_keys = []
    print("[설정] 버프 중지.")
    return jsonify({"status": "stopped"})

# --- 메인 실행 ---
def main():
    if not hasattr(minimap_config, 'MINIMAP_COORDS') or not minimap_config.MINIMAP_COORDS:
        print("\n오류: 미니맵이 설정되지 않았습니다!")
        print("이 프로그램을 실행하기 전에, 먼저 'python app.py'를 실행하여 웹 UI에서 미니맵 설정을 완료해야 합니다.")
        return
    print(f"로딩된 미니맵 좌표: {minimap_config.MINIMAP_COORDS}")

    # --- 백그라운드 스레드 시작 ---
    # 1. 키보드 입력을 처리할 작업자 스레드
    threading.Thread(target=key_press_worker, daemon=True).start()
    
    # 2. 다른 플레이어와의 거리를 계산하여 버프를 실행할 스레드
    threading.Thread(target=proximity_buff_thread, daemon=True).start()
    
    # 3. 내 캐릭터 위치를 탐지하여 중계 서버로 보낼 스레드
    threading.Thread(target=position_detector_thread, daemon=True).start()

    # --- 메인 스레드에서는 Flask 설정 서버를 실행 ---
    print(f"--- 탐지기 클라이언트 실행 중 ---")
    print(f"버프 설정을 위한 로컬 서버가 http://127.0.0.1:{CONFIG_PORT} 에서 실행됩니다.")
    config_app.run(host='127.0.0.1', port=CONFIG_PORT)

if __name__ == '__main__':
    # 이 스크립트를 실행하려면 추가 라이브러리가 필요할 수 있습니다.
    # pip install "python-socketio[client]" flask flask-cors
    main()