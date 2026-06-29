using UnityEngine;
using TMPro;

public class IntermittentSensorNode : MonoBehaviour
{
    [Header("Identification")]
    public int nodeID; // 노드 고유 번호
    public TMP_Text idTextMesh; // 머리 위 ID 표시용

    [Header("Battery Specs")]
    public float maxBatteryJoules = 594f;
    [Range(0f, 1f)] public float initialBatteryRatio = 0.5f;
    public float wakeUpThreshold = 118.8f;
    public float sleepThreshold = 5.94f;

    [Header("State Power (mW)")]
    public float powerDeepSleep = 0.05f;
    public float powerIdle = 434.85f;
    public float powerSensing = 505.95f;
    public float powerComputing = 490.0f;
    public float powerTransmitting = 800.0f;

    [Header("State Duration (s)")]
    public float durationIdle = 1.0f;
    public float durationSensing = 3.0f;
    public float durationComputing = 12.0f;
    public float durationTransmitting = 0.1f;

    [Header("Solar Harvesting")]
    public float solarConstant = 1361f;
    public float clearSkyTransmittance = 0.7f;
    public float diffuseRatio = 0.15f;
    public float panelConversionFactor = 0.0000003f;
    public bool useWeatherSystem = true;
    
    [Header("Live Status & Logging")]
    public SensorNodeState currentState = SensorNodeState.DeepSleep;
    public float currentBatteryJoules;
    public float currentHarvesting_mW = 0f;
    public float currentConsuming_mW = 0f;
    
    // 로깅을 위한 누적 데이터 (1시간 윈도우용)
    public float windowHarvestedJoules = 0f;
    public float windowConsumedJoules = 0f;

    [Header("Paper Evaluation Metrics")]
    public float windowDeepSleepSeconds = 0f;
    public float windowIdleSeconds = 0f;
    public float windowSensingSeconds = 0f;
    public float windowComputingSeconds = 0f;
    public float windowTransmittingSeconds = 0f;
    public int windowWakeUpCount = 0;
    public int windowDeepSleepEntryCount = 0;
    public int windowDepletionCount = 0;
    public int windowSensingCompletionCount = 0;
    public int windowInferenceCompletionCount = 0;
    public int windowTransmissionCompletionCount = 0;

    public float totalHarvestedJoules = 0f;
    public float totalConsumedJoules = 0f;
    public float totalDeepSleepSeconds = 0f;
    public float totalIdleSeconds = 0f;
    public float totalSensingSeconds = 0f;
    public float totalComputingSeconds = 0f;
    public float totalTransmittingSeconds = 0f;
    public int totalWakeUpCount = 0;
    public int totalDeepSleepEntryCount = 0;
    public int totalDepletionCount = 0;
    public int totalSensingCompletionCount = 0;
    public int totalInferenceCompletionCount = 0;
    public int totalTransmissionCompletionCount = 0;

    private Light celestialLight;
    private float stateTimer = 0f;

    void Awake()
    {
        // [기능 1] 유니티 창이 활성화되지 않아도 계속 동작하게 설정
        Application.runInBackground = true; 
    }

    void Start()
    {
        currentBatteryJoules = maxBatteryJoules * initialBatteryRatio;
        celestialLight = RenderSettings.sun;

        // [기능 3] 머리 위 ID 텍스트 설정
        if (idTextMesh != null)
        {
            idTextMesh.text = $"ID: {nodeID}";
        }
    }

    void Update()
    {
        float gameDeltaTime = GetGameTimeDelta();
        if (celestialLight == null) celestialLight = RenderSettings.sun;
        UpdateHarvesting(gameDeltaTime);
        UpdateStateMachine(gameDeltaTime);
    }

    private void UpdateHarvesting(float gameDeltaTime)
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
        if (useWeatherSystem && UniStorm.UniStormSystem.Instance != null)
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

        float harvestedJoules = currentHarvesting_mW / 1000f * gameDeltaTime;
        AddEnergy(harvestedJoules);
        windowHarvestedJoules += harvestedJoules; // 누적
        totalHarvestedJoules += harvestedJoules;
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

    private void UpdateStateMachine(float gameDeltaTime)
    {
        AccumulateStateResidency(currentState, gameDeltaTime);
        currentConsuming_mW = GetPowerMilliwatts(currentState);

        if (currentState == SensorNodeState.DeepSleep)
        {
            SensorNodeState wakeUpState = currentBatteryJoules >= wakeUpThreshold ? SensorNodeState.Idle : SensorNodeState.DeepSleep;
            if (wakeUpState != SensorNodeState.DeepSleep)
            {
                SwitchState(wakeUpState);
                currentConsuming_mW = GetPowerMilliwatts(currentState);
            }
        }
        else
        {
            stateTimer += gameDeltaTime;

            float stateDuration = GetDurationSeconds(currentState);
            if (stateDuration <= 0f || stateTimer >= stateDuration)
            {
                RegisterStateCompletion(currentState);
                SwitchState(GetNextState(currentState, currentBatteryJoules));
                currentConsuming_mW = GetPowerMilliwatts(currentState);
            }
        }

        float consumedJoules = currentConsuming_mW / 1000f * gameDeltaTime;
        ConsumeEnergy(consumedJoules);
        windowConsumedJoules += consumedJoules; // 누적
        totalConsumedJoules += consumedJoules;

        if (currentBatteryJoules <= sleepThreshold && currentState != SensorNodeState.DeepSleep)
        {
            windowDepletionCount++;
            totalDepletionCount++;
            SwitchState(SensorNodeState.DeepSleep);
        }
    }

    private void SwitchState(SensorNodeState newState)
    {
        if (currentState == newState) return;

        if (currentState == SensorNodeState.DeepSleep && newState != SensorNodeState.DeepSleep)
        {
            windowWakeUpCount++;
            totalWakeUpCount++;
        }

        if (newState == SensorNodeState.DeepSleep)
        {
            windowDeepSleepEntryCount++;
            totalDeepSleepEntryCount++;
        }

        currentState = newState;
        stateTimer = 0f;
    }

    private void RegisterStateCompletion(SensorNodeState completedState)
    {
        switch (completedState)
        {
            case SensorNodeState.Sensing:
                windowSensingCompletionCount++;
                totalSensingCompletionCount++;
                break;
            case SensorNodeState.Computing:
                windowInferenceCompletionCount++;
                totalInferenceCompletionCount++;
                break;
            case SensorNodeState.Transmitting:
                windowTransmissionCompletionCount++;
                totalTransmissionCompletionCount++;
                break;
        }
    }

    private void AccumulateStateResidency(SensorNodeState state, float gameDeltaTime)
    {
        switch (state)
        {
            case SensorNodeState.DeepSleep:
                windowDeepSleepSeconds += gameDeltaTime;
                totalDeepSleepSeconds += gameDeltaTime;
                break;
            case SensorNodeState.Idle:
                windowIdleSeconds += gameDeltaTime;
                totalIdleSeconds += gameDeltaTime;
                break;
            case SensorNodeState.Sensing:
                windowSensingSeconds += gameDeltaTime;
                totalSensingSeconds += gameDeltaTime;
                break;
            case SensorNodeState.Computing:
                windowComputingSeconds += gameDeltaTime;
                totalComputingSeconds += gameDeltaTime;
                break;
            case SensorNodeState.Transmitting:
                windowTransmittingSeconds += gameDeltaTime;
                totalTransmittingSeconds += gameDeltaTime;
                break;
        }
    }

    private void AddEnergy(float j) { currentBatteryJoules = Mathf.Clamp(currentBatteryJoules + j, 0, maxBatteryJoules); }
    private void ConsumeEnergy(float j) { currentBatteryJoules = Mathf.Clamp(currentBatteryJoules - j, 0, maxBatteryJoules); }

    private float GetPowerMilliwatts(SensorNodeState state)
    {
        switch (state)
        {
            case SensorNodeState.DeepSleep: return powerDeepSleep;
            case SensorNodeState.Idle: return powerIdle;
            case SensorNodeState.Sensing: return powerSensing;
            case SensorNodeState.Computing: return powerComputing;
            case SensorNodeState.Transmitting: return powerTransmitting;
            default: return 0f;
        }
    }

    private float GetDurationSeconds(SensorNodeState state)
    {
        switch (state)
        {
            case SensorNodeState.Idle: return durationIdle;
            case SensorNodeState.Sensing: return durationSensing;
            case SensorNodeState.Computing: return durationComputing;
            case SensorNodeState.Transmitting: return durationTransmitting;
            default: return 0f;
        }
    }

    private SensorNodeState GetNextState(SensorNodeState state, float batteryJoules)
    {
        if (batteryJoules <= sleepThreshold)
        {
            return SensorNodeState.DeepSleep;
        }

        switch (state)
        {
            case SensorNodeState.DeepSleep:
                return batteryJoules >= wakeUpThreshold ? SensorNodeState.Idle : SensorNodeState.DeepSleep;
            case SensorNodeState.Idle:
                return SensorNodeState.Sensing;
            case SensorNodeState.Sensing:
                return SensorNodeState.Computing;
            case SensorNodeState.Computing:
                return SensorNodeState.Transmitting;
            case SensorNodeState.Transmitting:
                return SensorNodeState.DeepSleep;
            default:
                return SensorNodeState.DeepSleep;
        }
    }

    public float GetBatteryPercent()
    {
        if (maxBatteryJoules <= 0f) return 0f;
        return Mathf.Clamp01(currentBatteryJoules / maxBatteryJoules) * 100f;
    }

    public float GetWindowTrackedSeconds()
    {
        return windowDeepSleepSeconds + windowIdleSeconds + windowSensingSeconds + windowComputingSeconds + windowTransmittingSeconds;
    }

    public float GetWindowDutyCyclePercent()
    {
        float trackedSeconds = GetWindowTrackedSeconds();
        if (trackedSeconds <= 0f) return 0f;
        return ((trackedSeconds - windowDeepSleepSeconds) / trackedSeconds) * 100f;
    }

    public float GetWindowNetEnergyJoules()
    {
        return windowHarvestedJoules - windowConsumedJoules;
    }

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
    public void ResetWindowData()
    {
        windowHarvestedJoules = 0f;
        windowConsumedJoules = 0f;
        windowDeepSleepSeconds = 0f;
        windowIdleSeconds = 0f;
        windowSensingSeconds = 0f;
        windowComputingSeconds = 0f;
        windowTransmittingSeconds = 0f;
        windowWakeUpCount = 0;
        windowDeepSleepEntryCount = 0;
        windowDepletionCount = 0;
        windowSensingCompletionCount = 0;
        windowInferenceCompletionCount = 0;
        windowTransmissionCompletionCount = 0;
    }
}