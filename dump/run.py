import cv2
import numpy as np
import sys
import time
import threading
from ultralytics import YOLO
import senxor.proc
from sec100Client import sec100Client

# ==========================================
# 1. CONFIGURATION
# ==========================================
MODEL_PATH = "./checkpoints/best.pt"  # Your trained model
TEMP_UNIT = "C"
EMISSIVITY = 95
OVERLAY_OPACITY = 0.5   # Opacity of thermal overlay on detection window

# Camera Credentials
SEC_IP = "192.168.136.100"
SEC_USER = "Service"
SEC_PASS = "servicelevel"

# Alignment Matrix (Strictly for 1080p)
ALIGNMENT_MATRIX = np.array([
    [-5.12000000e+00, -6.27019161e-16,  1.34760000e+03],
    [ 6.27019161e-16, -5.12000000e+00,  6.73200000e+02]
], dtype=np.float32)

# ==========================================
# HELPER: GET VALID THERMAL AREA
# ==========================================
def get_thermal_bbox(matrix, therm_w, therm_h, rgb_w, rgb_h):
    corners_therm = np.array([
        [0, 0],
        [therm_w, 0],
        [therm_w, therm_h],
        [0, therm_h]
    ], dtype=np.float32)

    corners_transformed = cv2.transform(np.array([corners_therm]), matrix)[0]
    x, y, w, h = cv2.boundingRect(corners_transformed)
    return x, y, w, h

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

    def stop(self):
        self.is_running = False
        self.thread.join()
        self.capture.release()
    
    def get_frame(self):
        return self.status, self.frame

# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    # ---------------------------------------------------------
    # 1. SETUP CAMERAS (1080p to match Alignment Matrix)
    # ---------------------------------------------------------
    print("--- Initializing Thermal Camera ---")
    if not senxor.list_senxor():
        print("Error: Senxor camera not found.")
        sys.exit(1)
    
    dev_therm = senxor.connect()
    dev_therm.fields.EMISSIVITY.set(EMISSIVITY)
    dev_therm.set_read_temp_units(TEMP_UNIT)
    dev_therm.start_stream()

    print("--- Initializing Visible Camera (1080p) ---")
    sec100 = sec100Client(SEC_IP, SEC_USER, SEC_PASS)
    
    # Force 1080p because the Matrix depends on it
    try:
        sec100.setVideo0ImageResolution(sec100.ImageSize.IMAGE_1920x1080)
        sec100.setVideo0FrameRate(30)
        time.sleep(1.5)
    except Exception as e:
        print(f"Warning setting resolution: {e}")

    # Get RTSP Stream 0
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

    # ---------------------------------------------------------
    # 2. LOAD YOLO MODEL
    # ---------------------------------------------------------
    print(f"--- Loading YOLO Model ({MODEL_PATH}) ---")
    try:
        model = YOLO(MODEL_PATH)
        print("Model loaded successfully.")
    except Exception as e:
        print(f"Error loading YOLO model: {e}")
        sys.exit(1)

    # ---------------------------------------------------------
    # 3. CALCULATE CROP REGION (Once)
    # ---------------------------------------------------------
    print("Waiting for frames to calculate crop region...")
    ret, frame_vis = threaded_cam.get_frame()
    _, frame_therm = dev_therm.read()
    
    while frame_vis is None or frame_therm is None:
        ret, frame_vis = threaded_cam.get_frame()
        _, frame_therm = dev_therm.read()
        time.sleep(0.1)

    vis_h, vis_w = frame_vis.shape[:2]
    therm_h, therm_w = frame_therm.shape[:2]

    # Calculate Box
    bx, by, bw, bh = get_thermal_bbox(ALIGNMENT_MATRIX, therm_w, therm_h, vis_w, vis_h)
    center_x = bx + bw // 2
    center_y = by + bh // 2

    # Calculate 640x640 Crop
    CROP_SIZE = 640
    HALF_SIZE = CROP_SIZE // 2
    x_start = max(0, center_x - HALF_SIZE)
    y_start = max(0, center_y - HALF_SIZE)
    x_end = min(vis_w, center_x + HALF_SIZE)
    y_end = min(vis_h, center_y + HALF_SIZE)

    print(f"Crop Configured: {x_end-x_start}x{y_end-y_start} at ({x_start}, {y_start})")

    # ---------------------------------------------------------
    # 4. DETECTION LOOP
    # ---------------------------------------------------------
    print("\n--- STARTING DETECTION ---")
    print("Showing 640x640 Crop with AI + Thermal")
    cv2.namedWindow("YOLO Detection (Cropped)", cv2.WINDOW_NORMAL)

    try:
        while True:
            # Get fresh frames
            vis_ret, frame_vis = threaded_cam.get_frame()
            _, frame_therm = dev_therm.read()

            if not vis_ret or frame_vis is None:
                continue

            # ---------------------------------------
            # A. PREPARE INPUT (CROP RGB)
            # ---------------------------------------
            # Extract only the 640x640 region of interest
            final_rgb = frame_vis[y_start:y_end, x_start:x_end]

            # ---------------------------------------
            # B. RUN YOLO ON CROP
            # ---------------------------------------
            # Run inference on the 640x640 crop
            results = model(final_rgb, verbose=False)
            
            # Draw boxes (annotated_crop is now the BGR image with boxes)
            annotated_crop = results[0].plot()

            # ---------------------------------------
            # C. ADD THERMAL OVERLAY (Optional)
            # ---------------------------------------
            if frame_therm is not None:
                # 1. Process Thermal
                uint8_therm = senxor.proc.normalize(frame_therm, dtype=np.uint8)
                cmap = senxor.proc.get_colormaps("inferno", "cv")
                colored_therm = senxor.proc.apply_colormap(uint8_therm, lut=cmap)
                therm_bgr = cv2.cvtColor(colored_therm, cv2.COLOR_RGB2BGR)
                therm_bgr = cv2.flip(therm_bgr, 1)

                # 2. Align Thermal to full 1080p
                aligned_therm = cv2.warpAffine(
                    therm_bgr, 
                    ALIGNMENT_MATRIX, 
                    (vis_w, vis_h), 
                    flags=cv2.INTER_LANCZOS4
                )

                # 3. Crop Thermal to same 640x640 region
                final_therm = aligned_therm[y_start:y_end, x_start:x_end]

                # 4. Blend: Annotated RGB + Thermal
                # This puts the thermal heatmap OVER the bounding boxes slightly
                # If you want boxes ON TOP of thermal, swap the order or apply opacity differently
                display_image = cv2.addWeighted(annotated_crop, 1.0, final_therm, OVERLAY_OPACITY, 0)
            else:
                display_image = annotated_crop

            # ---------------------------------------
            # D. DISPLAY
            # ---------------------------------------
            cv2.imshow("YOLO Detection (Cropped)", display_image)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    finally:
        if threaded_cam: threaded_cam.stop()
        dev_therm.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()