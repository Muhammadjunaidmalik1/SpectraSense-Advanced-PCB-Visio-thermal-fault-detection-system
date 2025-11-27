import cv2
import numpy as np
import sys
import time
import threading
import os
import senxor.proc
from sec100Client import sec100Client

# ==========================================
# CONFIGURATION - This gives the calibration setup with 640x640 center crop GUI
# ==========================================
SAVE_DIR = "dataset_pcb_640_crop"  # Updated folder name
# For 1080p resolution
ALIGNMENT_MATRIX = np.array([
    [-5.12000000e+00, -6.27019161e-16,  1.34760000e+03],
    [ 6.27019161e-16, -5.12000000e+00,  6.73200000e+02]
], dtype=np.float32)

SEC_IP = "192.168.136.100"
SEC_USER = "Service"
SEC_PASS = "servicelevel"
TEMP_UNIT = "C"
EMISSIVITY = 95
OVERLAY_OPACITY = 0.6 

# Create the directory if it doesn't exist
os.makedirs(SAVE_DIR, exist_ok=True)

# ==========================================
# HELPER: GET VALID THERMAL AREA
# ==========================================
def get_thermal_bbox(matrix, therm_w, therm_h, rgb_w, rgb_h):
    """
    Calculates the bounding box of the thermal image projected onto the RGB image.
    We use this to find the CENTER of the thermal view.
    """
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
    dev_therm.fields.EMISSIVITY.set(EMISSIVITY)
    dev_therm.set_read_temp_units(TEMP_UNIT)
    dev_therm.start_stream()

    print("--- Initializing Visible Camera ---")
    sec100 = sec100Client(SEC_IP, SEC_USER, SEC_PASS)
    try:
        sec100.setVideo0ImageResolution(sec100.ImageSize.IMAGE_1920x1080)
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

    # ---------------------------------------------------------
    # 2. CALCULATE CROP CENTER (DO THIS ONCE)
    # ---------------------------------------------------------
    ret, frame_vis = threaded_cam.get_frame()
    _, frame_therm = dev_therm.read()
    
    print("Waiting for valid frames to calculate center...")
    while frame_vis is None or frame_therm is None:
        ret, frame_vis = threaded_cam.get_frame()
        _, frame_therm = dev_therm.read()
        time.sleep(0.1)

    vis_h, vis_w = frame_vis.shape[:2]
    therm_h, therm_w = frame_therm.shape[:2]

    # 1. Find where the thermal image is (Bounding Box)
    bx, by, bw, bh = get_thermal_bbox(ALIGNMENT_MATRIX, therm_w, therm_h, vis_w, vis_h)
    
    # 2. Find the Center of that Bounding Box
    center_x = bx + bw // 2
    center_y = by + bh // 2

    # 3. Calculate 640x640 Crop Coordinates
    CROP_SIZE = 640
    HALF_SIZE = CROP_SIZE // 2

    x_start = center_x - HALF_SIZE
    y_start = center_y - HALF_SIZE
    x_end = center_x + HALF_SIZE
    y_end = center_y + HALF_SIZE

    # 4. Safety Clamp (Ensure we don't crash if crop is off-screen)
    # If the crop goes off the left edge, shift it right
    if x_start < 0:
        x_end += abs(x_start)
        x_start = 0
    # If crop goes off top edge
    if y_start < 0:
        y_end += abs(y_start)
        y_start = 0
    # If crop goes off right/bottom edge
    if x_end > vis_w:
        x_start -= (x_end - vis_w)
        x_end = vis_w
    if y_end > vis_h:
        y_start -= (y_end - vis_h)
        y_end = vis_h
        
    print(f"\n--- CROP CONFIGURATION ---")
    print(f"Thermal Center found at: ({center_x}, {center_y})")
    print(f"Crop Region: x[{x_start}:{x_end}], y[{y_start}:{y_end}]")
    print(f"Final Size: {x_end-x_start}x{y_end-y_start}")

    # ---------------------------------------------------------
    # 3. CAPTURE LOOP
    # ---------------------------------------------------------
    cv2.namedWindow("Data Collection (640x640 Center)", cv2.WINDOW_NORMAL)
    print("\n--- DATA COLLECTION READY ---")
    print(f"Saving to: {os.path.abspath(SAVE_DIR)}")
    print("Press 's' to save.")
    print("Press 'q' to quit.")

    try:
        while True:
            vis_ret, frame_vis = threaded_cam.get_frame()
            _, frame_therm = dev_therm.read()

            if not vis_ret or frame_vis is None or frame_therm is None:
                continue

            # Process Thermal
            uint8_therm = senxor.proc.normalize(frame_therm, dtype=np.uint8)
            cmap = senxor.proc.get_colormaps("inferno", "cv")
            colored_therm = senxor.proc.apply_colormap(uint8_therm, lut=cmap)
            therm_bgr = cv2.cvtColor(colored_therm, cv2.COLOR_RGB2BGR)
            therm_bgr = cv2.flip(therm_bgr, 1)

            # Warp Thermal to match FULL RGB
            aligned_therm = cv2.warpAffine(
                therm_bgr, 
                ALIGNMENT_MATRIX, 
                (vis_w, vis_h), 
                flags=cv2.INTER_LANCZOS4
            )

            # -----------------------------------------------------
            # CENTER CROP (NO RESIZING)
            # -----------------------------------------------------
            # We strictly slice the array. No cv2.resize used.
            final_rgb = frame_vis[y_start:y_end, x_start:x_end]
            final_therm = aligned_therm[y_start:y_end, x_start:x_end]
            
            # Note: If the image edges were hit, the size might be < 640.
            # But usually for 1080p center objects, this will be exactly 640x640.

            # Create Fused Preview
            fused_image = cv2.addWeighted(final_rgb, 1.0, final_therm, OVERLAY_OPACITY, 0)

            # Display
            cv2.imshow("Data Collection (640x640 Center)", fused_image)

            # Key Listener
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('s'):
                timestamp = int(time.time() * 1000)
                
                rgb_filename = f"{SAVE_DIR}/img_{timestamp}_rgb.jpg"
                therm_filename = f"{SAVE_DIR}/img_{timestamp}_therm.jpg"
                fused_filename = f"{SAVE_DIR}/img_{timestamp}_fused.jpg"
                
                # Save
                cv2.imwrite(rgb_filename, final_rgb)
                cv2.imwrite(therm_filename, final_therm)
                cv2.imwrite(fused_filename, fused_image)
                
                print(f"Saved pair: {timestamp}")
                
                # Visual Flash
                cv2.imshow("Data Collection (640x640 Center)", np.full_like(fused_image, 255))
                cv2.waitKey(50)

            elif key == ord('q'):
                break

    finally:
        if 'threaded_cam' in locals() and threaded_cam: 
            threaded_cam.stop()
        if 'dev_therm' in locals() and dev_therm:
            dev_therm.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()