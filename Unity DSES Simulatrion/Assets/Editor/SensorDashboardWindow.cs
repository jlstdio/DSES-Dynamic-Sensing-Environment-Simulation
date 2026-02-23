using UnityEngine;
using UnityEditor;

public class SensorDashboardWindow : EditorWindow
{
    [MenuItem("Window/AIoT Research Dashboard")]
    public static void ShowWindow()
    {
        GetWindow<SensorDashboardWindow>("Research Dashboard");
    }

    void OnGUI()
    {
        GUILayout.Label("Continuous Surveillance AIoT - 1 Hour Window Stats", EditorStyles.boldLabel);
        EditorGUILayout.Space();

        if (!Application.isPlaying)
        {
            GUILayout.Label("시뮬레이션을 실행(Play)하면 실시간 데이터와 그래프가 표시됩니다.");
            return;
        }

        IntermittentSensorNode[] nodes = GameObject.FindObjectsOfType<IntermittentSensorNode>();
        int activeNodes = 0;
        foreach (var n in nodes) if (n.currentState != IntermittentSensorNode.NodeState.DeepSleep) activeNodes++;

        // 요약 정보
        EditorGUILayout.HelpBox($"Total Nodes: {nodes.Length}\nActive (Computing/Sensing): {activeNodes}\nDeep Sleep: {nodes.Length - activeNodes}", MessageType.Info);
        
        EditorGUILayout.Space();
        GUILayout.Label("Network Average Efficiency Trend (Last 24 Windows)", EditorStyles.boldLabel);

        // 간단한 1시간 단위 윈도우 그래프 그리기
        DrawGraph();

        if (Application.isPlaying) Repaint(); // 실시간 갱신
    }

    private void DrawGraph()
    {
        var history = SimulationDataManager.networkAverageEfficiencyHistory;
        if (history == null || history.Count == 0) return;

        Rect graphRect = GUILayoutUtility.GetRect(position.width, 150);
        EditorGUI.DrawRect(graphRect, new Color(0.1f, 0.1f, 0.1f)); // 배경

        float maxEfficiency = 150f; // y축 최대값 (150%)
        
        Handles.color = Color.green;
        Vector3[] points = new Vector3[history.Count];
        
        float xStep = graphRect.width / Mathf.Max(1, history.Count - 1);
        
        for (int i = 0; i < history.Count; i++)
        {
            float x = graphRect.x + (i * xStep);
            // 효율 수치를 그래프 높이에 맞게 정규화 (최대치 넘어가면 잘림 방지)
            float normalizedY = Mathf.Clamp01(history[i] / maxEfficiency); 
            float y = graphRect.y + graphRect.height - (normalizedY * graphRect.height);
            
            points[i] = new Vector3(x, y, 0);
        }

        // 선 연결
        Handles.DrawPolyLine(points);

        // 점 찍기 및 수치 텍스트
        GUIStyle textStyle = new GUIStyle(EditorStyles.whiteMiniLabel);
        for (int i = 0; i < points.Length; i++)
        {
            Handles.DrawSolidDisc(points[i], Vector3.forward, 3f);
            GUI.Label(new Rect(points[i].x - 10, points[i].y - 20, 50, 20), $"{history[i]:F0}%", textStyle);
        }
    }
}