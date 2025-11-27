
PCB_chip_detection - v3 New dataset
==============================

This dataset was exported via roboflow.com on November 27, 2025 at 12:57 PM GMT

Roboflow is an end-to-end computer vision platform that helps you
* collaborate with your team on computer vision projects
* collect & organize images
* understand and search unstructured image data
* annotate, and create datasets
* export, train, and deploy computer vision models
* use active learning to improve your dataset over time

For state of the art Computer Vision training notebooks you can use with this dataset,
visit https://github.com/roboflow/notebooks

To find over 100k other datasets and pre-trained models, visit https://universe.roboflow.com

The dataset includes 301 images.
-motordriver- are annotated in YOLOv11 format.

The following pre-processing was applied to each image:
* Auto-orientation of pixel data (with EXIF-orientation stripping)

The following augmentation was applied to create 3 versions of each source image:
* 50% probability of horizontal flip
* 50% probability of vertical flip
* Equal probability of one of the following 90-degree rotations: none, clockwise, counter-clockwise, upside-down
* Random rotation of between -18 and +18 degrees
* Random shear of between -26° to +26° horizontally and -23° to +23° vertically
* Random exposure adjustment of between -17 and +17 percent
* Random Gaussian blur of between 0 and 2 pixels
* Salt and pepper noise was applied to 6.2 percent of pixels


