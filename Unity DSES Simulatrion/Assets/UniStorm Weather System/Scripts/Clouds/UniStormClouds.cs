using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace UniStorm.Utility
{
    public class UniStormClouds : MonoBehaviour
    {
        [HideInInspector] public Material skyMaterial;
        [HideInInspector] public Material cloudsMaterial;
        [HideInInspector] public Material shadowsMaterial;
        [HideInInspector] public Material shadowsBuildingMaterial;
        [HideInInspector] public Transform cloudShadows;
        [HideInInspector] public Light sun;
        [HideInInspector] public Transform moon;
        [HideInInspector] public enum CloudPerformance { Low = 0, Medium = 1, High = 2, Ultra = 3 }
        [HideInInspector] private int[] presetResolutions = { 1024, 2048, 2048, 2048 };
        [HideInInspector] private string[] keywordsA = { "LOW", "MEDIUM", "HIGH", "ULTRA" };
        [HideInInspector] public enum CloudShadowsType { Off = 0, Simulated, RealTime }
        [HideInInspector] public CloudShadowsType CloudShadowsTypeRef = CloudShadowsType.Off;
        [HideInInspector] public enum CloudType { TwoD = 0, Volumetric }
        [HideInInspector] private string[] keywordsB = { "TWOD", "VOLUMETRIC" };
        [HideInInspector] public CloudType cloudType = CloudType.Volumetric;
        [HideInInspector] public CloudPerformance performance = CloudPerformance.High;
        [HideInInspector] public int CloudShadowResolutionValue = 256;
        [HideInInspector] [Range(0, 1)] public float cloudTransparency = 0.85f;
        [HideInInspector] [Range(0, 6)] public int shadowBlurIterations;
        private int frameCount = 0;

        [HideInInspector] public int fullBufferIndex = 0;
        [HideInInspector] public RenderTexture[] fullCloudsBuffer;
        [HideInInspector] public RenderTexture lowResCloudsBuffer;
        [HideInInspector] public RenderTexture[] cloudShadowsBuffer;
        [HideInInspector] public RenderTexture PublicCloudShadowTexture;

        private float baseCloudOffset;
        private float detailCloudOffset;

        public bool IsInitialized
        {
            get
            {
                return fullCloudsBuffer != null && fullCloudsBuffer.Length >= 2 &&
                       cloudShadowsBuffer != null && cloudShadowsBuffer.Length >= 2 &&
                       lowResCloudsBuffer != null &&
                       skyMaterial != null &&
                       shadowsBuildingMaterial != null &&
                       cloudsMaterial != null;
            }
        }

        private void Start()
        {
            GenerateInitialNoise();

            if (UniStormSystem.Instance.UseRuntimeDelay == UniStormSystem.EnableFeature.Enabled)
            {
                StartCoroutine(InitializeClouds());
            }
        }

        void GenerateInitialNoise()
        {
            SetCloudDetails(performance, cloudType, CloudShadowsTypeRef);
            GetComponent<MeshRenderer>().enabled = true;

            GenerateNoise.GenerateBaseCloudNoise();
            GenerateNoise.GenerateCloudDetailNoise();
            GenerateNoise.GenerateCloudCurlNoise();

            GetComponent<MeshFilter>().sharedMesh = ProceduralHemispherePolarUVs.hemisphere;
            GetComponentsInChildren<MeshFilter>()[1].sharedMesh = ProceduralHemispherePolarUVs.hemisphereInv;
            skyMaterial.SetFloat("_uLightningTimer", 0.0f);

            if (CloudShadowResolutionValue == 0)
            {
                CloudShadowResolutionValue = 256;
            }

            shadowsBuildingMaterial = new Material(Shader.Find("Hidden/UniStorm/CloudShadows"));

            InitializeRenderTextures();
        }

        void InitializeRenderTextures()
        {
            int size = presetResolutions[(int)performance];

            EnsureArray(ref fullCloudsBuffer, 2);
            EnsureArray(ref cloudShadowsBuffer, 2);

            EnsureRenderTarget(ref fullCloudsBuffer[0], size, size, RenderTextureFormat.ARGBHalf, FilterMode.Bilinear, "fullCloudBuff0");
            EnsureRenderTarget(ref fullCloudsBuffer[1], size, size, RenderTextureFormat.ARGBHalf, FilterMode.Bilinear, "fullCloudBuff1");
            EnsureRenderTarget(ref cloudShadowsBuffer[0], CloudShadowResolutionValue, CloudShadowResolutionValue, RenderTextureFormat.ARGBHalf, FilterMode.Bilinear, "cloudShadowBuff0");
            EnsureRenderTarget(ref cloudShadowsBuffer[1], size, size, RenderTextureFormat.ARGBHalf, FilterMode.Bilinear, "cloudShadowBuff1");

            EnsureRenderTarget(ref lowResCloudsBuffer, size / 4, size / 4, RenderTextureFormat.ARGBFloat, FilterMode.Point, "quarterCloudBuff");
        }

        IEnumerator InitializeClouds()
        {
            yield return new WaitUntil(() => UniStormSystem.Instance.UniStormInitialized);
        }

        #region Helper Functions and Variables
        public void EnsureArray<T>(ref T[] array, int size, T initialValue = default(T))
        {
            if (array == null || array.Length != size)
            {
                array = new T[size];
                for (int i = 0; i != size; i++)
                    array[i] = initialValue;
            }
        }

        public bool EnsureRenderTarget(ref RenderTexture rt, int width, int height, RenderTextureFormat format, FilterMode filterMode, string name, int depthBits = 0, int antiAliasing = 1)
        {
            if (rt != null && (rt.width != width || rt.height != height || rt.format != format || rt.filterMode != filterMode || rt.antiAliasing != antiAliasing))
            {
                RenderTexture.ReleaseTemporary(rt);
                rt = null;
            }
            if (rt == null)
            {
                rt = RenderTexture.GetTemporary(width, height, depthBits, format, RenderTextureReadWrite.Default, antiAliasing);
                rt.name = name;
                rt.filterMode = filterMode;
                rt.wrapMode = TextureWrapMode.Repeat;
                return true;
            }

#if UNITY_ANDROID || UNITY_IPHONE
            rt.DiscardContents();
#endif

            return false;
        }

        static int[] haltonSequence = {
            8, 4, 12, 2, 10, 6, 14, 1
        };

        static int[,] offset = {
            {2,1}, {1,2 }, {2,0}, {0,1},
            {2,3}, {3,2}, {3,1}, {0,3},
            {1,0}, {1,1}, {3,3}, {0,0},
            {2,2}, {1,3}, {3,0}, {0,2}
        };

        static int[,] bayerOffsets = {
            {0,8,2,10 },
            {12,4,14,6 },
            {3,11,1,9 },
            {15,7,13,5 }
        };
        #endregion

        private int frameIndex = 0;
        private int haltonSequenceIndex = 0;

        public void SetCloudDetails(CloudPerformance performance, CloudType cloudType, CloudShadowsType cloudShadowsType, bool forceRecreateTextures = false)
        {
            if (this.performance != performance || this.CloudShadowsTypeRef != cloudShadowsType || this.cloudType != cloudType
                || forceRecreateTextures)
            {
                if (cloudShadowsBuffer != null && cloudShadowsBuffer.Length > 0)
                {
                    cloudShadowsBuffer[0].Release();
                    cloudShadowsBuffer[1].Release();
                }
                if (lowResCloudsBuffer != null) lowResCloudsBuffer.Release();
                if (fullCloudsBuffer != null && fullCloudsBuffer.Length > 0)
                {
                    fullCloudsBuffer[0].Release();
                    fullCloudsBuffer[1].Release();
                }

                frameCount = 0;
            }

            this.performance = performance;
            this.cloudType = cloudType;
            this.CloudShadowsTypeRef = cloudShadowsType;

            switch (cloudShadowsType)
            {
                case CloudShadowsType.Off:
                    this.cloudShadows.gameObject.GetComponentsInChildren<MeshRenderer>()[1].enabled = false;
                    sun.cookie = null;
                    break;
                case CloudShadowsType.Simulated:
                    this.cloudShadows.gameObject.GetComponentsInChildren<MeshRenderer>()[1].enabled = false;
                    break;
                case CloudShadowsType.RealTime:
                    this.cloudShadows.gameObject.GetComponentsInChildren<MeshRenderer>()[1].enabled = true;
                    sun.cookie = null;
                    break;
                default:
                    break;
            }

            foreach (string s in skyMaterial.shaderKeywords)
                skyMaterial.DisableKeyword(s);

            skyMaterial.EnableKeyword(keywordsA[(int)performance]);
            skyMaterial.EnableKeyword(keywordsB[(int)cloudType]);
        }

#if UNITY_EDITOR
        private void OnValidate()
        {
            SetCloudDetails(performance, cloudType, CloudShadowsTypeRef, true);
        }
#endif

        void Update()
        {
            // Instance가 null이거나 Unity에 의해 이미 파괴된 오브젝트(fake-null)인 경우를 모두 방어
            if (UniStormSystem.Instance != null && UniStormSystem.Instance.UniStormInitialized)
            {
                CloudsUpdate();
            }
        }

        void CloudsUpdate()
        {
            cloudShadows.position = UniStormSystem.Instance.PlayerCamera.transform.position;

            frameIndex = (frameIndex + 1) % 16;

            if (frameIndex == 0)
                haltonSequenceIndex = (haltonSequenceIndex + 1) % haltonSequence.Length;
            fullBufferIndex = fullBufferIndex ^ 1;

            float offsetX = offset[frameIndex, 0];
            float offsetY = offset[frameIndex, 1];

            frameCount++;
            if (frameCount < 32)
                skyMaterial.EnableKeyword("PREWARM");
            else if (frameCount == 32)
                skyMaterial.DisableKeyword("PREWARM");

            int size = presetResolutions[(int)performance];

            skyMaterial.SetTexture("_uBaseNoise", GenerateNoise.baseNoiseTexture);
            skyMaterial.SetTexture("_uDetailNoise", GenerateNoise.detailNoiseTexture);
            skyMaterial.SetTexture("_uCurlNoise", GenerateNoise.curlNoiseTexture);

            baseCloudOffset += skyMaterial.GetFloat("_uCloudsMovementSpeed") * Time.deltaTime;
            detailCloudOffset += skyMaterial.GetFloat("_uCloudsTurbulenceSpeed") * Time.deltaTime;

            skyMaterial.SetFloat("_uBaseCloudOffset", baseCloudOffset);
            skyMaterial.SetFloat("_uDetailCloudOffset", detailCloudOffset);

            skyMaterial.SetFloat("_uSize", size);
            skyMaterial.SetInt("_uCount", frameCount);
            skyMaterial.SetVector("_uJitter", new Vector2(offsetX, offsetY));
            skyMaterial.SetFloat("_uRaymarchOffset", (haltonSequence[haltonSequenceIndex] / 16.0f + bayerOffsets[offset[frameIndex, 0], offset[frameIndex, 1]] / 16.0f));

            skyMaterial.SetVector("_uSunDir", sun.transform.forward);
            skyMaterial.SetVector("_uMoonDir", Vector3.Normalize(moon.forward));
            skyMaterial.SetVector("_uWorldSpaceCameraPos", UniStormSystem.Instance.PlayerCamera.transform.position);

            //Update the cloudsMaterial with the latest texture

            // place this code directly above the "cloudsMaterial.SetTexture"
            skyMaterial.SetTexture("_uLowresCloudTex", lowResCloudsBuffer);
            skyMaterial.SetTexture("_uPreviousCloudTex", fullCloudsBuffer[fullBufferIndex]);
            RenderTexture temp = RenderTexture.active;
            Graphics.Blit(null, lowResCloudsBuffer, skyMaterial, 0);
            Graphics.Blit(null, fullCloudsBuffer[fullBufferIndex ^ 1], skyMaterial, 1);
            RenderTexture.active = temp;
            // -------------------------------------------------
            cloudsMaterial.SetTexture("_MainTex", fullCloudsBuffer[fullBufferIndex ^ 1]);
        }

        void OnDestroy()
        {
            if (fullCloudsBuffer != null)
            {
                if (fullCloudsBuffer[0] != null) RenderTexture.ReleaseTemporary(fullCloudsBuffer[0]);
                if (fullCloudsBuffer[1] != null) RenderTexture.ReleaseTemporary(fullCloudsBuffer[1]);
            }
            if (cloudShadowsBuffer != null)
            {
                if (cloudShadowsBuffer[0] != null) RenderTexture.ReleaseTemporary(cloudShadowsBuffer[0]);
                if (cloudShadowsBuffer[1] != null) RenderTexture.ReleaseTemporary(cloudShadowsBuffer[1]);
            }
            if (lowResCloudsBuffer != null) RenderTexture.ReleaseTemporary(lowResCloudsBuffer);
        }
    }
}
 