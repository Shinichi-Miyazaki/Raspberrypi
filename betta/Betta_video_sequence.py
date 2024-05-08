"""Betta_video_sequence.py
Author: Shinichi Miyazaki
Date 20230308

使い方
1. 実験名をexperiment_nameに記載する。
2. USBを接続したら、パス名を調べて (右クリックでコピー) USBpathにペーストする。
3. 各種パラメータ (Latency_to_shoot, Total_video_duration, Single_video_duration, Video_size, Framerate) を適宜変更する。
4. プログラムを実行する。

ありがちなエラー
1. total_video_durationを短くしていって、Single_video_durationより短くなるとエラーが起こる。
"""


import os
import datetime
import time
import threading
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
from libcamera import Transform

# 実験のたびに変更するパラメータ
experiment_name = "test2"
# 実験名を短い英数字で""の間に記載、ファイル名になる。
USBpath = "/media/si/2EEF-F720" # USBを接続したら、パス名を調べて (右クリックでコピー) ""内にペースト

# 以下は適宜変更
Latency_to_shoot = 0  # プログラム実行から動画撮影開始までの時間 (sec)
Total_video_duration = 0.05 # 動画の時間 (hour)
Single_video_duration = 1  # 単体の動画の時間 (min)
Video_size = (640, 480) # 動画のサイズ (width, height)
Framerate = 4  # 動画のフレームレート (frames/sec)
Bitrate = 500000  # 動画のビットレート (bit/sec)

# 以下は変更しない
Total_video_duration_sec = Total_video_duration * 3600  # 動画の時間 (sec)
Single_video_duration_sec = Single_video_duration * 60  # 単体の動画の時間 (sec)
Num_of_videos = int(Total_video_duration_sec / Single_video_duration_sec)
data_dir_path = USBpath + f"/{experiment_name}/"

# time log container
timelog = []

def take_video_periodically():
    global timelog
    
    for num in range(Num_of_videos):
        print(datetime.datetime.now())
        filename = "{0:05d}".format(num) + ".mp4"
        encoder = H264Encoder(Bitrate)
        output = FfmpegOutput(data_dir_path + filename)
        picam2.start_recording(encoder, output)
        time.sleep(Single_video_duration_sec)
        print(datetime.datetime.now())
        picam2.stop_recording()
        print(datetime.datetime.now())
        now = datetime.datetime.now()
        timelog.append(now.strftime('%H:%M:%S.%f'))
    

def main():
    global timelog
    global picam2

    os.makedirs(data_dir_path, exist_ok=True)
    os.chdir(data_dir_path)

    time.sleep(Latency_to_shoot)
    picam2 = Picamera2()
    picam2.video_configuration.controls.FrameRate = Framerate
    picam2.video_configuration.size = Video_size
    picam2.video_configuration.transform = Transform(hflip=True,vflip=True)
    
    take_video_periodically()
    with open("timelog.txt", "w") as f:
        for i in timelog:
            f.write(i + "\n")

if __name__ == '__main__':
    main()