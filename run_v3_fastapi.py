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

# --- FASTAPI IMPORTS ---
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()

# Allow CORS so your frontend (React/Vue/HTML) can access data from any port
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# SHARED STATE
# ==========================================
video_frame = None
telemetry_data = {
    "system_status": "IDLE",      # IDLE, PRE-TRIGGER, RECORDING, SAVING
    "timestamp": "",
    "max_temp": 0.0,
    "temp_state": "LOW",          # LOW (Blue), GOOD (Green), HIGH (Red)
    "timer": 0.0,                 # Seconds (for countdowns or duration)
    "warning": None,              # null, "LOW TEMP", "OVER TEMP", "TOO LONG"
    "is_recording": False,
    "video_path": ""
}
data_lock = threading.Lock()

# ==========================================
# CONFIGURATION
# ==========================================
MODEL_PATH = "./checkpoints/best_new_dataset.pt"  
TEMP_UNIT = "C"
EMISSIVITY = 95
OVERLAY_OPACITY = 0.5   

CLASS_NAME_IRON = 'soldering_iron' 
CLASS_NAME_CHIP = 'ic_chip'

# Logic Thresholds
RECORD_MIN_DURATION = 10.0
WAIT_FOR_TRIGGER = 1.0     
TEMP_THRESHOLD = 250.0  # < 250 = Low Temp (Blue)
OVER_TEMP_LIMIT = 300.0 # > 300 = Over Temp (Red)

# Performance
RECORD_FPS = 10.0      
SKIP_FRAMES = 3        

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
# LOGIC ENGINE
# ==========================================
def run_detection_logic():
    global video_frame, telemetry_data, data_lock

    # 1. Init Hardware
    if not senxor.list_senxor(): return
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

    try: rtsp_path = sec100.getVideo0RtspPath()
    except: rtsp_path = "live/0"
    if rtsp_path.startswith('/'): rtsp_path = rtsp_path[1:]
    
    rtsp_url = f"rtsp://{SEC_USER}:{SEC_PASS}@{SEC_IP}:554/{rtsp_path}"
    threaded_cam = ThreadedCamera(rtsp_url)
    time.sleep(1)
    if not threaded_cam.status: return

    # 2. Init AI
    try: model = YOLO(MODEL_PATH)
    except: return

    # 3. Init Crop
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

    # Variables
    intersection_start_time = None
    is_recording = False
    recording_start_timestamp = 0
    video_writer = None
    temp_file = None
    current_vid_path = ""
    
    frame_counter = 0
    last_annotated_crop = None
    last_results_boxes = []

    print("\n--- SYSTEM READY ---")
    print("Video: http://localhost:8000/video_feed")
    print("Data:  http://localhost:8000/telemetry")

    try:
        while True:
            vis_ret, frame_vis = threaded_cam.get_frame()
            _, frame_therm = dev_therm.read()

            if not vis_ret or frame_vis is None: continue

            final_rgb = frame_vis[y_start:y_end, x_start:x_end]
            
            # --- AI INFERENCE ---
            frame_counter += 1
            if frame_counter % SKIP_FRAMES == 0 or last_annotated_crop is None:
                results = model(final_rgb, conf=0.40, verbose=False)
                last_annotated_crop = results[0].plot() # Draw Boxes only
                last_results_boxes = results[0].boxes
            
            annotated_crop = last_annotated_crop

            # --- THERMAL ---
            max_temp_val = 0.0
            vis_crop = None
            if frame_therm is not None:
                raw_aligned = cv2.warpAffine(frame_therm, ALIGNMENT_MATRIX, (vis_w, vis_h), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
                raw_crop = raw_aligned[y_start:y_end, x_start:x_end]
                max_temp_val = np.max(raw_crop)

                uint8_therm = senxor.proc.normalize(frame_therm, dtype=np.uint8)
                colored_therm = senxor.proc.apply_colormap(uint8_therm, lut=senxor.proc.get_colormaps("inferno", "cv"))
                therm_bgr = cv2.cvtColor(colored_therm, cv2.COLOR_RGB2BGR)
                therm_bgr = cv2.flip(therm_bgr, 1)
                vis_aligned = cv2.warpAffine(therm_bgr, ALIGNMENT_MATRIX, (vis_w, vis_h), flags=cv2.INTER_LANCZOS4)
                vis_crop = vis_aligned[y_start:y_end, x_start:x_end]
                
                # Blend Heatmap onto RGB + Boxes
                display_image = cv2.addWeighted(annotated_crop, 1.0, vis_crop, OVERLAY_OPACITY, 0)
            else:
                display_image = annotated_crop

            # --- INTERSECTION ---
            list_irons = []
            list_chips = []
            for box in last_results_boxes:
                cls_id = int(box.cls[0])
                cls_name = model.names[cls_id]
                coords = box.xyxy[0].cpu().numpy()
                if cls_name == CLASS_NAME_IRON: list_irons.append(coords)
                elif cls_name == CLASS_NAME_CHIP: list_chips.append(coords)

            intersecting = False
            for iron in list_irons:
                for chip in list_chips:
                    if check_intersection(iron, chip):
                        intersecting = True; break
                if intersecting: break

            # --- LOGIC & DATA PACKAGING ---
            # Default Data State
            api_status = "IDLE"
            api_timer = 0.0
            api_warning = None
            
            # Determine Temp State (Blue/Green/Red)
            if max_temp_val < TEMP_THRESHOLD: api_temp_state = "LOW"
            elif max_temp_val <= OVER_TEMP_LIMIT: api_temp_state = "GOOD"
            else: 
                api_temp_state = "HIGH"
                api_warning = "OVER TEMP"

            if not is_recording:
                # IDLE / PRE-TRIGGER
                if intersecting:
                    if intersection_start_time is None:
                        intersection_start_time = time.time()
                    elapsed = time.time() - intersection_start_time
                    
                    api_status = "PRE-TRIGGER"
                    api_timer = elapsed

                    # Warning for Low Temp
                    if api_temp_state == "LOW":
                        api_warning = "LOW TEMP"

                    # TRIGGER
                    if elapsed >= WAIT_FOR_TRIGGER:
                        is_recording = True
                        recording_start_timestamp = time.time()
                        intersection_start_time = None
                        
                        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                        current_vid_path = os.path.join(OUTPUT_FOLDER, f"rec_{ts_str}.avi")
                        csv_path = os.path.join(OUTPUT_FOLDER, f"temp_{ts_str}.csv")
                        
                        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
                        video_writer = cv2.VideoWriter(current_vid_path, fourcc, RECORD_FPS, (x_end-x_start, y_end-y_start))
                        temp_file = open(csv_path, "w")
                        temp_file.write("Timestamp,Max_Temp_C\n")
                        print(f"--- STARTED: {current_vid_path} ---")
                else:
                    intersection_start_time = None 
            else:
                # RECORDING
                api_status = "RECORDING"
                elapsed = time.time() - recording_start_timestamp
                api_timer = elapsed

                # Low Temp Warning during recording
                if api_temp_state == "LOW":
                    api_warning = "LOW TEMP"

                # Save Data
                if video_writer: video_writer.write(display_image)
                if temp_file:
                    t_stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    temp_file.write(f"{t_stamp},{max_temp_val:.2f}\n")

                if elapsed >= RECORD_MIN_DURATION:
                    if intersecting:
                        api_warning = "TOO LONG" # Overrides other warnings
                    else:
                        is_recording = False
                        api_status = "SAVING"
                        video_writer.release()
                        temp_file.close()
                        video_writer = None; temp_file = None
                        current_vid_path = ""
                        print("--- STOPPED ---")

            # --- UPDATE SHARED DATA ---
            with data_lock:
                video_frame = display_image.copy() # Plain video (no text)
                
                # Update JSON Data
                telemetry_data["system_status"] = api_status
                telemetry_data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                telemetry_data["max_temp"] = round(float(max_temp_val), 1)
                telemetry_data["temp_state"] = api_temp_state
                telemetry_data["timer"] = round(float(api_timer), 1)
                telemetry_data["warning"] = api_warning
                telemetry_data["is_recording"] = is_recording
                telemetry_data["video_path"] = current_vid_path

    finally:
        if video_writer: video_writer.release()
        if temp_file: temp_file.close()
        if threaded_cam: threaded_cam.stop()
        dev_therm.close()

# ==========================================
# ENDPOINTS
# ==========================================
@app.get("/telemetry")
async def get_telemetry():
    """Returns JSON data for frontend rendering."""
    with data_lock:
        return telemetry_data

def generate_frames():
    global video_frame, data_lock
    while True:
        with data_lock:
            if video_frame is None:
                time.sleep(0.01); continue
            (flag, encodedImage) = cv2.imencode(".jpg", video_frame)
            if not flag: continue
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + bytearray(encodedImage) + b'\r\n')

@app.get("/video_feed")
async def video_feed():
    """Returns pure video stream (RGB + Boxes + Heatmap) without text overlays."""
    return StreamingResponse(generate_frames(), media_type="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    t = threading.Thread(target=run_detection_logic)
    t.daemon = True 
    t.start()
    uvicorn.run(app, host="0.0.0.0", port=8000)