# MCU Profiling - ESP32-C3 Supermini 에너지 분석

ESP32-C3 Supermini 마이크로컨트롤러의 에너지 프로파일 데이터를 분석하는 도구입니다.

## 📁 폴더 구조

```
mcu_profiling/
├── analyze_energy_profiles.py  # 🆕 통합 분석 스크립트 (이것만 실행하세요!)
├── data/                        # 원본 CSV 데이터
│   ├── eps32-c3-supermini_profiles_accel+gyro+mag.csv
│   ├── eps32-c3-supermini_profiles_accel+gyro.csv
│   ├── eps32-c3-supermini_profiles_accel_only.csv
│   ├── eps32-c3-supermini_profiles_gyro+mag.csv
│   ├── eps32-c3-supermini_profiles_no-sensing.csv
│   └── eps32-c3-supermini_profiles_ultrasonic.csv
├── results/                     # 분석 결과 출력
│   ├── detailed_energy_analysis.csv
│   ├── transmission_by_layer.csv
│   └── ENERGY_ANALYSIS_REPORT.md
└── README.md                    # 이 파일

# 레거시 파일 (참고용, 더 이상 사용 안 함)
├── analyze_detailed_energy.py
├── create_sensor_independent_summary.py
└── create_summary_reports.py
```

## 🚀 사용법

### 1. 분석 실행

```bash
cd mcu_profiling
python3 analyze_energy_profiles.py
```

단 하나의 스크립트가 모든 분석을 수행합니다:
- ✅ 센서별 상세 에너지 분석
- ✅ Layer별 전송 에너지 분석
- ✅ 센서 무관 요약
- ✅ Markdown 리포트 생성

### 2. 결과 확인

분석이 완료되면 `results/` 폴더에 다음 파일들이 생성됩니다:

#### 📄 `detailed_energy_analysis.csv`
센서별, Mode별 상세 에너지 데이터
- 모든 센서 조합에 대한 원시 분석 결과
- Mode 0-7의 전력, 에너지, 시간 데이터

#### 📄 `transmission_by_layer.csv`
Layer별 전송 에너지 요약
- Layer 0-4의 전송 시간, 전력, 에너지
- Byte당 에너지 소비량
- 측정 횟수

#### 📄 `ENERGY_ANALYSIS_REPORT.md` ⭐
**주요 결과 리포트** (사람이 읽기 좋은 형식)
- Mode별 요약
- Layer별 성능
- 전송 특성
- 센싱 효율
- 실전 시나리오

## 📊 데이터 형식

### 입력 CSV 형식
```
Time(ms), Voltage(V), Current(mA), Power(mW), Mode
```

### Mode 정의
- **0**: Idle (대기)
- **1-5**: Layer 0-4 (신경망 추론)
- **6**: Transmission (ESP-NOW 전송)
- **7**: Sensing (센서 데이터 수집)

## 🔧 기술 스펙

### 레이어 연산량 (FLOPs)
```python
Layer 0: 232,800 FLOPs
Layer 1: 291,000 FLOPs
Layer 2: 436,500 FLOPs
Layer 3: 582,000 FLOPs
Layer 4: 727,500 FLOPs
```

### 레이어 출력 크기
```python
Layer 0: 400 bytes
Layer 1: 320 bytes
Layer 2: 240 bytes
Layer 3: 160 bytes
Layer 4: 80 bytes
```

## 📈 주요 발견사항

### ⚠️ 전송 이슈
- **Layer 1, 2의 전송 시간이 비정상적으로 김** (138ms vs 27-31ms)
- ESP-NOW 구현 검토 필요

### ✅ 최적화 포인트
1. **전송 최적화**: 가장 높은 전력 소비 (731-887 mW)
2. **센서 선택**: accel+gyro 조합이 가장 효율적 (439.48 mW)
3. **배치 전송**: Layer별로 매번 전송하지 말고 모아서 전송

### 📊 에너지 효율
- Layer 4가 가장 효율적: 2,613.45 mJ/MFLOP
- ESP32-C3는 하드웨어 FPU가 약함 (일반 AI 가속기보다 수천 배 낮은 효율)

## 🔬 개발 정보

### 의존성
```bash
pip install pandas numpy openpyxl
```

### 측정 환경
- MCU: ESP32-C3 Supermini
- 전류 센서: INA219
- 통신: ESP-NOW
- 신경망: 5-layer 1D CNN

## 📝 참고사항

### 레거시 스크립트들
다음 스크립트들은 더 이상 직접 실행할 필요가 없습니다 (참고용으로만 보관):
- `analyze_detailed_energy.py` - 상세 분석
- `create_sensor_independent_summary.py` - 센서 무관 요약
- `create_summary_reports.py` - Excel 리포트

모든 기능이 `analyze_energy_profiles.py`에 통합되었습니다.

## 💡 자주 묻는 질문

**Q: 새로운 CSV 파일을 추가하려면?**
A: `data/` 폴더에 `eps32-c3-supermini_profiles_*.csv` 형식으로 추가하고 스크립트를 다시 실행하세요.

**Q: 결과를 초기화하려면?**
A: `results/` 폴더의 내용을 삭제하고 다시 실행하세요.

**Q: 분석 로직을 수정하려면?**
A: `analyze_energy_profiles.py` 파일을 수정하세요. 모든 분석 로직이 이 파일에 있습니다.

---

**마지막 업데이트**: 2025-12-25
**버전**: 2.0 (통합 버전)
