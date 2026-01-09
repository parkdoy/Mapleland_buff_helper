import time
import importlib
import threading

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS

from config_utils import run_minimap_configuration

# --- Flask App and SocketIO Initialization ---
app = Flask(__name__)
CORS(app) # Enable Cross-Origin Resource Sharing
app.config['SECRET_KEY'] = 'secret!'
# Allow all origins for Socket.IO to prevent cross-origin issues
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

# --- Globals for Server State ---
MINIMAP_COORDS = None # Stores the coordinates for the map UI
player_positions = {} # Stores the latest position for each client SID
positions_lock = threading.Lock()
connected_clients = set() # Manually tracks all connected SIDs
clients_lock = threading.Lock()


# --- Web Routes ---
@app.route('/')
def index():
    """Serves the main web page."""
    return render_template('index.html')

@app.route('/recalibrate', methods=['POST'])
def recalibrate():
    """
    Allows a host to run the minimap configuration process.
    The resulting coordinates are broadcast to all clients to build the UI.
    """
    global MINIMAP_COORDS
    print("미니맵 재설정 요청을 받았습니다...")
    
    try:
        new_coords = run_minimap_configuration()
        if new_coords:
            MINIMAP_COORDS = new_coords
            print(f"미니맵 설정이 인-메모리에서 업데이트되었습니다: {new_coords}")
            
            # Manually broadcast the new config to all connected clients
            print(f"수동으로 설정을 모든 클라이언트에게 방송합니다...")
            with clients_lock:
                sids = list(connected_clients)
                for sid in sids:
                    socketio.emit('config_updated', {'coords': new_coords}, room=sid, namespace='/')
            print(f"{len(sids)}명의 클라이언트에게 방송 완료.")
            
            return jsonify({"status": "success", "coords": new_coords})
        else:
            print("미니맵 재설정이 사용자에 의해 취소되었습니다.")
            return jsonify({"status": "cancelled"})
            
    except Exception as e:
        print(f"오류: 재설정 중 예외 발생: {e}")
        return jsonify({"status": "error", "message": str(e)})

# --- SocketIO Event Handlers ---
@socketio.on('connect')
def handle_connect():
    """A new client has connected."""
    with clients_lock:
        connected_clients.add(request.sid)
    print(f"클라이언트 연결됨: {request.sid}. 현재 접속자: {len(connected_clients)}")
    
    # If the minimap is already configured, send the coords to the new client
    if MINIMAP_COORDS:
        emit('config_updated', {'coords': MINIMAP_COORDS})
    
    # Send all currently known player positions to the new client
    with positions_lock:
        if player_positions:
            emit('position_update_batch', player_positions)

@socketio.on('disconnect')
def handle_disconnect():
    """A client has disconnected."""
    sid_that_left = request.sid
    with clients_lock:
        connected_clients.discard(sid_that_left)
    print(f"클라이언트 연결 끊김: {sid_that_left}. 현재 접속자: {len(connected_clients)}")
    
    # Remove the player from the positions dictionary
    with positions_lock:
        if sid_that_left in player_positions:
            del player_positions[sid_that_left]
            
            # Notify all other clients that this player has left
            with clients_lock:
                sids_to_send = list(connected_clients)
                for client_sid in sids_to_send:
                    socketio.emit('player_left', {'sid': sid_that_left}, room=client_sid, namespace='/')

@socketio.on('my_position')
def handle_my_position(data):
    """Received a position update from a detector client."""
    sid = request.sid
    pos = data.get('pos')
    if pos:
        batch_to_send = {}
        # Store the new position and get a full copy of all positions
        with positions_lock:
            player_positions[sid] = pos
            batch_to_send = dict(player_positions)
        
        # Relay (broadcast) the ENTIRE batch of positions to all connected clients
        with clients_lock:
            sids_to_send = list(connected_clients)
            for client_sid in sids_to_send:
                socketio.emit('position_update_batch', batch_to_send, room=client_sid, namespace='/')

# --- Main Execution ---
if __name__ == '__main__':
    print("--- Flask-SocketIO 중계 서버 시작 ---")
    print("이 서버는 UI를 제공하고 위치 정보를 중계하는 역할만 합니다.")
    print("각 플레이어의 PC에서 'python detector.py'를 실행해야 캐릭터가 표시됩니다.")
    print("웹 브라우저에서 http://127.0.0.1:5000 로 접속하세요.")
    # host='0.0.0.0' allows access from other devices on the same network
    socketio.run(app, host='0.0.0.0', port=5000)