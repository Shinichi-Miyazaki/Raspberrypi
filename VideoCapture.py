import os
import cv2
from datetime import datetime

# /dev/video0を指定
DEV_ID = 0

# params
Width = 640  # 幅
Height = 480  # 高さ
FPS = 10  # フレームレート (frames/sec)
VideoDuration = 0.5 # ビデオの長さ　(分)

# USBを接続したら、パス名を調べて (右クリックでコピー) 下の""内にペースト
USBpath = ""

def main():
    # /dev/video0を指定
    cap = cv2.VideoCapture(DEV_ID)

    # パラメータの指定
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, Width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, Height)
    cap.set(cv2.CAP_PROP_FPS, FPS)

    # 記録フォルダの作成
    os.makedirs(USBpath + "/Videos", exist_ok=True)

    # ファイル名に日付を指定
    date = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = USBpath + "/Videos" + date + ".mp4"

    # 動画パラメータの指定
    fourcc = cv2.VideoWriter_fourcc('m', 'p', '4', 'v')
    out = cv2.VideoWriter(path, fourcc, FPS, (Width, Height))

    # キャプチャ
    for _ in range(FPS * int(VideoDuration*60)):
        ret, frame = cap.read()
        out.write(frame)
        # 画像表示
        cv2.imshow("Frame", frame)

    # 後片付け
    cap.release()
    out.release()
    cv2.destroyAllWindows()
    return


if __name__ == "__main__":
    main()