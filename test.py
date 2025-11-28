from ultralytics import YOLO
import os
import torch

def main():
    # ==========================================
    # CONFIGURATION
    # ==========================================
    # Path to your trained model
    model_path = './checkpoints/best_epoch_200.pt' 
    
    # Folder containing images you want to test
    source_folder = './datasets/PCB_chip_detect/test/images'
    
    # Where to save the results (will create runs/detect/pcb_local_test)
    project_name = 'runs/detect'
    run_name = 'pcb_local_test'

    # ==========================================
    # 1. SETUP & CHECKS
    # ==========================================
    if not os.path.exists(model_path):
        print(f"❌ Error: Could not find model at '{model_path}'")
        print("   Please download 'best.pt' and place it next to this script.")
        return

    if not os.path.exists(source_folder):
        print(f"❌ Error: Could not find image folder '{source_folder}'")
        print("   Please create this folder and put some images in it.")
        return

    # Check for GPU
    device = 0 if torch.cuda.is_available() else 'cpu'
    print(f"--- Running on: {'GPU' if device == 0 else 'CPU'} ---")

    # ==========================================
    # 2. RUN INFERENCE
    # ==========================================
    print(f"Loading model: {model_path}...")
    model = YOLO(model_path)

    print(f"Processing images in: {source_folder}...")
    
    # Run prediction
    # save=True:  Saves images with boxes drawn
    # conf=0.25:  Only show detections with >25% confidence
    results = model.predict(
        source=source_folder,
        save=True,
        conf=0.25,
        device=device,
        project=project_name,
        name=run_name,
        exist_ok=True  # Overwrite folder if it exists (so you don't get predict2, predict3...)
    )

    # ==========================================
    # 3. REPORT
    # ==========================================
    # Ultralytics automatically saves to: project_name / run_name
    save_dir = os.path.join(project_name, run_name)
    
    print("\n✅ DONE!")
    print(f"   Results saved to: {os.path.abspath(save_dir)}")
    print("   Go open that folder to see your images with boxes!")

if __name__ == '__main__':
    main()