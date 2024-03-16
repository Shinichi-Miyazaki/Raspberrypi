import os
import datetime
import time
import threading
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
from libcamera import Transform
from picamera2.outputs import FileOutput

# 実験のたびに変更するパラメータ
USBpath = "/home/shi/Desktop/test" # USBを接続したら、パス名を調べて (右クリックでコピー) ""内にペースト

# 以下は適宜変更
Latency_to_shoot = 0  # プログラム実行から動画撮影開始までの時間 (sec)
Total_video_duration = 0.02 # 動画の時間 (hour)
Single_video_duration = 0.1  # 単体の動画の時間 (min)
Video_size = (640, 480) # 動画のサイズ (width, height)
Framerate = 4  # 動画のフレームレート (frames/sec)

# 以下は変更しない
Total_video_duration_sec = Total_video_duration * 3600  # 動画の時間 (sec)
Single_video_duration_sec = Single_video_duration * 60  # 単体の動画の時間 (sec)
Num_of_videos = int(Total_video_duration_sec / Single_video_duration_sec)

with Picamera2() as camera:
    os.chdir(USBpath)
    video_config = camera.create_video_configuration(main={"size": Video_size},
                                                     transform=Transform(hflip=True,
                                                                         vflip=True))
    camera.video_configuration.controls.FrameRate = Framerate
    camera.configure(video_config)
    time.sleep(Latency_to_shoot)
    for filename in ['clip%02d.h264' % i for i in range(Num_of_videos)]:
        encoder = H264Encoder()
        camera.start_encoder(encoder, FileOutput(filename))
        time.sleep(Single_video_duration_sec)
        camera.stop_encoder(encoder)