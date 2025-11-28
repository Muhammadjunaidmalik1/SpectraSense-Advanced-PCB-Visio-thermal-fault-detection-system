import cv2
import numpy as np
import sys
import time
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

WINDOW_NAME = "Dual Stream Alignment Tool"

def nothing(x):
    pass

def main():
    # ---------------------------------------------------------
    # 1. INITIALIZE THERMAL CAMERA (Senxor)
    # ---------------------------------------------------------
    print("--- Connecting to Thermal Camera ---")
    addrs = senxor.list_senxor()
    if not addrs:
        print("No Senxor thermal camera found. Check USB connection.")
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
    cap_vis = None
    
    try:
        sec100 = sec100Client(SEC_IP, SEC_USER, SEC_PASS)
        
        # 1. Try to Enable RTSP (Ignore if 'Not Found' error occurs)
        try:
            if not sec100.getVideo0EnableRtsp():
                print("Enabling RTSP stream...")
                sec100.setVideo0EnableRtsp(True)
                time.sleep(2)
        except Exception as e:
            print(f"Warning: Could not check/set RTSP enable status ({e}). Assuming it is ON.")

        # 2. Get Port (Default to 554 if fails)
        try:
            rtsp_port = sec100.getRtspPort()
        except:
            rtsp_port = 554

        # 3. Get Path (Default to 'live/0' if fails)
        try:
            rtsp_path = sec100.getVideo0RtspPath()
        except:
            rtsp_path = "live/0"

        # --- CRITICAL FIX: CLEAN THE PATH ---
        # The camera returns "/live/0", but we need "live/0" to avoid double slash
        if rtsp_path.startswith('/'):
            rtsp_path = rtsp_path[1:]

        # 4. Construct URL WITH CREDENTIALS
        # Format: rtsp://user:pass@ip:port/path
        rtsp_url = f"rtsp://{SEC_USER}:{SEC_PASS}@{SEC_IP}:{rtsp_port}/{rtsp_path}"
        
        print(f"Attempting connection to: {rtsp_url}")
        
        # Open Stream
        cap_vis = cv2.VideoCapture(rtsp_url)
        
        if not cap_vis.isOpened():
            print("Error: OpenCV could not open the RTSP stream.")
            print("Troubleshooting steps:")
            print("1. Verify the camera IP is reachable via ping.")
            print("2. Ensure no other application (VLC, Browser) is using the stream.")
            sys.exit(1)
        else:
            print("Visible camera connected successfully!")
            
    except Exception as e:
        print(f"Critical Error connecting to Sec100: {e}")
        sys.exit(1)

    # ---------------------------------------------------------
    # 3. SETUP GUI CONTROLS
    # ---------------------------------------------------------
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    
    # Trackbars
    cv2.createTrackbar("Scale (x0.01)", WINDOW_NAME, 100, 1000, nothing) 
    cv2.createTrackbar("Rotation (deg)", WINDOW_NAME, 180, 360, nothing) 
    cv2.createTrackbar("X Offset", WINDOW_NAME, 1000, 2000, nothing)     
    cv2.createTrackbar("Y Offset", WINDOW_NAME, 1000, 2000, nothing)     
    cv2.createTrackbar("Opacity %", WINDOW_NAME, 50, 100, nothing)       

    print("\nControls:")
    print(" - Adjust sliders to align the thermal image.")
    print(" - Press 'q' to quit and save the matrix.")

    transformation_matrix = None

    while True:
        # --- Read Frames ---
        ret_vis, frame_vis = cap_vis.read()
        header_therm, frame_therm = dev_therm.read()

        if not ret_vis:
            # If we lose the visible frame, try to reconnect or just skip
            print("Waiting for visible frame...")
            time.sleep(0.1)
            continue
        
        if frame_therm is None:
            continue

        # --- Process Thermal Image ---
        # Normalize and colorize
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

        # 1. Rotation + Scale matrix
        M = cv2.getRotationMatrix2D(center_therm, rot_val, scale_val)

        # 2. Translation adjustment
        # We adjust the translation so the thermal center moves to the visible center + user offset
        M[0, 2] += (vis_center_x - center_therm[0]) + x_off_val
        M[1, 2] += (vis_center_y - center_therm[1]) + y_off_val
        
        transformation_matrix = M 

        # --- Warp and Blend ---
        warped_therm = cv2.warpAffine(therm_bgr, M, (w_vis, h_vis))
        overlay = cv2.addWeighted(frame_vis, 1.0, warped_therm, alpha_val, 0)

        # --- Resize for Display (Max 1280px wide) ---
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
    cap_vis.release()
    dev_therm.close()
    cv2.destroyAllWindows()

    print("\n" + "="*40)
    print("CALIBRATION COMPLETE")
    print("="*40)
    print("Transformation Matrix (copy this):")
    if transformation_matrix is not None:
        print(np.array2string(transformation_matrix, separator=', '))
    else:
        print("No matrix generated.")
    print("="*40)

if __name__ == "__main__":
    main()