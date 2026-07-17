"""Betta_video.py
Author: Shinichi Miyazaki
Date: 20230308

使い方
1. 実験名をexperiment_nameに記載する。
2. USBを接続したら、パス名を調べて (右クリックでコピー) USBpathにペーストする。
3. 各種パラメータ (Latency_to_shoot, Video_duration, Video_size, Framerate) を適宜変更する。
4. プログラムを実行する。
"""

import time
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
from libcamera import Transform

# 実験のたびに変更するパラメータ
experiment_name = "" # 実験名を短い英数字で""の間に記載、ファイル名になる。
USBpath = "" # USBを接続したら、パス名を調べて (右クリックでコピー) ""内にペースト

# 以下は適宜変更
Latency_to_shoot = 10  # プログラム実行から動画撮影開始までの時間 (sec)
Video_duration = 0.01  # 動画の時間 (hour)
Video_size = (640, 480) # 動画のサイズ (width, height)
Framerate = 4  # 動画のフレームレート (frames/sec)

# 以下は変更しない
Video_duration_sec = Video_duration * 3600  # 動画の時間 (sec)
data_path = USBpath + f"/{experiment_name}.mp4"  # 動画の保存先
encoder = H264Encoder(10000000)
output = FfmpegOutput(data_path)
def main():
    picam2 = Picamera2()
    # configure camera
    video_config = picam2.create_video_configuration(main={"size": Video_size},
                                                     transform=Transform(hflip=True,
                                                                         vflip=True))
    picam2.video_configuration.controls.FrameRate = Framerate
    picam2.configure(video_config)

    # shoot video
    time.sleep(Latency_to_shoot)
    picam2.start_recording(encoder, output)
    time.sleep(Video_duration_sec)
    picam2.stop_recording()

if __name__ == '__main__':
    main()