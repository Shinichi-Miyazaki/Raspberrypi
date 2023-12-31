"""TimeLapseCapture.py
Author: Shinichi Miyazaki

"""
import datetime
import picamera
import os
import time
import threading
import numpy as np
import pandas as pd

### params ###
interval = 2 #タイムラプスのインターバル (秒)
num_of_images = 4 #イメージの枚数
today = datetime.date.today()

# USBを接続したら、パス名を調べて (右クリックでコピー) 下の""内にペースト
USBpath = ""
data_dir_path = USBpath + "/TimeLapse{}/".format(today)

# data container
timelog = []

def take_image_periodically(num):
    global timelog
    filename = "{0:05d}".format(num) + ".jpg"

    camera.capture(data_dir_path + filename)

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
    camera = picamera.PiCamera()

    os.makedirs(data_dir_path, exist_ok = True)

    schedule(interval_sec=interval,
             callable_task=take_image_periodically)
    timelog = pd.DataFrame(np.array(timelog),
                           columns=["timelog"])
    print(timelog)
    timelog.to_csv(data_dir_path + "/timelog.csv")


if __name__ == '__main__':
    main()