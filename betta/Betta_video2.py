import time
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput

# 動画サイズとフレームレートの設定
VIDEO_SIZE = (1920, 1080)  # 横幅、縦幅
FRAME_RATE = 30
DURATION = 100 # 動画の時間 (sec)

picam2 = Picamera2()

# 動画設定
video_config = picam2.create_video_configuration()
picam2.video_configuration.size = VIDEO_SIZE
picam2.video_configuration.controls.FrameRate = FRAME_RATE
picam2.configure(video_config)

encoder = H264Encoder(10000000)
output = FfmpegOutput('test.mp4')

picam2.start_recording(encoder, output)
time.sleep(DURATION)
picam2.stop_recording()