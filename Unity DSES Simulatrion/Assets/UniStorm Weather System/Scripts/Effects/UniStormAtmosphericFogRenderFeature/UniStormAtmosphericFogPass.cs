using System;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine.XR;

public class UniStormAtmosphericFogPass : ScriptableRenderPass
{
    public UniStormAtmosphericFogFeature.Settings settings;

    RenderTextureDescriptor cameraRenderTextureDescriptor;

    RTHandle source;
    RTHandle destination;

    string m_ProfilerTag;
    Material fogMaterial;

    float TimeStamp;

    public UniStormAtmosphericFogPass(string tag)
    {
        m_ProfilerTag = tag;
        Shader unistormAtmoshpericFogShader = Shader.Find("UniStorm/URP/UniStormAtmosphericFog");
#if UNITY_EDITOR
        if (unistormAtmoshpericFogShader == null) return;
#endif
        fogMaterial = new Material(unistormAtmoshpericFogShader);
    }

    [System.Obsolete]
    public override void Configure(CommandBuffer cmd, RenderTextureDescriptor cameraTextureDescriptor)
    {
        cameraTextureDescriptor.depthBufferBits = 0;

        base.Configure(cmd, cameraTextureDescriptor);

        renderPassEvent = settings.renderPassEvent;

        // Allocate the destination RTHandle
        if (destination == null)
        {
            destination = RTHandles.Alloc(
                cameraTextureDescriptor.width,
                cameraTextureDescriptor.height,
                depthBufferBits: 0,
                colorFormat: cameraTextureDescriptor.graphicsFormat,
                filterMode: FilterMode.Bilinear,
                name: "_UniStormFogDestination"
            );
        }

        cameraRenderTextureDescriptor = cameraTextureDescriptor;
        SetupDirectionalLights();
    }

    internal void Setup(RTHandle colorTarget)
    {
        // Set up the source RTHandle
        source = colorTarget;
    }

    private void SetupDirectionalLights()
    {
        Light[] directionalLights = Light.GetLights(LightType.Directional, 0);

        foreach (Light directionalLight in directionalLights)
        {
            if (directionalLight.gameObject.name.IndexOf("sun", StringComparison.OrdinalIgnoreCase) >= 0)
                settings.SunSource = directionalLight;
            if (directionalLight.gameObject.name.IndexOf("moon", StringComparison.OrdinalIgnoreCase) >= 0)
                settings.MoonSource = directionalLight;
        }
    }

    [Obsolete]
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
#if UNITY_EDITOR
        if (fogMaterial == null || UnityEditor.EditorApplication.isPaused) return;
#endif

        CameraData cameraData = renderingData.cameraData;
        Camera camera = cameraData.camera;

        //Skip execution for the Scene View camera or if not in runtime
        if (cameraData.cameraType == CameraType.SceneView || !Application.isPlaying) return;

        Transform camtr = camera.transform;

        var camPos = camtr.position;
        float FdotC = camPos.y - settings.height;
        float paramK = (FdotC <= 0.0f ? 1.0f : 0.0f);

        Camera.MonoOrStereoscopicEye leftStereoscopicEye = Camera.MonoOrStereoscopicEye.Mono;
        if (XRSettings.enabled && XRSettings.stereoRenderingMode == XRSettings.StereoRenderingMode.SinglePassInstanced)
            leftStereoscopicEye = Camera.MonoOrStereoscopicEye.Left;

        Vector3[] leftEyeFrustumCorners = new Vector3[4];
        Vector3[] rightEyeFrustumCorners = new Vector3[4];
        camera.CalculateFrustumCorners(new Rect(0, 0, 1, 1), camera.farClipPlane, leftStereoscopicEye, leftEyeFrustumCorners);
        camera.CalculateFrustumCorners(new Rect(0, 0, 1, 1), camera.farClipPlane, Camera.MonoOrStereoscopicEye.Right, rightEyeFrustumCorners);
        Matrix4x4 leftEyeFrustumMatrix = Matrix4x4.identity;
        Matrix4x4 rightEyeFrustumMatrix = Matrix4x4.identity;

        for (int i = 0; i < leftEyeFrustumCorners.Length; i++)
        {
            leftEyeFrustumCorners[i] = camera.transform.TransformVector(leftEyeFrustumCorners[i]);
        }

        for (int i = 0; i < rightEyeFrustumCorners.Length; i++)
        {
            rightEyeFrustumCorners[i] = camera.transform.TransformVector(rightEyeFrustumCorners[i]);
        }

        leftEyeFrustumMatrix.SetRow(0, leftEyeFrustumCorners[1]);
        leftEyeFrustumMatrix.SetRow(1, leftEyeFrustumCorners[2]);
        leftEyeFrustumMatrix.SetRow(2, leftEyeFrustumCorners[3]);
        leftEyeFrustumMatrix.SetRow(3, leftEyeFrustumCorners[0]);

        rightEyeFrustumMatrix.SetRow(0, rightEyeFrustumCorners[1]);
        rightEyeFrustumMatrix.SetRow(1, rightEyeFrustumCorners[2]);
        rightEyeFrustumMatrix.SetRow(2, rightEyeFrustumCorners[3]);
        rightEyeFrustumMatrix.SetRow(3, rightEyeFrustumCorners[0]);

        fogMaterial.SetMatrixArray("_FrustumCornersWSArray", new Matrix4x4[2] { leftEyeFrustumMatrix, rightEyeFrustumMatrix });

        fogMaterial.SetVector("_CameraWS", camPos);
        fogMaterial.SetVector("_HeightParams", new Vector4(settings.height, FdotC, paramK, settings.heightDensity * 0.5f));
        fogMaterial.SetVector("_DistanceParams", new Vector4(-Mathf.Max(settings.startDistance, 0.0f), 0, 0, 0));

        if (settings.SunSource != null)
            fogMaterial.SetVector("_SunVector", settings.SunSource.transform.rotation * -Vector3.forward);
        if (settings.MoonSource != null)
            fogMaterial.SetVector("_MoonVector", settings.MoonSource.transform.rotation * -Vector3.forward);
        fogMaterial.SetFloat("_SunIntensity", settings.SunIntensity);
        fogMaterial.SetFloat("_MoonIntensity", settings.MoonIntensity);
        fogMaterial.SetFloat("_SunAlpha", settings.SunFalloffIntensity);
        fogMaterial.SetColor("_SunColor", settings.SunColor);
        fogMaterial.SetColor("_MoonColor", settings.MoonColor);

        fogMaterial.SetColor("_UpperColor", settings.TopColor);
        fogMaterial.SetColor("_BottomColor", settings.BottomColor);
        fogMaterial.SetFloat("_FogBlendHeight", settings.BlendHeight);
        fogMaterial.SetFloat("_FogGradientHeight", settings.FogGradientHeight);

        fogMaterial.SetFloat("_SunControl", settings.SunControl);
        fogMaterial.SetFloat("_MoonControl", settings.MoonControl);

        if (settings.Dither == UniStormAtmosphericFogFeature.DitheringControl.Enabled)
        {
            fogMaterial.SetFloat("_EnableDithering", 1);
            fogMaterial.SetTexture("_NoiseTex", settings.NoiseTexture);
        }
        else
        {
            fogMaterial.SetFloat("_EnableDithering", 0);
        }

        var sceneMode = RenderSettings.fogMode;
        var sceneDensity = RenderSettings.fogDensity;
        var sceneStart = RenderSettings.fogStartDistance;
        var sceneEnd = RenderSettings.fogEndDistance;
        Vector4 sceneParams;
        bool linear = (sceneMode == FogMode.Linear);
        float diff = linear ? sceneEnd - sceneStart : 0.0f;
        float invDiff = Mathf.Abs(diff) > 0.0001f ? 1.0f / diff : 0.0f;
        sceneParams.x = sceneDensity * 1.2011224087f;
        sceneParams.y = sceneDensity * 1.4426950408f;
        sceneParams.z = linear ? -invDiff : 0.0f;
        sceneParams.w = linear ? sceneEnd * invDiff : 0.0f;
        fogMaterial.SetVector("_SceneFogParams", sceneParams);
        fogMaterial.SetVector("_SceneFogMode", new Vector4((int)sceneMode, settings.useRadialDistance ? 1 : 0, 0, 0));

        int pass = 0;
        if (settings.distanceFog && settings.heightFog)
            pass = 0; // distance + height
        else if (settings.distanceFog)
            pass = 1; // distance only
        else
            pass = 2; // height only

        CommandBuffer cmd = CommandBufferPool.Get(m_ProfilerTag);

        // Ensure source RTHandle is set
        if (source == null)
        {
            source = renderingData.cameraData.renderer.cameraColorTargetHandle;
        }

        // Set up the Blit parameters
        RenderTargetIdentifier sourceRT = source.nameID;
        RenderTargetIdentifier destinationRT = destination.nameID;

        cmd.Clear();

        // Handle stereo rendering modes if necessary
        if (XRSettings.stereoRenderingMode == XRSettings.StereoRenderingMode.SinglePassInstanced
            && cameraRenderTextureDescriptor.volumeDepth == 2)
        {
            cmd.EnableShaderKeyword("STEREO_INSTANCING_ON");
        }

        if (XRSettings.stereoRenderingMode == XRSettings.StereoRenderingMode.MultiPass
            && camera.stereoActiveEye != Camera.MonoOrStereoscopicEye.Mono && camera.stereoEnabled == true)
        {
            cmd.EnableShaderKeyword("STEREO_MULTIVIEW_ON");
        }

        // Perform the Blit operation
        cmd.Blit(sourceRT, destinationRT, fogMaterial, pass);
        cmd.Blit(destinationRT, sourceRT);

        cmd.DisableShaderKeyword("STEREO_INSTANCING_ON");
        cmd.DisableShaderKeyword("STEREO_MULTIVIEW_ON");

        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }

    private Mesh m_FullscreenMesh;

    private Mesh GetFullscreenMesh()
    {
        if (m_FullscreenMesh != null)
            return m_FullscreenMesh;

        m_FullscreenMesh = new Mesh { name = "Fullscreen Quad" };

        Vector3[] vertices = new Vector3[4]
        {
            new Vector3(-1f, -1f, 0f),
            new Vector3(-1f,  1f, 0f),
            new Vector3( 1f,  1f, 0f),
            new Vector3( 1f, -1f, 0f)
        };

        Vector2[] uvs = new Vector2[4]
        {
            new Vector2(0f, 1f),
            new Vector2(0f, 0f),
            new Vector2(1f, 0f),
            new Vector2(1f, 1f)
        };

        int[] indices = new int[6] { 0, 1, 2, 0, 2, 3 };

        m_FullscreenMesh.vertices = vertices;
        m_FullscreenMesh.uv = uvs;
        m_FullscreenMesh.triangles = indices;
        m_FullscreenMesh.RecalculateNormals();
        m_FullscreenMesh.RecalculateBounds();

        return m_FullscreenMesh;
    }

    public override void OnCameraCleanup(CommandBuffer cmd)
    {
        if (destination != null)
        {
            RTHandles.Release(destination);
            destination = null;
        }
    }
}
