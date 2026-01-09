import cv2
import numpy as np
from PIL import ImageGrab

# --- DEBUG FLAG ---
# Set to True to save intermediate images for debugging.
DEBUG = False

# --- Yellow Color Detection Range in HSV ---
# The original code had a bug where the range was set for Red (Hue 0-10)
# instead of Yellow. This range is corrected to be around Hue 25-35.
LOWER_YELLOW = np.array([25, 150, 150])
UPPER_YELLOW = np.array([35, 255, 255])

def find_character_position(minimap_coords):
    """
    Detects the character's position by finding a yellow dot within the given
    absolute screen coordinates of the minimap.

    Args:
        minimap_coords (dict): A dictionary with absolute screen coordinates
                               ("x", "y", "width", "height").

    Returns:
        tuple: (x, y) coordinates of the character's center, relative to the
               minimap's top-left corner. Returns None if not found.
    """
    if not minimap_coords:
        return None

    # The coordinates are already absolute screen coordinates.
    minimap_bbox = (
        minimap_coords["x"],
        minimap_coords["y"],
        minimap_coords["x"] + minimap_coords["width"],
        minimap_coords["y"] + minimap_coords["height"]
    )

    try:
        screenshot = ImageGrab.grab(bbox=minimap_bbox)
        minimap_image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    except Exception as e:
        print(f"오류: 미니맵 영역을 캡처할 수 없습니다: {e}")
        return None

    if DEBUG:
        cv2.imwrite("debug_minimap.png", minimap_image)

    hsv_image = cv2.cvtColor(minimap_image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv_image, LOWER_YELLOW, UPPER_YELLOW)

    if DEBUG:
        cv2.imwrite("debug_mask.png", mask)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if contours and cv2.contourArea(max(contours, key=cv2.contourArea)) > 5:
        largest_contour = max(contours, key=cv2.contourArea)
        
        M = cv2.moments(largest_contour)
        if M["m00"] != 0:
            center_x = int(M["m10"] / M["m00"])
            center_y = int(M["m01"] / M["m00"])
            
            if DEBUG:
                cv2.drawContours(minimap_image, [largest_contour], -1, (0, 255, 0), 1)
                cv2.circle(minimap_image, (center_x, center_y), 3, (0, 0, 255), -1)
                cv2.imwrite("debug_detected.png", minimap_image)

            return center_x, center_y

    if DEBUG:
        # This will save the image even if no contour is found
        cv2.imwrite("debug_detected.png", minimap_image)
        
    return None