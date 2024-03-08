from picamera2 import Picamera2
import time


picam2 = Picamera2()

#width & height, framerate(frames/sec)
picam2.video_configuration.size = (640, 480)
picam2.video_configuration.controls.FrameRate = 4
#transformは上下左右反転 1 or 0
picam2.video_configuration.controls.LensPosition = 1.5

#duration = 撮影時間
time.sleep(12600)
picam2.start_and_record_video("ch1_240306_ID13.mp4", duration=129600)