import pygetwindow as gw
Worlds={
    "MapleStory Worlds-Mapleland (엘나스)",
    "MapleStory Worlds-Mapleland (리프레)",
    "MapleStory Worlds-Mapleland (루더스/니할)"
}


def find_game_window():
    for title in Worlds:
        windows = gw.getWindowsWithTitle(title)
        if windows:
            window = windows[0]
            CAPTURE_WIDTH = window.width
            CAPTURE_HEIGHT = window.height
            print(f"Detected game window size: {CAPTURE_WIDTH}x{CAPTURE_HEIGHT} for window: {title}")
            return window
    print("Game window not found.")
    return None