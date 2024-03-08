"""Betta_video_sequence.py
Author: Shinichi Miyazaki
Date 20230308

"""
import os
import datetime
import time
import threading
from picamera2 import Picamera2

# 実験のたびに変更するパラメータ
experiment_name = "test3" # 実験名を短い英数字で""の間に記載、ファイル名になる。
USBpath = "/media/hayashilab/5F89-3C97" # USBを接続したら、パス名を調べて (右クリックでコピー) ""内にペースト

# 以下は適宜変更
Latency_to_shoot = 0  # プログラム実行から動画撮影開始までの時間 (sec)
Video_duration = 0.1  # 動画の時間 (hour)
Video_size = (640, 480) # 動画のサイズ (width, height)
Framerate = 4  # 動画のフレームレート (frames/sec)
LensPosition = 1.5  # レンズの位置

# 以下は変更しない
Total_video_duration_sec = Video_duration * 3600  # 動画の時間 (sec)
Single_video_duration = 1 # (min)
Single_video_duration_sec = Single_video_duration * 60  # 単体の動画の時間 (sec)
Num_of_videos = int(Total_video_duration_sec / Single_video_duration_sec)
data_dir_path = USBpath + f"/{experiment_name}/"

# time log container
timelog = []

def take_video_periodically(num):
    global timelog
    filename = "{0:05d}".format(num) + ".mp4"
    picam2.start_and_record_video(filename, duration=Single_video_duration_sec)
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
    for i in range(Num_of_videos):
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
    global picam2

    os.makedirs(data_dir_path, exist_ok=True)
    os.chdir(data_dir_path)

    time.sleep(Latency_to_shoot)
    picam2 = Picamera2()
    picam2.video_configuration.size = Video_size
    picam2.video_configuration.controls.FrameRate = Framerate
    picam2.video_configuration.controls.LensPosition = LensPosition
    schedule(interval_sec=Single_video_duration_sec,
             callable_task=take_video_periodically)
    with open("timelog.txt", "w") as f:
        for i in timelog:
            f.write(i + "\n")

if __name__ == '__main__':
    main()