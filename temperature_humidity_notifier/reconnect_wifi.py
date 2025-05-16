#!/usr/bin/env python3
import subprocess
import time
import logging
import os

# ログ設定
logging.basicConfig(
    filename='/home/pi/wifi_monitor.log',
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)

def is_connected():
    """インターネット接続を確認する"""
    try:
        # Googleのパブリックサーバーにpingを送信
        subprocess.check_output(['ping', '-c', '1', '8.8.8.8'], stderr=subprocess.STDOUT, timeout=3)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False

def restart_wifi():
    """WiFiインターフェースを再起動する"""
    logging.info("WiFi接続が切れました。再接続を試みます...")
    try:
        # WiFiインターフェースの再起動
        subprocess.call(['sudo', 'ifconfig', 'wlan0', 'down'])
        time.sleep(1)
        subprocess.call(['sudo', 'ifconfig', 'wlan0', 'up'])
        time.sleep(5)

        # それでも接続できない場合はwpa_supplicantも再起動
        if not is_connected():
            logging.info("インターフェース再起動で接続できません。wpa_supplicantを再起動します...")
            subprocess.call(['sudo', 'systemctl', 'restart', 'wpa_supplicant'])
            time.sleep(10)

        # さらに接続できない場合はnetworkingサービス全体を再起動
        if not is_connected():
            logging.info("wpa_supplicant再起動でも接続できません。ネットワークサービスを再起動します...")
            subprocess.call(['sudo', 'systemctl', 'restart', 'networking'])
            time.sleep(15)

        # 接続確認
        if is_connected():
            logging.info("WiFi接続が復旧しました")
            return True
        else:
            logging.error("WiFi接続の復旧に失敗しました")
            return False
    except Exception as e:
        logging.error(f"再接続処理中にエラーが発生しました: {str(e)}")
        return False

def main():
    check_interval = 60  # 接続確認の間隔（秒）

    logging.info("WiFi接続モニタリングを開始しました")

    while True:
        if not is_connected():
            restart_wifi()
        time.sleep(check_interval)

if __name__ == "__main__":
    main()