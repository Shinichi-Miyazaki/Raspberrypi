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
interval = 2  # タイムラプスのインターバル (秒)
num_of_images = 4  # イメージの枚数
Video_size = (640, 480) # 動画のサイズ (width, height)
experiment_name = "" # 実験名を短い英数字で""の間に記載

# USBを接続したら、パス名を調べて (右クリックでコピー) 下の""内にペースト
USBpath = ""
data_dir_path = USBpath + f"/{experiment_name}/"

# data container
timelog = []


def take_image_periodically(num):
    global timelog
    filename = "{0:05d}".format(num) + ".jpg"

    camera.switch_mode_and_capture_file(capture_config,
                                        data_dir_path + filename)
    now = datetime.datetime.now()
    timelog.append(now.strftime('%H:%M:%S.%f'))


def schedule(interval_sec,
             callable_task,
             args=None,
             kwargs=None):
    args = args or []
    kwargs = kwargs or {}
    # 基準時刻を作る
    base_timing = datetime.datetime.now()
    for i in range(num_of_images):
        # 処理を別スレッドで実行する
        t = threading.Thread(target=callable_task,
                             args=(i,),
                             kwargs=kwargs)
        t.start()

        # 基準時刻と現在時刻の剰余を元に、次の実行までの時間を計算する
        current_timing = datetime.datetime.now()
        elapsed_sec = (current_timing - base_timing).total_seconds()
        sleep_sec = interval_sec - (elapsed_sec % interval_sec)

        time.sleep(max(sleep_sec, 0))


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
    schedule(interval_sec=interval,
             callable_task=take_image_periodically)
    with open("timelog.txt", "w") as f:
        for i in timelog:
            f.write(i + "\n")

    print(timelog)


if __name__ == '__main__':
    main()
