"""TimeLapseCapture.py
Author: Shinichi Miyazaki

"""
import os
import datetime
import time
import threading
from picamera2 import Picamera2
from libcamera import Transform

# パラメータ
imaging_fps = 1  # タイムラプスのインターバル (秒)
num_of_images = 30  # 各バーストごとのイメージの枚数
burst_interval = 3 # イメージの撮影間隔 (時間)
burst_interval_sec = burst_interval * 3600 # イメージの撮影間隔 (秒)

Total_duration = 240 # イメージングのトータル時間 (時間)
burst_num = int(Total_duration / burst_interval) # イメージの撮影回数

Video_size = (1280, 960) # 動画のサイズ (width, height)
experiment_name = "survival_test" # 実験名を短い英数字で""の間に記載

# USBを接続したら、パス名を調べて (右クリックでコピー) 下の""内にペースト
USBpath = "/media/shi/2EEF-F720"
data_dir_path = USBpath + f"/{experiment_name}/"

# data container
timelog = []

def take_image_periodically(num):
    global timelog
    for i in range(num_of_images):
        filename = f"Burst_{num:03d}_image_{i:03d}" + ".jpg"
        camera.switch_mode_and_capture_file(capture_config,
                                            data_dir_path + filename)
        time.sleep(1)

    now = datetime.datetime.now()
    timelog.append(now.strftime('%H:%M:%S.%f'))


def main():
    global timelog
    global camera
    global capture_config

    camera = Picamera2()
    capture_config = camera.create_still_configuration(main={"size": Video_size},
                                                       transform=Transform(hflip=True,
                                                                           vflip=True))
    camera.start(show_preview=True)
    os.makedirs(data_dir_path, exist_ok=True)
    os.chdir(data_dir_path)
    for burst_idx in range(burst_num):
        take_image_periodically(burst_idx)
        time.sleep(burst_interval_sec - num_of_images * imaging_fps)

    with open("timelog.txt", "w") as f:
        for i in timelog:
            f.write(i + "\n")

    print(timelog)


if __name__ == '__main__':
    main()
