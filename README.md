# SpectraSense-Advanced-PCB-Visio-thermal-fault-detection-system
The repository for Advanced PCB Visio-thermal fault detection system developed at SICK hackathon 2025 at Makerspace Munich.

## Overview
SpectraSense is an advanced PCB fault detection system that uses visual and thermal imaging to identify defects in soldering process and keep record of those defects.

## Features
- Real-time thermal image and RGB image analysis
- Electronic parts detection
- Solder quality determination using thermal camera
- Integration with SICK sensor technology
- Video stream is connected to a web app via FastAPI.

## Getting Started
### Prerequisites
- Python 3.11.9
- Node.js v24.11.1
- Required dependencies (see `requirements.txt`)

### Installation
```bash
git clone https://github.com/Muhammadjunaidmalik1/SpectraSense-Advanced-PCB-Visio-thermal-fault-detection-system.git

cd SpectraSense-Advanced-PCB-Visio-thermal-fault-detection-system

pip install -r requirements.txt
```

### Usage

1. **Calibrate cameras** - Determine the transformation between thermal and RGB cameras:
```bash
python calibration.py
```

2. **Update calibration matrix** - Use the transformation matrix obtained from calibration in the this file to run both cameras simultaneously:
```bash
python run_calibrated_cams.py
```

3. **Record data** - Capture thermal and RGB image pairs for training:
```bash
python data_recorder.py
```

4. **Train model** - Train YOLOv11 on the custom PCB dataset:
```bash
python train.py
```

5. **Test model** - Verify the trained model performance:
```bash
python test.py
```

6. **Run detection** - Execute real-time solder quality detection on video streams:
```bash
python run.py
```

## To run the Web App

1. **Start the backend** - In one terminal, run:
```bash
python run_with_fastapi.py
```

2. **Start the frontend** - In another terminal:
```bash
cd frontend
npm run dev
```

<div>
	<img src="/assets/Front end with the soldering stream.png" width="33%" />
	<p><em>Sample Scene</em></p>
</div>


## License
This project was developed for the SICK Hackathon.