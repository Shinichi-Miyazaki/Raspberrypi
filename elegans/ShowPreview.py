"""ShowPreview.py
Author: Shinichi Miyazaki

このプログラムはRaspberry piでカメラのプレビュー画像を表示します。
Durationという変数に希望の時間を秒単位で記載することで、表示時間を決めることが可能です。
実行前に、paramsの部分を任意の数値に書き換えてから実行してください。
"""

from picamera2 import Picamera2, Preview
import time
from libcamera import Transform

### params ###
Duration = 200 #(sec)表示時間
Resolution = (1024, 768) #(x, y)解像度

def main(Duration):
    camera = Picamera2()
    camera_config = camera.create_preview_configuration(main={"size": Resolution},
                                                        transform = Transform(hflip=True, vflip=True))
    camera.configure(camera_config)
    camera.start_preview(Preview.QTGL)#,width = Resolution[0],height = Resolution[1])
    camera.start()
    time.sleep(Duration)
    camera.stop_preview()

if __name__ == '__main__':
    main(Duration)