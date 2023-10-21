"""ShowPreview.py
Author: Shinichi Miyazaki

このプログラムはRaspberry piでカメラのプレビュー画像を表示します。
Durationという変数に希望の時間を秒単位で記載することで、表示時間を決めることが可能です。
実行前に、paramsの部分を任意の数値に書き換えてから実行してください。
"""

import picamera
import os
import time

### params ###
Duration = 10 #(sec)
Resolution = (720, 480) #(x, y)
def main(Duration):
    camera=picamera.PiCamera()
    camera.start_preview()
    camera.resolution = Resolution
    camera.framerate=10
    time.sleep(Duration)
    camera.stop_preview()

if __name__ == '__main__':
    main(Duration)