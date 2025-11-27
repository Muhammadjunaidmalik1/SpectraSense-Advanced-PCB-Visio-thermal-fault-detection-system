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
# 1. CONFIGURATION
# ==========================================
MODEL_PATH = "./checkpoints/best_epoch_200.pt"  
TEMP_UNIT = "C"
EMISSIVITY = 95
OVERLAY_OPACITY = 0.5   

CLASS_NAME_IRON = 'Chip' 
CLASS_NAME_CHIP = 'soldering_iron'

# --- LOGIC THRESHOLDS ---
RECORD_MIN_DURATION = 10.0  # Seconds
WAIT_FOR_TRIGGER = 1.0      # Seconds
TEMP_THRESHOLD = 250.0      # Degrees C
OVER_TEMP_LIMIT = 300.0     # Degrees C (Flashing Alarm)

# --- PERFORMANCE ---
RECORD_FPS = 10.0      
SKIP_FRAMES = 3        

# --- UI SETTINGS ---
BAR_MIN = 20.0
BAR_MAX = 350.0
BAR_WIDTH = 250
BAR_HEIGHT = 20

OUTPUT_FOLDER = "recordings"
SEC_IP = "192.168.136.100"
SEC_USER = "Service"
SEC_PASS = "servicelevel"

ALIGNMENT_MATRIX = np.array([
    [-5.12000000e+00, -6.27019161e-16,  1.34760000e+03],
    [ 6.27019161e-16, -5.12000000e+00,  6.73200000e+02]
], dtype=np.float32)

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def check_intersection(box1, box2):
    x1_max = max(box1[0], box2[0])
    y1_max = max(box1[1], box2[1])
    x2_min = min(box1[2], box2[2])
    y2_min = min(box1[3], box2[3])
    return (x2_min > x1_max) and (y2_min > y1_max)

def get_thermal_bbox(matrix, therm_w, therm_h, rgb_w, rgb_h):
    corners_therm = np.array([[0, 0],[therm_w, 0],[therm_w, therm_h],[0, therm_h]], dtype=np.float32)
    corners_transformed = cv2.transform(np.array([corners_therm]), matrix)[0]
    return cv2.boundingRect(corners_transformed)

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
            time.sleep(0.001)

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
    # --- SETUP CAMERAS ---
    if not senxor.list_senxor(): 
        print("Senxor not found")
        sys.exit(1)
    dev_therm = senxor.connect()
    dev_therm.fields.EMISSIVITY.set(EMISSIVITY)
    dev_therm.set_read_temp_units(TEMP_UNIT)
    dev_therm.start_stream()

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
        print("Camera failed.")
        sys.exit(1)

    # --- LOAD YOLO ---
    try:
        model = YOLO(MODEL_PATH)
        print("Model loaded.")
    except Exception as e:
        print(f"Error loading model: {e}"); sys.exit(1)

    # --- CALCULATE CROP ---
    print("Aligning streams...")
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

    # --- VARIABLES ---
    intersection_start_time = None
    is_recording = False
    recording_start_timestamp = 0
    video_writer = None
    temp_file = None
    
    frame_counter = 0
    last_annotated_crop = None
    last_results_boxes = []

    cv2.namedWindow("System UI", cv2.WINDOW_NORMAL)
    print("\n--- SYSTEM READY ---")
    print(f"Trigger: Contact > {WAIT_FOR_TRIGGER}s AND Temp > {TEMP_THRESHOLD}C")
    
    try:
        while True:
            vis_ret, frame_vis = threaded_cam.get_frame()
            _, frame_therm = dev_therm.read()

            if not vis_ret or frame_vis is None: continue

            final_rgb = frame_vis[y_start:y_end, x_start:x_end]
            
            # ---------------------------------------
            # 1. OPTIMIZED AI INFERENCE
            # ---------------------------------------
            frame_counter += 1
            if frame_counter % SKIP_FRAMES == 0 or last_annotated_crop is None:
                # Run YOLO
                results = model(final_rgb, conf=0.40, verbose=False)
                last_annotated_crop = results[0].plot()
                last_results_boxes = results[0].boxes
            
            # Use cached frame for display speed
            annotated_crop = last_annotated_crop

            # ---------------------------------------
            # 2. THERMAL PROCESSING
            # ---------------------------------------
            max_temp_val = 0.0
            vis_crop = None
            if frame_therm is not None:
                # Calculate Max Temp (Raw Data)
                raw_aligned = cv2.warpAffine(frame_therm, ALIGNMENT_MATRIX, (vis_w, vis_h), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
                raw_crop = raw_aligned[y_start:y_end, x_start:x_end]
                max_temp_val = np.max(raw_crop)

                # Visual Overlay
                uint8_therm = senxor.proc.normalize(frame_therm, dtype=np.uint8)
                colored_therm = senxor.proc.apply_colormap(uint8_therm, lut=senxor.proc.get_colormaps("inferno", "cv"))
                therm_bgr = cv2.cvtColor(colored_therm, cv2.COLOR_RGB2BGR)
                therm_bgr = cv2.flip(therm_bgr, 1)
                vis_aligned = cv2.warpAffine(therm_bgr, ALIGNMENT_MATRIX, (vis_w, vis_h), flags=cv2.INTER_LANCZOS4)
                vis_crop = vis_aligned[y_start:y_end, x_start:x_end]
                
                # Blend
                display_image = cv2.addWeighted(annotated_crop, 1.0, vis_crop, OVERLAY_OPACITY, 0)
            else:
                display_image = annotated_crop

            # ---------------------------------------
            # 3. INTERSECTION CHECK
            # ---------------------------------------
            list_irons = []
            list_chips = []
            
            # Parse Boxes
            for box in last_results_boxes:
                cls_id = int(box.cls[0])
                cls_name = model.names[cls_id]
                coords = box.xyxy[0].cpu().numpy()
                if cls_name == CLASS_NAME_IRON: list_irons.append(coords)
                elif cls_name == CLASS_NAME_CHIP: list_chips.append(coords)

            # Check Logic
            intersecting = False
            for iron in list_irons:
                for chip in list_chips:
                    if check_intersection(iron, chip):
                        intersecting = True
                        break
                if intersecting: break

            # ---------------------------------------
            # 4. RECORDING STATE MACHINE
            # ---------------------------------------
            status_text = "Status: IDLE"
            
            if not is_recording:
                # --- IDLE STATE ---
                if intersecting:
                    if intersection_start_time is None:
                        intersection_start_time = time.time()
                    elapsed_contact = time.time() - intersection_start_time
                    
                    if max_temp_val <= TEMP_THRESHOLD:
                        status_text = f"Status: Heating ({max_temp_val:.0f}C)"
                    else:
                        status_text = f"Status: Pre-Trigger ({elapsed_contact:.1f}s)"

                    # *** TRIGGER CONDITION ***
                    if (elapsed_contact >= WAIT_FOR_TRIGGER) and (max_temp_val > TEMP_THRESHOLD):
                        is_recording = True
                        recording_start_timestamp = time.time()
                        intersection_start_time = None
                        
                        # Init Recorder
                        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                        vid_path = os.path.join(OUTPUT_FOLDER, f"rec_{ts_str}.avi")
                        csv_path = os.path.join(OUTPUT_FOLDER, f"temp_{ts_str}.csv")
                        
                        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
                        video_writer = cv2.VideoWriter(vid_path, fourcc, RECORD_FPS, (x_end-x_start, y_end-y_start))
                        temp_file = open(csv_path, "w")
                        temp_file.write("Timestamp,Max_Temp_C\n")
                        print(f"--- TRIGGERED: {vid_path} ---")
                else:
                    intersection_start_time = None 
            else:
                # --- RECORDING STATE ---
                elapsed_rec_time = time.time() - recording_start_timestamp
                
                # Write Data
                if video_writer: video_writer.write(display_image)
                if temp_file:
                    t_stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    temp_file.write(f"{t_stamp},{max_temp_val:.2f}\n")

                if elapsed_rec_time < RECORD_MIN_DURATION:
                    status_text = "Status: RECORDING (Minimum Lock)"
                else:
                    if intersecting:
                        status_text = "Status: RECORDING (Extended)"
                        # Flashing Warning
                        if int(time.time() * 2) % 2 == 0:
                            cv2.putText(display_image, "SOLDERING TOO LONG!", (50, 300), 
                                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
                    else:
                        # STOP
                        is_recording = False
                        video_writer.release()
                        temp_file.close()
                        video_writer = None
                        temp_file = None
                        status_text = "Status: SAVED"
                        print("--- STOPPED ---")

            # ---------------------------------------
            # 5. UI OVERLAY (On Top of Everything)
            # ---------------------------------------
            # White Panel (Top Left)
            overlay = display_image.copy()
            cv2.rectangle(overlay, (0, 0), (320, 140), (255, 255, 255), -1) 
            cv2.addWeighted(overlay, 0.7, display_image, 0.3, 0, display_image)

            # Text Labels (Black)
            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(display_image, timestamp_str, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
            cv2.putText(display_image, status_text, (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

            # Temp Bar
            bar_x, bar_y = 10, 75
            cv2.rectangle(display_image, (bar_x, bar_y), (bar_x + BAR_WIDTH, bar_y + BAR_HEIGHT), (200, 200, 200), -1)
            
            clamp_temp = max(BAR_MIN, min(max_temp_val, BAR_MAX))
            fill_ratio = (clamp_temp - BAR_MIN) / (BAR_MAX - BAR_MIN)
            fill_width = int(BAR_WIDTH * fill_ratio)
            
            bar_color = (0, 255, 0)
            if max_temp_val > 150: bar_color = (0, 165, 255)
            if max_temp_val > 250: bar_color = (0, 0, 255)

            if fill_width > 0:
                cv2.rectangle(display_image, (bar_x, bar_y), (bar_x + fill_width, bar_y + BAR_HEIGHT), bar_color, -1)
            cv2.rectangle(display_image, (bar_x, bar_y), (bar_x + BAR_WIDTH, bar_y + BAR_HEIGHT), (0, 0, 0), 1)

            cv2.putText(display_image, f"{int(BAR_MIN)}C", (bar_x, bar_y + BAR_HEIGHT + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,0,0), 1)
            cv2.putText(display_image, f"{int(BAR_MAX)}C", (bar_x + BAR_WIDTH - 30, bar_y + BAR_HEIGHT + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,0,0), 1)
            cv2.putText(display_image, f"Max: {max_temp_val:.1f}C", (bar_x + 80, bar_y + BAR_HEIGHT + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,0), 2)

            # Over Temp Alarm
            if max_temp_val > OVER_TEMP_LIMIT:
                if int(time.time() * 5) % 2 == 0:
                    cv2.putText(display_image, "OVER TEMP!", (10, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            cv2.imshow("System UI", display_image)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    finally:
        if video_writer: video_writer.release()
        if temp_file: temp_file.close()
        if threaded_cam: threaded_cam.stop()
        dev_therm.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()