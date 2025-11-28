import cv2
import numpy as np
import sys
import time
import threading
import senxor.proc
from sec100Client import sec100Client

# ==========================================
# 1. PASTE YOUR CALIBRATION MATRIX HERE
# ==========================================
# Replace these numbers with the output from your calibration tool
# ALIGNMENT_MATRIX = np.array([
#     [-1.79000000e+00, -2.19211777e-16,  4.55200000e+02],
#  [ 2.19211777e-16, -1.79000000e+00,  2.29400000e+02]
# ], dtype=np.float32)

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

# Overlay Opacity (0.0 = Invisible, 0.5 = 50% blend, 1.0 = Thermal only)
OVERLAY_OPACITY = 0.6 

# Thermal Settings
TEMP_UNIT = "C"
EMISSIVITY = 95

WINDOW_NAME = "SpectraSense Fused Stream"

# ==========================================
# HELPER: ZERO-LAG THREADED CAMERA
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
    # 1. SETUP THERMAL CAMERA
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

    # ---------------------------------------------------------
    # 2. SETUP VISIBLE CAMERA (Optimized)
    # ---------------------------------------------------------
    print("--- Initializing Visible Camera ---")
    threaded_cam = None
    
    try:
        sec100 = sec100Client(SEC_IP, SEC_USER, SEC_PASS)
        
        # Optimize Resolution for Speed (720p)
        try:
            sec100.setVideo0ImageResolution(sec100.ImageSize.IMAGE_1280x720)
            sec100.setVideo0FrameRate(30)
            time.sleep(1.5)
        except:
            pass

        # Construct URL
        try:
            rtsp_port = sec100.getRtspPort()
            rtsp_path = sec100.getVideo0RtspPath()
            if rtsp_path.startswith('/'): rtsp_path = rtsp_path[1:]
        except:
            rtsp_port = 554
            rtsp_path = "live/0"

        rtsp_url = f"rtsp://{SEC_USER}:{SEC_PASS}@{SEC_IP}:{rtsp_port}/{rtsp_path}"
        print(f"Connecting to: {rtsp_url}")
        
        threaded_cam = ThreadedCamera(rtsp_url)
        time.sleep(1) # Warmup

        if not threaded_cam.status:
            print("Failed to open RTSP stream.")
            sys.exit(1)

    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)

    # ---------------------------------------------------------
    # 3. MAIN LOOP
    # ---------------------------------------------------------
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    print("\nSystem Running. Press 'q' to quit.")

    try:
        while True:
            # 1. Get Frames
            vis_ret, frame_vis = threaded_cam.get_frame()
            therm_head, frame_therm = dev_therm.read()

            if not vis_ret or frame_vis is None:
                continue
            if frame_therm is None:
                continue

            # 2. Process Thermal (Colorize)
            uint8_therm = senxor.proc.normalize(frame_therm, dtype=np.uint8)
            cmap = senxor.proc.get_colormaps("inferno", "cv")
            colored_therm = senxor.proc.apply_colormap(uint8_therm, lut=cmap)
            therm_bgr = cv2.cvtColor(colored_therm, cv2.COLOR_RGB2BGR)
            therm_bgr = cv2.flip(therm_bgr, 1)

            # 3. Apply Alignment (The Magic Step)
            # We use the visible frame's dimensions as the target size
            h_vis, w_vis = frame_vis.shape[:2]
            
            aligned_therm = cv2.warpAffine(
                therm_bgr, 
                ALIGNMENT_MATRIX, 
                (w_vis, h_vis)
            )

            # 4. Blend Over
            # weighted sum: src1 * alpha + src2 * beta + gamma
            fused_image = cv2.addWeighted(
                frame_vis, 1.0, 
                aligned_therm, OVERLAY_OPACITY, 
                0
            )

            # 5. Display
            # Optional: Resize if it's too big for your screen
            disp_h, disp_w = fused_image.shape[:2]
            if disp_w > 1280:
                scale = 1280 / disp_w
                display_img = cv2.resize(fused_image, (0,0), fx=scale, fy=scale)
            else:
                display_img = fused_image

            cv2.imshow(WINDOW_NAME, display_img)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    finally:
        if threaded_cam: threaded_cam.stop()
        dev_therm.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()