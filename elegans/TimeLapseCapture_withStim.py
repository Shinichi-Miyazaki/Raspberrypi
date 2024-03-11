"""TimeLapseCapture.py
Author: Shinichi Miyazaki

"""
import os
import datetime
import time
import threading
import RPi.GPIO as GPIO
from picamera2 import Picamera2
from libcamera import Transform

# init
GPIO.setmode(GPIO.BCM)
GPIO.setup(25, GPIO.OUT)

# params
interval = 2  # タイムラプスのインターバル (秒)
num_of_images = 4  # イメージの枚数
Video_size = (640, 480) # 動画のサイズ (width, height)
today = datetime.date.today()

# USBを接続したら、パス名を調べて (右クリックでコピー) 下の""内にペースト
USBpath = "/home/shi/Desktop/test"
data_dir_path = USBpath + "/TimeLapse{}/".format(today)

# data container
timelog = []


def capture(num):
    filename = "{0:05d}".format(num) + ".jpg"
    camera.switch_mode_and_capture_file(capture_config,
                                        data_dir_path + filename)
    now = datetime.datetime.now()
    timelog.append(now.strftime('%H:%M:%S.%f'))


def take_image_periodically(num):
    global timelog
    if num % 30 == 5:
        capture(num)
        GPIO.output(25, GPIO.HIGH)
    elif num % 30 == 10:
        capture(num)
        GPIO.output(25, GPIO.LOW)
    else:
        capture(num)


def schedule(interval_sec,
             callable_task):
    global image_i
    # 基準時刻を作る
    base_timing = datetime.datetime.now()
    for image_i in range(num_of_images):
        # 処理を別スレッドで実行する
        t = threading.Thread(target=callable_task,
                             args=(image_i,))
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
    timelog.to_csv(data_dir_path + "/timelog.csv")


if __name__ == '__main__':
    main()
