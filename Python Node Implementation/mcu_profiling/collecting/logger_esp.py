"""
[실행 가이드]
1. 하드웨어 연결 (3-bit Sync):
   - Worker Pin 2 (LSB) -> Logger Pin 2 (Input)
   - Worker Pin 3 (Mid) -> Logger Pin 3 (Input)
   - Worker Pin 4 (MSB) -> Logger Pin 4 (Input)
   - GND끼리 반드시 연결!

2. 모드 정의 (CSV 'Mode' 컬럼 값):
   0: Idle
   1: Node 0 Compute
   2: Node 1 Compute
   3: Node 2 Compute
   4: Node 3 Compute
   5: Node 4 Compute
   6: Transmission
"""

from machine import I2C, Pin
import time
from ina219_driver import INA219

# =========================================================
# [설정] 핀 및 주기 설정
# =========================================================
I2C_SDA_PIN = 8
I2C_SCL_PIN = 9

# 동기화 입력 핀 (Logger 기준)
PIN_IN_0 = Pin(2, Pin.IN, Pin.PULL_DOWN) # LSB
PIN_IN_1 = Pin(3, Pin.IN, Pin.PULL_DOWN)
PIN_IN_2 = Pin(4, Pin.IN, Pin.PULL_DOWN) # MSB

LOG_INTERVAL = 10  # ms

# =========================================================
# [초기화]
# =========================================================
try:
    i2c = I2C(0, scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN), freq=400000)
    sensor = INA219(i2c, addr=0x40)
    sensor.set_calibration_32V_2A()
    print("Msg: Logger Ready with 3-bit Sync Mode.")
except Exception as e:
    print(f"Msg: Init Error - {e}")

print("Time(ms),Voltage(V),Current(mA),Power(mW),Mode")

start_time = time.ticks_ms()

while True:
    try:
        bus_v = sensor.get_bus_voltage()
        current_ma = sensor.get_current()
        power_mw = bus_v * current_ma
        
        bit0 = PIN_IN_0.value()
        bit1 = PIN_IN_1.value()
        bit2 = PIN_IN_2.value()
        
        mode = bit0 | (bit1 << 1) | (bit2 << 2)
        
        now = time.ticks_diff(time.ticks_ms(), start_time)
        print(f"{now},{bus_v:.2f},{current_ma:.2f},{power_mw:.2f},{mode}")
        
        time.sleep_ms(LOG_INTERVAL)
        
    except Exception as e:
        print(f"Msg: Error - {e}")
        time.sleep(1)