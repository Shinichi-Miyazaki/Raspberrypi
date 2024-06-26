"""ShowPreview.py
Author: Shinichi Miyazaki

このプログラムはRaspberry piでカメラのプレビュー画像を表示します。
Durationという変数に希望の時間を秒単位で記載することで、表示時間を決めることが可能です。
実行前に、paramsの部分を任意の数値に書き換えてから実行してください。
デフォルトの解像度は(1640, 1232)です。解像度を変更するとsensor modeが変更され、時に望んだ範囲が映らなくなるので注意。
"""

from picamera2 import Picamera2, Preview
import time
from libcamera import Transform

### params ###
Duration = 200 #(sec)表示時間
Resolution = (1640, 1232) #(x, y) default = (1640, 1232)

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