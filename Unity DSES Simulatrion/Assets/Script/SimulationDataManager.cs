using UnityEngine;
using System.IO;
using System.Text;
using System.Collections.Generic;

public class SimulationDataManager : MonoBehaviour
{
    public float logIntervalSeconds = 3600f; // 1시간(3600초) 단위 로깅
    private float timer = 0f;
    private int windowCount = 0;
    
    private IntermittentSensorNode[] allNodes;
    private string nodeMetricsPath;
    private string networkMetricsPath;

    public static List<float> networkAverageEfficiencyHistory = new List<float>();
    public static List<float> networkAliveRatioHistory = new List<float>();
    public static List<float> networkAverageBatteryHistory = new List<float>();

    public static float latestNetworkEnergyNeutrality = 0f;
    public static float latestNetworkAliveRatio = 0f;
    public static float latestNetworkActiveRatio = 0f;
    public static float latestNetworkAverageBattery = 0f;
    public static int latestNetworkInferenceCount = 0;
    public static int latestNetworkTransmissionCount = 0;
    public static int latestNetworkDepletionCount = 0;

    void Start()
    {
        allNodes = FindObjectsOfType<IntermittentSensorNode>();
        nodeMetricsPath = Path.Combine(Application.dataPath, "Simulation_NodeMetrics.csv");
        networkMetricsPath = Path.Combine(Application.dataPath, "Simulation_NetworkMetrics.csv");

        if (!File.Exists(nodeMetricsPath))
        {
            File.WriteAllText(
                nodeMetricsPath,
                "TimeWindow(h),NodeID,State,Battery(J),Battery(%),Harvested_1hr(J),Consumed_1hr(J),NetEnergy_1hr(J),Efficiency(%),DutyCycle(%),DeepSleep_s,Idle_s,Sensing_s,Computing_s,Transmitting_s,WakeUps,DeepSleepEntries,DepletionEvents,SensingCompletions,InferenceCompletions,TransmissionCompletions\n");
        }

        if (!File.Exists(networkMetricsPath))
        {
            File.WriteAllText(
                networkMetricsPath,
                "TimeWindow(h),NodeCount,AliveRatio(%),ActiveRatio(%),AverageBattery(%),NetHarvested(J),NetConsumed(J),NetEnergy(J),EnergyNeutrality(%),WakeUps,DepletionEvents,InferenceCompletions,TransmissionCompletions\n");
        }

        Debug.Log($"[Data Logger] Node CSV: {nodeMetricsPath}");
        Debug.Log($"[Data Logger] Network CSV: {networkMetricsPath}");
    }

    void Update()
    {
        // UniStorm 시간 배속에 동기화하여 게임 시간 기준으로 누적
        timer += GetGameTimeDelta();

        if (timer >= logIntervalSeconds)
        {
            LogDataToCSV();
            timer = 0f;
            windowCount++;
        }
    }

    private float GetGameTimeDelta()
    {
        var uni = UniStorm.UniStormSystem.Instance;
        if (uni != null &&
            uni.TimeFlow      == UniStorm.UniStormSystem.EnableFeature.Enabled &&
            uni.RealWorldTime == UniStorm.UniStormSystem.EnableFeature.Disabled)
        {
            bool isNight = uni.Hour <= 6 || uni.Hour > 18;
            float lengthMinutes = isNight ? uni.NightLength : uni.DayLength;
            return Time.deltaTime * (86400f / (lengthMinutes * 120f));
        }
        return Time.deltaTime;
    }

    private void LogDataToCSV()
    {
        allNodes = FindObjectsOfType<IntermittentSensorNode>();

        StringBuilder nodeBuilder = new StringBuilder();
        StringBuilder networkBuilder = new StringBuilder();
        float totalNetHarvest = 0f;
        float totalNetConsume = 0f;
        float totalBatteryPercent = 0f;
        int aliveNodes = 0;
        int activeNodes = 0;
        int totalWakeUps = 0;
        int totalDepletions = 0;
        int totalInferences = 0;
        int totalTransmissions = 0;

        foreach (var node in allNodes)
        {
            float efficiency = (node.windowConsumedJoules > 0) ? 
                (node.windowHarvestedJoules / node.windowConsumedJoules) * 100f : 0f;
            float batteryPercent = node.GetBatteryPercent();
            float nodeNetEnergy = node.GetWindowNetEnergyJoules();
            float dutyCycle = node.GetWindowDutyCyclePercent();

            nodeBuilder.AppendLine(
                $"{windowCount + 1},{node.nodeID},{node.currentState}," +
                $"{node.currentBatteryJoules:F2},{batteryPercent:F2},{node.windowHarvestedJoules:F4}," +
                $"{node.windowConsumedJoules:F4},{nodeNetEnergy:F4},{efficiency:F2},{dutyCycle:F2}," +
                $"{node.windowDeepSleepSeconds:F2},{node.windowIdleSeconds:F2},{node.windowSensingSeconds:F2}," +
                $"{node.windowComputingSeconds:F2},{node.windowTransmittingSeconds:F2}," +
                $"{node.windowWakeUpCount},{node.windowDeepSleepEntryCount},{node.windowDepletionCount}," +
                $"{node.windowSensingCompletionCount},{node.windowInferenceCompletionCount},{node.windowTransmissionCompletionCount}");

            totalNetHarvest += node.windowHarvestedJoules;
            totalNetConsume += node.windowConsumedJoules;
            totalBatteryPercent += batteryPercent;
            totalWakeUps += node.windowWakeUpCount;
            totalDepletions += node.windowDepletionCount;
            totalInferences += node.windowInferenceCompletionCount;
            totalTransmissions += node.windowTransmissionCompletionCount;

            if (node.currentBatteryJoules > 0f) aliveNodes++;
            if (node.currentState != SensorNodeState.DeepSleep) activeNodes++;

            node.ResetWindowData();
        }

        File.AppendAllText(nodeMetricsPath, nodeBuilder.ToString());

        float netAvgEfficiency = (totalNetConsume > 0) ? (totalNetHarvest / totalNetConsume) * 100f : 0f;
        float networkNetEnergy = totalNetHarvest - totalNetConsume;
        float aliveRatio = allNodes.Length > 0 ? (aliveNodes / (float)allNodes.Length) * 100f : 0f;
        float activeRatio = allNodes.Length > 0 ? (activeNodes / (float)allNodes.Length) * 100f : 0f;
        float avgBatteryPercent = allNodes.Length > 0 ? totalBatteryPercent / allNodes.Length : 0f;

        networkBuilder.AppendLine(
            $"{windowCount + 1},{allNodes.Length},{aliveRatio:F2},{activeRatio:F2},{avgBatteryPercent:F2}," +
            $"{totalNetHarvest:F4},{totalNetConsume:F4},{networkNetEnergy:F4},{netAvgEfficiency:F2}," +
            $"{totalWakeUps},{totalDepletions},{totalInferences},{totalTransmissions}");
        File.AppendAllText(networkMetricsPath, networkBuilder.ToString());

        networkAverageEfficiencyHistory.Add(netAvgEfficiency);
        if (networkAverageEfficiencyHistory.Count > 24) networkAverageEfficiencyHistory.RemoveAt(0); // 최대 24개 유지
        networkAliveRatioHistory.Add(aliveRatio);
        if (networkAliveRatioHistory.Count > 24) networkAliveRatioHistory.RemoveAt(0);
        networkAverageBatteryHistory.Add(avgBatteryPercent);
        if (networkAverageBatteryHistory.Count > 24) networkAverageBatteryHistory.RemoveAt(0);

        latestNetworkEnergyNeutrality = netAvgEfficiency;
        latestNetworkAliveRatio = aliveRatio;
        latestNetworkActiveRatio = activeRatio;
        latestNetworkAverageBattery = avgBatteryPercent;
        latestNetworkInferenceCount = totalInferences;
        latestNetworkTransmissionCount = totalTransmissions;
        latestNetworkDepletionCount = totalDepletions;

        Debug.Log(
            $"[Data Logger] Window {windowCount + 1} 저장 완료 | Energy Neutrality: {netAvgEfficiency:F1}% | " +
            $"Alive: {aliveRatio:F1}% | Avg Battery: {avgBatteryPercent:F1}% | Inference: {totalInferences} | Tx: {totalTransmissions}");
    }
}