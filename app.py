import queue
import threading
import math
import time
import importlib

import pydirectinput
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS

from character_detector import find_character_position
from config_utils import run_minimap_configuration

# --- Flask App and SocketIO Initialization ---
app = Flask(__name__)
CORS(app) # Enable Cross-Origin Resource Sharing
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='threading')

# --- Global Configuration (Loaded at startup) ---
MINIMAP_COORDS = None

def load_config():
    """Loads minimap configuration from the file into global variables."""
    global MINIMAP_COORDS
    try:
        # We need to reload the module to get the latest values after a recalibration
        import minimap_config
        importlib.reload(minimap_config)
        MINIMAP_COORDS = minimap_config.MINIMAP_COORDS
        print("미니맵 설정 로드 완료.")
        return True
    except (ImportError, AttributeError):
        print("경고: 유효한 `minimap_config.py`를 찾을 수 없습니다. 미니맵 재설정이 필요합니다.")
        return False

# --- Constants ---
PROXIMITY_THRESHOLD = 35   # Distance in pixels to trigger buffs
BUFF_COOLDOWN = 10         # Seconds to wait between buffing sessions

# --- Thread-Safe Data Structures & Proximity Checker Globals ---
execution_queue = queue.Queue()
player_positions = {}
positions_lock = threading.Lock()

last_buff_time = 0
connected_clients = set()
clients_lock = threading.Lock()


# --- Worker and Proximity Checker Functions ---
def press_single_key(key):
    """Presses a single key using pydirectinput."""
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] '{key}' 키 입력 실행...")
    pydirectinput.press(key)

def key_press_worker():
    """Worker thread that takes keys from a queue and presses them."""
    while True:
        key = execution_queue.get()
        press_single_key(key)
        time.sleep(0.4) # Small delay between each key press
        execution_queue.task_done()

def proximity_checker_thread():
    """
    Worker thread that periodically checks player proximity and triggers buffs.
    """
    global proximity_checker_running, last_buff_time, buff_keys
    while True:
        if not proximity_checker_running or not MINIMAP_COORDS or not buff_keys:
            time.sleep(0.5)
            continue

        # Check cooldown to prevent buff spam
        current_time = time.time()
        if current_time - last_buff_time < BUFF_COOLDOWN:
            time.sleep(0.5)
            continue

        my_pos = find_character_position(MINIMAP_COORDS)
        if not my_pos:
            time.sleep(0.5)
            continue

        with positions_lock:
            all_player_pos = list(player_positions.values())

        if not all_player_pos:
            time.sleep(0.5)
            continue

        should_buff = False
        for other_pos in all_player_pos:
            distance = math.sqrt((my_pos[0] - other_pos[0])**2 + (my_pos[1] - other_pos[1])**2)
            # Trigger if a player is close, but not exactly on top (which is likely ourselves)
            if 0 < distance < PROXIMITY_THRESHOLD:
                should_buff = True
                break 

        if should_buff:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 근접한 플레이어 감지! 버프를 실행합니다.")
            for key in buff_keys:
                execution_queue.put(key)
            last_buff_time = current_time
        
        time.sleep(0.5) # Check for players roughly twice a second


# --- Web Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_my_position', methods=['GET'])
def get_my_position():
    """Endpoint for the client to request its own character position."""
    if not MINIMAP_COORDS:
        return jsonify({"status": "no_config"})
    
    position = find_character_position(MINIMAP_COORDS)
    if position:
        return jsonify({"status": "success", "pos": position})
    else:
        return jsonify({"status": "not_found"})

@app.route('/recalibrate', methods=['POST'])
def recalibrate():
    """Triggers the minimap recalibration process and an immediate first detection."""
    global MINIMAP_COORDS
    print("미니맵 재설정 요청을 받았습니다...")
    
    try:
        new_coords = run_minimap_configuration()
        
        if new_coords:
            MINIMAP_COORDS = new_coords
            print("미니맵 설정이 인-메모리에서 업데이트되었습니다.")
            
            # --- ADDED: Perform an immediate detection after calibration ---
            print("설정 완료 후 즉시 첫 번째 위치 감지를 시작합니다...")
            position = find_character_position(MINIMAP_COORDS)
            
            response_data = {"status": "success", "coords": new_coords}
            if position:
                print(f"첫 번째 감지 성공: {position}")
                response_data["pos_status"] = "found"
                response_data["pos"] = position
            else:
                print("첫 번째 감지 실패: 캐릭터를 찾을 수 없습니다.")
                response_data["pos_status"] = "not_found"
            
            # Manually broadcast to all tracked clients to avoid 'broadcast' argument issues.
            print(f"수동으로 설정을 방송합니다...")
            with clients_lock:
                # Iterate over a copy of the set in case it changes during iteration
                sids = list(connected_clients)
                for sid in sids:
                    socketio.emit('config_updated', {'coords': new_coords}, room=sid, namespace='/')
            print(f"{len(sids)}명의 클라이언트에게 방송 완료.")
                
            return jsonify(response_data)
            
        else:
            print("미니맵 재설정이 사용자에 의해 취소되었습니다.")
            return jsonify({"status": "cancelled"})
            
    except Exception as e:
        # Catch any unexpected errors during screen capture or processing
        print(f"오류: 재설정 중 예외 발생: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/start', methods=['POST'])
def start_task():
    """Starts the proximity checker with a given set of buff keys."""
    global proximity_checker_running, buff_keys, last_buff_time
    if proximity_checker_running:
        return jsonify({"status": "이미 실행 중입니다. 먼저 중지해주세요."}), 400
    
    data = request.get_json()
    keys = data.get('keys')
    if not keys or not isinstance(keys, list):
        return jsonify({"status": "버프 키가 올바르게 제공되지 않았습니다."}), 400

    buff_keys = keys
    last_buff_time = 0 # Reset cooldown timer
    proximity_checker_running = True
    print(f"근접 버프 도우미 시작. 감지할 키: {buff_keys}")
    return jsonify({"status": "실행 중", "keys": buff_keys})

@app.route('/stop', methods=['POST'])
def stop_task():
    """Stops the proximity checker."""
    global proximity_checker_running, buff_keys
    if not proximity_checker_running:
        return jsonify({"status": "이미 중지되었습니다."})
    
    proximity_checker_running = False
    buff_keys = []
    # Clear any pending key presses from the queue
    with execution_queue.mutex:
        execution_queue.queue.clear()
    
    print("근접 버프 도우미 중지.")
    return jsonify({"status": "유휴"})

# --- SocketIO Event Handlers ---
@socketio.on('connect')
def handle_connect():
    with clients_lock:
        connected_clients.add(request.sid)
    print(f"클라이언트 연결됨: {request.sid}. 현재 접속자: {len(connected_clients)}")
    # If the minimap is already configured, send the coords to the new client
    if MINIMAP_COORDS:
        emit('config_updated', {'coords': MINIMAP_COORDS})
        
    with positions_lock:
        if player_positions:
            emit('position_update_batch', player_positions)

@socketio.on('disconnect')
def handle_disconnect():
    with clients_lock:
        connected_clients.discard(request.sid)
    print(f"클라이언트 연결 끊김: {request.sid}. 현재 접속자: {len(connected_clients)}")
    with positions_lock:
        if request.sid in player_positions:
            del player_positions[request.sid]
            emit('player_left', {'sid': request.sid}, broadcast=True)

@socketio.on('my_position')
def handle_my_position(data):
    sid = request.sid
    pos = data.get('pos')
    if pos:
        with positions_lock:
            player_positions[sid] = pos
        # Manually broadcast the update to all connected clients
        update_payload = {'sid': sid, 'pos': pos}
        with clients_lock:
            for client_sid in connected_clients:
                emit('position_update', update_payload, room=client_sid)

# --- Main Execution ---
if __name__ == '__main__':
    # We no longer load config at startup. It must be done via the UI.
    key_worker = threading.Thread(target=key_press_worker, daemon=True)
    key_worker.start()

    scheduler = threading.Thread(target=proximity_checker_thread, daemon=True)
    scheduler.start()

    print("--- Flask-SocketIO 서버 시작 ---")
    print("웹 브라우저에서 http://127.0.0.1:5000 로 접속하세요.")
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
