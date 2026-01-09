import threading

from flask import Flask, request
from flask_socketio import SocketIO, emit

# --- Flask App and SocketIO Initialization ---
# This is now a pure backend server, Flask is only used to bootstrap SocketIO.
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
# Allow all origins for Socket.IO to prevent cross-origin issues
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

# --- Globals for Server State ---
player_positions = {} # Stores the latest position for each client SID
positions_lock = threading.Lock()
connected_clients = set() # Manually tracks all connected SIDs
clients_lock = threading.Lock()

# --- SocketIO Event Handlers ---
@socketio.on('connect')
def handle_connect():
    """A new client (either a detector or a web browser) has connected."""
    with clients_lock:
        connected_clients.add(request.sid)
    print(f"클라이언트 연결됨: {request.sid}. 현재 접속자: {len(connected_clients)}")
    
    # Immediately send all currently known player positions to the new client
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
    
    # Remove the player from the positions dictionary and notify remaining clients
    with positions_lock:
        if sid_that_left in player_positions:
            del player_positions[sid_that_left]
            
            # Broadcast the new, smaller list of players to everyone
            batch_to_send = dict(player_positions)
            with clients_lock:
                sids_to_send = list(connected_clients)
                for client_sid in sids_to_send:
                    socketio.emit('position_update_batch', batch_to_send, room=client_sid, namespace='/')

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
    print("이 서버는 위치 정보 중계 역할만 합니다.")
    print("각 플레이어는 'python detector.py'를 실행해야 합니다.")
    # host='0.0.0.0' allows access from other devices on the same network
    socketio.run(app, host='0.0.0.0', port=5000)
