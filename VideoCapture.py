"""VideCapture.py
Author: Shinichi Miyazaki

このプログラムはRaspberry piとカメラで、指定のサイズのビデオを指定のフレームレートと時間で撮影します。
保存先は USBpath　というところに記載することで指定します。
"""

import os
import cv2
from datetime import datetime

### params ###
Width = 640  # 幅
Height = 480  # 高さ
FPS = 10  # フレームレート (frames/sec)
VideoDuration = 0.5 # ビデオの長さ　(分)
# USBを接続したら、パス名を調べて (右クリックでコピー) 下の""内にペースト
USBpath = ""

def main():
    cap = cv2.VideoCapture(0)
    # 撮影するビデオの設定
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, Width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, Height)
    cap.set(cv2.CAP_PROP_FPS, FPS)

    # 保存フォルダの作成
    os.makedirs(USBpath + "/Videos", exist_ok=True)

    # 日付を取得してビデオ名の作成
    date = datetime.now().strftime("%Y%m%d_%H%M%S")
    VideoPath = USBpath + "/Videos" + date + ".mp4"

    # コーデックの指定
    fourcc = cv2.VideoWriter_fourcc('m', 'p', '4', 'v')
    out = cv2.VideoWriter(VideoPath, fourcc, FPS, (Width, Height))

    # キャプチャ
    for _ in range(FPS * int(VideoDuration*60)):
        ret, frame = cap.read()
        out.write(frame)
        # プレビュー表示
        cv2.imshow("Frame", frame)
        key = cv2.waitKey(1)

    # 後片付け
    cap.release()
    out.release()
    cv2.destroyAllWindows()
    return


if __name__ == "__main__":
    main()