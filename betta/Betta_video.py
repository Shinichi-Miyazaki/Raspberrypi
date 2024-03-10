"""Betta_video.py
Author: Shinichi Miyazaki
Date: 20230308
"""

import time
from picamera2 import Picamera2

# 実験のたびに変更するパラメータ
experiment_name = "" # 実験名を短い英数字で""の間に記載、ファイル名になる。
USBpath = ""　# USBを接続したら、パス名を調べて (右クリックでコピー) ""内にペースト

# 以下は適宜変更
Latency_to_shoot = 12600  # プログラム実行から動画撮影開始までの時間 (sec)
Video_duration = 36  # 動画の時間 (hour)
Video_size = (640, 480) # 動画のサイズ (width, height)
Framerate = 4  # 動画のフレームレート (frames/sec)
LensPosition = 1.5  # レンズの位置

# 以下は変更しない
Video_duration_sec = Video_duration * 3600  # 動画の時間 (sec)
data_path = USBpath + f"/{experiment_name}.mp4"  # 動画の保存先
def main():
    picam2 = Picamera2()
    picam2.video_configuration.size = Video_size
    picam2.video_configuration.controls.FrameRate = Framerate
    picam2.video_configuration.controls.LensPosition = LensPosition
    time.sleep(Latency_to_shoot)
    picam2.start_and_record_video(data_path, duration=Video_duration_sec)

if __name__ == '__main__':
    main()