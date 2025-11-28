from ultralytics import YOLO
import torch
from datetime import datetime
import os

def main():
    # ---------------------------------------------------------
    # 1. SETUP & CHECKS
    # ---------------------------------------------------------
    # Generate a unique timestamp for this training run
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_name = f"pcb_train_{timestamp}"
    
    print(f"--- STARTING TRAINING RUN: {run_name} ---")

    # Check for GPU
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        print(f"✅ GPU Detected: {gpu_name}")
        device_id = 0
    else:
        print("⚠️ GPU NOT DETECTED. Training will be very slow on CPU.")
        device_id = 'cpu'

    # ---------------------------------------------------------
    # 2. LOAD MODEL
    # ---------------------------------------------------------
    # Change to yolo11n.pt for speed and change to 'yolo11s.pt' or 'yolo11m.pt' if you need higher accuracy.
    model = YOLO('yolo11m.pt') 

    # ---------------------------------------------------------
    # 3. START TRAINING
    # ---------------------------------------------------------
    # This will download the pretrained weights automatically if missing.
    try:
        results = model.train(
            data='data.yaml',  # PATH TO YOUR YAML FILE
            epochs=100,             # 100 is a good baseline
            imgsz=640,              # Matches your recording size
            batch=8,               # Batch size
            device=device_id,       # Forces GPU usage
            name=run_name,          # usage of the timestamped name
            patience=20,            # Stop early if no improvement for 20 epochs
            save=True,              # Save checkpoints
            verbose=True
        )
        
        print(f"\n✅ Training Completed Successfully!")
        print(f"   Best Model Saved at: runs/detect/{run_name}/weights/best.pt")

    except Exception as e:
        print(f"\n❌ An error occurred during training: {e}")

if __name__ == '__main__':
    # This guard is required for multiprocessing on Windows
    main()