using UnityEngine;

public class NodeSpawner : MonoBehaviour
{
    public GameObject nodePrefab; // 센서 노드 프리팹
    public int nodeCount = 100;    // 생성할 노드 개수 (이미지 설정대로 100개)
    public Vector2 spawnRange = new Vector2(200, 200); // 배치 범위
    public LayerMask terrainLayer; // 지형 레이어

    // [추가] 게임이 시작될 때 유니티가 자동으로 호출하는 함수
    void Start()
    {
        Debug.Log("노드 자동 생성을 시작합니다.");
        SpawnNodes();
    }

    [ContextMenu("Spawn Nodes")] // 인스펙터 우클릭 메뉴 기능 유지
    public void SpawnNodes()
    {
        // 이미 생성된 노드들이 있다면 중복 생성을 방지하기 위해 
        // 기존 자식 오브젝트들을 모두 삭제하고 싶다면 아래 주석을 해제하세요.
        /*
        foreach (Transform child in transform) {
            Destroy(child.gameObject);
        }
        */

        int successCount = 0;
        for (int i = 0; i < nodeCount; i++)
        {
            float x = Random.Range(-spawnRange.x / 2, spawnRange.x / 2);
            float z = Random.Range(-spawnRange.y / 2, spawnRange.y / 2);
            
            // 시작 지점의 높이를 지형보다 충분히 높게 설정 (예: 500f)
            Vector3 rayStart = new Vector3(transform.position.x + x, 500f, transform.position.z + z);
            
            // 아래 방향으로 레이저를 쏴서 지형을 찾음
            if (Physics.Raycast(rayStart, Vector3.down, out RaycastHit hit, 1000f, terrainLayer))
            {
                // 지형 바로 위(0.2m)에 노드 생성
                GameObject newNode = Instantiate(nodePrefab, hit.point + Vector3.up * 0.2f, Quaternion.identity);

                // [기능 3] 노드에 ID 할당 및 이름 변경
                IntermittentSensorNode sensor = newNode.GetComponent<IntermittentSensorNode>();
                if (sensor != null)
                {
                    sensor.nodeID = i;
                    newNode.name = $"Node_{i:D3}"; // 리스트 정렬을 위해 001, 002 형태로 이름 지정
                }

                newNode.transform.SetParent(this.transform); // 관리하기 편하게 Spawner의 자식으로 등록
                successCount++;
            }
        }
        Debug.Log($"{successCount}개의 노드가 성공적으로 배치되었습니다.");
    }
}