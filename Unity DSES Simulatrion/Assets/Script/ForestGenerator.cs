using UnityEngine;

public class ForestGenerator : MonoBehaviour
{
    [Header("Forest Settings")]
    public GameObject[] treePrefabs;    // 여러 나무를 담을 '배열'로 변경!
    public int treeCount = 100;
    public int randomSeed = 12345;
    public float terrainSize = 100f;

    void Start()
    {
        GenerateForest();
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

        for (int i = 0; i < treeCount; i++)
        {
            float randomX = Random.Range(0f, terrainSize);
            float randomZ = Random.Range(0f, terrainSize);
            float terrainHeight = Terrain.activeTerrain.SampleHeight(new Vector3(randomX, 0, randomZ));
            
            Vector3 spawnPosition = new Vector3(randomX, terrainHeight, randomZ);
            Quaternion randomRotation = Quaternion.Euler(0f, Random.Range(0f, 360f), 0f);
            
            // 등록된 여러 나무 중 무작위로 하나를 뽑아서 배치
            int randomTreeIndex = Random.Range(0, treePrefabs.Length);
            GameObject treeInstance = Instantiate(treePrefabs[randomTreeIndex], spawnPosition, randomRotation, transform);

            // Raycast 기반 그늘 감지를 위해 MeshCollider 자동 추가 (없는 경우에만)
            foreach (MeshFilter mf in treeInstance.GetComponentsInChildren<MeshFilter>())
            {
                if (mf.GetComponent<Collider>() == null)
                {
                    MeshCollider mc = mf.gameObject.AddComponent<MeshCollider>();
                    mc.sharedMesh = mf.sharedMesh;
                }
            }
        }
    }
}