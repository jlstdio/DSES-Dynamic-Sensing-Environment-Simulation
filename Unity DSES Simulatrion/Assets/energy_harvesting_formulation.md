## Energy Harvesting and Consumption Model for Battery-less AIoT

본 모델은 숲속과 같은 이기종 하베스팅 환경(Heterogeneous Harvesting Conditions)에서 작동하는 무전원(Battery-less) AIoT 센서 노드의 에너지 상태를 정밀하게 시뮬레이션하기 위해 설계되었습니다. 실제 지구의 대기 광학 법칙(Atmospheric Optics)과 ESP32-C3-SuperMini 기반의 하드웨어 전력 프로파일링 데이터를 결합하여 연속적인 모니터링 시스템의 물리적 타당성을 검증합니다.

### 1. Solar Energy Harvesting Model (Energy In)

센서 노드에 도달하는 태양 에너지는 단순한 이분법적 그림자 판별을 넘어, 직달 일사량(Direct Normal Irradiance, DNI)과 산란 일사량(Diffuse Horizontal Irradiance, DHI)을 분리하여 계산합니다.

**1.1. Air Mass (대기 질량)**
태양광이 대기를 통과하는 거리는 태양의 천정각(Zenith Angle, )에 따라 달라지며, 이는 대기 산란 및 흡수율에 직접적인 영향을 미칩니다.


**1.2. Physical Irradiance (물리적 일사량 계산)**
맑은 날 지표면에 도달하는 직달 일사량 $I_{DNI}$와 대기에 의해 산란된 간접광 $I_{DHI}$는 다음과 같이 정의됩니다.


* : 태양 상수 (Solar Constant, )
* : 맑은 날의 대기 투과율 (Clear Sky Transmittance, )
* : 대기 산란 비율 (Diffuse Ratio, )

**1.3. Spatiotemporal Occlusion & Global Irradiance (지형지물 차단 및 총 일사량)**
노드의 위치에 따른 광학적 차단(Occlusion)을 모델링하기 위해, 태양을 향한 직접적인 시야 확보 여부를 나타내는 $O_{direct}\in{0,1}$와, 열린 하늘의 비율을 나타내는 Sky View Factor $SVF\in[0,1]$를 산출합니다. 기상 상태에 따른 투과 감쇄율 $A_{weather}$를 포함하여, 노드가 위치한 지표면이 수신하는 총 일사량 $I_{total}$은 람베르트의 코사인 법칙(Lambert's Cosine Law)을 적용하여 다음과 같이 도출됩니다.


**1.4. Hardware-Profiled Energy Conversion (하드웨어 변환)**
실험 환경에서 제시된 초소형 태양광 패널의 제약(양지 최대 , 음지 )을 만족시키기 위해, 물리적 일사량()을 실제 하베스팅 전력()으로 스케일링하는 하드웨어 변환 계수  (패널의 유효 면적 및 효율)를 적용합니다.


> 
> **Note:** 이 수식을 통해  (나무에 의해 직사광선이 완전히 차단된 상태)일 때, 직달 일사량 항이 소거되고 산란광인  부분만 수식에 남아, 최대 하베스팅 전력()의 약 15~16% 수준인 가 물리적으로 도출됨을 증명할 수 있습니다.
> 
> 

### 2. Energy Consumption State Machine (Energy Out)

노드의 에너지 소비 모델 $P_{out}$은 ESP32-C3-SuperMini 및 부착된 센서의 전력 프로파일링을 기반으로 5가지 주요 상태(State)로 나뉘어 동작합니다.

* 
**Deep Sleep ():** 배터리가 치명적 임계치() 이하로 떨어졌을 때 진입하며, 회복 임계치()에 도달할 때까지 에너지를 수집합니다. ()


* 
**Idle ():** 연산이나 통신을 수행하지 않는 기본 활성 대기 상태입니다. ( )


* 
**Sensing ():** 물리적 이벤트를 감지하기 위해 가속도계, 자이로스코프, 지자계 센서 등을 가동하는 상태입니다. ( )


* 
**Computing ():** 수집된 데이터를 바탕으로 5-layer CNN 모델의 추론(Inference)을 수행합니다. 전체 추론 시 총 을 소모합니다. (평균  )


* 
**Transmitting ():** 연산된 중간 텐서(Intermediate Tensor)를 이웃 노드로 오프로딩(Offloading)하기 위해 ESP-NOW 프로토콜을 사용하는 상태입니다. (평균  )



### 3. Continuous Energy Update (연속 에너지 갱신)

시간 에서의 노드 배터리 잔량 $E(t)$는 최대 배터리 용량  (50 mAh 기준 )의 한계 내에서 다음과 같이 매 타임스텝 마다 연속적으로 갱신됩니다.