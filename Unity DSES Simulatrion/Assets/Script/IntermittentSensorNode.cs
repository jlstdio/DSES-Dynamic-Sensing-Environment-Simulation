using UnityEngine;
using TMPro;

public class IntermittentSensorNode : MonoBehaviour
{
    public enum NodeState { DeepSleep, Sensing, Computing, Transmitting, Idle }
    
    [Header("Identification")]
    public int nodeID; // 노드 고유 번호
    public TMP_Text idTextMesh; // 머리 위 ID 표시용
    
    [Header("Hardware Specs (ESP32-C3 & Sensor)")]
    public float maxBatteryJoules = 594f; // 50 mAh @ 3.3V
    public float currentBatteryJoules;
    public float wakeUpThreshold = 118.8f; // 20% Recovery
    public float sleepThreshold = 5.94f;   // 1% Critical

    [Header("Power Consumption (mW)")]
    public float powerDeepSleep = 0.05f; 
    public float powerIdle = 434.85f;
    public float powerSensing = 505.95f;
    public float powerComputing = 490.0f;
    public float powerTransmitting = 800.0f;

    [Header("Real-World Solar Physics")]
    public float solarConstant = 1361f;         
    public float clearSkyTransmittance = 0.7f;  
    public float diffuseRatio = 0.15f;          
    public float panelConversionFactor = 0.0000003f; // 최대 300uW 스케일링용

    [Header("Live Status & Logging")]
    public NodeState currentState = NodeState.DeepSleep;
    public float currentHarvesting_mW = 0f;
    public float currentConsuming_mW = 0f;
    
    // 로깅을 위한 누적 데이터 (1시간 윈도우용)
    public float windowHarvestedJoules = 0f;
    public float windowConsumedJoules = 0f;

    private Light celestialLight;
    private float stateTimer = 0f;

    void Awake()
    {
        // [기능 1] 유니티 창이 활성화되지 않아도 계속 동작하게 설정
        Application.runInBackground = true; 
    }

    void Start()
    {
        currentBatteryJoules = maxBatteryJoules * 0.5f; // 시작 시 10%
        celestialLight = RenderSettings.sun;

        // [기능 3] 머리 위 ID 텍스트 설정
        if (idTextMesh != null)
        {
            idTextMesh.text = $"ID: {nodeID}";
        }
    }

    void Update()
    {
        if (celestialLight == null) celestialLight = RenderSettings.sun;
        UpdateHarvesting();
        UpdateStateMachine();
    }

    private void UpdateHarvesting()
    {
        Vector3 sunDir = -celestialLight.transform.forward;
        float cosZenith = Mathf.Max(0.02f, sunDir.y); 

        if (sunDir.y <= 0)
        {
            currentHarvesting_mW = 0f;
            return;
        }

        float airMass = 1f / cosZenith;
        float DNI = solarConstant * Mathf.Pow(clearSkyTransmittance, airMass);
        float DHI = DNI * diffuseRatio;

        CalculatePhysicalOcclusion(sunDir, out float directOcclusion, out float skyViewFactor);

        // 구름 커버리지(_uCloudsCoverage)를 태양광 감쇄계수로 변환
        // UniStorm 셰이더 값 범위: ~0.36(맑음) ~ ~0.72(폭풍) → 1.0(맑음) ~ 0.0(완전 흐림)으로 역매핑
        // 날씨 전환 애니메이션 중에도 구름이 점점 끼는 과정이 연속적으로 에너지에 반영됨
        float weatherAttenuation;
        if (UniStorm.UniStormSystem.Instance != null)
        {
            float cloudCoverage = UniStorm.UniStormSystem.Instance.m_UniStormClouds != null
                ? UniStorm.UniStormSystem.Instance.m_UniStormClouds.skyMaterial.GetFloat("_uCloudsCoverage")
                : 0.36f;
            // 0.36(맑음) → 1.0, 0.72(폭풍) → 0.0 으로 선형 역매핑 후 SunIntensity 기반 하한(0.25)과 블렌딩
            float cloudAttenuation = Mathf.Clamp01(1f - (cloudCoverage - 0.36f) / (0.72f - 0.36f));
            weatherAttenuation = Mathf.Max(cloudAttenuation, UniStorm.UniStormSystem.Instance.SunIntensity * cloudAttenuation);
        }
        else
        {
            weatherAttenuation = Mathf.Clamp01(celestialLight.intensity);
        }

        float totalIrradiance_W_m2 = ((DNI * directOcclusion * cosZenith) + (DHI * skyViewFactor)) * weatherAttenuation;
        currentHarvesting_mW = (totalIrradiance_W_m2 * panelConversionFactor) * 1000f;

        float harvestedJoules = currentHarvesting_mW / 1000f * GetGameTimeDelta();
        AddEnergy(harvestedJoules);
        windowHarvestedJoules += harvestedJoules; // 누적
    }

    private void CalculatePhysicalOcclusion(Vector3 sunDir, out float directOcclusion, out float skyViewFactor)
    {
        Vector3 origin = transform.position + Vector3.up * 0.1f;
        directOcclusion = Physics.Raycast(origin, sunDir, 500f) ? 0.0f : 1.0f;

        int openSkyRays = 0;
        Vector3[] diffuseDirs = { Vector3.up, (Vector3.up+Vector3.right).normalized, (Vector3.up+Vector3.left).normalized, (Vector3.up+Vector3.forward).normalized, (Vector3.up+Vector3.back).normalized };
        foreach (var dir in diffuseDirs) { if (!Physics.Raycast(origin, dir, 100f)) openSkyRays++; }
        skyViewFactor = (float)openSkyRays / diffuseDirs.Length;
    }

    private void UpdateStateMachine()
    {
        currentConsuming_mW = 0f;
        switch (currentState)
        {
            case NodeState.DeepSleep:
                currentConsuming_mW = powerDeepSleep;
                if (currentBatteryJoules >= wakeUpThreshold) SwitchState(NodeState.Sensing);
                break;
            case NodeState.Sensing:
                currentConsuming_mW = powerSensing;
                stateTimer += GetGameTimeDelta();
                if (stateTimer >= 3.0f) SwitchState(NodeState.Computing);
                break;
            case NodeState.Computing:
                currentConsuming_mW = powerComputing;
                stateTimer += GetGameTimeDelta();
                if (stateTimer >= 12.0f) SwitchState(NodeState.Transmitting);
                break;
            case NodeState.Transmitting:
                currentConsuming_mW = powerTransmitting;
                stateTimer += GetGameTimeDelta();
                if (stateTimer >= 0.1f) SwitchState(NodeState.DeepSleep); // 테스트용 딥슬립 회귀
                break;
        }

        float consumedJoules = currentConsuming_mW / 1000f * GetGameTimeDelta();
        ConsumeEnergy(consumedJoules);
        windowConsumedJoules += consumedJoules; // 누적

        if (currentBatteryJoules <= sleepThreshold && currentState != NodeState.DeepSleep)
        {
            SwitchState(NodeState.DeepSleep);
        }
    }

    private void SwitchState(NodeState newState) { currentState = newState; stateTimer = 0f; }
    private void AddEnergy(float j) { currentBatteryJoules = Mathf.Clamp(currentBatteryJoules + j, 0, maxBatteryJoules); }
    private void ConsumeEnergy(float j) { currentBatteryJoules = Mathf.Clamp(currentBatteryJoules - j, 0, maxBatteryJoules); }

    /// <summary>
    /// UniStorm의 시간 배속에 동기화된 게임 시간 기준 deltaTime을 반환합니다.
    /// UniStorm 공식: m_TimeFloat += Time.deltaTime / DayLength / 120
    ///   → 1 실제 초 = (86400 / (DayLength × 120)) 게임 초
    ///   예) DayLength=10 → 72배속 (1게임일 = 20실제분)
    /// UniStorm이 없거나 RealWorldTime 모드이면 Time.deltaTime 그대로 반환합니다.
    /// </summary>
    public float GetGameTimeDelta()
    {
        var uni = UniStorm.UniStormSystem.Instance;
        if (uni != null &&
            uni.TimeFlow    == UniStorm.UniStormSystem.EnableFeature.Enabled &&
            uni.RealWorldTime == UniStorm.UniStormSystem.EnableFeature.Disabled)
        {
            bool isNight = uni.Hour <= 6 || uni.Hour > 18;
            float lengthMinutes = isNight ? uni.NightLength : uni.DayLength;
            // 86400 game-seconds in a day / (lengthMinutes * 120 real-seconds per half-day × 2)
            return Time.deltaTime * (86400f / (lengthMinutes * 120f));
        }
        return Time.deltaTime;
    }

    // 윈도우 초기화
    public void ResetWindowData() { windowHarvestedJoules = 0f; windowConsumedJoules = 0f; }
}