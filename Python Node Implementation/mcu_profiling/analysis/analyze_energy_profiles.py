import pandas as pd
import numpy as np
import glob
import os

csv_files = glob.glob('eps32-c3-supermini_profiles*.csv')
csv_files.sort()

print(f"Found {len(csv_files)} CSV files:")
for f in csv_files:
    print(f"  - {f}")
print()

results = []

BASE_LOOPS = 500
LAYER_FLOP_RATIOS = {
    0: 0.8,
    1: 1.0,
    2: 1.5,
    3: 2.0,
    4: 2.5
}

# Convolution 1D: input_len=100, kernel_size=3, sliding window
input_len = 100
kernel_size = 3
sliding_operations = input_len - kernel_size

for layer_id in range(5):
    loops = int(BASE_LOOPS * LAYER_FLOP_RATIOS[layer_id])
    flops_per_layer = loops * sliding_operations * 6  # 6 FLOPs per sliding operation
    LAYER_FLOP_RATIOS[layer_id] = flops_per_layer

print("=== Layer Computational Load (FLOPs) ===")
for layer_id, flops in LAYER_FLOP_RATIOS.items():
    print(f"Layer {layer_id}: {flops:,} FLOPs")
print()

for csv_file in csv_files:
    print(f"\n{'='*80}")
    print(f"Analyzing: {csv_file}")
    print(f"{'='*80}\n")
    
    sensor_type = csv_file.replace('eps32-c3-supermini_profiles_', '').replace('.csv', '')
    
    try:
        df = pd.read_csv(csv_file)
        df.columns = df.columns.str.strip()
        # print(f"Columns found: {df.columns.tolist()}")
        
        if 'Mode' in df.columns:
            df['Mode'] = df['Mode'].astype(int)
        
        elif len(df.columns) == 5:
            df.columns = ['Time(ms)', 'Voltage(V)', 'Current(mA)', 'Power(mW)', 'Mode']
            df['Mode'] = df['Mode'].astype(int)
        
        else:
            print(f"Warning: Unexpected CSV structure in {csv_file}")
            print(f"Columns: {df.columns.tolist()}")
            continue

    except Exception as e:
        print(f"Error reading {csv_file}: {e}")
        import traceback
        traceback.print_exc()
        continue
    
    print(f"Total records: {len(df)}")
    print(f"Available modes: {sorted(df['Mode'].unique())}")
    print(f"First few rows:")
    print(df.head())
    print()
    
    for mode in sorted(df['Mode'].unique()):
        mode_data = df[df['Mode'] == mode]
        
        print(f"Processing mode {mode}: {len(mode_data)} records")
        
        if len(mode_data) == 0:
            print(f"  Skipping mode {mode} - no data")
            continue
        
        power_mean = mode_data['Power(mW)'].mean()
        power_std = mode_data['Power(mW)'].std()
        power_max = mode_data['Power(mW)'].max()
        power_min = mode_data['Power(mW)'].min()
        
        time_start = mode_data['Time(ms)'].min()
        time_end = mode_data['Time(ms)'].max()
        duration_ms = time_end - time_start + 12
        
        # calc energy (mW * ms = mJ)
        energy_total_mJ = power_mean * duration_ms
        
        # energy usage per second (J/s = W)
        if duration_ms > 0:
            power_per_second_mW = power_mean  # 평균 전력이 곧 초당 에너지 사용량
            energy_per_ms = power_mean  # mW * 1ms = mW (평균 전력)
        else:
            power_per_second_mW = 0
            energy_per_ms = 0
        
        # Mode description
        mode_desc = ""
        layer_id = None
        flops = None
        
        if mode == 0:
            mode_desc = "Idle"
        elif 1 <= mode <= 5:
            layer_id = mode - 1
            mode_desc = f"Layer {layer_id} Inference"
            flops = LAYER_FLOP_RATIOS[layer_id]
        elif mode == 6:
            mode_desc = "Transmission"
        elif mode == 7:
            mode_desc = f"Sensing ({sensor_type})"
        
        print(f"Mode {mode}: {mode_desc}")
        print(f"  Duration: {duration_ms:.2f} ms")
        print(f"  Power - Mean: {power_mean:.2f} mW, Std: {power_std:.2f} mW")
        print(f"  Power - Max: {power_max:.2f} mW, Min: {power_min:.2f} mW")
        print(f"  Total Energy: {energy_total_mJ:.2f} mJ")
        print(f"  Energy per ms: {energy_per_ms:.2f} mW")
        
        if flops:
            print(f"  Computational Load: {flops:,} FLOPs")
            if duration_ms > 0:
                flops_per_ms = flops / duration_ms
                print(f"  Performance: {flops_per_ms:.2f} FLOPs/ms")
        
        print()
        
        result = {
            'CSV_File': csv_file,
            'Sensor_Type': sensor_type,
            'Mode': mode,
            'Mode_Description': mode_desc,
            'Duration_ms': duration_ms,
            'Power_Mean_mW': power_mean,
            'Power_Std_mW': power_std,
            'Power_Max_mW': power_max,
            'Power_Min_mW': power_min,
            'Total_Energy_mJ': energy_total_mJ,
            'Energy_per_ms_mW': energy_per_ms,
            'Layer_ID': layer_id,
            'FLOPs': flops
        }
        
        if flops and duration_ms > 0:
            result['FLOPs_per_ms'] = flops / duration_ms
            result['Energy_per_MFLOP_mJ'] = energy_total_mJ / (flops / 1e6)
        
        results.append(result)

results_df = pd.DataFrame(results)

# Mode 6 (Transmission) Analysis: Energy per Byte
print(f"\n{'='*80}")
print("Mode 6 (Transmission) Analysis: Energy per Byte")
print(f"{'='*80}\n")

transmission_data = results_df[results_df['Mode'] == 6]
if len(transmission_data) > 0:
    # Assumption: Transmission data size (needs verification in actual code)
    # Typically, inference results are a few hundred bytes
    assumed_bytes = 256  # Assumed value
    
    for idx, row in transmission_data.iterrows():
        energy_per_byte = row['Total_Energy_mJ'] / assumed_bytes
        results_df.at[idx, 'Assumed_Bytes'] = assumed_bytes
        results_df.at[idx, 'Energy_per_Byte_uJ'] = energy_per_byte * 1000  # mJ to uJ
        
        print(f"Sensor Type: {row['Sensor_Type']}")
        print(f"  Duration: {row['Duration_ms']:.2f} ms")
        print(f"  Total Energy: {row['Total_Energy_mJ']:.2f} mJ")
        print(f"  Assumed Data Size: {assumed_bytes} bytes")
        print(f"  Energy per Byte: {energy_per_byte * 1000:.2f} µJ/byte")
        print()

# Mode 7 (Sensing) Analysis: 3-second Operation
print(f"\n{'='*80}")
print("Mode 7 (Sensing) Analysis: 3-second Operation")
print(f"{'='*80}\n")

sensing_data = results_df[results_df['Mode'] == 7].copy()
if len(sensing_data) > 0:
    print("Sensor Energy Consumption (3-second measurement):\n")
    for idx, row in sensing_data.iterrows():
        energy_3sec_mJ = row['Energy_per_ms_mW'] * 3000
        
        results_df.at[idx, 'Energy_3sec_mJ'] = energy_3sec_mJ
        results_df.at[idx, 'Energy_3sec_J'] = energy_3sec_mJ / 1000
        sensing_data.at[idx, 'Energy_3sec_mJ'] = energy_3sec_mJ
        sensing_data.at[idx, 'Energy_3sec_J'] = energy_3sec_mJ / 1000
        
        print(f"Sensor: {row['Sensor_Type']}")
        print(f"  Measured Duration: {row['Duration_ms']:.2f} ms")
        print(f"  Average Power: {row['Power_Mean_mW']:.2f} mW")
        print(f"  Energy for 3 seconds: {energy_3sec_mJ:.2f} mJ ({energy_3sec_mJ/1000:.3f} J)")
        print(f"  Energy per second: {energy_3sec_mJ/3:.2f} mJ/s")
        print()

output_file = 'energy_analysis_summary.csv'
results_df.to_csv(output_file, index=False)
print(f"\nResults saved to: {output_file}")

print(f"\n{'='*80}")
print("SUMMARY TABLE")
print(f"{'='*80}\n")

summary_by_mode = results_df.groupby('Mode').agg({
    'Mode_Description': 'first',
    'Duration_ms': 'mean',
    'Power_Mean_mW': 'mean',
    'Total_Energy_mJ': 'mean',
    'Energy_per_ms_mW': 'mean'
}).round(2)

print(summary_by_mode)
print()

if len(sensing_data) > 0:
    print("\nSensor-specific Summary (Mode 7):")
    sensor_summary = sensing_data[['Sensor_Type', 'Power_Mean_mW', 'Energy_3sec_mJ', 'Energy_3sec_J']].copy()
    sensor_summary = sensor_summary.round(2)
    print(sensor_summary.to_string(index=False))
    print()

layer_data = results_df[(results_df['Mode'] >= 1) & (results_df['Mode'] <= 5)]
if len(layer_data) > 0:
    print("\nLayer-specific Summary (Mode 1-5):")
    layer_summary = layer_data[['Layer_ID', 'Duration_ms', 'Power_Mean_mW', 'Total_Energy_mJ', 'FLOPs', 'Energy_per_MFLOP_mJ']].copy()
    layer_summary = layer_summary.groupby('Layer_ID').mean().round(2)
    print(layer_summary)
    print()

print(f"\nAnalysis complete! Check '{output_file}' for detailed results.")
