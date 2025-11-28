import cv2
import numpy as np
import sys
import time
import threading
import senxor.proc
from sec100Client import sec100Client

# ==========================================
# CONFIGURATION - Heps in calibration of RGB and Thermal cameras
# ==========================================
SEC_IP = "192.168.136.100"
SEC_USER = "Service"
SEC_PASS = "servicelevel"

# Thermal Settings
TEMP_UNIT = "C"
EMISSIVITY = 95

WINDOW_NAME = "Dual Stream Alignment Tool"

# ==========================================
# HELPER: THREADED CAMERA CLASS
# ==========================================
class ThreadedCamera:
    """
    Continuously reads frames from the camera in a separate thread.
    This prevents the RTSP buffer from filling up and causing lag.
    """
    def __init__(self, src):
        self.capture = cv2.VideoCapture(src)
        # Set buffer size to 1 to minimize internal buffering
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
                # Grab and retrieve the latest frame
                (self.status, self.frame) = self.capture.read()
            time.sleep(0.01) # Slight rest to save CPU

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
    # 1. INITIALIZE THERMAL CAMERA (Senxor)
    # ---------------------------------------------------------
    print("--- Connecting to Thermal Camera ---")
    addrs = senxor.list_senxor()
    if not addrs:
        print("No Senxor thermal camera found.")
        sys.exit(1)
    
    dev_therm = senxor.connect()
    if not dev_therm.is_connected:
        print("Failed to connect to Senxor.")
        sys.exit(1)
        
    try:
        dev_therm.fields.EMISSIVITY.set(EMISSIVITY)
        dev_therm.set_read_temp_units(TEMP_UNIT)
        dev_therm.start_stream()
        print("Thermal stream started.")
    except Exception as e:
        print(f"Error configuring thermal: {e}")

    # ---------------------------------------------------------
    # 2. INITIALIZE VISIBLE CAMERA (Sec100)
    # ---------------------------------------------------------
    print("--- Connecting to Visible Camera (Sec100) ---")
    threaded_cam = None
    
    try:
        sec100 = sec100Client(SEC_IP, SEC_USER, SEC_PASS)
        
        # --- OPTIMIZATION 1: Set Resolution to 720p or 1080p ---
        # Reducing resolution massively reduces decoding latency
        try:
            print("Optimizing camera resolution for low latency (1280x720)...")
            # Using ImageSize Enum: 4 = 1280x720, 5 = 1920x1080
            target_res = sec100.ImageSize.IMAGE_1920x1080
            sec100.setVideo0ImageResolution(target_res)
            
            # Also ensure Frame Rate is decent (e.g., 30 or 60)
            sec100.setVideo0FrameRate(30)

            # --- OPTIONAL: Set Encoder Bitrate if needed ---
            #bitrate_val = sec100.VideoCompressionRate.COMPRESSION_RATE_8191
            #sec100.setVideo0EncoderBitrate(bitrate_val)
            #print(f"Video Bitrate set to: {bitrate_val.name}")    


            time.sleep(2) # Allow camera to re-sync
        except Exception as e:
            print(f"Warning: Could not set resolution ({e}). Proceeding with defaults.")

        # Get Connection Details
        try:
            rtsp_port = sec100.getRtspPort()
            rtsp_path = sec100.getVideo0RtspPath()
        except:
            rtsp_port = 554
            rtsp_path = "live/0"

        # Clean Path
        if rtsp_path.startswith('/'):
            rtsp_path = rtsp_path[1:]

        # Build URL
        rtsp_url = f"rtsp://{SEC_USER}:{SEC_PASS}@{SEC_IP}:{rtsp_port}/{rtsp_path}"
        print(f"Connecting to: {rtsp_url}")
        
        # --- OPTIMIZATION 2: Use Threaded Capture ---
        threaded_cam = ThreadedCamera(rtsp_url)
        
        # Wait briefly for first frame
        time.sleep(1)
        ret, test_frame = threaded_cam.get_frame()
        if not ret or test_frame is None:
            print("Error: Could not start RTSP stream.")
            sys.exit(1)
        else:
            print("Visible camera connected with Low Latency Threading!")
            
    except Exception as e:
        print(f"Critical Error connecting to Sec100: {e}")
        if threaded_cam: threaded_cam.stop()
        sys.exit(1)

    # ---------------------------------------------------------
    # 3. SETUP GUI
    # ---------------------------------------------------------
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    
    cv2.createTrackbar("Scale (x0.01)", WINDOW_NAME, 100, 1000, nothing) 
    cv2.createTrackbar("Rotation (deg)", WINDOW_NAME, 180, 360, nothing) 
    cv2.createTrackbar("X Offset", WINDOW_NAME, 1000, 2000, nothing)     
    cv2.createTrackbar("Y Offset", WINDOW_NAME, 1000, 2000, nothing)     
    cv2.createTrackbar("Opacity %", WINDOW_NAME, 50, 100, nothing)       

    print("\nControls:")
    print(" - Adjust sliders to align feeds.")
    print(" - Press 'q' to quit.")

    transformation_matrix = None

    while True:
        # --- Read Frames ---
        # Get latest visible frame from thread
        ret_vis, frame_vis = threaded_cam.get_frame()
        
        # Read thermal frame directly
        header_therm, frame_therm = dev_therm.read()

        if not ret_vis or frame_vis is None:
            time.sleep(0.01)
            continue
        
        if frame_therm is None:
            continue

        # --- Process Thermal Image ---
        uint8_therm = senxor.proc.normalize(frame_therm, dtype=np.uint8)
        cmap_cv_inferno = senxor.proc.get_colormaps("inferno", "cv")
        colored_therm = senxor.proc.apply_colormap(uint8_therm, lut=cmap_cv_inferno)
        therm_bgr = cv2.cvtColor(colored_therm, cv2.COLOR_RGB2BGR)
        therm_bgr = cv2.flip(therm_bgr, 1)

        h_vis, w_vis = frame_vis.shape[:2]
        h_therm, w_therm = therm_bgr.shape[:2]

        # --- Calculate Matrix ---
        scale_val = cv2.getTrackbarPos("Scale (x0.01)", WINDOW_NAME) / 100.0
        rot_val = cv2.getTrackbarPos("Rotation (deg)", WINDOW_NAME) - 180
        x_off_val = cv2.getTrackbarPos("X Offset", WINDOW_NAME) - 1000
        y_off_val = cv2.getTrackbarPos("Y Offset", WINDOW_NAME) - 1000
        alpha_val = cv2.getTrackbarPos("Opacity %", WINDOW_NAME) / 100.0

        if scale_val == 0: scale_val = 0.01

        center_therm = (w_therm // 2, h_therm // 2)
        vis_center_x, vis_center_y = w_vis // 2, h_vis // 2

        M = cv2.getRotationMatrix2D(center_therm, rot_val, scale_val)
        M[0, 2] += (vis_center_x - center_therm[0]) + x_off_val
        M[1, 2] += (vis_center_y - center_therm[1]) + y_off_val
        
        transformation_matrix = M

        # --- Warp and Blend ---
        warped_therm = cv2.warpAffine(therm_bgr, M, (w_vis, h_vis))
        overlay = cv2.addWeighted(frame_vis, 1.0, warped_therm, alpha_val, 0)

        # --- Display ---
        # Resize only for display purposes if the window is huge
        display_h, display_w = overlay.shape[:2]
        if display_w > 1280:
            scale_disp = 1280 / display_w
            display_img = cv2.resize(overlay, (0,0), fx=scale_disp, fy=scale_disp)
        else:
            display_img = overlay

        cv2.imshow(WINDOW_NAME, display_img)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # ---------------------------------------------------------
    # 4. CLEANUP
    # ---------------------------------------------------------
    if threaded_cam: threaded_cam.stop()
    dev_therm.close()
    cv2.destroyAllWindows()

    print("\n" + "="*40)
    print("CALIBRATION COMPLETE")
    print("="*40)
    print("Transformation Matrix:")
    if transformation_matrix is not None:
        print(np.array2string(transformation_matrix, separator=', '))
    else:
        print("No matrix generated.")
    print("="*40)

if __name__ == "__main__":
    main()