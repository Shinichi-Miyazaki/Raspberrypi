"""TimeLapseCapture.py
Author: Shinichi Miyazaki

"""
import os
import datetime
import time
import threading
from picamera2 import Picamera2
from libcamera import Transform

# Common parameters
image_size = (1280, 1024)  # イメージのサイズ (width, height)
experiment_name = "20240329_Lego3_survival" # 実験名を短い英数字で""の間に記載
# USBを接続したら、パス名を調べて (右クリックでコピー) 下の""内にペースト
USBpath = "/media/si/2EEF-F720"
data_dir_path = USBpath + f"/{experiment_name}/"


# parameters for time lapse imaging
timelapse_imaging_interval = 2  # タイムラプスのインターバル (秒)
timelapse_imaging_num_of_images = 43200  # イメージの枚数

# Parameters for burst imaging
burst_imaging_interval = 10  # タイムラプスのインターバル (秒)
burst_imaging_num_of_images = 120 # 各バーストごとのイメージの枚数
burst_interval = 3 # イメージの撮影間隔 (時間)
burst_interval_sec = burst_interval * 3600 # イメージの撮影間隔 (秒)

total_duration_for_burst_imaging = 240 # イメージングのトータル時間 (時間)
burst_num = int(total_duration_for_burst_imaging / burst_interval) # イメージの撮影回数



# data container
timelog = []

def burst_imaging(num):
    global timelog
    for i in range(burst_imaging_num_of_images):
        filename = f"Burst_{num:03d}_image_{i:03d}" + ".jpg"
        camera.switch_mode_and_capture_file(capture_config,
                                            data_dir_path + filename)
        time.sleep(burst_imaging_interval)
        now = datetime.datetime.now()
        timelog.append(now.strftime('%H:%M:%S.%f'))
    with open("timelog.txt", "w") as f:
        for i in timelog:
            f.write(i + "\n")


def timelapse_imaging(num):
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
    for i in range(timelapse_imaging_num_of_images):
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
    capture_config = camera.create_still_configuration(main={"size": image_size},
                                                       transform=Transform(hflip=True,
                                                                           vflip=True))
    camera.start(show_preview=True)
    os.makedirs(data_dir_path, exist_ok=True)
    os.chdir(data_dir_path)

    schedule(interval_sec=timelapse_imaging_interval,
             callable_task=timelapse_imaging)
    with open("timelog.txt", "w") as f:
        for i in timelog:
            f.write(i + "\n")

    for burst_idx in range(burst_num):
        burst_imaging(burst_idx)
        time.sleep(burst_interval_sec - burst_imaging_num_of_images * burst_imaging_interval)

    with open("timelog.txt", "w") as f:
        for i in timelog:
            f.write(i + "\n")


if __name__ == '__main__':
    main()
