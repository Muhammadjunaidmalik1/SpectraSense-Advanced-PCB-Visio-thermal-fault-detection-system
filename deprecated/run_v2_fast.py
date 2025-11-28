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
from fastapi.responses import StreamingResponse
import uvicorn

# Initialize FastAPI
app = FastAPI()

# Global variables for frame sharing
output_frame = None
lock = threading.Lock()

# ==========================================
# This is the script without the nuanced logics for soldering iron detection
# and includes FastAPI for video streaming.
# ==========================================

# ==========================================
# 1. CONFIGURATION
# ==========================================
MODEL_PATH = "./checkpoints/best_epoch_200.pt"  
TEMP_UNIT = "C"
EMISSIVITY = 95
OVERLAY_OPACITY = 0.5   

CLASS_NAME_IRON = 'Chip' 
CLASS_NAME_CHIP = 'soldering_iron'

RECORD_DURATION = 10     
WAIT_FOR_TRIGGER = 1.0   
COOLDOWN_DURATION = 20.0 
TEMP_THRESHOLD = 250.0   

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
# HELPER FUNCTIONS (Same as before)
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
            time.sleep(0.005)

    def stop(self):
        self.is_running = False
        self.thread.join()
        self.capture.release()
    
    def get_frame(self):
        return self.status, self.frame

# ==========================================
# PROCESSING LOOP (Background Thread)
# ==========================================
def run_detection_logic():
    global output_frame, lock

    # --- SETUP CAMERAS ---
    if not senxor.list_senxor(): sys.exit(1)
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
    intersection_start_time = None
    is_recording = False
    recording_end_time = 0
    last_recording_finish_time = 0
    
    video_writer = None
    temp_file = None
    
    print("\n--- SYSTEM READY ---")
    print("Streaming to http://localhost:8000/video_feed")

    try:
        while True:
            vis_ret, frame_vis = threaded_cam.get_frame()
            _, frame_therm = dev_therm.read()

            if not vis_ret or frame_vis is None: continue

            final_rgb = frame_vis[y_start:y_end, x_start:x_end]
            results = model(final_rgb, conf=0.40, verbose=False)
            annotated_crop = results[0].plot()

            max_temp_val = 0.0
            vis_crop = None
            
            if frame_therm is not None:
                raw_aligned = cv2.warpAffine(
                    frame_therm, ALIGNMENT_MATRIX, (vis_w, vis_h), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=0
                )
                raw_crop = raw_aligned[y_start:y_end, x_start:x_end]
                max_temp_val = np.max(raw_crop)

                uint8_therm = senxor.proc.normalize(frame_therm, dtype=np.uint8)
                colored_therm = senxor.proc.apply_colormap(uint8_therm, lut=senxor.proc.get_colormaps("inferno", "cv"))
                therm_bgr = cv2.cvtColor(colored_therm, cv2.COLOR_RGB2BGR)
                therm_bgr = cv2.flip(therm_bgr, 1)
                
                vis_aligned = cv2.warpAffine(therm_bgr, ALIGNMENT_MATRIX, (vis_w, vis_h), flags=cv2.INTER_LANCZOS4)
                vis_crop = vis_aligned[y_start:y_end, x_start:x_end]
                display_image = cv2.addWeighted(annotated_crop, 1.0, vis_crop, OVERLAY_OPACITY, 0)
            else:
                display_image = annotated_crop

            list_irons = []
            list_chips = []
            for box in results[0].boxes:
                cls_id = int(box.cls[0])
                cls_name = model.names[cls_id]
                coords = box.xyxy[0].cpu().numpy()
                if cls_name == CLASS_NAME_IRON: list_irons.append(coords)
                elif cls_name == CLASS_NAME_CHIP: list_chips.append(coords)

            intersecting = False
            for iron in list_irons:
                for chip in list_chips:
                    if check_intersection(iron, chip):
                        intersecting = True
                        break
                if intersecting: break

            if not is_recording:
                time_since_last_rec = time.time() - last_recording_finish_time
                in_cooldown = time_since_last_rec < COOLDOWN_DURATION

                if intersecting:
                    if intersection_start_time is None:
                        intersection_start_time = time.time()
                    elapsed = time.time() - intersection_start_time
                    
                    info_color = (0, 255, 255)
                    if in_cooldown: 
                        info_msg = f"Cooldown: {int(COOLDOWN_DURATION - time_since_last_rec)}s"
                        info_color = (0, 0, 255) 
                    elif max_temp_val <= TEMP_THRESHOLD:
                        info_msg = f"Wait Temp: {max_temp_val:.0f}/{TEMP_THRESHOLD}C"
                    else:
                        info_msg = f"Triggering in {max(0, WAIT_FOR_TRIGGER - elapsed):.1f}s"
                        info_color = (0, 255, 0) 

                    cv2.putText(display_image, info_msg, (10, 600), cv2.FONT_HERSHEY_SIMPLEX, 0.7, info_color, 2)
                    
                    if (elapsed >= WAIT_FOR_TRIGGER) and (max_temp_val > TEMP_THRESHOLD) and (not in_cooldown):
                        is_recording = True
                        intersection_start_time = None
                        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                        vid_path = os.path.join(OUTPUT_FOLDER, f"rec_{ts_str}.avi")
                        csv_path = os.path.join(OUTPUT_FOLDER, f"temp_{ts_str}.csv")
                        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
                        video_writer = cv2.VideoWriter(vid_path, fourcc, 30.0, (x_end-x_start, y_end-y_start))
                        temp_file = open(csv_path, "w")
                        temp_file.write("Timestamp,Max_Temp_C\n")
                        recording_end_time = time.time() + RECORD_DURATION
                        print(f"--- TRIGGERED: {vid_path} ---")
                else:
                    intersection_start_time = None 

            status_text = "Status: SCANNING"
            color = (0, 255, 0)

            if is_recording:
                status_text = f"REC: {int(recording_end_time - time.time())}s | Temp: {max_temp_val:.1f}C"
                color = (0, 0, 255)
                if video_writer: video_writer.write(display_image)
                if temp_file:
                    t_stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    temp_file.write(f"{t_stamp},{max_temp_val:.2f}\n")
                if time.time() > recording_end_time:
                    is_recording = False
                    last_recording_finish_time = time.time()
                    video_writer.release()
                    temp_file.close()
                    video_writer = None
                    temp_file = None
            elif intersection_start_time is not None:
                status_text = "Status: INTERSECTING..."
                color = (0, 255, 255)

            cv2.putText(display_image, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            
            # --- UPDATE SHARED FRAME ---
            with lock:
                output_frame = display_image.copy()
            # ---------------------------
            
    finally:
        if video_writer: video_writer.release()
        if temp_file: temp_file.close()
        if threaded_cam: threaded_cam.stop()
        dev_therm.close()

# ==========================================
# FASTAPI ENDPOINTS
# ==========================================
def generate_frames():
    """Video streaming generator function."""
    global output_frame, lock
    while True:
        with lock:
            if output_frame is None:
                time.sleep(0.01) # Avoid tight loop if no frame yet
                continue
            
            # Encode frame as JPEG
            (flag, encodedImage) = cv2.imencode(".jpg", output_frame)
            if not flag:
                continue
        
        # Yield byte stream
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + bytearray(encodedImage) + b'\r\n')

@app.get("/video_feed")
async def video_feed():
    """Video streaming route."""
    return StreamingResponse(generate_frames(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/")
def index():
    """Check if server is running."""
    return {"message": "System Running. Go to /video_feed to view stream."}

# ==========================================
# MAIN ENTRY POINT
# ==========================================
if __name__ == "__main__":
    # 1. Start Detection Thread (Background)
    t = threading.Thread(target=run_detection_logic)
    t.daemon = True 
    t.start()

    # 2. Start FastAPI Server
    # Default port for Uvicorn is 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)