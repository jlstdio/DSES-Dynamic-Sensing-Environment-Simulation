using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;

public class EnvironmentMapExporter : MonoBehaviour
{
    [Header("Export Settings")]
    public bool autoExportOnStart = true;
    public bool overwriteLatest = true;
    public int heightmapResolution = 100;
    public int minimumNodeCount = 1;
    public int minimumTreeCount = 1;
    public float startupDelaySeconds = 1.0f;

    private bool hasExported;

    [Serializable]
    private class ExportManifest
    {
        public string timestamp;
        public int nodeCount;
        public int treeCount;
        public int heightmapResolution;
        public float minX;
        public float maxX;
        public float minZ;
        public float maxZ;
        public string trigger;
    }

    [Serializable]
    private class TreeColliderRecord
    {
        public string colliderType;
        public bool isTrigger;
        public float centerX;
        public float centerY;
        public float centerZ;
        public float sizeX;
        public float sizeY;
        public float sizeZ;
    }

    [Serializable]
    private class TreePhysicsRecord
    {
        public int treeId;
        public string name;
        public string sourcePrefabName;
        public int sourcePrefabIndex;
        public string sourcePrefabPath;
        public float x;
        public float y;
        public float z;
        public float rotationY;
        public float scaleX;
        public float scaleY;
        public float scaleZ;
        public float bboxCenterX;
        public float bboxCenterY;
        public float bboxCenterZ;
        public float bboxSizeX;
        public float bboxSizeY;
        public float bboxSizeZ;
        public float estimatedHeight;
        public float estimatedRadius;
        public int rendererCount;
        public int colliderCount;
        public List<TreeColliderRecord> colliders;
    }

    [Serializable]
    private class TreePhysicsCollection
    {
        public List<TreePhysicsRecord> trees;
    }

    private struct Bounds2D
    {
        public float minX;
        public float maxX;
        public float minZ;
        public float maxZ;
    }

    void Start()
    {
        if (autoExportOnStart)
        {
            StartCoroutine(AutoExportRoutine());
        }
    }

    private System.Collections.IEnumerator AutoExportRoutine()
    {
        if (startupDelaySeconds > 0f)
        {
            yield return new WaitForSeconds(startupDelaySeconds);
        }

        TryAutoExport("EnvironmentMapExporter.Start");
    }

    public void TryAutoExport(string trigger)
    {
        if (hasExported && !overwriteLatest)
        {
            // already exported once and overwrite disabled
            return;
        }

        var nodes = FindObjectsOfType<IntermittentSensorNode>();
        if (nodes.Length < minimumNodeCount)
        {
            Debug.Log($"[EnvironmentMapExporter] Skip export, nodes={nodes.Length} < minimumNodeCount={minimumNodeCount}");
            return;
        }

        Terrain[] terrains = Terrain.activeTerrains;
        if (terrains == null || terrains.Length == 0)
        {
            Debug.LogWarning("[EnvironmentMapExporter] Skip export, no active terrains found.");
            return;
        }

        List<Transform> trees = CollectTrees();
        if (trees.Count < minimumTreeCount)
        {
            Debug.Log($"[EnvironmentMapExporter] Skip export, trees={trees.Count} < minimumTreeCount={minimumTreeCount}");
            return;
        }

        ExportEnvironment(nodes, trigger);
        hasExported = true;
    }

    [ContextMenu("Export Environment Snapshot")]
    public void ExportNow()
    {
        ExportEnvironment(FindObjectsOfType<IntermittentSensorNode>(), "ManualContextMenu");
        hasExported = true;
    }

    private void ExportEnvironment(IntermittentSensorNode[] nodes, string trigger)
    {
        Debug.Log("[EnvironmentMapExporter] Working");

        string rootPath = Directory.GetParent(Application.dataPath).FullName;
        string exportRoot = Path.Combine(rootPath, "python", "exports", "latest");
        Directory.CreateDirectory(exportRoot);

        Bounds2D bounds = ComputeTerrainBounds(Terrain.activeTerrains);
        float[,] heights = BuildHeightMap(bounds, heightmapResolution);
        var trees = CollectTrees();

        WriteHeightMapCsv(Path.Combine(exportRoot, "heightmap.csv"), heights);
        WriteNodesCsv(Path.Combine(exportRoot, "nodes.csv"), nodes);
        WriteTreesCsv(Path.Combine(exportRoot, "trees.csv"), trees);
        WriteTreesPhysicsJson(Path.Combine(exportRoot, "trees_physics.json"), trees);

        var manifest = new ExportManifest
        {
            timestamp = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture),
            nodeCount = nodes.Length,
            treeCount = trees.Count,
            heightmapResolution = heightmapResolution,
            minX = bounds.minX,
            maxX = bounds.maxX,
            minZ = bounds.minZ,
            maxZ = bounds.maxZ,
            trigger = trigger,
        };

        string manifestJson = JsonUtility.ToJson(manifest, true);
        File.WriteAllText(Path.Combine(exportRoot, "manifest.json"), manifestJson);

        Debug.Log($"[EnvironmentMapExporter] Export complete: {exportRoot} (nodes={nodes.Length}, trees={trees.Count}, res={heightmapResolution}) | done");
    }

    private Bounds2D ComputeTerrainBounds(Terrain[] terrains)
    {
        Bounds2D bounds = new Bounds2D
        {
            minX = float.MaxValue,
            maxX = float.MinValue,
            minZ = float.MaxValue,
            maxZ = float.MinValue,
        };

        foreach (Terrain terrain in terrains)
        {
            if (terrain == null) continue;
            Vector3 p = terrain.transform.position;
            Vector3 s = terrain.terrainData.size;

            bounds.minX = Mathf.Min(bounds.minX, p.x);
            bounds.maxX = Mathf.Max(bounds.maxX, p.x + s.x);
            bounds.minZ = Mathf.Min(bounds.minZ, p.z);
            bounds.maxZ = Mathf.Max(bounds.maxZ, p.z + s.z);
        }

        return bounds;
    }

    private float[,] BuildHeightMap(Bounds2D bounds, int resolution)
    {
        int r = Mathf.Max(2, resolution);
        float[,] heights = new float[r, r];

        for (int z = 0; z < r; z++)
        {
            float tZ = z / (float)(r - 1);
            float worldZ = Mathf.Lerp(bounds.minZ, bounds.maxZ, tZ);

            for (int x = 0; x < r; x++)
            {
                float tX = x / (float)(r - 1);
                float worldX = Mathf.Lerp(bounds.minX, bounds.maxX, tX);

                heights[z, x] = SampleWorldHeight(worldX, worldZ);
            }
        }

        return heights;
    }

    private float SampleWorldHeight(float worldX, float worldZ)
    {
        foreach (Terrain terrain in Terrain.activeTerrains)
        {
            if (terrain == null) continue;
            Vector3 p = terrain.transform.position;
            Vector3 s = terrain.terrainData.size;

            if (worldX >= p.x && worldX <= p.x + s.x && worldZ >= p.z && worldZ <= p.z + s.z)
            {
                return p.y + terrain.SampleHeight(new Vector3(worldX, 0f, worldZ));
            }
        }

        return 0f;
    }

    private List<Transform> CollectTrees()
    {
        List<Transform> trees = new List<Transform>();
        ForestGenerator[] forests = FindObjectsOfType<ForestGenerator>();

        foreach (ForestGenerator forest in forests)
        {
            if (forest == null) continue;
            foreach (Transform child in forest.transform)
            {
                trees.Add(child);
            }
        }

        return trees;
    }

    private void WriteHeightMapCsv(string filePath, float[,] heights)
    {
        StringBuilder sb = new StringBuilder();
        int rows = heights.GetLength(0);
        int cols = heights.GetLength(1);

        for (int z = 0; z < rows; z++)
        {
            for (int x = 0; x < cols; x++)
            {
                if (x > 0) sb.Append(',');
                sb.Append(heights[z, x].ToString("F4", CultureInfo.InvariantCulture));
            }
            sb.AppendLine();
        }

        File.WriteAllText(filePath, sb.ToString());
    }

    private void WriteNodesCsv(string filePath, IntermittentSensorNode[] nodes)
    {
        StringBuilder sb = new StringBuilder();
        sb.AppendLine("node_id,x,y,z,state,battery_j");

        foreach (IntermittentSensorNode node in nodes)
        {
            Vector3 p = node.transform.position;
            sb.AppendLine(
                $"{node.nodeID}," +
                $"{p.x.ToString("F4", CultureInfo.InvariantCulture)}," +
                $"{p.y.ToString("F4", CultureInfo.InvariantCulture)}," +
                $"{p.z.ToString("F4", CultureInfo.InvariantCulture)}," +
                $"{node.currentState}," +
                $"{node.currentBatteryJoules.ToString("F4", CultureInfo.InvariantCulture)}");
        }

        File.WriteAllText(filePath, sb.ToString());
    }

    private void WriteTreesCsv(string filePath, List<Transform> trees)
    {
        StringBuilder sb = new StringBuilder();
        sb.AppendLine("tree_id,name,source_prefab_name,source_prefab_index,source_prefab_path,x,y,z,rotation_y,scale_x,scale_y,scale_z,height,radius,bbox_size_x,bbox_size_y,bbox_size_z,renderer_count,collider_count");

        for (int i = 0; i < trees.Count; i++)
        {
            Transform t = trees[i];
            Vector3 p = t.position;
            float height = EstimateTreeHeight(t);
            float radius = EstimateTreeRadius(t);
            Bounds b = GetRendererBoundsOrFallback(t);
            Renderer[] renderers = t.GetComponentsInChildren<Renderer>();
            Collider[] colliders = t.GetComponentsInChildren<Collider>();
            string safeName = t.name.Replace(',', '_');

            TreeExportMetadata metadata = t.GetComponent<TreeExportMetadata>();
            string prefabName = metadata != null && !string.IsNullOrEmpty(metadata.sourcePrefabName)
                ? metadata.sourcePrefabName
                : safeName.Replace("(Clone)", string.Empty).Trim();
            int prefabIndex = metadata != null ? metadata.sourcePrefabIndex : -1;
            string prefabPath = metadata != null && !string.IsNullOrEmpty(metadata.sourcePrefabPath)
                ? metadata.sourcePrefabPath
                : string.Empty;

            prefabName = prefabName.Replace(',', '_');
            prefabPath = prefabPath.Replace(',', '_');

            sb.AppendLine(
                $"{i}," +
                $"{safeName}," +
                $"{prefabName}," +
                $"{prefabIndex}," +
                $"{prefabPath}," +
                $"{p.x.ToString("F4", CultureInfo.InvariantCulture)}," +
                $"{p.y.ToString("F4", CultureInfo.InvariantCulture)}," +
                $"{p.z.ToString("F4", CultureInfo.InvariantCulture)}," +
                $"{t.eulerAngles.y.ToString("F4", CultureInfo.InvariantCulture)}," +
                $"{t.lossyScale.x.ToString("F4", CultureInfo.InvariantCulture)}," +
                $"{t.lossyScale.y.ToString("F4", CultureInfo.InvariantCulture)}," +
                $"{t.lossyScale.z.ToString("F4", CultureInfo.InvariantCulture)}," +
                $"{height.ToString("F4", CultureInfo.InvariantCulture)}," +
                $"{radius.ToString("F4", CultureInfo.InvariantCulture)}," +
                $"{b.size.x.ToString("F4", CultureInfo.InvariantCulture)}," +
                $"{b.size.y.ToString("F4", CultureInfo.InvariantCulture)}," +
                $"{b.size.z.ToString("F4", CultureInfo.InvariantCulture)}," +
                $"{renderers.Length}," +
                $"{colliders.Length}");
        }

        File.WriteAllText(filePath, sb.ToString());
    }

    private void WriteTreesPhysicsJson(string filePath, List<Transform> trees)
    {
        var collection = new TreePhysicsCollection
        {
            trees = new List<TreePhysicsRecord>()
        };

        for (int i = 0; i < trees.Count; i++)
        {
            Transform t = trees[i];
            Bounds b = GetRendererBoundsOrFallback(t);
            Collider[] colliders = t.GetComponentsInChildren<Collider>();
            TreeExportMetadata metadata = t.GetComponent<TreeExportMetadata>();
            string prefabName = metadata != null && !string.IsNullOrEmpty(metadata.sourcePrefabName)
                ? metadata.sourcePrefabName
                : t.name.Replace("(Clone)", string.Empty).Trim();
            int prefabIndex = metadata != null ? metadata.sourcePrefabIndex : -1;
            string prefabPath = metadata != null ? metadata.sourcePrefabPath : string.Empty;

            var record = new TreePhysicsRecord
            {
                treeId = i,
                name = t.name,
                sourcePrefabName = prefabName,
                sourcePrefabIndex = prefabIndex,
                sourcePrefabPath = prefabPath,
                x = t.position.x,
                y = t.position.y,
                z = t.position.z,
                rotationY = t.eulerAngles.y,
                scaleX = t.lossyScale.x,
                scaleY = t.lossyScale.y,
                scaleZ = t.lossyScale.z,
                bboxCenterX = b.center.x,
                bboxCenterY = b.center.y,
                bboxCenterZ = b.center.z,
                bboxSizeX = b.size.x,
                bboxSizeY = b.size.y,
                bboxSizeZ = b.size.z,
                estimatedHeight = EstimateTreeHeight(t),
                estimatedRadius = EstimateTreeRadius(t),
                rendererCount = t.GetComponentsInChildren<Renderer>().Length,
                colliderCount = colliders.Length,
                colliders = new List<TreeColliderRecord>(),
            };

            foreach (Collider c in colliders)
            {
                Bounds cb = c.bounds;
                record.colliders.Add(new TreeColliderRecord
                {
                    colliderType = c.GetType().Name,
                    isTrigger = c.isTrigger,
                    centerX = cb.center.x,
                    centerY = cb.center.y,
                    centerZ = cb.center.z,
                    sizeX = cb.size.x,
                    sizeY = cb.size.y,
                    sizeZ = cb.size.z,
                });
            }

            collection.trees.Add(record);
        }

        string json = JsonUtility.ToJson(collection, true);
        File.WriteAllText(filePath, json);
    }

    private Bounds GetRendererBoundsOrFallback(Transform tree)
    {
        Renderer[] renderers = tree.GetComponentsInChildren<Renderer>();
        if (renderers.Length == 0)
        {
            return new Bounds(tree.position, Vector3.zero);
        }

        Bounds bounds = renderers[0].bounds;
        for (int i = 1; i < renderers.Length; i++)
        {
            bounds.Encapsulate(renderers[i].bounds);
        }

        return bounds;
    }

    private float EstimateTreeHeight(Transform tree)
    {
        return GetRendererBoundsOrFallback(tree).size.y;
    }

    private float EstimateTreeRadius(Transform tree)
    {
        Bounds bounds = GetRendererBoundsOrFallback(tree);
        return Mathf.Max(bounds.extents.x, bounds.extents.z);
    }
}