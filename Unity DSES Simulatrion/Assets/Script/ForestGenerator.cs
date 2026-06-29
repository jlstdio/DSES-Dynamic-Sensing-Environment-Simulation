using UnityEngine;
using System.Collections;
using MapMagic.Core;
using MapMagic.Terrains;
#if UNITY_EDITOR
using UnityEditor;
#endif

public class ForestGenerator : MonoBehaviour
{
    [Header("Forest Settings")]
    public GameObject[] treePrefabs;    // 여러 나무를 담을 '배열'로 변경!
    public int treeCount = 100;
    public int randomSeed = 12345;

    [Header("Spawn Area")]
    [Tooltip("맵 테두리로부터 안쪽으로 들어올 여유 거리 (미터)")]
    public float margin = 20f;

    [Header("Safety")]
    public float terrainWaitTimeout = 60f;

    private MapMagicObject mapMagic;
    private Rect spawnableArea;

    void Start()
    {
        StartCoroutine(WaitForTerrainAndGenerate());
    }

    private IEnumerator WaitForTerrainAndGenerate()
    {
        // MapMagicObject 찾기
        float elapsed = 0f;
        while (mapMagic == null)
        {
            mapMagic = FindObjectOfType<MapMagicObject>();
            if (mapMagic != null) break;
            elapsed += Time.deltaTime;
            if (elapsed > terrainWaitTimeout) { Debug.LogError("[ForestGenerator] MapMagicObject 타임아웃"); yield break; }
            yield return null;
        }

        // 활성 terrain 대기
        elapsed = 0f;
        while (true)
        {
            bool found = false;
            foreach (Terrain t in mapMagic.tiles.AllActiveTerrains()) { if (t != null) { found = true; break; } }
            if (found) break;
            elapsed += Time.deltaTime;
            if (elapsed > terrainWaitTimeout) { Debug.LogError("[ForestGenerator] 활성 terrain 타임아웃"); yield break; }
            yield return null;
        }

        yield return new WaitForFixedUpdate();

        ComputeSpawnableArea();
        GenerateForest();
    }

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
            if (wr.yMin < minZ) minZ = wr.yMin;
            if (wr.xMax > maxX) maxX = wr.xMax;
            if (wr.yMax > maxZ) maxZ = wr.yMax;
        }

        spawnableArea = new Rect(minX + margin, minZ + margin,
                                 (maxX - minX) - margin * 2f,
                                 (maxZ - minZ) - margin * 2f);
    }

    private Terrain FindTerrainAt(float x, float z)
    {
        TerrainTile tile = mapMagic.tiles.FindByWorldPosition(x, z);
        return tile != null ? tile.ActiveTerrain : null;
    }

    public void GenerateForest()
    {
        foreach (Transform child in transform)
        {
            Destroy(child.gameObject);
        }

        Random.InitState(randomSeed);

        // 나무 프리팹이 하나도 안 들어가 있으면 에러 방지
        if (treePrefabs.Length == 0) return;

        int placed = 0;
        int maxRetries = treeCount * 50;
        int attempts = 0;

        while (placed < treeCount && attempts < maxRetries)
        {
            attempts++;
            float randomX = Random.Range(spawnableArea.xMin, spawnableArea.xMax);
            float randomZ = Random.Range(spawnableArea.yMin, spawnableArea.yMax);

            Terrain terrain = FindTerrainAt(randomX, randomZ);
            if (terrain == null) continue;

            float terrainHeight = terrain.SampleHeight(new Vector3(randomX, 0, randomZ));
            float worldY = terrain.transform.position.y + terrainHeight;

            Vector3 spawnPosition = new Vector3(randomX, worldY, randomZ);
            Quaternion randomRotation = Quaternion.Euler(0f, Random.Range(0f, 360f), 0f);
            
            // 등록된 여러 나무 중 무작위로 하나를 뽑아서 배치
            int randomTreeIndex = Random.Range(0, treePrefabs.Length);
            GameObject treeInstance = Instantiate(treePrefabs[randomTreeIndex], spawnPosition, randomRotation, transform);

            // Export metadata for Python-side reconstruction
            TreeExportMetadata metadata = treeInstance.GetComponent<TreeExportMetadata>();
            if (metadata == null)
            {
                metadata = treeInstance.AddComponent<TreeExportMetadata>();
            }

            GameObject sourcePrefab = treePrefabs[randomTreeIndex];
            metadata.sourcePrefabName = sourcePrefab != null ? sourcePrefab.name : treeInstance.name;
            metadata.sourcePrefabIndex = randomTreeIndex;

#if UNITY_EDITOR
            metadata.sourcePrefabPath = sourcePrefab != null ? AssetDatabase.GetAssetPath(sourcePrefab) : string.Empty;
#else
            metadata.sourcePrefabPath = string.Empty;
#endif

            // Raycast 기반 그늘 감지를 위해 MeshCollider 자동 추가 (없는 경우에만)
            foreach (MeshFilter mf in treeInstance.GetComponentsInChildren<MeshFilter>())
            {
                if (mf.GetComponent<Collider>() == null)
                {
                    MeshCollider mc = mf.gameObject.AddComponent<MeshCollider>();
                    mc.sharedMesh = mf.sharedMesh;
                }
            }
            placed++;
        }

        Debug.Log($"[ForestGenerator] ✅ {placed}/{treeCount}개의 나무가 terrain 위에 배치되었습니다.");

        EnvironmentMapExporter exporter = FindObjectOfType<EnvironmentMapExporter>();
        if (exporter != null)
        {
            exporter.TryAutoExport("ForestGenerator.GenerateForest");
        }
    }
}