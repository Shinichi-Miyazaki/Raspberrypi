# Make Lego System

# Requiered Materials
## Raspberry pi and camera
- Raspberry Pi 4 (RAM 4GB is enough, 2GB might be OK)
- Raspberry Pi PiNoir Camera Module V2.1
- Case for Raspberry pi 
  - Miuzei 最新 Raspberry Pi 4 ケース ラスベリー パイ4 5.1V 3A USB-C 
- longer flexible flat cable 
  - Raspberry Pi カメラ モジュール 延長ケーブル フラットケーブル

## Monitor and other
- Monitor
  - HP ProDisplay 21.5インチワイドIPSモニター P224 
- HDMI 2.0 切替器 5入力1出力 HDMIセレクター 分配器 4K 60Hz 3D HDCP2.2対応 リモコン付き 
- Twozoh Micro HDMI to HDMI ケーブル 2M (HDMI マイクロタイプDオス) 
- ロジクール ワイヤレスキーボード 無線 薄型 小型 K380GY 

## Power for LED
- Jesverty直流安定化電源SPS-3010 （30V/10A）
- 10cm+20cm 240個（40*6） ブレッドボードジャンパー デュポンワイヤケーブルキット オス-メス
- Logicool Signature M750MGR 

## Lego block
- Purchased by Brickers (https://brickers.jp/)

__Currently, 55000 yen for a system__

# Construct the system
## Step 1: make a case for Raspberry pi
1. Assemble the case for Raspberry pi, according to the instruction.

## Step 2: Install the Raspberry pi OS 
1. Download the Raspberry pi OS imager from the official site. (https://www.raspberrypi.com/software/)
2. Connect a microSD card to your computer using adaptor.
3. Open the Raspberry pi OS imager and select the OS and the microSD card. Basically the latet OS is   
OK for using picamera2, which is the module used in our script. The default setting is OK. If you want to use  
SSH, you can enable it in the advanced setting. 
4. Write the OS to the microSD card. This step take several minutes.  

## Step 3: Set up the Raspberry pi
1. Insert the microSD card to the Raspberry pi.
2. Connect the Raspberry pi to the monitor using HDMI cable.
3. Connect the power supply to the Raspberry pi.
4. Connect the wired mouse. (This mouse is only for the initial setup, later you can switch to the wireless mouse)
5. Follow the instruction on the screen. During setup, you should turn on the Bluetooth and connect to the keyboard and mouse. 

## Step 4: Connect to wifi and download git
1. Connect to the wifi.
2. Open the terminal and type the following command.
```bash
sudo apt-get update
sudo apt-get upgrade
sudo apt-get install git
```

## Step 5: Clone the repository "RaspberryPi"
1. Make a directory for the repository on your desktop. Name is like "Scripts" is OK. 
2. copy the path of the Script directory. 
3. Open the terminal and type the following command.
```bash
cd /home/pi/Desktop/Scripts (or the path you copied)
git clone https://github.com/Shinichi-Miyazaki/Raspberrypi.git
```  

## Step 6: Change screen setting  
For long term imaging, the screen sleep setting should be turn off. 
1. open nano editor   
```bash 
sudo nano /etc/xdg/lxsession/LXDE/autostart
```  
2. add followings   
``` bash 
@xset s off 
@xset s noblank
@xset -dpms
```  

