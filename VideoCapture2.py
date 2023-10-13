import cv2
from datetime import datetime

# /dev/video0を指定
DEV_ID = 0

# パラメータ
WIDTH = 640
HEIGHT = 480
FPS = 5

# 録画時間(秒)
REC_SEC = 10

def main():
    # /dev/video0を指定
    cap = cv2.VideoCapture(DEV_ID)

    # パラメータの指定
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, FPS)

    # ファイル名に日付を指定
    date = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = "./" + date + ".mp4"

    # 動画パラメータの指定
    fourcc = cv2.VideoWriter_fourcc('m', 'p', '4', 'v')
    out = cv2.VideoWriter(path, fourcc, FPS, (WIDTH, HEIGHT))

    # キャプチャ
    for _ in range(FPS * REC_SEC):
        ret, frame = cap.read()
        out.write(frame)

    # 後片付け
    cap.release()
    out.release()
    cv2.destroyAllWindows()
    return


if __name__ == "__main__":
    main()