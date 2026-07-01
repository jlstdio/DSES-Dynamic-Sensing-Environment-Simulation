import pandas as pd

# CSV 읽기
df = pd.read_csv('results/detailed_energy_analysis.csv')

print("="*100)
print("ESP32-C3 Supermini 에너지 프로파일 - 센서 무관 요약")
print("="*100)

# 1. Mode 0 (Idle) - 센서 무관 평균
print("\n1. Mode 0 (Idle - 대기 상태)")
print("─"*80)
idle_data = df[df['Mode'] == 0]
if len(idle_data) > 0:
    avg_energy_per_ms = idle_data['Energy_per_ms_mW'].mean()
    avg_power = idle_data['Avg_Power_mW'].mean()
    print(f"  1ms당 에너지: {avg_energy_per_ms:.2f} mW")
    print(f"  평균 전력: {avg_power:.2f} mW")

# 2. Layers 1-5 - 센서 무관 평균
print("\n\n2. Mode 1-5 (Layer별 추론 - 한 번 실행 기준)")
print("─"*80)
layers = df[(df['Mode'] >= 1) & (df['Mode'] <= 5)]
layer_summary = layers.groupby('Layer_ID').agg({
    'Avg_Duration_per_Run_ms': 'mean',
    'Energy_per_ms_mW': 'mean',
    'Total_Energy_per_Run_mJ': 'mean',
    'FLOPs': 'first',
    'Output_Bytes': 'first',
    'FLOPs_per_ms': 'mean',
    'Energy_per_MFLOP_mJ': 'mean'
})

for layer_id in range(5):
    if layer_id in layer_summary.index:
        row = layer_summary.loc[layer_id]
        print(f"\n  ⚡ Layer {int(layer_id)}")
        print(f"     연산량: {int(row['FLOPs']):,} FLOPs")
        print(f"     평균 실행 시간: {row['Avg_Duration_per_Run_ms']:.2f} ms")
        print(f"     1회 총 에너지: {row['Total_Energy_per_Run_mJ']:.2f} mJ ({row['Total_Energy_per_Run_mJ']/1000:.2f} J)")
        print(f"     1ms당 에너지: {row['Energy_per_ms_mW']:.2f} mW")
        print(f"     출력 크기: {int(row['Output_Bytes'])} bytes")
        print(f"     에너지 효율: {row['Energy_per_MFLOP_mJ']:.2f} mJ/MFLOP")

# 3. Mode 6 (Transmission) - byte별로 정리
print("\n\n3. Mode 6 (Transmission - 전송)")
print("─"*80)
tx_data = df[df['Mode'] == 6]
if len(tx_data) > 0:
    avg_energy_per_ms = tx_data['Energy_per_ms_mW'].mean()
    avg_duration = tx_data['Avg_Duration_per_Run_ms'].mean()
    avg_total_energy = tx_data['Total_Energy_per_Run_mJ'].mean()
    
    print(f"  평균 1ms당 에너지: {avg_energy_per_ms:.2f} mW")
    print(f"  평균 1회 전송 시간: {avg_duration:.2f} ms")
    print(f"  평균 1회 총 에너지: {avg_total_energy:.2f} mJ")
    
    print("\n  📊 Layer별 전송 (출력 byte 크기에 따라):")
    
    # Layer별 출력 크기
    layer_outputs = {
        0: 400,
        1: 320,
        2: 240,
        3: 160,
        4: 80
    }
    
    for layer_id, output_bytes in layer_outputs.items():
        # 이 Layer의 평균 전송 에너지 계산
        energy_per_byte = avg_total_energy / output_bytes
        
        print(f"\n     Layer {layer_id} → {output_bytes} bytes")
        print(f"       1회 전송 에너지: {avg_total_energy:.2f} mJ")
        print(f"       Byte당 에너지: {energy_per_byte:.2f} mJ/byte ({energy_per_byte*1000:.2f} µJ/byte)")

# 4. Mode 7 (Sensing) - 센서별
print("\n\n4. Mode 7 (Sensing - 센서)")
print("─"*80)
sensing_data = df[df['Mode'] == 7]
if len(sensing_data) > 0:
    print("  센서별 1ms당 지속 에너지 소비:\n")
    
    sensing_summary = sensing_data[['Sensor_Type', 'Energy_per_ms_mW', 'Avg_Duration_per_Run_ms', 'Total_Energy_per_Run_mJ']].copy()
    sensing_summary['Energy_3sec_mJ'] = sensing_summary['Energy_per_ms_mW'] * 3000
    sensing_summary['Energy_3sec_J'] = sensing_summary['Energy_3sec_mJ'] / 1000
    
    sensing_summary = sensing_summary.sort_values('Energy_per_ms_mW')
    
    for idx, row in sensing_summary.iterrows():
        print(f"  📡 {row['Sensor_Type']}")
        print(f"     1ms당 에너지: {row['Energy_per_ms_mW']:.2f} mW")
        print(f"     3초 동작 시 총 에너지: {row['Energy_3sec_J']:.2f} J")
        print()

# CSV로 저장
print("\n" + "="*100)
print("요약 테이블 저장")
print("="*100 + "\n")

# 대기
idle_summary_df = pd.DataFrame([{
    'Mode': 'Mode 0 (Idle)',
    'Description': '대기 상태',
    'Energy_per_ms_mW': idle_data['Energy_per_ms_mW'].mean(),
    'Avg_Power_mW': idle_data['Avg_Power_mW'].mean()
}])

# 레이어
layer_summary_df = layer_summary.reset_index()
layer_summary_df['Mode'] = 'Mode ' + (layer_summary_df['Layer_ID'] + 1).astype(int).astype(str)
layer_summary_df['Description'] = 'Layer ' + layer_summary_df['Layer_ID'].astype(int).astype(str)
layer_summary_df = layer_summary_df.rename(columns={
    'Avg_Duration_per_Run_ms': 'Execution_Time_ms',
    'Total_Energy_per_Run_mJ': 'Total_Energy_mJ',
    'Output_Bytes': 'Output_Size_bytes'
})
layer_summary_df = layer_summary_df[[
    'Mode', 'Description', 'FLOPs', 'Execution_Time_ms', 'Total_Energy_mJ',
    'Energy_per_ms_mW', 'Output_Size_bytes', 'Energy_per_MFLOP_mJ'
]]

# 전송
tx_summary_df = pd.DataFrame([
    {
        'Mode': 'Mode 6 (Transmission)',
        'Description': f'Layer {layer_id} 전송',
        'Output_Size_bytes': output_bytes,
        'Avg_Transmission_Time_ms': tx_data['Avg_Duration_per_Run_ms'].mean(),
        'Total_Energy_mJ': tx_data['Total_Energy_per_Run_mJ'].mean(),
        'Energy_per_ms_mW': tx_data['Energy_per_ms_mW'].mean(),
        'Energy_per_byte_mJ': tx_data['Total_Energy_per_Run_mJ'].mean() / output_bytes,
        'Energy_per_byte_uJ': (tx_data['Total_Energy_per_Run_mJ'].mean() / output_bytes) * 1000
    }
    for layer_id, output_bytes in layer_outputs.items()
])

# 센싱
sensing_summary_df = sensing_summary.copy()
sensing_summary_df['Mode'] = 'Mode 7 (Sensing)'
sensing_summary_df['Description'] = sensing_summary_df['Sensor_Type']
sensing_summary_df = sensing_summary_df[[
    'Mode', 'Description', 'Energy_per_ms_mW', 'Energy_3sec_J'
]]

# 전체 저장
idle_summary_df.to_csv('summary_idle_only.csv', index=False)
layer_summary_df.to_csv('summary_layers_only.csv', index=False)
tx_summary_df.to_csv('summary_transmission_by_bytes.csv', index=False)
sensing_summary_df.to_csv('summary_sensing_by_sensor.csv', index=False)

print("✓ summary_idle_only.csv")
print("✓ summary_layers_only.csv")
print("✓ summary_transmission_by_bytes.csv")
print("✓ summary_sensing_by_sensor.csv")

# 통합 요약
all_summary = pd.concat([
    idle_summary_df[['Mode', 'Description']].assign(
        Key_Metric='1ms당 에너지',
        Value=idle_summary_df['Energy_per_ms_mW'].apply(lambda x: f"{x:.2f} mW")
    ),
    layer_summary_df[['Mode', 'Description']].assign(
        Key_Metric='연산량/시간/에너지',
        Value=layer_summary_df.apply(
            lambda r: f"{int(r['FLOPs']):,} FLOPs / {r['Execution_Time_ms']:.0f} ms / {r['Total_Energy_mJ']/1000:.2f} J",
            axis=1
        )
    ),
    tx_summary_df[['Mode', 'Description']].assign(
        Key_Metric='전송 (byte당)',
        Value=tx_summary_df.apply(
            lambda r: f"{int(r['Output_Size_bytes'])} bytes → {r['Energy_per_byte_uJ']:.0f} µJ/byte",
            axis=1
        )
    ),
    sensing_summary_df[['Mode', 'Description']].assign(
        Key_Metric='센서 (1ms당)',
        Value=sensing_summary_df['Energy_per_ms_mW'].apply(lambda x: f"{x:.2f} mW")
    )
], ignore_index=True)

all_summary.to_csv('SUMMARY_ALL_MODES.csv', index=False)
print("✓ SUMMARY_ALL_MODES.csv (통합 요약)")

print("\n" + "="*100)
print("✓ 분석 완료!")
print("="*100)
