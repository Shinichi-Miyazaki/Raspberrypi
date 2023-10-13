import cv2
import datetime

# params
Width = 640  # 幅
Height = 480  # 高さ
FPS = 10  # フレームレート (frames/sec)
VideoDuration = 1 # ビデオの長さ　(分)

today = datetime.date.today()
# USBを接続したら、パス名を調べて (右クリックでコピー) 下の""内にペースト
USBpath = ""
data_dir_path = USBpath + "/Video{}/".format(today)

# VideoCaptureオブジェクト取得
cap = cv2.VideoCapture(0, cv2.CAP_V4L2)

# キャプチャパラメータ設定
cap.set(cv2.CAP_PROP_FRAME_WIDTH, Width)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, Height)
cap.set(cv2.CAP_PROP_FPS, FPS)

# ファイル名生成
date = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
path = data_dir_path + "./" + date + ".mp4"

# 出力ファイル設定
fourcc = cv2.VideoWriter_fourcc('m', 'p', '4', 'v')
out = cv2.VideoWriter(path, fourcc, FPS, (Width, Height))

base_timing = datetime.datetime.now()

# キャプチャ実行
while (True):
    # フレームを取得
    ret, frame = cap.read()

    # 読み込めない場合エラー処理
    if not ret:
        print("not capture")
        break

    # フレームを出力
    out.write(frame)

    # 画像表示
    cv2.imshow("Frame", frame)

    # 時間を超えたら終了
    current_timing = datetime.datetime.now()
    elapsed_sec = (current_timing - base_timing).total_seconds()
    if elapsed_sec > VideoDuration*60:
        break



# カメラデバイスクローズ
cap.release()
out.release()

# ウィンドウクローズ
cv2.destroyAllWindows()