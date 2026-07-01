import pandas as pd

# Read the detailed results
df = pd.read_csv('results/energy_analysis_summary.csv')

# Create separate summary sheets

# 1. Mode 0 (Idle) Summary
idle_data = df[df['Mode'] == 0].copy()
idle_summary = idle_data[[
    'Sensor_Type', 'Duration_ms', 'Power_Mean_mW', 'Power_Std_mW',
    'Power_Max_mW', 'Power_Min_mW', 'Total_Energy_mJ', 'Energy_per_ms_mW'
]].round(2)

# 2. Layers 1-5 (Inference) Summary
layer_data = df[(df['Mode'] >= 1) & (df['Mode'] <= 5)].copy()
layer_summary = layer_data[[
    'Sensor_Type', 'Mode', 'Layer_ID', 'Duration_ms', 'Power_Mean_mW',
    'Power_Std_mW', 'Power_Max_mW', 'Power_Min_mW', 'Total_Energy_mJ',
    'Energy_per_ms_mW', 'FLOPs', 'FLOPs_per_ms', 'Energy_per_MFLOP_mJ'
]].round(2)

# 3. Mode 6 (Transmission) Summary
tx_data = df[df['Mode'] == 6].copy()
tx_summary = tx_data[[
    'Sensor_Type', 'Duration_ms', 'Power_Mean_mW', 'Power_Std_mW',
    'Power_Max_mW', 'Power_Min_mW', 'Total_Energy_mJ', 'Energy_per_ms_mW',
    'Assumed_Bytes', 'Energy_per_Byte_uJ'
]].round(2)

# 4. Mode 7 (Sensing) Summary
sensing_data = df[df['Mode'] == 7].copy()
sensing_summary = sensing_data[[
    'Sensor_Type', 'Duration_ms', 'Power_Mean_mW', 'Power_Std_mW',
    'Power_Max_mW', 'Power_Min_mW', 'Total_Energy_mJ', 'Energy_per_ms_mW',
    'Energy_3sec_mJ', 'Energy_3sec_J'
]].round(2)

# 5. Overall Average by Mode
mode_avg = df.groupby('Mode').agg({
    'Mode_Description': 'first',
    'Duration_ms': 'mean',
    'Power_Mean_mW': 'mean',
    'Power_Std_mW': 'mean',
    'Total_Energy_mJ': 'mean',
    'Energy_per_ms_mW': 'mean'
}).round(2)

# Save to Excel with multiple sheets
with pd.ExcelWriter('energy_profile_analysis.xlsx', engine='openpyxl') as writer:
    mode_avg.to_excel(writer, sheet_name='Overall_Summary')
    idle_summary.to_excel(writer, sheet_name='Mode0_Idle', index=False)
    layer_summary.to_excel(writer, sheet_name='Mode1-5_Layers', index=False)
    tx_summary.to_excel(writer, sheet_name='Mode6_Transmission', index=False)
    sensing_summary.to_excel(writer, sheet_name='Mode7_Sensing', index=False)
    df.to_excel(writer, sheet_name='Complete_Data', index=False)

print("✓ Created energy_profile_analysis.xlsx with organized data")

# Also create simplified CSV summaries
print("\n=== Creating individual summary CSV files ===\n")

# Idle summary
idle_summary.to_csv('summary_mode0_idle.csv', index=False)
print("✓ summary_mode0_idle.csv")

# Layer summary - aggregated by layer
layer_by_layer = layer_data.groupby('Layer_ID').agg({
    'Duration_ms': 'mean',
    'Power_Mean_mW': 'mean',
    'Power_Std_mW': 'mean',
    'Total_Energy_mJ': 'mean',
    'Energy_per_ms_mW': 'mean',
    'FLOPs': 'first',
    'FLOPs_per_ms': 'mean',
    'Energy_per_MFLOP_mJ': 'mean'
}).round(2)
layer_by_layer.to_csv('summary_mode1-5_layers_avg.csv')
print("✓ summary_mode1-5_layers_avg.csv")

# Complete layer data
layer_summary.to_csv('summary_mode1-5_layers_complete.csv', index=False)
print("✓ summary_mode1-5_layers_complete.csv")

# Transmission summary
tx_summary.to_csv('summary_mode6_transmission.csv', index=False)
print("✓ summary_mode6_transmission.csv")

# Sensing summary
sensing_summary.to_csv('summary_mode7_sensing.csv', index=False)
print("✓ summary_mode7_sensing.csv")

# Create a final consolidated summary
print("\n=== Creating final consolidated summary ===\n")

consolidated = []

# Mode 0: Idle
if len(idle_data) > 0:
    consolidated.append({
        'Mode': '0 (Idle)',
        'Description': 'Idle state - waiting',
        'Avg_Duration_ms': idle_data['Duration_ms'].mean(),
        'Avg_Power_mW': idle_data['Power_Mean_mW'].mean(),
        'Avg_Energy_Total_mJ': idle_data['Total_Energy_mJ'].mean(),
        'Notes': f"Measured across {len(idle_data)} sensor configs"
    })

# Modes 1-5: Layers
for layer_id in range(5):
    layer_specific = layer_data[layer_data['Layer_ID'] == layer_id]
    if len(layer_specific) > 0:
        consolidated.append({
            'Mode': f'{int(layer_id)+1} (Layer {int(layer_id)})',
            'Description': f'Inference Layer {int(layer_id)}',
            'Avg_Duration_ms': layer_specific['Duration_ms'].mean(),
            'Avg_Power_mW': layer_specific['Power_Mean_mW'].mean(),
            'Avg_Energy_Total_mJ': layer_specific['Total_Energy_mJ'].mean(),
            'FLOPs': layer_specific['FLOPs'].iloc[0],
            'Avg_FLOPs_per_ms': layer_specific['FLOPs_per_ms'].mean(),
            'Avg_Energy_per_MFLOP_mJ': layer_specific['Energy_per_MFLOP_mJ'].mean(),
            'Notes': f"Measured across {len(layer_specific)} sensor configs"
        })

# Mode 6: Transmission
if len(tx_data) > 0:
    consolidated.append({
        'Mode': '6 (Transmission)',
        'Description': 'Data transmission',
        'Avg_Duration_ms': tx_data['Duration_ms'].mean(),
        'Avg_Power_mW': tx_data['Power_Mean_mW'].mean(),
        'Avg_Energy_Total_mJ': tx_data['Total_Energy_mJ'].mean(),
        'Avg_Energy_per_Byte_uJ': tx_data['Energy_per_Byte_uJ'].mean(),
        'Notes': f"Assumed {tx_data['Assumed_Bytes'].iloc[0]:.0f} bytes per transmission"
    })

# Mode 7: Sensing
sensing_by_type = sensing_data.groupby('Sensor_Type').agg({
    'Power_Mean_mW': 'mean',
    'Energy_3sec_mJ': 'mean',
    'Energy_3sec_J': 'mean'
}).round(2)

for sensor_type, row in sensing_by_type.iterrows():
    consolidated.append({
        'Mode': f'7 (Sensing: {sensor_type})',
        'Description': f'Sensor operation - {sensor_type}',
        'Avg_Power_mW': row['Power_Mean_mW'],
        'Energy_for_3sec_mJ': row['Energy_3sec_mJ'],
        'Energy_for_3sec_J': row['Energy_3sec_J'],
        'Energy_per_sec_mJ': row['Energy_3sec_mJ'] / 3,
        'Notes': '3 seconds operation'
    })

consolidated_df = pd.DataFrame(consolidated)
consolidated_df = consolidated_df.round(2)
consolidated_df.to_csv('FINAL_CONSOLIDATED_SUMMARY.csv', index=False)
print("✓ FINAL_CONSOLIDATED_SUMMARY.csv")

print("\n" + "="*80)
print("FINAL CONSOLIDATED SUMMARY")
print("="*80 + "\n")
print(consolidated_df.to_string(index=False))

print("\n\n" + "="*80)
print("All analysis files created successfully!")
print("="*80)
print("\nKey files:")
print("  1. energy_profile_analysis.xlsx - Multi-sheet Excel with all data")
print("  2. FINAL_CONSOLIDATED_SUMMARY.csv - Quick reference summary")
print("  3. summary_mode*.csv - Individual mode summaries")
print("  4. energy_analysis_summary.csv - Complete detailed data")
