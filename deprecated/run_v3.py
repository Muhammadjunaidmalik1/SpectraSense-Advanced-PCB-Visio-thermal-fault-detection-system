import cv2
import numpy as np
import sys
import time
import threading
import os
from datetime import datetime
from ultralytics import YOLO
import senxor.proc
from sec100Client import sec100Client

# ==========================================
# This script runs the yolo model on aligned RGB and Thermal streams,
# allows manual recording of video and temperature data for a fixed duration.
# ==========================================


# ==========================================
# CONFIGURATION
# ==========================================
MODEL_PATH = "./checkpoints/best_epoch_200.pt"   
TEMP_UNIT = "C"
EMISSIVITY = 95
OVERLAY_OPACITY = 0.5   

# Recording Settings
RECORD_DURATION = 10  # seconds
OUTPUT_FOLDER = "recordings"

# Camera Credentials
SEC_IP = "192.168.136.100"
SEC_USER = "Service"
SEC_PASS = "servicelevel"

# Alignment Matrix (1080p)
ALIGNMENT_MATRIX = np.array([
    [-5.12000000e+00, -6.27019161e-16,  1.34760000e+03],
    [ 6.27019161e-16, -5.12000000e+00,  6.73200000e+02]
], dtype=np.float32)

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

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

def get_thermal_bbox(matrix, therm_w, therm_h, rgb_w, rgb_h):
    corners_therm = np.array([[0, 0],[therm_w, 0],[therm_w, therm_h],[0, therm_h]], dtype=np.float32)
    corners_transformed = cv2.transform(np.array([corners_therm]), matrix)[0]
    return cv2.boundingRect(corners_transformed)

# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    # --- 1. SETUP CAMERAS ---
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
    try:
        sec100.setVideo0ImageResolution(sec100.ImageSize.IMAGE_1920x1080)
        sec100.setVideo0FrameRate(30)
        time.sleep(1.5)
    except: pass

    try:
        rtsp_path = sec100.getVideo0RtspPath()
        if rtsp_path.startswith('/'): rtsp_path = rtsp_path[1:]
        rtsp_port = sec100.getRtspPort()
    except:
        rtsp_port = 554; rtsp_path = "live/0"

    rtsp_url = f"rtsp://{SEC_USER}:{SEC_PASS}@{SEC_IP}:{rtsp_port}/{rtsp_path}"
    threaded_cam = ThreadedCamera(rtsp_url)
    time.sleep(1)

    if not threaded_cam.status:
        print("Failed to open RTSP stream.")
        sys.exit(1)

    # --- 2. LOAD YOLO MODEL ---
    print(f"--- Loading YOLO Model ({MODEL_PATH}) ---")
    try:
        model = YOLO(MODEL_PATH)
        print("Model loaded.")
    except Exception as e:
        print(f"Error loading model: {e}"); sys.exit(1)

    # --- 3. CALCULATE CROP ---
    print("Calculating crop...")
    ret, frame_vis = threaded_cam.get_frame()
    _, frame_therm = dev_therm.read()
    while frame_vis is None or frame_therm is None:
        ret, frame_vis = threaded_cam.get_frame()
        _, frame_therm = dev_therm.read()
        time.sleep(0.1)

    vis_h, vis_w = frame_vis.shape[:2]
    therm_h, therm_w = frame_therm.shape[:2]
    bx, by, bw, bh = get_thermal_bbox(ALIGNMENT_MATRIX, therm_w, therm_h, vis_w, vis_h)
    center_x, center_y = bx + bw // 2, by + bh // 2
    
    CROP_SIZE = 640
    x_start = max(0, center_x - CROP_SIZE // 2)
    y_start = max(0, center_y - CROP_SIZE // 2)
    x_end = min(vis_w, center_x + CROP_SIZE // 2)
    y_end = min(vis_h, center_y + CROP_SIZE // 2)

    # --- STATE VARIABLES ---
    is_recording = False
    recording_end_time = 0
    video_writer = None
    temp_file = None
    
    cv2.namedWindow("Manual Record", cv2.WINDOW_NORMAL)
    print("\n--- SYSTEM READY ---")
    print("Press 's' to START recording (10s).")
    print("Press 'q' to QUIT.")

    try:
        while True:
            vis_ret, frame_vis = threaded_cam.get_frame()
            _, frame_therm = dev_therm.read()

            if not vis_ret or frame_vis is None: continue

            # 1. Prepare Input (Crop)
            final_rgb = frame_vis[y_start:y_end, x_start:x_end]

            # 2. YOLO Inference (Visuals Only)
            results = model(final_rgb, conf=0.40, verbose=False)
            annotated_crop = results[0].plot()

            # --- INTERSECTION LOGIC (COMMENTED OUT) ---
            # box_iron = None
            # box_chip = None
            # for box in results[0].boxes:
            #     cls_id = int(box.cls[0])
            #     cls_name = model.names[cls_id]
            #     if cls_name == "soldering iron": box_iron = box.xyxy[0].cpu().numpy()
            #     elif cls_name == "ic chip": box_chip = box.xyxy[0].cpu().numpy()
            # if box_iron is not None and box_chip is not None and check_intersection(box_iron, box_chip):
            #      pass 
            # ------------------------------------------

            # 3. Thermal Processing
            max_temp_val = 0.0
            display_image = annotated_crop

            if frame_therm is not None:
                # A. Raw Data Warp (For accurate temp measurement)
                raw_aligned = cv2.warpAffine(
                    frame_therm, ALIGNMENT_MATRIX, (vis_w, vis_h), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=0
                )
                raw_crop = raw_aligned[y_start:y_end, x_start:x_end]
                
                # Get Max Temp in the crop area
                max_temp_val = np.max(raw_crop)

                # B. Visualization Warp (For display)
                uint8_therm = senxor.proc.normalize(frame_therm, dtype=np.uint8)
                colored_therm = senxor.proc.apply_colormap(uint8_therm, lut=senxor.proc.get_colormaps("inferno", "cv"))
                therm_bgr = cv2.cvtColor(colored_therm, cv2.COLOR_RGB2BGR)
                therm_bgr = cv2.flip(therm_bgr, 1)
                
                vis_aligned = cv2.warpAffine(therm_bgr, ALIGNMENT_MATRIX, (vis_w, vis_h), flags=cv2.INTER_LANCZOS4)
                vis_crop = vis_aligned[y_start:y_end, x_start:x_end]
                
                display_image = cv2.addWeighted(annotated_crop, 1.0, vis_crop, OVERLAY_OPACITY, 0)

            # 4. Recording Handling
            status_text = "Status: IDLE (Press 's')"
            color = (0, 255, 0)

            # Check Key Presses
            key = cv2.waitKey(1) & 0xFF

            # START RECORDING TRIGGER
            if key == ord('s') and not is_recording:
                is_recording = True
                ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                vid_path = os.path.join(OUTPUT_FOLDER, f"rec_{ts_str}.avi")
                txt_path = os.path.join(OUTPUT_FOLDER, f"temp_{ts_str}.txt")
                
                # Init Video Writer (MJPG)
                fourcc = cv2.VideoWriter_fourcc(*'MJPG')
                video_writer = cv2.VideoWriter(vid_path, fourcc, 30.0, (x_end-x_start, y_end-y_start))
                
                # Init Text File
                temp_file = open(txt_path, "w")
                temp_file.write("Timestamp,Max_Temp_C\n")
                
                recording_end_time = time.time() + RECORD_DURATION
                print(f"--- STARTED RECORDING: {vid_path} ---")

            # ACTIVE RECORDING LOOP
            if is_recording:
                status_text = f"REC: {int(recording_end_time - time.time())}s | Max Temp: {max_temp_val:.1f}C"
                color = (0, 0, 255)
                
                # Save Video Frame
                if video_writer:
                    video_writer.write(display_image)
                
                # Save Temperature Data
                if temp_file:
                    t_stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    temp_file.write(f"{t_stamp},{max_temp_val:.2f}\n")
                
                # Check Stop Condition
                if time.time() > recording_end_time:
                    print("--- Recording Finished ---")
                    is_recording = False
                    video_writer.release()
                    temp_file.close()
                    video_writer = None
                    temp_file = None

            elif key == ord('q'):
                break

            # UI Overlay
            cv2.putText(display_image, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            cv2.imshow("Manual Record", display_image)

    finally:
        if video_writer: video_writer.release()
        if temp_file: temp_file.close()
        if threaded_cam: threaded_cam.stop()
        dev_therm.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()