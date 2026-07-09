# ESP32-C3 Profiling Reference for Simulation Framework

This document provides detailed profiling information for the ESP32-C3 microcontroller, focusing on computation (operations, operators, energy models) and communication (Wi-Fi and BLE specifications) to support the simulation framework described in the user's document.

## 1. Computation Profiling (ESP32-C3 RISC-V CPU)

The ESP32-C3 features a 32-bit RISC-V single-core processor capable of running at up to 160 MHz [1]. Understanding its computation capabilities and energy consumption is crucial for accurate simulation.

### 1.1 CPU Architecture and Clock Speed
- **Architecture**: 32-bit RISC-V single-core processor.
- **Clock Frequencies**: Configurable, typically 80 MHz or 160 MHz.
- **CoreMark Score**: 483.27 CoreMark at 160 MHz (3.02 CoreMark/MHz) [1].

### 1.2 Instruction Cycle Counts
The RISC-V instruction set on the ESP32-C3 has specific cycle counts for various operations, which differ slightly from newer chips like the ESP32-C6 [2].

| Instruction Type | CPU Cycles (ESP32-C3) | Notes |
| :--- | :--- | :--- |
| Integer Arithmetic (`addi`, `add`, etc.) | 1 | Basic operations typically execute in a single cycle. |
| Unconditional Branch (`j`) | 2 | Always takes 2 cycles on ESP32-C3 [2]. |
| Conditional Branch (`bne`, `beq`) | 1 (Not taken) / 3 (Taken) | Branch prediction affects cycle count. A taken branch incurs a penalty [2]. |
| Load/Store | Variable | Depends on memory hierarchy (Cache hit/miss, SRAM vs. Flash). |

### 1.3 Audio Inference Computation Cost (Example: MFCC)
For audio sensing and inference, extracting features like Mel-Frequency Cepstral Coefficients (MFCC) is a common preprocessing step.
- **MFCC Processing Time**: On an optimized integer-only implementation for MCUs, processing a 40 ms audio frame (at 16 kHz) takes approximately 6.8 ms [3].
- **Cycle Estimation**: This corresponds to roughly 100,000 to 150,000 cycles for feature extraction per frame, depending on the exact MCU and optimization level.

### 1.4 Computation Energy Model
The energy consumed by the CPU depends on the active mode current and the clock frequency.

| Operating Mode | Current Draw | Notes |
| :--- | :--- | :--- |
| Active (CPU only, 160 MHz) | ~23 - 30 mA | Running typical code from Flash/SRAM [4]. |
| Active (CPU only, 80 MHz) | ~18 - 22 mA | Reduced clock speed saves power [4]. |
| Light Sleep | ~130 µA | Full RAM retention [4]. |
| Deep Sleep | ~5 µA | RTC timer only (datasheet spec, dev boards may draw more) [1] [4]. |

**Energy per Cycle Calculation (at 160 MHz):**
- Current: ~25 mA (average)
- Voltage: 3.3 V
- Power: $P = 25 \text{ mA} \times 3.3 \text{ V} = 82.5 \text{ mW}$
- Time per cycle: $t = 1 / 160 \text{ MHz} = 6.25 \text{ ns}$
- Energy per cycle: $E = 82.5 \text{ mW} \times 6.25 \text{ ns} \approx 0.515 \text{ nJ/cycle}$

**Energy per Byte (Pre-processing/Inference):**
If an operation takes $C$ cycles per byte, the energy is $C \times 0.515 \text{ nJ}$.
- `cycles_per_byte_preprocess`: e.g., 50 cycles/byte $\rightarrow$ ~25 nJ/byte.
- `cycles_per_byte_inference`: e.g., 200 cycles/byte $\rightarrow$ ~103 nJ/byte.

---

## 2. Communication Profiling (Wi-Fi and BLE)

Communication is typically the most power-hungry aspect of an IoT node. The ESP32-C3 supports both 2.4 GHz Wi-Fi (802.11b/g/n) and Bluetooth 5 (LE) [1].

### 2.1 Wi-Fi (802.11b/g/n) Specifications

Wi-Fi transmission involves significant peak currents.

| Wi-Fi State | Current Draw | Notes |
| :--- | :--- | :--- |
| TX (802.11b, 1 Mbps, @21 dBm) | 335 mA | Peak current during transmission [1]. |
| TX (802.11n, HT20, @18 dBm) | ~260 mA | Typical high-rate transmission. |
| RX (802.11b/g/n) | 84 - 97 mA | Listening mode [1]. |
| Modem Sleep (CPU active, Wi-Fi idle) | ~15 - 20 mA | Wi-Fi radio off, CPU running [4]. |

**Wi-Fi Energy per Byte Model:**
- Transmission duration for a packet of size $S$ bytes at rate $R$ Mbps is roughly $T_{tx} = (S \times 8) / R + T_{overhead}$.
- Energy per packet: $E_{tx} = P_{tx} \times T_{tx} = (335 \text{ mA} \times 3.3 \text{ V}) \times T_{tx}$.
- Given the high overhead of Wi-Fi (preambles, MAC headers, ACK reception), the energy per byte is highly dependent on packet size. For short packets, the overhead dominates.

### 2.2 Bluetooth Low Energy (BLE 5.0) Specifications

BLE is optimized for short bursts of data and low power consumption.

| BLE State | Current Draw | Notes |
| :--- | :--- | :--- |
| TX Peak (0 dBm) | ~130 mA | Fixed hardware peak during transmission [5]. |
| RX Peak | ~100 - 130 mA | During reception/scanning [5]. |
| Advertising Event Duration | 2 - 4 ms | Time to transmit on 3 channels [5]. |

**BLE Advertising Energy Model:**
- An advertising event transmits on 3 channels (37, 38, 39).
- **Payload Size**: Legacy advertising allows up to 31 bytes. Extended advertising (BLE 5.0) allows up to 254 bytes [6].
- **Energy per Event**: A 3 ms event at 130 mA and 3.3 V consumes: $E_{adv} = 130 \text{ mA} \times 3.3 \text{ V} \times 3 \text{ ms} = 1.287 \text{ mJ}$.
- **Average Current**: Depends on the advertising interval. For a 1000 ms interval, the average current (with light sleep) is ~0.5 - 1.5 mA [5].

**BLE Energy per Byte:**
- Adding bytes to the advertising payload increases the transmission time slightly.
- At 1 Mbps, transmitting 1 byte takes $8 \mu s$.
- Energy cost per additional byte: $E_{byte} = 130 \text{ mA} \times 3.3 \text{ V} \times 8 \mu s \approx 3.4 \mu J$.

### 2.3 Packet Delivery Ratio (PDR) and Distance Model

For the simulation broker, determining whether a packet is received depends on the distance and the environment. The Log-Distance Path Loss Model is commonly used [7].

**Log-Distance Path Loss Formula:**
$PL(d) = PL(d_0) + 10 \gamma \log_{10}\left(\frac{d}{d_0}\right) + X_g$
- $PL(d)$: Path loss at distance $d$ (dB).
- $PL(d_0)$: Path loss at reference distance $d_0$ (usually 1m).
- $\gamma$: Path loss exponent (e.g., 2.0 for free space, 2.4 - 3.0 for indoor environments) [7].
- $X_g$: Gaussian random variable representing shadow fading.

**Received Signal Strength (RSSI):**
$RSSI = P_{tx} - PL(d)$

**PDR Calculation:**
The PDR is a function of the Signal-to-Noise Ratio (SNR).
$SNR = RSSI - \text{Noise Floor}$
If the SNR is above the receiver sensitivity threshold (e.g., -97 dBm for BLE 1 Mbps [1]), the packet is received with high probability. The probability drops sharply as SNR approaches the threshold.

---

## 3. Recommended Parameters for Simulation Configuration

Based on the research, here are recommended baseline values for the JSON configuration files mentioned in the user's plan.

### `mcu_profiles.json` (ESP32-C3 Mini)
```json
{
  "profile_name": "esp32_c3_mini",
  "cpu_freq_mhz": 160,
  "joules_per_cycle": 5.15e-10,
  "cycles_per_byte_preprocess": 50,
  "cycles_per_byte_inference": 200,
  "cycles_per_byte_tx_prep": 10
}
```

### `comm_config.json` (BLE & Wi-Fi)
```json
{
  "wifi_normal": {
    "radio_tx_peak_ma": 335,
    "radio_rx_peak_ma": 90,
    "tx_joules_per_byte": 1.5e-5,
    "rx_joules_per_byte": 1.0e-5,
    "base_overhead_joules": 0.005,
    "path_loss_exponent": 2.5
  },
  "ble_normal": {
    "radio_tx_peak_ma": 130,
    "radio_rx_peak_ma": 130,
    "tx_joules_per_byte": 3.4e-6,
    "rx_joules_per_byte": 3.4e-6,
    "base_overhead_joules": 0.0012,
    "path_loss_exponent": 2.5
  }
}
```

## References
[1] Espressif Systems. "ESP32-C3 Series Datasheet". https://www.espressif.com/sites/default/files/documentation/esp32-c3_datasheet_en.pdf
[2] CtrlSrc. "Counting CPU cycles on ESP32-C3 and ESP32-C6 microcontrollers". https://ctrlsrc.io/posts/2023/counting-cpu-cycles-on-esp32c3-esp32c6/
[3] Fariselli, M., et al. "Integer-Only Approximated MFCC for Ultra-Low Power Audio NN Processing on Multi-Core MCUs". https://cps4eu.eu/wp-content/uploads/2021/05/Integer-Only-Approximated-MFCC-for-Ultra-LowPower-Audio-NN-Processing-on-Multi-Core-MCUs.pdf
[4] PCBSync. "ESP32-C3: The Complete RISC-V WiFi Microcontroller Guide for Engineers". https://pcbsync.com/esp32-c3/
[5] Hubble Network. "ESP32 Power Consumption in BLE Mode". https://hubble.com/community/guides/esp32-power-consumption-in-ble-mode-what-to-expect-from-advertising-scanning-and-connected-states/
[6] Novel Bits. "Maximum Data Size in a Bluetooth Advertising Packet". https://novelbits.io/maximum-data-bluetooth-advertising-packet-ble/
[7] Wikipedia. "Log-distance path loss model". https://en.wikipedia.org/wiki/Log-distance_path_loss_model
