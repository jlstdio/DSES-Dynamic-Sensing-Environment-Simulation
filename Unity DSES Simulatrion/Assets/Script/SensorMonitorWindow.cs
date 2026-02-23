using UnityEngine;
using UnityEditor;

public class SensorMonitorWindow : EditorWindow
{
    private Vector2 scrollPosition;

    [MenuItem("Window/AIoT Sensor Monitor")]
    public static void ShowWindow()
    {
        GetWindow<SensorMonitorWindow>("Sensor Monitor");
    }

    void OnGUI()
    {
        GUILayout.Label("AIoT 노드 실시간 물리 모니터링", EditorStyles.boldLabel);

        // 씬 내의 모든 IntermittentSensorNode 찾음
        IntermittentSensorNode[] nodes = GameObject.FindObjectsOfType<IntermittentSensorNode>();

        if (nodes.Length == 0)
        {
            GUILayout.Label("배치된 노드가 없습니다.");
            return;
        }

        // 요약 정보 (논문 프로파일링 기준 상태)
        int deepSleepCount = 0;
        foreach (var n in nodes) if (n.currentState == IntermittentSensorNode.NodeState.DeepSleep) deepSleepCount++;
        
        EditorGUILayout.HelpBox($"총 노드: {nodes.Length} | 활성: {nodes.Length - deepSleepCount} | 딥슬립: {deepSleepCount}", MessageType.Info);

        EditorGUILayout.Space();

        scrollPosition = EditorGUILayout.BeginScrollView(scrollPosition);
        
        foreach (var node in nodes)
        {
            EditorGUILayout.BeginHorizontal("box");

            // [기능 3] ID 표시 (ID 순서대로 정렬되어 보임)
            GUILayout.Label($"ID: {node.nodeID:D3}", GUILayout.Width(50));
            GUILayout.Label($"{node.name}", GUILayout.Width(100));
            
            // 1. 이름 및 현재 상태 (DeepSleep 등)
            string stateLabel = $"[{node.currentState}] {node.name}";
            GUILayout.Label(stateLabel, GUILayout.Width(180));

            // 2. 배터리 상태 (J 단위 및 퍼센트 계산)
            float batteryPercent = (node.currentBatteryJoules / node.maxBatteryJoules) * 100f;
            GUI.color = batteryPercent > 20 ? Color.white : Color.red;
            GUILayout.Label($"{node.currentBatteryJoules:F1}J ({batteryPercent:F1}%)", GUILayout.Width(100));
            GUI.color = Color.white;

            // 3. 실시간 하베스팅 전력량 (mW)
            GUILayout.Label($"{node.currentHarvesting_mW:F3}mW", GUILayout.Width(80));

            // 4. 강제 기상/수면 버튼 (연구 테스트용)
            GUI.backgroundColor = (node.currentState == IntermittentSensorNode.NodeState.DeepSleep) ? Color.gray : Color.green;
            if (GUILayout.Button("Action", GUILayout.Width(60)))
            {
                // 수동으로 상태를 전환하여 에너지가 없을 때의 거동을 테스트할 수 있습니다.
                Selection.activeGameObject = node.gameObject; // 클릭 시 해당 오브젝트 선택
            }
            GUI.backgroundColor = Color.white;

            EditorGUILayout.EndHorizontal();
        }

        EditorGUILayout.EndScrollView();

        if (Application.isPlaying) Repaint();
    }
}