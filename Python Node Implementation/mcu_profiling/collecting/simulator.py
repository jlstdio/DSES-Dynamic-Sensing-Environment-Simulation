import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# ==============================================================================
# [설정] 프로파일링 데이터 및 하드웨어 스펙
# ==============================================================================
# ESP32-C3 Specs
VOLTAGE = 3.3
I_CPU = 25.0       # mA (Active Computation)
I_TX_ESPNOW = 280.0 # mA (Peak for ESP-NOW)
I_TX_WIFI = 300.0   # mA (Peak for Raw WiFi)
T_ESPNOW_OH = 3.0   # ms (Overhead)
T_WIFI_OH = 200.0   # ms (Overhead)

# 모델 프로파일 (위의 train_profiler.py 결과 반영 가정)
# ResNet-10은 5개 노드가 나누어 처리하므로 전체 연산량을 5등분 가정 (불균형 고려 시 수정 가능)
PROFILE = {
    "RESNET10": {
        "Total_Compute_Time": 400.0, # ms (전체 모델이 1개 칩에서 돌 때 가정)
        "Accuracy": 92.5,            # % (High Accuracy)
        "Partitions": 5,             # 5 Node Split
        "Feature_Map_Size": 1280,    # Bytes (Int8 intermediate)
    },
    "DSCNN_TINY": {
        "Total_Compute_Time": 40.0,  # ms (ResNet의 1/10 수준으로 가볍다고 가정)
        "Accuracy": 78.0,            # % (Low Accuracy)
        "Output_Size": 1,            # Byte (Class ID only)
    },
    "RAW_DATA": {
        "Size": 32000,               # Bytes (32KB Raw Audio)
    }
}

class SimulationEngine:
    def __init__(self):
        self.results = []

    def calc_energy(self, current, time_ms):
        return VOLTAGE * current * (time_ms / 1000.0)

    def run_scenario_single_tiny(self):
        """
        [Scenario 1] Single Node + Tiny Model (DS-CNN)
        - 동작: 센싱 -> 가벼운 연산 -> 결과(1B) 전송 -> Sleep
        """
        # 1. Compute
        t_compute = PROFILE["DSCNN_TINY"]["Total_Compute_Time"]
        e_compute = self.calc_energy(I_CPU, t_compute)
        
        # 2. TX (Result only, ESP-NOW assumed for result)
        # Payload 1 Byte is negligible, mostly overhead
        t_tx = T_ESPNOW_OH + (1.0 / 1000.0) 
        e_tx = self.calc_energy(I_TX_ESPNOW, t_tx)
        
        total_energy = e_compute + e_tx
        
        self.results.append({
            "Scenario": "Single Node (Tiny Model)",
            "Node_Type": "Single",
            "Energy_Compute": e_compute,
            "Energy_TX": e_tx,
            "Total_Energy": total_energy,
            "Accuracy": PROFILE["DSCNN_TINY"]["Accuracy"]
        })

    def run_scenario_distributed(self):
        """
        [Scenario 2] Distributed 5-Nodes + Heavy Model (ResNet-10)
        - 동작: 5개 노드가 파이프라인 처리
        """
        # 전체 연산량을 5개 노드가 나눔 (이상적인 분할 가정)
        t_compute_per_node = PROFILE["RESNET10"]["Total_Compute_Time"] / 5.0
        e_compute_per_node = self.calc_energy(I_CPU, t_compute_per_node)
        
        # 통신: Feature Map (1.2KB) 전송
        data_size = PROFILE["RESNET10"]["Feature_Map_Size"]
        t_tx = T_ESPNOW_OH + (data_size / 1000.0) # 1MB/s rate assumed
        e_tx_per_node = self.calc_energy(I_TX_ESPNOW, t_tx)
        
        # 마지막 노드는 결과(1B)만 보냄 (에너지 적음)
        t_tx_last = T_ESPNOW_OH + 0.001
        e_tx_last = self.calc_energy(I_TX_ESPNOW, t_tx_last)
        
        # 총 에너지 합계 (5개 노드 전체)
        # Node 0~3: Compute + Feature TX
        # Node 4: Compute + Result TX
        total_system_energy = (e_compute_per_node + e_tx_per_node) * 4 + \
                              (e_compute_per_node + e_tx_last)
        
        self.results.append({
            "Scenario": "Distributed (ResNet-10)",
            "Node_Type": "Cluster (Sum)",
            "Energy_Compute": e_compute_per_node * 5,
            "Energy_TX": (e_tx_per_node * 4) + e_tx_last,
            "Total_Energy": total_system_energy,
            "Accuracy": PROFILE["RESNET10"]["Accuracy"]
        })

    def run_scenario_baseline_raw(self):
        """
        [Scenario 3] Baseline (Single Node Raw TX)
        - 동작: 센싱 -> Wi-Fi로 32KB 전송
        """
        # Compute: 0 (No AI)
        e_compute = 0
        
        # TX: Wi-Fi Large Payload
        t_tx = T_WIFI_OH + (PROFILE["RAW_DATA"]["Size"] / 500.0) # 500KB/s assumed
        e_tx = self.calc_energy(I_TX_WIFI, t_tx)
        
        self.results.append({
            "Scenario": "Baseline (Raw TX)",
            "Node_Type": "Single",
            "Energy_Compute": 0,
            "Energy_TX": e_tx,
            "Total_Energy": e_tx,
            "Accuracy": 100.0 # Raw data has full info (potential)
        })

# === 실행 및 시각화 ===
sim = SimulationEngine()
sim.run_scenario_single_tiny()
sim.run_scenario_distributed()
sim.run_scenario_baseline_raw()

df = pd.DataFrame(sim.results)
print(df)

# 시각화
fig, ax1 = plt.subplots(figsize=(10, 6))

# 에너지 막대 그래프
scenarios = df["Scenario"]
e_comp = df["Energy_Compute"]
e_tx = df["Energy_TX"]

p1 = ax1.bar(scenarios, e_comp, label="Compute Energy", color='skyblue')
p2 = ax1.bar(scenarios, e_tx, bottom=e_comp, label="TX Energy", color='salmon')

ax1.set_ylabel("Energy Consumption (mJ)")
ax1.set_title("Energy vs Accuracy Trade-off Analysis")
ax1.legend(loc='upper left')

# 정확도 선 그래프 (보조축)
ax2 = ax1.twinx()
ax2.plot(scenarios, df["Accuracy"], color='green', marker='o', linewidth=2, linestyle='--', label="Accuracy (%)")
ax2.set_ylabel("Model Accuracy (%)")
ax2.set_ylim(0, 110)
ax2.legend(loc='upper right')

for i, v in enumerate(df["Total_Energy"]):
    ax1.text(i, v + 1, f"{v:.1f} mJ", ha='center', va='bottom', fontweight='bold')

plt.tight_layout()
plt.show()