#!/usr/bin/env python3
"""
gpio_reset.py
Raspberry PiのGPIOピンをリセットするための独立したスクリプト
特にDHT22温湿度センサーが使用するピンの初期化を目的としています
"""

import time
import os
import sys
import subprocess
import board

# DHT22センサーが接続されているGPIOピン
DHT_PIN = board.D4  # BCM4 に相当

def reset_gpio_with_system_commands():
    """システムコマンドを使用してGPIOをリセットする"""
    print("システムコマンドを使用してGPIOをリセットしています...")

    try:
        # GPIOサービスの再起動
        subprocess.run(["sudo", "systemctl", "restart", "pigpiod"], check=True)
        print("pigpiodサービスを再起動しました")
    except subprocess.CalledProcessError as e:
        print(f"pigpiodサービスの再起動に失敗しました: {e}")

    try:
        # GPIOカーネルモジュールのリロード
        subprocess.run(["sudo", "rmmod", "gpio_rpi"], check=True)
        time.sleep(1)
        subprocess.run(["sudo", "modprobe", "gpio_rpi"], check=True)
        print("GPIOカーネルモジュールをリロードしました")
    except subprocess.CalledProcessError as e:
        print(f"GPIOカーネルモジュールのリロードに失敗しました: {e}")

def reset_gpio_with_rpi_library():
    """RPi.GPIOライブラリを使用してGPIOをリセットする"""
    try:
        import RPi.GPIO as GPIO

        print("RPi.GPIOライブラリを使用してGPIOをリセットしています...")

        # GPIO設定をリセット
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)

        # DHT22用のピン（BCM4）を特に注意してリセット
        pin_number = 4  # board.D4 に相当するBCMピン番号

        # 一度出力モードに設定して初期化
        GPIO.setup(pin_number, GPIO.OUT)
        GPIO.output(pin_number, GPIO.LOW)
        time.sleep(0.5)

        # 入力モードに戻す
        GPIO.setup(pin_number, GPIO.IN)
        time.sleep(0.5)

        # 完全クリーンアップ
        GPIO.cleanup()
        print("GPIOのリセットが完了しました")

        return True
    except Exception as e:
        print(f"RPi.GPIOライブラリによるリセット中にエラーが発生しました: {e}")
        return False

def reset_adafruit_dht():
    """Adafruit DHT用のリセット処理"""
    try:
        import adafruit_dht

        print("AdafruitのDHTライブラリを使用してセンサーをリセットしています...")

        # DHT22センサーオブジェクトを一度作成
        dht_device = adafruit_dht.DHT22(DHT_PIN)

        # 正常に初期化できたかテストするため読み取りを試みる
        try:
            temperature = dht_device.temperature
            humidity = dht_device.humidity
            print(f"センサーからのテスト読み取り: 温度={temperature}°C, 湿度={humidity}%")
        except Exception as e:
            print(f"テスト読み取り中にエラーが発生しました（正常な場合があります）: {e}")

        # 適切にクリーンアップ
        time.sleep(1)
        dht_device.exit()
        print("DHT22センサーのリセットが完了しました")

        return True
    except Exception as e:
        print(f"AdafruitのDHTライブラリによるリセット中にエラーが発生しました: {e}")
        return False

def main():
    """メイン関数"""
    print("GPIOリセットスクリプトを開始します...")

    # PIDファイルのパス
    pid_file = "/tmp/gpio_reset.pid"

    # 重複実行チェック
    if os.path.exists(pid_file):
        with open(pid_file, 'r') as f:
            old_pid = f.read().strip()
        try:
            # PIDが有効かチェック
            os.kill(int(old_pid), 0)
            print(f"別のインスタンスが既に実行中です（PID: {old_pid}）。終了します。")
            sys.exit(1)
        except (OSError, ProcessLookupError):
            # PIDは無効なので処理を続行
            pass

    # 新しいPIDを書き込み
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))

    try:
        # システムコマンドでのリセット
        reset_gpio_with_system_commands()

        # 少し待機
        time.sleep(2)

        # RPi.GPIOライブラリでのリセット
        reset_gpio_with_rpi_library()

        # 少し待機
        time.sleep(2)

        # Adafruit DHTライブラリでのリセット
        reset_adafruit_dht()

        print("すべてのGPIOリセット処理が完了しました")

    finally:
        # PIDファイルを削除
        if os.path.exists(pid_file):
            os.remove(pid_file)

if __name__ == "__main__":
    main()