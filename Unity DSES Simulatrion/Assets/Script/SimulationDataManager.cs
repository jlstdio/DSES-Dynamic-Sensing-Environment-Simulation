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
    private string filePath;

    // 그래프용 데이터를 저장할 큐 (최근 24시간 기록 유지)
    public static List<float> networkAverageEfficiencyHistory = new List<float>();

    void Start()
    {
        allNodes = FindObjectsOfType<IntermittentSensorNode>();
        filePath = Path.Combine(Application.dataPath, "Simulation_Log.csv");

        // CSV 헤더 작성
        if (!File.Exists(filePath))
        {
            File.WriteAllText(filePath, "TimeWindow(h),NodeID,State,Battery(J),Harvested_1hr(J),Consumed_1hr(J),Efficiency(%)\n");
        }
        Debug.Log($"[Data Logger] CSV 파일 경로: {filePath}");
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

    /// <summary>UniStorm 배속에 동기화된 게임 시간 deltaTime 반환</summary>
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
        StringBuilder sb = new StringBuilder();
        float totalNetHarvest = 0f;
        float totalNetConsume = 0f;

        foreach (var node in allNodes)
        {
            // 효율 계산 (소비 대비 충전 비율)
            float efficiency = (node.windowConsumedJoules > 0) ? 
                (node.windowHarvestedJoules / node.windowConsumedJoules) * 100f : 0f;

            sb.AppendLine($"{windowCount + 1},{node.gameObject.name},{node.currentState}," +
                          $"{node.currentBatteryJoules:F2},{node.windowHarvestedJoules:F4}," +
                          $"{node.windowConsumedJoules:F4},{efficiency:F2}");

            totalNetHarvest += node.windowHarvestedJoules;
            totalNetConsume += node.windowConsumedJoules;

            // 다음 1시간을 위해 노드의 누적 데이터 초기화
            node.ResetWindowData();
        }

        File.AppendAllText(filePath, sb.ToString());

        // 대시보드 그래프용 네트워크 평균 효율 저장
        float netAvgEfficiency = (totalNetConsume > 0) ? (totalNetHarvest / totalNetConsume) * 100f : 0f;
        networkAverageEfficiencyHistory.Add(netAvgEfficiency);
        if (networkAverageEfficiencyHistory.Count > 24) networkAverageEfficiencyHistory.RemoveAt(0); // 최대 24개 유지

        Debug.Log($"[Data Logger] {windowCount + 1}시간 차 데이터 CSV 저장 완료. 평균 효율: {netAvgEfficiency:F1}%");
    }
}