import cv2
import numpy as np
import sys
import time
import threading
import senxor.proc
from sec100Client import sec100Client

# ==========================================
# ALIGNMENT MATRIX - Add the alignment matrix obtained from calibration.py
# ==========================================
ALIGNMENT_MATRIX = np.array([
    [-3.8100000e+00, -4.6659043e-16,  9.2380000e+02],
    [ 4.6659043e-16, -3.8100000e+00,  4.8160000e+02]
], dtype=np.float32)

# ==========================================
# CONFIGURATION
# ==========================================
SEC_IP = "192.168.136.100"
SEC_USER = "Service"
SEC_PASS = "servicelevel"
OVERLAY_OPACITY = 0.6 
TEMP_UNIT = "C"
EMISSIVITY = 95
WINDOW_NAME = "SpectraSense Fused Stream"

# ==========================================
# MOUSE TRACKING GLOBALS
# ==========================================
mouse_x, mouse_y = -1, -1

def mouse_callback(event, x, y, flags, param):
    """Updates the global mouse coordinates when cursor moves"""
    global mouse_x, mouse_y
    if event == cv2.EVENT_MOUSEMOVE:
        mouse_x, mouse_y = x, y

# ==========================================
# HELPER: THREADED CAMERA
# ==========================================
class ThreadedCamera:
    def __init__(self, src):
        self.capture = cv2.VideoCapture(src)
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.daemon = True
        self.status = False
        self.frame = None
        self.is_running = False
        if self.capture.isOpened():
            self.status = True
            self.is_running = True
            self.thread.start()

    def update(self):
        while self.is_running:
            if self.capture.isOpened():
                (self.status, self.frame) = self.capture.read()
            time.sleep(0.005)

    def get_frame(self):
        return self.status, self.frame

    def stop(self):
        self.is_running = False
        self.thread.join()
        self.capture.release()

def main():
    # ---------------------------------------------------------
    # 1. SETUP CAMERAS
    # ---------------------------------------------------------
    print("--- Initializing Thermal Camera ---")
    if not senxor.list_senxor():
        print("Error: Senxor camera not found.")
        sys.exit(1)
    
    dev_therm = senxor.connect()
    try:
        dev_therm.fields.EMISSIVITY.set(EMISSIVITY)
        dev_therm.set_read_temp_units(TEMP_UNIT)
        dev_therm.start_stream()
    except Exception as e:
        print(f"Error configuring thermal: {e}")

    print("--- Initializing Visible Camera ---")
    threaded_cam = None
    try:
        sec100 = sec100Client(SEC_IP, SEC_USER, SEC_PASS)
        try:
            sec100.setVideo0ImageResolution(sec100.ImageSize.IMAGE_1280x720)
            sec100.setVideo0FrameRate(30)
            time.sleep(1.5)
        except: pass

        try:
            rtsp_port = sec100.getRtspPort()
            rtsp_path = sec100.getVideo0RtspPath()
            if rtsp_path.startswith('/'): rtsp_path = rtsp_path[1:]
        except:
            rtsp_port = 554; rtsp_path = "live/0"

        rtsp_url = f"rtsp://{SEC_USER}:{SEC_PASS}@{SEC_IP}:{rtsp_port}/{rtsp_path}"
        threaded_cam = ThreadedCamera(rtsp_url)
        time.sleep(1)
        if not threaded_cam.status:
            print("Failed to open RTSP stream.")
            sys.exit(1)

    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)

    # ---------------------------------------------------------
    # 2. SETUP WINDOW & CALLBACK
    # ---------------------------------------------------------
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    # Register the mouse callback to the window
    cv2.setMouseCallback(WINDOW_NAME, mouse_callback)
    
    print("\nSystem Running. Hover over image to see temperature.")
    print("Press 'q' to quit.")

    try:
        while True:
            vis_ret, frame_vis = threaded_cam.get_frame()
            _, frame_therm = dev_therm.read() # frame_therm is RAW FLOATS (Temps)

            if not vis_ret or frame_vis is None or frame_therm is None:
                continue

            # -------------------------------------
            # PROCESS 1: VISUAL (Color)
            # -------------------------------------
            uint8_therm = senxor.proc.normalize(frame_therm, dtype=np.uint8)
            cmap = senxor.proc.get_colormaps("inferno", "cv")
            colored_therm = senxor.proc.apply_colormap(uint8_therm, lut=cmap)
            therm_bgr = cv2.cvtColor(colored_therm, cv2.COLOR_RGB2BGR)
            therm_bgr = cv2.flip(therm_bgr, 1)

            h_vis, w_vis = frame_vis.shape[:2]
            
            # Warp the COLOR image for display
            aligned_therm_vis = cv2.warpAffine(therm_bgr, ALIGNMENT_MATRIX, (w_vis, h_vis))

            # -------------------------------------
            # PROCESS 2: RAW DATA (Temperature)
            # -------------------------------------
            # Flip raw data to match the flip we did on the visual image
            raw_therm_flipped = cv2.flip(frame_therm, 1)
            
            # Warp the RAW float data using the exact same matrix
            # We use INTER_NEAREST to avoid interpolating fake temperatures between pixels
            aligned_raw_therm = cv2.warpAffine(
                raw_therm_flipped, 
                ALIGNMENT_MATRIX, 
                (w_vis, h_vis),
                flags=cv2.INTER_NEAREST, 
                borderMode=cv2.BORDER_CONSTANT, 
                borderValue=-999 # Use impossible temp as background
            )

            # -------------------------------------
            # FUSION & DISPLAY
            # -------------------------------------
            fused_image = cv2.addWeighted(frame_vis, 1.0, aligned_therm_vis, OVERLAY_OPACITY, 0)

            # Get Cursor Temp
            cursor_text = "Temp: --.- C"
            if 0 <= mouse_x < w_vis and 0 <= mouse_y < h_vis:
                temp_at_cursor = aligned_raw_therm[mouse_y, mouse_x]
                if temp_at_cursor > -100: # Filter out the border/background
                    cursor_text = f"Temp: {temp_at_cursor:.1f} C"
                    
                    # Optional: Draw a small circle at cursor
                    cv2.circle(fused_image, (mouse_x, mouse_y), 5, (0, 255, 0), 1)

            # Draw Information Box at Top Right
            cv2.rectangle(fused_image, (w_vis - 200, 0), (w_vis, 50), (0, 0, 0), -1) # Black background
            cv2.putText(fused_image, cursor_text, (w_vis - 190, 35), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

            cv2.imshow(WINDOW_NAME, fused_image)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    finally:
        if threaded_cam: threaded_cam.stop()
        dev_therm.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
