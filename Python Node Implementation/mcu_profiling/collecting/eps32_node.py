import network
import espnow
import time
import machine
import gc
import random
from machine import Pin, I2C
import struct

# ==============================================================================
# [설정] 핀 설정 (3-bit Sync)
# ==============================================================================
# 상태를 알리는 3개의 핀 (Output)
# LSB(비트0): GPIO 2, Bit1: GPIO 3, MSB(비트2): GPIO 4
PIN_BIT_0 = Pin(2, Pin.OUT)
PIN_BIT_1 = Pin(3, Pin.OUT)
PIN_BIT_2 = Pin(4, Pin.OUT)

def set_sync_state(state_val):
    """
    상태 값을 3비트 이진수로 변환하여 핀 출력 설정
    state_val: 0~7 정수
    """
    PIN_BIT_0.value(state_val & 0x01)
    PIN_BIT_1.value((state_val >> 1) & 0x01)
    PIN_BIT_2.value((state_val >> 2) & 0x01)

# 상태 정의
STATE_IDLE      = 0  # 000
STATE_NODE_0    = 1  # 001
STATE_NODE_1    = 2  # 010
STATE_NODE_2    = 3  # 011
STATE_NODE_3    = 4  # 100
STATE_NODE_4    = 5  # 101
STATE_TX        = 6  # 110
STATE_SENSING   = 7  # 111 (센싱 상태)

# ESP-NOW 설정
NEXT_NODE_MAC = b'\xFF\xFF\xFF\xFF\xFF\xFF' 
sta = network.WLAN(network.STA_IF)
sta.active(True)
enow = espnow.ESPNow()
enow.active(True)
enow.add_peer(NEXT_NODE_MAC)

# ==============================================================================
# [설정] 레이어별 연산 부하 설정
# ==============================================================================
# 각 노드의 상대적 연산 부하 비율 (ResNet 구조 반영)
LAYER_FLOP_RATIOS = {
    0: 0.8,
    1: 1.0,
    2: 1.5,
    3: 2.0,
    4: 2.5
}

# 기본 반복 횟수 (MicroPython 속도 고려하여 조정)
BASE_LOOPS = 500

# ==============================================================================
# [설정] 센서 핀 설정
# ==============================================================================
# MPU9250 I2C 설정 (ESP32-C3)
MPU9250_ADDR = 0x68  # MPU9250 I2C 주소 (AD0=LOW)
AK8963_ADDR = 0x0C   # 내장 자기계 주소
I2C_SCL_PIN = 7      # I2C Clock 핀
I2C_SDA_PIN = 6      # I2C Data 핀

# 초음파 센서 핀 설정 (HC-SR04)
ULTRASONIC_TRIGGER_PIN = 8  # Trigger 핀
ULTRASONIC_ECHO_PIN = 9     # Echo 핀

# I2C 초기화
try:
    i2c = I2C(0, scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN), freq=400000)
    print("I2C initialized")
except Exception as e:
    print(f"I2C init error: {e}")
    i2c = None

# 초음파 센서 핀 초기화
trigger_pin = Pin(ULTRASONIC_TRIGGER_PIN, Pin.OUT)
echo_pin = Pin(ULTRASONIC_ECHO_PIN, Pin.IN)
trigger_pin.off()

# ==============================================================================
# [클래스] MPU9250 드라이버
# ==============================================================================
class MPU9250:
    def __init__(self, i2c, addr=0x68):
        self.i2c = i2c
        self.addr = addr
        self.mag_addr = 0x0C
        
        # MPU9250 초기화
        try:
            # WHO_AM_I 확인
            who_am_i = self.i2c.readfrom_mem(self.addr, 0x75, 1)[0]
            print(f"MPU9250 WHO_AM_I: 0x{who_am_i:02X}")
            
            # Power Management 1 - 슬립 모드 해제
            self.i2c.writeto_mem(self.addr, 0x6B, b'\x00')
            time.sleep_ms(100)
            
            # 가속도계 설정: ±2g
            self.i2c.writeto_mem(self.addr, 0x1C, b'\x00')
            
            # 자이로스코프 설정: ±250°/s
            self.i2c.writeto_mem(self.addr, 0x1B, b'\x00')
            
            print("MPU9250 initialized successfully")
        except Exception as e:
            print(f"MPU9250 init error: {e}")
    
    def read_accel(self):
        """가속도계 데이터 읽기 (X, Y, Z)"""
        try:
            data = self.i2c.readfrom_mem(self.addr, 0x3B, 6)
            ax = struct.unpack('>h', data[0:2])[0] / 16384.0
            ay = struct.unpack('>h', data[2:4])[0] / 16384.0
            az = struct.unpack('>h', data[4:6])[0] / 16384.0
            return [ax, ay, az]
        except Exception as e:
            print(f"Accel read error: {e}")
            return [0.0, 0.0, 0.0]
    
    def read_gyro(self):
        """자이로스코프 데이터 읽기 (X, Y, Z)"""
        try:
            data = self.i2c.readfrom_mem(self.addr, 0x43, 6)
            gx = struct.unpack('>h', data[0:2])[0] / 131.0
            gy = struct.unpack('>h', data[2:4])[0] / 131.0
            gz = struct.unpack('>h', data[4:6])[0] / 131.0
            return [gx, gy, gz]
        except Exception as e:
            print(f"Gyro read error: {e}")
            return [0.0, 0.0, 0.0]
    
    def power_off_gyro(self):
        """자이로스코프 전원 끄기 (전력 절감)"""
        try:
            # PWR_MGMT_2 레지스터: 자이로 X, Y, Z 비활성화
            self.i2c.writeto_mem(self.addr, 0x6C, b'\x07')
        except Exception as e:
            print(f"Gyro power off error: {e}")
    
    def power_on_gyro(self):
        """자이로스코프 전원 켜기"""
        try:
            # PWR_MGMT_2 레지스터: 모든 센서 활성화
            self.i2c.writeto_mem(self.addr, 0x6C, b'\x00')
            time.sleep_ms(50)  # 안정화 대기
        except Exception as e:
            print(f"Gyro power on error: {e}")
    
    def init_magnetometer(self):
        """자기계(AK8963) 초기화"""
        try:
            # I2C 마스터 모드 활성화 (바이패스 모드)
            self.i2c.writeto_mem(self.addr, 0x37, b'\x02')
            time.sleep_ms(10)
            
            # AK8963 WHO_AM_I 확인
            mag_id = self.i2c.readfrom_mem(self.mag_addr, 0x00, 1)[0]
            print(f"AK8963 WHO_AM_I: 0x{mag_id:02X}")
            
            # 연속 측정 모드 2 (100Hz), 16-bit 출력
            self.i2c.writeto_mem(self.mag_addr, 0x0A, b'\x16')
            time.sleep_ms(10)
            
            print("AK8963 magnetometer initialized")
            return True
        except Exception as e:
            print(f"Magnetometer init error: {e}")
            return False
    
    def read_magnetometer(self):
        """자기계 데이터 읽기 (X, Y, Z)"""
        try:
            # ST2 레지스터를 읽어 데이터 준비 확인
            status = self.i2c.readfrom_mem(self.mag_addr, 0x02, 1)[0]
            if status & 0x01:  # DRDY 비트 확인
                data = self.i2c.readfrom_mem(self.mag_addr, 0x03, 6)
                mx = struct.unpack('<h', data[0:2])[0] * 0.15  # µT 단위
                my = struct.unpack('<h', data[2:4])[0] * 0.15
                mz = struct.unpack('<h', data[4:6])[0] * 0.15
                # ST2 읽기 (데이터 래치 해제)
                self.i2c.readfrom_mem(self.mag_addr, 0x09, 1)
                return [mx, my, mz]
            else:
                return [0.0, 0.0, 0.0]
        except Exception as e:
            print(f"Magnetometer read error: {e}")
            return [0.0, 0.0, 0.0]
    
    def power_off_accel(self):
        """가속도계 전원 끄기 (전력 절감)"""
        try:
            # PWR_MGMT_2 레지스터: 가속도 X, Y, Z 비활성화
            self.i2c.writeto_mem(self.addr, 0x6C, b'\x38')
        except Exception as e:
            print(f"Accel power off error: {e}")
    
    def power_on_accel(self):
        """가속도계 전원 켜기"""
        try:
            # PWR_MGMT_2 레지스터: 모든 센서 활성화
            self.i2c.writeto_mem(self.addr, 0x6C, b'\x00')
            time.sleep_ms(50)  # 안정화 대기
        except Exception as e:
            print(f"Accel power on error: {e}")

# MPU9250 인스턴스 생성
mpu = None
mag_initialized = False
if i2c is not None:
    try:
        mpu = MPU9250(i2c)
        # 자기계 초기화 시도
        mag_initialized = mpu.init_magnetometer()
    except Exception as e:
        print(f"MPU9250 object creation error: {e}")

# ==============================================================================
# [함수] 초음파 센서 거리 측정
# ==============================================================================
def read_ultrasonic_distance():
    """
    초음파 센서로 거리 측정 (cm)
    반환값: 거리 (cm), 실패 시 -1
    """
    try:
        # 트리거 펄스 생성 (10μs)
        trigger_pin.off()
        time.sleep_us(2)
        trigger_pin.on()
        time.sleep_us(10)
        trigger_pin.off()
        
        # 에코 신호 대기 (타임아웃: 30ms = 약 5m)
        timeout_us = 30000
        start_time = time.ticks_us()
        
        # 에코 핀이 HIGH가 될 때까지 대기
        while echo_pin.value() == 0:
            if time.ticks_diff(time.ticks_us(), start_time) > timeout_us:
                return -1  # 타임아웃
        pulse_start = time.ticks_us()
        
        # 에코 핀이 LOW가 될 때까지 대기
        while echo_pin.value() == 1:
            if time.ticks_diff(time.ticks_us(), pulse_start) > timeout_us:
                return -1  # 타임아웃
        pulse_end = time.ticks_us()
        
        # 거리 계산: (시간 / 2) / 29.1 = cm
        pulse_duration = time.ticks_diff(pulse_end, pulse_start)
        distance = (pulse_duration / 2) / 29.1
        
        return distance
    except Exception as e:
        print(f"Ultrasonic read error: {e}")
        return -1

# ==============================================================================
# [함수] 실제 연산 시뮬레이션 (Convolution 흉내)
# ==============================================================================
def process_layer_compute(node_id):
    state_code = node_id + 1 # Node 0은 State 1 (001)
    print(f"   [State {state_code}] Processing Layer for Node {node_id}...")
    
    # 1. 상태 핀 설정 (High) - 해당 노드 연산 중임을 알림
    set_sync_state(state_code)
    start = time.ticks_us()
    
    # 2. 가상 데이터 생성 (노이즈)
    input_len = 100 
    data = [random.random() for _ in range(input_len)]
    weights = [random.random() for _ in range(3)] # Kernel size 3
    
    # 3. 연산 수행 (Convolution 유사 동작: 곱셈 + 덧셈)
    # 노드별 부하 비율에 따라 반복 횟수 조정
    loops = int(BASE_LOOPS * LAYER_FLOP_RATIOS.get(node_id, 1.0))
    
    result_acc = 0.0
    for _ in range(loops):
        # 1D Convolution Sliding Window 흉내
        for j in range(len(data) - 3):
            # MAC 연산 (Multiply-Accumulate)
            val = (data[j] * weights[0]) + (data[j+1] * weights[1]) + (data[j+2] * weights[2])
            result_acc += val
            
    end = time.ticks_us()
    
    diff = time.ticks_diff(end, start) / 1000.0
    print(f"   > Done. Time: {diff:.2f} ms")
    return result_acc

def process_transmission():
    print(f"   [State {STATE_TX}] Transmitting Data...")
    
    # 1. 상태 핀 설정 (Transmission Mode - 110)
    set_sync_state(STATE_TX)
    
    # 2. 데이터 전송 (Payload 1.2KB 가정)
    payload = b'\x01' * 1280
    try:
        enow.send(NEXT_NODE_MAC, payload)
    except Exception as e:
        print("TX Error:", e)
        
    # 전송 후 잠시 대기 (실제 전송 시간 및 전류 스파이크 확보)
    time.sleep_ms(10)

def process_sensing():
    """
    센싱 단계: MPU9250 또는 초음파 센서 사용
    3초 동안 센서 데이터 수집
    
    MPU9250 전력 소비 (대략적인 값):
    - 가속도계(Accel): ~450 µA
    - 자이로스코프(Gyro): ~3.2 mA
    - 자기계(Mag): ~280 µA
    센서 수가 적을수록 전력 소비 감소
    """
    print(f"   [State {STATE_SENSING}] Sensing Data...")
    
    # 1. 상태 핀 설정 (Sensing Mode - 111)
    set_sync_state(STATE_SENSING)
    start = time.ticks_us()
    
    # 2. 센서 선택 (주석을 번갈아가며 사용)
    
    # ========== 시나리오 1-1: MPU9250 - 가속도계만 사용 (저전력) ==========
    '''
    # 전력: ~450 µA (가장 낮음)
    # 용도: 기본 움직임 감지, 방향 변화 감지
    if mpu is not None:
        # 자이로스코프 전원 끄기 (전력 절감)
        mpu.power_off_gyro()
        
        sensing_duration_ms = 3000  # 3초
        sample_count = 300  # 3초 동안 100Hz = 300 샘플
        
        sensor_data = []
        for i in range(sample_count):
            # 실제 I2C 통신: 가속도 데이터만 읽기 (6 bytes)
            accel = mpu.read_accel()
            sensor_data.append({'accel': accel})
            time.sleep_ms(10)  # 100Hz = 10ms 간격
        
        print(f"      > MPU9250 (Accel only): {len(sensor_data)} samples, ~450µA")
        print(f"      > Last sample: {sensor_data[-1]}")
    else:
        print("      > MPU9250 not available, skipping...")
    '''
    # ========== 시나리오 1-2: MPU9250 - 가속도계 + 자이로스코프 사용 (중간 전력) ==========
    # 전력: ~3.65 mA (중간)
    # 용도: 정밀한 움직임 추적, 회전 감지, IMU 융합
    '''
    if mpu is not None:
        # 자이로스코프 전원 켜기
        mpu.power_on_gyro()
        
        sensing_duration_ms = 3000  # 3초
        sample_count = 300  # 3초 동안 100Hz = 300 샘플
        
        sensor_data = []
        for i in range(sample_count):
            # 실제 I2C 통신: 가속도 + 자이로 데이터 읽기 (12 bytes)
            accel = mpu.read_accel()
            gyro = mpu.read_gyro()
            sensor_data.append({'accel': accel, 'gyro': gyro})
            time.sleep_ms(10)  # 100Hz = 10ms 간격
        
        print(f"      > MPU9250 (Accel+Gyro): {len(sensor_data)} samples, ~3.65mA")
        print(f"      > Last sample: {sensor_data[-1]}")
    else:
        print("      > MPU9250 not available, skipping...")
    '''
    # ========== 시나리오 1-3: MPU9250 - 자이로스코프 + 자기계 사용 ==========
    # 전력: ~3.48 mA (중간)
    # 용도: 회전 감지 + 방향 측정 (가속도 없이)
    # 자이로스코프와 자기계를 사용하여 회전 및 방향 정보 획득
    '''
    if mpu is not None and mag_initialized:
        # 가속도계 전원 끄기, 자이로스코프 전원 켜기
        mpu.power_on_gyro()
        
        sensing_duration_ms = 3000  # 3초
        sample_count = 300  # 3초 동안 100Hz = 300 샘플
        
        sensor_data = []
        for i in range(sample_count):
            # 실제 I2C 통신: 자이로 + 자기 데이터 읽기
            gyro = mpu.read_gyro()
            mag = mpu.read_magnetometer()
            sensor_data.append({'gyro': gyro, 'mag': mag})
            time.sleep_ms(10)  # 100Hz = 10ms 간격
        
        print(f"      > MPU9250 (Gyro+Mag): {len(sensor_data)} samples, ~3.48mA")
        print(f"      > Last sample: {sensor_data[-1]}")
    else:
        if mpu is None:
            print("      > MPU9250 not available, skipping...")
        elif not mag_initialized:
            print("      > Magnetometer not initialized, skipping...")
    '''
    # ========== 시나리오 1-4: MPU9250 - 모든 센서 사용 (9축) ==========
    '''
    # 전력: ~3.93 mA (최대)
    # 용도: 완전한 9축 IMU 센싱 - 가속도 + 자이로 + 자기계
    # AHRS (Attitude and Heading Reference System), 완전한 자세 추정
    if mpu is not None and mag_initialized:
        # 모든 센서 전원 켜기
        mpu.power_on_gyro()
        mpu.power_on_accel()
        
        sensing_duration_ms = 3000  # 3초
        sample_count = 300  # 3초 동안 100Hz = 300 샘플
        
        sensor_data = []
        for i in range(sample_count):
            # 실제 I2C 통신: 가속도 + 자이로 + 자기 데이터 읽기 (18 bytes)
            accel = mpu.read_accel()
            gyro = mpu.read_gyro()
            mag = mpu.read_magnetometer()
            sensor_data.append({'accel': accel, 'gyro': gyro, 'mag': mag})
            time.sleep_ms(10)  # 100Hz = 10ms 간격
        
        print(f"      > MPU9250 (All 9-axis): {len(sensor_data)} samples, ~3.93mA")
        print(f"      > Last sample: {sensor_data[-1]}")
    else:
        if mpu is None:
            print("      > MPU9250 not available, skipping...")
        elif not mag_initialized:
            print("      > Magnetometer not initialized, skipping...")
    
    '''
    # ========== 시나리오 2: 초음파 센서만 (거리 측정) ==========
    
    # 전력: ~15 mA (측정 시), ~2 mA (대기 시) - 펄스 방식이라 평균 전력은 낮음
    # 용도: 거리 측정, 장애물 감지, 근접 센싱
    sensing_duration_ms = 3000  # 3초
    sample_count = 30  # 3초 동안 10Hz = 30 샘플
    
    distance_data = []
    for i in range(sample_count):
        # 실제 초음파 센서 읽기
        distance_cm = read_ultrasonic_distance()
        if distance_cm > 0:
            distance_data.append(distance_cm)
        time.sleep_ms(100)  # 10Hz = 100ms 간격
    
    print(f"      > Ultrasonic: {len(distance_data)} samples, ~2-15mA (pulse)")
    if len(distance_data) > 0:
        avg_distance = sum(distance_data) / len(distance_data)
        print(f"      > Average distance: {avg_distance:.1f} cm")
    
    end = time.ticks_us()
    diff = time.ticks_diff(end, start) / 1000.0
    print(f"   > Sensing Done. Time: {diff:.2f} ms")
# ==============================================================================
# [메인] 전체 파이프라인 시뮬레이션 루프
# ==============================================================================
def main():
    print("=== ESP32 Pipeline Simulator Started ===")
    
    # 초기 상태: 핀 모두 Low (000)
    set_sync_state(STATE_IDLE)
    
    while True:
        print("\n--- New Cycle Start ---")
        
        # 1. 대기 (Idle) - 0.5초
        set_sync_state(STATE_IDLE)
        print("   [State 0] Idle (0.5s)...")
        time.sleep(0.5)
        
        # 2. 순차적 연산 및 전송 (Node 0 ~ Node 4)
        for node_idx in range(5):
            # (1) 레이어 연산 수행
            process_layer_compute(node_idx)
            
            # (2) 데이터 전송 수행 (각 노드 처리 직후)
            process_transmission()
            
            # (3) 센싱 수행 (통신 후)
            process_sensing()
            
        # 사이클 종료 후 다시 대기 상태로
        set_sync_state(STATE_IDLE)

if __name__ == "__main__":
    main()