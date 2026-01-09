import socketio
import time
import sys

try:
    from character_detector import find_character_position
    import minimap_config
except (ImportError, ModuleNotFoundError):
    print("오류: 필요한 파일을 가져올 수 없습니다.")
    print("실행 전, 먼저 'python app.py'를 실행하여 미니맵 설정을 완료하고 'minimap_config.py' 파일을 생성해야 합니다.")
    sys.exit(1)


# --- 설정 ---
# 파티장(메인 서버)의 PC IP 주소로 변경하세요.
# 예: SERVER_URL = 'http://192.168.1.5:5000'
SERVER_URL = 'http://127.0.0.1:5000'
DETECTION_INTERVAL = 0.25  # 위치 탐색 주기 (초)

# --- Socket.IO 클라이언트 ---
sio = socketio.Client()

@sio.event
def connect():
    print(f"성공: 중계 서버에 연결되었습니다 ({SERVER_URL})")

@sio.event
def connect_error(data):
    print(f"실패: 중계 서버에 연결할 수 없습니다 ({SERVER_URL})")
    print("서버 주소가 올바른지, app.py가 실행 중인지 확인하세요.")

@sio.event
def disconnect():
    print("연결 끊김: 중계 서버와의 연결이 끊어졌습니다.")

def main():
    """메인 실행 함수"""
    print("--- 탐지기 클라이언트 시작 ---")

    # 미니맵 설정이 있는지 확인
    if not hasattr(minimap_config, 'MINIMAP_COORDS') or not minimap_config.MINIMAP_COORDS:
        print("\n오류: 미니맵이 설정되지 않았습니다!")
        print("이 프로그램을 실행하기 전에, 먼저 'python app.py'를 실행하여 웹 UI에서 미니맵 설정을 완료해야 합니다.")
        return

    print(f"로딩된 미니맵 좌표: {minimap_config.MINIMAP_COORDS}")
    print(f"중계 서버에 연결을 시도합니다: {SERVER_URL} ...")

    try:
        sio.connect(SERVER_URL)
    except socketio.exceptions.ConnectionError:
        # connect_error 이벤트가 오류 메시지를 출력할 것입니다.
        return

    print("\n캐릭터 위치 탐색 및 전송을 시작합니다. (중지하려면 Ctrl+C)")
    try:
        while True:
            position = find_character_position(minimap_config.MINIMAP_COORDS)
            if position:
                sio.emit('my_position', {'pos': position})
            time.sleep(DETECTION_INTERVAL)
    except KeyboardInterrupt:
        print("\n사용자에 의해 탐지기가 중지되었습니다.")
    finally:
        sio.disconnect()
        print("서버 연결이 종료되었습니다.")

if __name__ == '__main__':
    # 이 스크립트를 실행하려면 python-socketio[client] 라이브러리가 필요합니다.
    # pip install "python-socketio[client]"
    main()
