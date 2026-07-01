import pandas as pd
import numpy as np

# CSV 파일 읽기
csv_files = [
    'data/eps32-c3-supermini_profiles_accel+gyro+mag.csv',
    'data/eps32-c3-supermini_profiles_accel+gyro.csv', 
    'data/eps32-c3-supermini_profiles_accel_only.csv',
    'data/eps32-c3-supermini_profiles_gyro+mag.csv',
    'data/eps32-c3-supermini_profiles_no-sensing.csv',
    'data/eps32-c3-supermini_profiles_ultrasonic.csv'
]

# 레이어별 연산량
LAYER_FLOPS = {
    0: 232800,
    1: 291000,
    2: 436500,
    3: 582000,
    4: 727500
}

# 레이어별 출력 크기 (가정 - 일반적인 신경망 구조)
# 각 레이어 출력은 float32 (4 bytes) 기준
LAYER_OUTPUT_SIZES = {
    0: 100 * 4,   # 100 features * 4 bytes = 400 bytes
    1: 80 * 4,    # 80 features * 4 bytes = 320 bytes
    2: 60 * 4,    # 60 features * 4 bytes = 240 bytes
    3: 40 * 4,    # 40 features * 4 bytes = 160 bytes
    4: 20 * 4,    # 20 features * 4 bytes = 80 bytes (final output)
}

results = []

print("="*100)
print("ESP32-C3 에너지 프로파일 상세 분석")
print("="*100)

# 각 CSV 파일 분석
for csv_file in csv_files:
    df = pd.read_csv(csv_file)
    df.columns = df.columns.str.strip()
    sensor_type = csv_file.replace('eps32-c3-supermini_profiles_', '').replace('.csv', '')
    
    print(f"\n{'='*100}")
    print(f"센서 타입: {sensor_type}")
    print(f"{'='*100}")
    
    # Mode별 분석
    for mode in sorted(df['Mode'].unique()):
        mode_data = df[df['Mode'] == mode]
        
        if len(mode_data) == 0:
            continue
        
        # 기본 통계
        power_mean = mode_data['Power(mW)'].mean()
        power_std = mode_data['Power(mW)'].std()
        
        # 각 Mode 실행 구간 찾기 (연속된 동일 Mode를 하나의 실행으로 간주)
        mode_runs = []
        in_run = False
        run_start = None
        
        for idx, row in df.iterrows():
            if row['Mode'] == mode:
                if not in_run:
                    run_start = row['Time(ms)']
                    in_run = True
                run_end = row['Time(ms)']
            else:
                if in_run:
                    duration = run_end - run_start + 12  # 샘플링 간격
                    mode_runs.append(duration)
                    in_run = False
        
        if in_run:  # 마지막 run 처리
            duration = run_end - run_start + 12
            mode_runs.append(duration)
        
        # 평균 실행 시간 (한 번 실행될 때)
        if mode_runs:
            avg_run_duration = np.mean(mode_runs)
            num_runs = len(mode_runs)
        else:
            avg_run_duration = 0
            num_runs = 0
        
        # ms당 에너지 = 평균 전력 (mW)
        energy_per_ms = power_mean
        
        # 한 번 실행 시 총 에너지
        total_energy_per_run = avg_run_duration * energy_per_ms if avg_run_duration > 0 else 0
        
        mode_desc = ""
        layer_id = None
        flops = None
        output_bytes = None
        
        if mode == 0:
            mode_desc = "Idle (대기)"
        elif 1 <= mode <= 5:
            layer_id = mode - 1
            mode_desc = f"Layer {layer_id}"
            flops = LAYER_FLOPS.get(layer_id, 0)
            output_bytes = LAYER_OUTPUT_SIZES.get(layer_id, 0)
        elif mode == 6:
            mode_desc = "Transmission"
        elif mode == 7:
            mode_desc = f"Sensing"
        
        print(f"\n{'─'*100}")
        print(f"Mode {mode}: {mode_desc}")
        print(f"{'─'*100}")
        print(f"  실행 횟수: {num_runs}회")
        print(f"  평균 1회 실행 시간: {avg_run_duration:.2f} ms")
        print(f"  평균 전력: {power_mean:.2f} ± {power_std:.2f} mW")
        print(f"  1 ms당 에너지: {energy_per_ms:.2f} mW (= {energy_per_ms:.2f} mJ/s)")
        print(f"  1회 실행 시 총 에너지: {total_energy_per_run:.2f} mJ")
        
        if flops:
            print(f"  연산량 (FLOPs): {flops:,}")
            if avg_run_duration > 0:
                flops_per_ms = flops / avg_run_duration
                print(f"  성능: {flops_per_ms:.2f} FLOPs/ms")
                energy_per_mflop = total_energy_per_run / (flops / 1e6)
                print(f"  에너지 효율: {energy_per_mflop:.2f} mJ/MFLOP")
            if output_bytes:
                print(f"  출력 데이터 크기: {output_bytes} bytes")
        
        if mode == 6:
            # Mode 6 직전 Layer 분석
            mode_sequence = []
            for idx, row in df.iterrows():
                mode_sequence.append((row['Time(ms)'], row['Mode']))
            
            # Mode 6 직전 Mode 찾기
            prev_modes_before_tx = {}
            for i in range(1, len(mode_sequence)):
                if mode_sequence[i][1] == 6:
                    prev_mode = mode_sequence[i-1][1]
                    if prev_mode not in prev_modes_before_tx:
                        prev_modes_before_tx[prev_mode] = 0
                    prev_modes_before_tx[prev_mode] += 1
            
            print(f"  전송 직전 Mode 빈도:")
            for prev_mode, count in sorted(prev_modes_before_tx.items()):
                if 1 <= prev_mode <= 5:
                    layer_id_tx = int(prev_mode - 1)
                    bytes_tx = LAYER_OUTPUT_SIZES.get(layer_id_tx, 0)
                    print(f"    Layer {layer_id_tx} → {count}회 전송, 예상 크기: {bytes_tx} bytes")
                    if bytes_tx > 0 and avg_run_duration > 0:
                        energy_per_byte = total_energy_per_run / bytes_tx
                        print(f"                     → Byte당 에너지: {energy_per_byte:.2f} mJ/byte = {energy_per_byte*1000:.2f} µJ/byte")
        
        # 결과 저장
        result = {
            'Sensor_Type': sensor_type,
            'Mode': mode,
            'Mode_Description': mode_desc,
            'Execution_Count': num_runs,
            'Avg_Duration_per_Run_ms': avg_run_duration,
            'Avg_Power_mW': power_mean,
            'Power_Std_mW': power_std,
            'Energy_per_ms_mW': energy_per_ms,
            'Total_Energy_per_Run_mJ': total_energy_per_run,
            'Layer_ID': layer_id,
            'FLOPs': flops,
            'Output_Bytes': output_bytes
        }
        
        if flops and avg_run_duration > 0:
            result['FLOPs_per_ms'] = flops / avg_run_duration
            result['Energy_per_MFLOP_mJ'] = total_energy_per_run / (flops / 1e6)
        
        results.append(result)

# DataFrame 생성 및 저장
import os
os.makedirs('results', exist_ok=True)
results_df = pd.DataFrame(results)
results_df.to_csv('results/detailed_energy_analysis.csv', index=False)

print(f"\n\n{'='*100}")
print("요약 테이블 생성")
print(f"{'='*100}\n")

# Mode별 요약
print("\n1. Mode 0 (Idle) - 대기 상태")
print("─"*80)
idle_summary = results_df[results_df['Mode'] == 0][['Sensor_Type', 'Energy_per_ms_mW', 'Avg_Duration_per_Run_ms']]
print(idle_summary.to_string(index=False))

print("\n\n2. Layers 1-5 (추론) - 한 번 실행 기준")
print("─"*80)
layer_summary = results_df[(results_df['Mode'] >= 1) & (results_df['Mode'] <= 5)].groupby('Layer_ID').agg({
    'Avg_Duration_per_Run_ms': 'mean',
    'Avg_Power_mW': 'mean',
    'Energy_per_ms_mW': 'mean',
    'Total_Energy_per_Run_mJ': 'mean',
    'FLOPs': 'first',
    'Output_Bytes': 'first',
    'FLOPs_per_ms': 'mean',
    'Energy_per_MFLOP_mJ': 'mean'
}).round(2)
print(layer_summary)

print("\n\n3. Mode 6 (Transmission) - 전송")
print("─"*80)
tx_summary = results_df[results_df['Mode'] == 6][['Sensor_Type', 'Avg_Duration_per_Run_ms', 'Energy_per_ms_mW', 'Total_Energy_per_Run_mJ']]
print(tx_summary.to_string(index=False))

print("\n\n4. Mode 7 (Sensing) - 센서")
print("─"*80)
sensing_summary = results_df[results_df['Mode'] == 7][['Sensor_Type', 'Energy_per_ms_mW', 'Avg_Duration_per_Run_ms', 'Total_Energy_per_Run_mJ']]
print(sensing_summary.to_string(index=False))

print(f"\n\n{'='*100}")
print("✓ 상세 분석 완료!")
print(f"  결과 파일: detailed_energy_analysis.csv")
print(f"{'='*100}\n")
