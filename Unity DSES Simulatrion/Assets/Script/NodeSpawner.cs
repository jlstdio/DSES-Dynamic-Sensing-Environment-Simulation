using UnityEngine;
using System.Collections;
using System.Collections.Generic;
using MapMagic.Core;
using MapMagic.Terrains;

public class NodeSpawner : MonoBehaviour
{
    [Header("Node Settings")]
    public GameObject nodePrefab;       // 센터 노드 프리팹
    public int nodeCount = 100;         // 생성할 노드 개수

    [Header("Spawn Area")]
    [Tooltip("맵 테두리로부터 안쪽으로 들어올 여유 거리 (미터)")]
    public float margin = 20f;          // 정사각형 맵 테두리 안쪽 margin

    [Header("Safety")]
    [Tooltip("노드 1개당 최대 재시도 횟수 (terrain 밖 좌표가 뽑혔을 때)")]
    public int maxRetriesPerNode = 50;
    [Tooltip("MapMagic terrain 준비 대기 최대 시간 (초)")]
    public float terrainWaitTimeout = 60f;

    // ── 내부 변수 ──
    private MapMagicObject mapMagic;
    private Rect spawnableArea;         // margin이 적용된 실제 배치 가능 영역

    void Start()
    {
        Debug.Log("[NodeSpawner] MapMagic terrain 준비를 대기합니다…");
        StartCoroutine(WaitForTerrainAndSpawn());
    }

    /// <summary>
    /// MapMagic이 최소 1개 이상의 terrain 타일을 생성 완료할 때까지 대기한 뒤 노드를 배치합니다.
    /// </summary>
    private IEnumerator WaitForTerrainAndSpawn()
    {
        // 1) MapMagicObject 인스턴스 찾기
        float elapsed = 0f;
        while (mapMagic == null)
        {
            mapMagic = FindObjectOfType<MapMagicObject>();
            if (mapMagic != null) break;

            elapsed += Time.deltaTime;
            if (elapsed > terrainWaitTimeout)
            {
                Debug.LogError("[NodeSpawner] MapMagicObject를 찾을 수 없습니다. 타임아웃 도달.");
                yield break;
            }
            yield return null;
        }
        Debug.Log("[NodeSpawner] MapMagicObject 발견.");

        // 2) 활성 Terrain 타일이 최소 1개 준비될 때까지 대기
        elapsed = 0f;
        while (!HasActiveTerrains())
        {
            elapsed += Time.deltaTime;
            if (elapsed > terrainWaitTimeout)
            {
                Debug.LogError("[NodeSpawner] 활성 terrain 타일을 찾지 못했습니다. 타임아웃 도달.");
                yield break;
            }
            yield return null;
        }

        // 3) terrain collider가 물리 시스템에 등록될 시간 확보 (1프레임 대기)
        yield return new WaitForFixedUpdate();

        // 4) 전체 terrain 경계 + margin 계산
        ComputeSpawnableArea();

        // 5) 노드 배치
        Debug.Log($"[NodeSpawner] Terrain 준비 완료. 배치 가능 영역: {spawnableArea}  (margin={margin}m)");
        SpawnNodes();
    }

    /// <summary>
    /// MapMagic 타일 중 활성 Terrain이 1개 이상 존재하는지 확인합니다.
    /// </summary>
    private bool HasActiveTerrains()
    {
        if (mapMagic == null) return false;
        foreach (Terrain t in mapMagic.tiles.AllActiveTerrains())
        {
            if (t != null) return true;
        }
        return false;
    }

    /// <summary>
    /// 모든 활성 MapMagic terrain 타일의 WorldRect를 합산하여
    /// 전체 맵 경계를 구하고, margin을 적용한 spawnableArea를 계산합니다.
    /// </summary>
    private void ComputeSpawnableArea()
    {
        float minX = float.MaxValue, minZ = float.MaxValue;
        float maxX = float.MinValue, maxZ = float.MinValue;

        foreach (TerrainTile tile in mapMagic.tiles.All())
        {
            Terrain terrain = tile.ActiveTerrain;
            if (terrain == null) continue;

            Rect wr = tile.WorldRect;
            if (wr.xMin < minX) minX = wr.xMin;
            if (wr.yMin < minZ) minZ = wr.yMin; // Rect.y = world-Z
            if (wr.xMax > maxX) maxX = wr.xMax;
            if (wr.yMax > maxZ) maxZ = wr.yMax;
        }

        // margin 적용 — 정사각형 맵의 네 테두리에서 안쪽으로 margin만큼 축소
        spawnableArea = new Rect(
            minX + margin,
            minZ + margin,
            (maxX - minX) - margin * 2f,
            (maxZ - minZ) - margin * 2f
        );

        if (spawnableArea.width <= 0 || spawnableArea.height <= 0)
        {
            Debug.LogError($"[NodeSpawner] margin({margin}m)이 맵 크기보다 커서 배치 가능 영역이 없습니다!");
        }
    }

    /// <summary>
    /// 주어진 (x, z) 월드 좌표가 위치하는 활성 Terrain을 찾아 반환합니다.
    /// 찾지 못하면 null을 반환합니다.
    /// </summary>
    private Terrain FindTerrainAt(float x, float z)
    {
        TerrainTile tile = mapMagic.tiles.FindByWorldPosition(x, z);
        if (tile != null) return tile.ActiveTerrain;
        return null;
    }

    [ContextMenu("Spawn Nodes")]
    public void SpawnNodes()
    {
        // 기존 자식 노드 정리
        foreach (Transform child in transform)
        {
            Destroy(child.gameObject);
        }

        int successCount = 0;
        int nodeIndex = 0;

        while (successCount < nodeCount)
        {
            bool placed = false;

            for (int retry = 0; retry < maxRetriesPerNode; retry++)
            {
                // (1) margin 적용된 영역 안에서 랜덤 (x, z)
                float x = Random.Range(spawnableArea.xMin, spawnableArea.xMax);
                float z = Random.Range(spawnableArea.yMin, spawnableArea.yMax); // Rect.y = world-Z

                // (2) 해당 좌표의 terrain 찾기
                Terrain terrain = FindTerrainAt(x, z);
                if (terrain == null) continue; // 타일 사이 빈 곳이면 재시도

                // (3) SampleHeight로 정확한 지형 높이 취득
                //     SampleHeight는 terrain 로컬 좌표 기준이므로 월드→로컬 변환
                float terrainHeight = terrain.SampleHeight(new Vector3(x, 0f, z));
                float worldY = terrain.transform.position.y + terrainHeight;

                // (4) 노드 생성 — terrain 표면 바로 위 0.2m
                Vector3 spawnPos = new Vector3(x, worldY + 0.2f, z);
                GameObject newNode = Instantiate(nodePrefab, spawnPos, Quaternion.identity);

                // ID 할당 및 이름 변경
                IntermittentSensorNode sensor = newNode.GetComponent<IntermittentSensorNode>();
                if (sensor != null)
                {
                    sensor.nodeID = nodeIndex;
                    newNode.name = $"Node_{nodeIndex:D3}";
                }

                newNode.transform.SetParent(this.transform);
                successCount++;
                nodeIndex++;
                placed = true;
                break; // 다음 노드로
            }

            if (!placed)
            {
                Debug.LogWarning($"[NodeSpawner] 노드 #{nodeIndex} 배치 실패 (최대 재시도 {maxRetriesPerNode}회 초과). " +
                                 $"현재까지 {successCount}/{nodeCount}개 배치 완료.");
                nodeIndex++;
                // 안전장치: 무한루프 방지 — 연속 실패 시 중단
                if (nodeIndex - successCount > nodeCount)
                {
                    Debug.LogError("[NodeSpawner] 배치 실패가 너무 많습니다. 맵/margin 설정을 확인해 주세요.");
                    break;
                }
            }
        }

        Debug.Log($"[NodeSpawner] ✅ {successCount}/{nodeCount}개의 노드가 terrain 위에 성공적으로 배치되었습니다. " +
                  $"(영역: {spawnableArea}, margin: {margin}m)");

        EnvironmentMapExporter exporter = FindObjectOfType<EnvironmentMapExporter>();
        if (exporter != null)
        {
            exporter.TryAutoExport("NodeSpawner.SpawnNodes");
        }
    }
}