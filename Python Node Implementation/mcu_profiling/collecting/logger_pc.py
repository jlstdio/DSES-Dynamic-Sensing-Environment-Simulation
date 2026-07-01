import serial
import time
import csv
import threading

"""
[실행 가이드]
1. 준비물:
   - ESP32-C3 보드 (Logger 역할)
   - INA219 모듈
   - 타겟 보드 (Worker) 및 전원 소스

2. 하드웨어 연결 (ESP32-C3 Mini 기준):
   - INA219 VCC -> ESP32 3.3V
   - INA219 GND -> ESP32 GND
   - INA219 SDA -> ESP32 GPIO 8 (아래 설정에서 변경 가능)
   - INA219 SCL -> ESP32 GPIO 9 (아래 설정에서 변경 가능)
   * 주의: 타겟 보드의 전원은 INA219의 Vin+와 Vin-를 통과해야 합니다.

3. 실행 순서:
   1) 'ina219.py' 라이브러리 파일을 ESP32에 먼저 업로드합니다.
   2) 이 코드('measurer.py')를 ESP32에 업로드하고 실행합니다.
      (전원 인가 시 자동 실행하려면 파일명을 'main.py'로 저장하세요.)
   3) PC에서 'serial_to_csv.py'를 실행하여 로그 데이터를 CSV로 저장합니다.
"""

# =========================================================
# [설정] PC에 연결된 Logger ESP32의 포트 설정
# =========================================================
# 윈도우 예시: "COM3", "COM4" 
# 맥/리눅스 예시: "/dev/ttyUSB0", "/dev/tty.usbmodem..."
SERIAL_PORT = "/dev/cu.usbmodem101"  # 여기에 실제 포트명을 입력하세요
BAUD_RATE = 115200
OUTPUT_FILE = "experiment_data.csv"

def save_serial_to_csv():
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"✅ Connected to {SERIAL_PORT}")
        print(f"📂 Saving data to {OUTPUT_FILE}...")
        print("❌ Press Ctrl+C to stop logging.\n")
        
        with open(OUTPUT_FILE, mode='w', newline='') as file:
            writer = csv.writer(file)
            # 헤더 작성 (Logger 코드 포맷에 맞춤)
            writer.writerow(["Time(ms)", "Voltage(V)", "Current(mA)", "Power(mW)"])
            
            while True:
                if ser.in_waiting > 0:
                    try:
                        # ESP32가 보낸 한 줄 읽기
                        line = ser.readline().decode('utf-8').strip()
                        
                        # 데이터 유효성 검사 (숫자와 콤마로 된 데이터인지)
                        if ',' in line and not line.startswith("Time"):
                            parts = line.split(',')
                            if len(parts) >= 4:
                                writer.writerow(parts)
                                print(f"Logged: {line}")
                        else:
                            # 디버그 메시지 등은 그냥 출력
                            print(f"[Msg] {line}")
                            
                    except UnicodeDecodeError:
                        continue # 깨진 데이터 무시
                        
    except serial.SerialException as e:
        print(f"⚠️ Error opening serial port: {e}")
    except KeyboardInterrupt:
        print("\n🛑 Logging stopped. Data saved.")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == "__main__":
    # pyserial 라이브러리 필요: pip install pyserial
    save_serial_to_csv()