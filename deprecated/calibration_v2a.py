import cv2
import numpy as np
import sys
import time
import threading
import os
import senxor.proc
from sec100Client import sec100Client

# ==========================================
# CONFIGURATION
# ==========================================
SEC_IP = "192.168.136.100"
SEC_USER = "Service"
SEC_PASS = "servicelevel"

# Thermal Settings
TEMP_UNIT = "C"
EMISSIVITY = 95

WINDOW_NAME = "Reverse Alignment (RGB -> Thermal)"

# ==========================================
# THREADED CAMERA (TCP FIX INCLUDED)
# ==========================================
class ThreadedCamera:
    def __init__(self, src):
        # Force TCP to avoid artifacts
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
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

def nothing(x):
    pass

def main():
    # ---------------------------------------------------------
    # 1. INITIALIZE CAMERAS
    # ---------------------------------------------------------
    print("--- Connecting to Thermal (Base) ---")
    dev_therm = senxor.connect()
    if not dev_therm.is_connected: sys.exit(1)
    dev_therm.fields.EMISSIVITY.set(EMISSIVITY)
    dev_therm.set_read_temp_units(TEMP_UNIT)
    dev_therm.start_stream()

    print("--- Connecting to RGB (Overlay) ---")
    sec100 = sec100Client(SEC_IP, SEC_USER, SEC_PASS)
    try:
        # We still use 720p, but we will shrink it later
        sec100.setVideo0ImageResolution(sec100.ImageSize.IMAGE_1280x720)
        sec100.setVideo0FrameRate(30)
        time.sleep(1.0)
    except: pass

    try:
        rtsp_port = sec100.getRtspPort()
        rtsp_path = sec100.getVideo0RtspPath()
        if rtsp_path.startswith('/'): rtsp_path = rtsp_path[1:]
    except:
        rtsp_port = 554; rtsp_path = "live/0"

    rtsp_url = f"rtsp://{SEC_USER}:{SEC_PASS}@{SEC_IP}:{rtsp_port}/{rtsp_path}"
    cam_vis = ThreadedCamera(rtsp_url)
    time.sleep(2) # Warmup

    # ---------------------------------------------------------
    # 2. SETUP GUI
    # ---------------------------------------------------------
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    
    # Scale Slider: 100 = 10% (0.1x), 1000 = 100% (1.0x)
    # Since RGB is huge, you likely need a scale around 10-20%
    cv2.createTrackbar("Scale (x0.001)", WINDOW_NAME, 150, 1000, nothing) 
    cv2.createTrackbar("Rotation (deg)", WINDOW_NAME, 180, 360, nothing) 
    
    # Offsets allow moving the RGB image around
    cv2.createTrackbar("X Offset", WINDOW_NAME, 1000, 2000, nothing)     
    cv2.createTrackbar("Y Offset", WINDOW_NAME, 1000, 2000, nothing)     
    cv2.createTrackbar("Opacity %", WINDOW_NAME, 50, 100, nothing)       

    print("\n CONTROLS:")
    print(" - Scale is now very sensitive (for shrinking RGB).")
    print(" - Press 'q' to save the REVERSE matrix.")

    reverse_matrix = None

    while True:
        # Get Frames
        vis_ret, frame_vis = cam_vis.get_frame() # RGB (Huge)
        _, frame_therm = dev_therm.read()        # Thermal (Small) - BACKGROUND

        if not vis_ret or frame_vis is None: continue
        if frame_therm is None: continue

        # Prepare Background (Thermal)
        uint8_therm = senxor.proc.normalize(frame_therm, dtype=np.uint8)
        cmap = senxor.proc.get_colormaps("inferno", "cv")
        colored_therm = senxor.proc.apply_colormap(uint8_therm, lut=cmap)
        therm_bgr = cv2.cvtColor(colored_therm, cv2.COLOR_RGB2BGR)
        therm_bgr = cv2.flip(therm_bgr, 1)

        # Dimensions
        h_therm, w_therm = therm_bgr.shape[:2] # This is our Target Canvas
        h_vis, w_vis = frame_vis.shape[:2]     # This is our Source

        # Get Sliders
        # Scale: 0-1000 maps to 0.0-1.0 (We need to shrink)
        scale_val = cv2.getTrackbarPos("Scale (x0.001)", WINDOW_NAME) / 1000.0
        if scale_val == 0: scale_val = 0.001

        rot_val = cv2.getTrackbarPos("Rotation (deg)", WINDOW_NAME) - 180
        x_off_val = cv2.getTrackbarPos("X Offset", WINDOW_NAME) - 1000
        y_off_val = cv2.getTrackbarPos("Y Offset", WINDOW_NAME) - 1000
        alpha = cv2.getTrackbarPos("Opacity %", WINDOW_NAME) / 100.0

        # Calculate Matrix: Moving RGB center -> Thermal Center
        center_vis = (w_vis // 2, h_vis // 2)
        center_therm = (w_therm // 2, h_therm // 2)

        M = cv2.getRotationMatrix2D(center_vis, rot_val, scale_val)
        M[0, 2] += (center_therm[0] - center_vis[0]) + x_off_val
        M[1, 2] += (center_therm[1] - center_vis[1]) + y_off_val
        
        reverse_matrix = M

        # WARP RGB to fit Thermal Canvas
        # Note: dsize is now (w_therm, h_therm) - the small canvas!
        warped_vis = cv2.warpAffine(frame_vis, M, (w_therm, h_therm))

        # Blend
        overlay = cv2.addWeighted(therm_bgr, 1.0, warped_vis, alpha, 0)

        # DISPLAY ZOOM
        # Since the thermal image is likely tiny, we assume 5x zoom for display
        # so you can actually see what you are doing.
        display_zoom = 5 
        disp_h, disp_w = overlay.shape[:2]
        display_img = cv2.resize(overlay, (disp_w * display_zoom, disp_h * display_zoom), 
                                 interpolation=cv2.INTER_NEAREST)

        cv2.imshow(WINDOW_NAME, display_img)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # ---------------------------------------------------------
    # OUTPUT
    # ---------------------------------------------------------
    if cam_vis: cam_vis.stop()
    dev_therm.close()
    cv2.destroyAllWindows()

    print("\n" + "="*40)
    print("REVERSE CALIBRATION COMPLETE")
    print("="*40)
    print("Use this matrix to warp RGB images into Thermal coordinates.")
    print("Note: Your RGB images will be downscaled significantly.")
    print("")
    if reverse_matrix is not None:
        print("REVERSE_MATRIX = np.array([")
        print(f"    [{reverse_matrix[0,0]:.5f}, {reverse_matrix[0,1]:.5f}, {reverse_matrix[0,2]:.5f}],")
        print(f"    [{reverse_matrix[1,0]:.5f}, {reverse_matrix[1,1]:.5f}, {reverse_matrix[1,2]:.5f}]")
        print("], dtype=np.float32)")
    print("="*40)

if __name__ == "__main__":
    main()