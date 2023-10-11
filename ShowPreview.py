import picamera
import os
import time

a=0
camera=picamera.PiCamera()
camera.start_preview()
camera.resolution = (720, 480)
camera.framerate=10
time.sleep(10)
camera.stop_preview()
