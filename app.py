import time
import pydirectinput
from flask import Flask, render_template, request, jsonify
import threading
from threading import Timer
import queue
import pygetwindow as gw

# --- Flask App Initialization ---
app = Flask(__name__)

# --- Thread-Safe Queue for Key Presses ---
execution_queue = queue.Queue()

# --- Custom Scheduler Globals ---
active_jobs = []
jobs_lock = threading.Lock()
scheduler_running = False

# --- Game Window Finder ---
Worlds={
    "MapleStory Worlds-Mapleland (엘나스)",
    "MapleStory Worlds-Mapleland (리프레)",
    "MapleStory Worlds-Mapleland (루더스/니할)"
}

def find_game_window():
    for title in Worlds:
        windows = gw.getWindowsWithTitle(title)
        if windows:
            return windows[0]
    return None

# --- Worker and Custom Scheduler Functions ---

def press_single_key(key):
    """
    Presses a single key directly. Game window focusing is handled manually by the user.
    """
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] '{key}' 키 입력 실행...")
    pydirectinput.press(key)
    print(f"    -> 성공: '{key}' 키를 눌렀습니다.")

def schedule_key_press(key):
    """Adds a key to the execution queue."""
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] '{key}' 키를 실행 대기열에 추가.")
    execution_queue.put(key)

def key_press_worker():
    """A dedicated worker thread that processes the execution queue."""
    while True:
        key = execution_queue.get()
        press_single_key(key)
        time.sleep(0.4)
        execution_queue.task_done()

def custom_scheduler_thread():
    """
    A custom scheduler loop that checks for due jobs.
    This replaces the 'schedule' library.
    """
    global active_jobs
    while True:
        if scheduler_running:
            now = time.time()
            with jobs_lock:
                for job in active_jobs:
                    if now >= job['next_run']:
                        schedule_key_press(job['key'])
                        job['next_run'] = now + job['interval']
        time.sleep(0.1) # Check for due jobs every 100ms

# --- Web Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start', methods=['POST'])
def start_task():
    global active_jobs, scheduler_running
    
    if scheduler_running:
        return jsonify({"status": "이미 실행 중입니다. 먼저 중지해주세요."}), 400

    tasks = request.get_json()
    if not isinstance(tasks, list) or not tasks:
        return jsonify({"status": "잘못된 요청입니다. 태스크 목록이 필요합니다."}), 400

    new_jobs = []
    now = time.time()
    try:
        for task in tasks:
            key = task.get('key')
            interval = int(task.get('interval'))
            if not key or interval <= 0:
                continue
            # Set all jobs to run immediately for the first press
            new_jobs.append({'key': key, 'interval': interval, 'next_run': now})
    except (TypeError, AttributeError) as e:
        return jsonify({"status": f"입력 오류: {e}"}), 400
    
    with jobs_lock:
        active_jobs = new_jobs
    
    scheduler_running = True
    print("--- 커스텀 스케줄러 시작 ---")
    return jsonify({"status": "실행 중", "tasks": tasks})

@app.route('/stop', methods=['POST'])
def stop_task():
    global active_jobs, scheduler_running

    if not scheduler_running:
        return jsonify({"status": "이미 중지되었습니다."})

    scheduler_running = False
    with jobs_lock:
        active_jobs = []
    
    with execution_queue.mutex:
        execution_queue.queue.clear()
    
    print("--- 사용자 요청으로 스케줄러 중지. 대기열 비움. ---")
    return jsonify({"status": "유휴"})

import webbrowser

# --- Main Execution ---
if __name__ == '__main__':
    def open_browser():
        # Open a new browser tab to the specific URL
        webbrowser.open_new('http://127.0.0.1:5000')

    # Start the key-pressing worker thread
    worker_thread = threading.Thread(target=key_press_worker, daemon=True)
    worker_thread.start()

    # Start the custom scheduler thread
    scheduler = threading.Thread(target=custom_scheduler_thread, daemon=True)
    scheduler.start()
    
    print("--- Flask 서버 및 커스텀 스케줄러/작업자 시작 ---")
    print("웹 브라우저를 열고 http://127.0.0.1:5000 으로 이동하세요.")
    
    # Open the web browser 1 second after the app starts
    Timer(1, open_browser).start()
    
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)