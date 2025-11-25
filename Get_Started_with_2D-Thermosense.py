# Sample code for using the 2D-Thermosense
import sys

# Importing various libraries/packages
import senxor.proc
import numpy as np
import cv2

addrs = senxor.list_senxor()
for addr in addrs:
    print(addr) # List address from the connected senxor devices

addr = addrs[0]

# Connect to the senxor device
dev = senxor.connect()
print(dev.is_connected) # Check whether the connection was successful. If True, the connection has been established.

try:
    dev.fields.EMISSIVITY.set(95) # Set emissivity: 0,95 (standard)
    print("Emission level successfully set!")
except Exception as e:
    print("Error setting the emissivity:", e)

# Set temperature unit for reading data
try:
    temp_unit = "C"  # K = Kelvin, C = Celsius, F = Fahrenheit
    dev.set_read_temp_units(temp_unit)
    print(f"Temperature output successfully set to {temp_unit}!")
except Exception as e:
    print("Error setting the temperature output unit:", e)

# Set temperature offset correction
try:
    offset_value = 0  # Adjust this value as needed
    dev.fields.OFFSET.set(offset_value)
    print(f"Temperature offset correction successfully set to {offset_value}!")
except Exception as e:
    print("Error setting the temperature offset correction:", e)

dev.start_stream() # Start the data stream from the device


while (1):
    header, frame = dev.read() # Read a single frame from the stream

    # Apply offset correction, if set
    if frame is not None:
        if offset_value != 0:
            frame = frame + offset_value
        
        #print(frame[0][0].dtype)
        #print(f"Frame min: {frame.min()} {temp_unit}, max: {frame.max()} {temp_unit}, mean: {frame.mean():.1f} {temp_unit}") # Print min, max and mean temperature values from the frame
        #np.set_printoptions(threshold=np.inf)  # When deleting the hashtag, all values are displayed in the console
        np.set_printoptions(precision=1, floatmode='fixed') # Set number format for printing
        #print(frame)  # Output raw data from the thermal image
        np.savetxt("thermal_frame.csv", frame.astype(np.float32), delimiter=",", fmt="%.2f")  # Save the raw data as CSV, number format with 2 decimal places

        uint8_image = senxor.proc.normalize(frame, dtype=np.uint8) # Normalize the frame to uint8 for visualization
        float32_image = senxor.proc.normalize(frame, dtype=np.float32) # Normalize the frame to float32 for further processing
        enlarged_image = senxor.proc.enlarge(uint8_image, scale=5)  # Enlarge image by a factor of 5
        cmap_cv_inferno = senxor.proc.get_colormaps("inferno", "cv") # Get the inferno colormap in OpenCV format
        #colored_image = senxor.proc.apply_colormap(float32_image, lut=cmap_cv_inferno) # Coloring the image
        colored_image = senxor.proc.apply_colormap(enlarged_image, lut=cmap_cv_inferno)

        # OpenCV displays images in BGR format
        bgr_image = cv2.cvtColor(colored_image, cv2.COLOR_RGB2BGR)

        bgr_image = cv2.flip(bgr_image, 1) # Flip image
        #print(bgr_image.shape)
        cv2.imshow("senxor", bgr_image) # Display the image using OpenCV, if the line is commented the image window will not open
        cv2.waitKey(1) # Wait for a key press to close the image window
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        #cv.destroyAllWindows() # Close all OpenCV windows
    else:
        print("No frame received!")

dev.close() # Stop the stream and close the connection