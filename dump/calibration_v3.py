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

WINDOW_NAME = "Homography Alignment Tool (Corner Pinning)"

# ==========================================
# HELPER: THREADED CAMERA (TCP FIX INCLUDED)
# ==========================================
class ThreadedCamera:
    def __init__(self, src):
        # FORCE TCP to fix "h264 error" and artifacts
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
    # 1. SETUP CAMERAS
    # ---------------------------------------------------------
    print("--- Connecting to Thermal Camera ---")
    dev_therm = senxor.connect()
    if not dev_therm.is_connected:
        print("Senxor disconnected.")
        sys.exit(1)
    dev_therm.fields.EMISSIVITY.set(EMISSIVITY)
    dev_therm.set_read_temp_units(TEMP_UNIT)
    dev_therm.start_stream()

    print("--- Connecting to Visible Camera (Sec100) ---")
    sec100 = sec100Client(SEC_IP, SEC_USER, SEC_PASS)
    
    # Set to 720p for low latency
    try:
        sec100.setVideo0ImageResolution(sec100.ImageSize.IMAGE_1280x720) 
        sec100.setVideo0FrameRate(30)
        time.sleep(1.0)
    except: pass

    # Build URL
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
    print("Waiting for stream stabilization...")
    time.sleep(2.0)

    # ---------------------------------------------------------
    # 2. SETUP GUI - 8 SLIDERS (4 CORNERS)
    # ---------------------------------------------------------
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    
    # We need to grab one frame to know limits for sliders
    ret, frame_vis = threaded_cam.get_frame()
    while frame_vis is None:
        ret, frame_vis = threaded_cam.get_frame()
        time.sleep(0.1)
    
    vis_h, vis_w = frame_vis.shape[:2]

    # Defaults: Initialize the thermal image as a box in the center of the screen
    pad_x = vis_w // 4
    pad_y = vis_h // 4
    
    # Top Left
    cv2.createTrackbar("TL X", WINDOW_NAME, pad_x, vis_w, nothing)
    cv2.createTrackbar("TL Y", WINDOW_NAME, pad_y, vis_h, nothing)
    # Top Right
    cv2.createTrackbar("TR X", WINDOW_NAME, vis_w - pad_x, vis_w, nothing)
    cv2.createTrackbar("TR Y", WINDOW_NAME, pad_y, vis_h, nothing)
    # Bottom Left
    cv2.createTrackbar("BL X", WINDOW_NAME, pad_x, vis_w, nothing)
    cv2.createTrackbar("BL Y", WINDOW_NAME, vis_h - pad_y, vis_h, nothing)
    # Bottom Right
    cv2.createTrackbar("BR X", WINDOW_NAME, vis_w - pad_x, vis_w, nothing)
    cv2.createTrackbar("BR Y", WINDOW_NAME, vis_h - pad_y, vis_h, nothing)
    
    cv2.createTrackbar("Opacity %", WINDOW_NAME, 50, 100, nothing)

    print("\n CONTROLS:")
    print(" - Use the 8 sliders to move the 4 corners of the thermal image.")
    print(" - Match the thermal corners to the visible features.")
    print(" - Press 'q' to SAVE MATRIX.")

    homography_matrix = None

    while True:
        # Get frames
        ret_vis, frame_vis = threaded_cam.get_frame()
        _, frame_therm = dev_therm.read()

        if not ret_vis or frame_vis is None: continue
        if frame_therm is None: continue

        # Process Thermal
        uint8_therm = senxor.proc.normalize(frame_therm, dtype=np.uint8)
        cmap = senxor.proc.get_colormaps("inferno", "cv")
        colored_therm = senxor.proc.apply_colormap(uint8_therm, lut=cmap)
        therm_bgr = cv2.cvtColor(colored_therm, cv2.COLOR_RGB2BGR)
        therm_bgr = cv2.flip(therm_bgr, 1)

        # -------------------------------------------------------
        # CALCULATE HOMOGRAPHY
        # -------------------------------------------------------
        th_h, th_w = therm_bgr.shape[:2]
        
        # 1. Source Points (The corners of the raw thermal image)
        src_pts = np.float32([
            [0, 0],         # Top Left
            [th_w, 0],      # Top Right
            [0, th_h],      # Bottom Left
            [th_w, th_h]    # Bottom Right
        ])

        # 2. Destination Points (Where the sliders say they should go on RGB image)
        tl_x = cv2.getTrackbarPos("TL X", WINDOW_NAME)
        tl_y = cv2.getTrackbarPos("TL Y", WINDOW_NAME)
        tr_x = cv2.getTrackbarPos("TR X", WINDOW_NAME)
        tr_y = cv2.getTrackbarPos("TR Y", WINDOW_NAME)
        bl_x = cv2.getTrackbarPos("BL X", WINDOW_NAME)
        bl_y = cv2.getTrackbarPos("BL Y", WINDOW_NAME)
        br_x = cv2.getTrackbarPos("BR X", WINDOW_NAME)
        br_y = cv2.getTrackbarPos("BR Y", WINDOW_NAME)

        dst_pts = np.float32([
            [tl_x, tl_y],
            [tr_x, tr_y],
            [bl_x, bl_y],
            [br_x, br_y]
        ])

        # 3. Compute Matrix (Perspective Transform)
        H = cv2.getPerspectiveTransform(src_pts, dst_pts)
        homography_matrix = H

        # 4. Apply Warp (Use warpPerspective instead of warpAffine)
        warped_therm = cv2.warpPerspective(therm_bgr, H, (vis_w, vis_h))

        # -------------------------------------------------------
        # DISPLAY
        # -------------------------------------------------------
        alpha = cv2.getTrackbarPos("Opacity %", WINDOW_NAME) / 100.0
        overlay = cv2.addWeighted(frame_vis, 1.0, warped_therm, alpha, 0)

        # Draw circles on the corners so you can see what you are moving
        # (Draw on overlay)
        cv2.circle(overlay, (tl_x, tl_y), 10, (0, 255, 0), 2) # Green TL
        cv2.circle(overlay, (tr_x, tr_y), 10, (0, 255, 0), 2)
        cv2.circle(overlay, (bl_x, bl_y), 10, (0, 255, 0), 2)
        cv2.circle(overlay, (br_x, br_y), 10, (0, 255, 0), 2)

        # Resize for display if needed
        disp_h, disp_w = overlay.shape[:2]
        if disp_w > 1280:
            scale_disp = 1280 / disp_w
            display_img = cv2.resize(overlay, (0,0), fx=scale_disp, fy=scale_disp)
        else:
            display_img = overlay

        cv2.imshow(WINDOW_NAME, display_img)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # ---------------------------------------------------------
    # CLEANUP & OUTPUT
    # ---------------------------------------------------------
    if threaded_cam: threaded_cam.stop()
    dev_therm.close()
    cv2.destroyAllWindows()

    print("\n" + "="*40)
    print("HOMOGRAPHY CALIBRATION COMPLETE")
    print("="*40)
    print("COPY THIS MATRIX for your viewing/dataset code:")
    print("")
    if homography_matrix is not None:
        print("HOMOGRAPHY_MATRIX = np.array([")
        print(f"    [{homography_matrix[0,0]:.5f}, {homography_matrix[0,1]:.5f}, {homography_matrix[0,2]:.5f}],")
        print(f"    [{homography_matrix[1,0]:.5f}, {homography_matrix[1,1]:.5f}, {homography_matrix[1,2]:.5f}],")
        print(f"    [{homography_matrix[2,0]:.5f}, {homography_matrix[2,1]:.5f}, {homography_matrix[2,2]:.5f}]")
        print("], dtype=np.float32)")
    else:
        print("No matrix generated.")
    print("")
    print("="*40)

if __name__ == "__main__":
    main()