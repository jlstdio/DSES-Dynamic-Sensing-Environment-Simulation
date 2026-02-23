using System.Linq;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine.XR;

public class UniStormSunShaftsPass : ScriptableRenderPass
{
    public FilterMode filterMode { get; set; }
    public UniStormSunShaftsFeature.Settings settings;

    RenderTextureDescriptor cameraRenderTextureDescriptor;

    RTHandle source;

    Material sunShaftsMaterial = null;

    string m_ProfilerTag;

    private Transform sunTransform;

    public Transform SunTransform
    {
        get
        {
            if (sunTransform == null)
            {
                Light[] lights = Light.GetLights(LightType.Directional, ~0);
                if (lights.Length > 0)
                {
                    Light sunLight = lights.FirstOrDefault(x => x.name.Equals(settings.celestialName));
                    if (sunLight != null)
                    {
                        sunTransform = sunLight.transform.GetChild(0);
                    }
                }
            }

            return sunTransform;
        }
    }

    public UniStormSunShaftsPass(string tag)
    {
        m_ProfilerTag = tag;
        Shader unistormSunShaftsShader = Shader.Find("UniStorm/URP/UniStormSunShafts");
#if UNITY_EDITOR
        if (unistormSunShaftsShader == null) return;
#endif
        sunShaftsMaterial = new Material(unistormSunShaftsShader);
    }

    public void Setup(RTHandle cameraColorTargetHandle)
    {
        source = cameraColorTargetHandle;
    }

    [System.Obsolete]
    public override void Configure(CommandBuffer cmd, RenderTextureDescriptor cameraTextureDescriptor)
    {
        base.Configure(cmd, cameraTextureDescriptor);

        renderPassEvent = settings.renderPassEvent;

        cameraRenderTextureDescriptor = cameraTextureDescriptor;
        // No need to call ConfigureTarget or ConfigureClear here
    }

    [System.Obsolete]
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
#if UNITY_EDITOR
        if (sunShaftsMaterial == null || UnityEditor.EditorApplication.isPaused) return;
#endif

        CameraData cameraData = renderingData.cameraData;
        Camera camera = cameraData.camera;

        //Skip execution for the Scene View camera or if not in runtime
        if (cameraData.cameraType == CameraType.SceneView || !Application.isPlaying) return;

        CommandBuffer cmd = CommandBufferPool.Get(m_ProfilerTag);

        cmd.Clear();

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

        int divider = 4;
        if (settings.resolution == UniStormSunShaftsFeature.SunShaftsResolution.Normal)
            divider = 2;
        else if (settings.resolution == UniStormSunShaftsFeature.SunShaftsResolution.High)
            divider = 1;

        Vector3 vl = Vector3.one * 0.5f;
        Vector3 vr = Vector3.one * 0.5f;

        Camera.MonoOrStereoscopicEye leftEye;
        if (camera.stereoActiveEye == Camera.MonoOrStereoscopicEye.Left
            && XRSettings.stereoRenderingMode == XRSettings.StereoRenderingMode.SinglePassInstanced)
        {
            leftEye = Camera.MonoOrStereoscopicEye.Left;
        }
        else
        {
            leftEye = Camera.MonoOrStereoscopicEye.Mono;
        }

        if (SunTransform)
        {
            var sunPosition = SunTransform.position;
            vl = camera.WorldToViewportPoint(sunPosition, leftEye);
            vr = camera.WorldToViewportPoint(sunPosition, Camera.MonoOrStereoscopicEye.Right);
        }
        else
        {
            vl = new Vector3(0.5f, 0.5f, 0.0f);
            vr = new Vector3(0.5f, 0.5f, 0.0f);
        }

        int width = cameraRenderTextureDescriptor.width;
        int height = cameraRenderTextureDescriptor.height;

        int rtW = width / divider;
        int rtH = height / divider;

        // Allocate temporary RTHandles for processing
        RTHandle lrDepthBuffer = GetTemporaryRTHandle(rtW, rtH);

        sunShaftsMaterial.SetVector("_BlurRadius4", new Vector4(1.0f, 1.0f, 0.0f, 0.0f) * settings.sunShaftBlurRadius);
        sunShaftsMaterial.SetVectorArray("_SunPositionArray", new Vector4[2]
        {
            new Vector4(vl.x, vl.y, vl.z, settings.maxRadius),
            new Vector4(vr.x, vr.y, vr.z, settings.maxRadius)
        });
        sunShaftsMaterial.SetVector("_SunThreshold", settings.sunThreshold);

        if (!settings.useDepthTexture)
        {
            var format = camera.allowHDR ? RenderTextureFormat.DefaultHDR : RenderTextureFormat.Default;

            RenderTextureDescriptor rtd = new RenderTextureDescriptor(width, height, format);
            rtd.msaaSamples = 1;
            rtd.depthBufferBits = 0;

            RTHandle tmpBuffer = RTHandles.Alloc(rtd, name: "TempSkyboxBuffer");

            sunShaftsMaterial.SetTexture("_Skybox", tmpBuffer);

            cmd.Blit(source.rt, lrDepthBuffer.rt, sunShaftsMaterial, 3);

            tmpBuffer.Release();
        }
        else
        {
            cmd.Blit(source.rt, lrDepthBuffer.rt, sunShaftsMaterial, 2);
        }

        // Radial blur iterations
        settings.radialBlurIterations = Mathf.Clamp(settings.radialBlurIterations, 1, 4);

        float ofs = settings.sunShaftBlurRadius * (1.0f / 768.0f);

        sunShaftsMaterial.SetVector("_BlurRadius4", new Vector4(ofs, ofs, 0.0f, 0.0f));
        sunShaftsMaterial.SetVectorArray("_SunPositionArray", new Vector4[2]
        {
            new Vector4(vl.x, vl.y, vl.z, settings.maxRadius),
            new Vector4(vr.x, vr.y, vr.z, settings.maxRadius)
        });

        for (int it2 = 0; it2 < settings.radialBlurIterations; it2++)
        {
            RTHandle lrColorB = GetTemporaryRTHandle(rtW, rtH);

            cmd.Blit(lrDepthBuffer.rt, lrColorB.rt, sunShaftsMaterial, 1);
            lrDepthBuffer.Release();

            ofs = settings.sunShaftBlurRadius * (((it2 * 2.0f + 1.0f) * 6.0f)) / 768.0f;
            sunShaftsMaterial.SetVector("_BlurRadius4", new Vector4(ofs, ofs, 0.0f, 0.0f));

            lrDepthBuffer = GetTemporaryRTHandle(rtW, rtH);
            cmd.Blit(lrColorB.rt, lrDepthBuffer.rt, sunShaftsMaterial, 1);
            lrColorB.Release();

            ofs = settings.sunShaftBlurRadius * (((it2 * 2.0f + 2.0f) * 6.0f)) / 768.0f;
            sunShaftsMaterial.SetVector("_BlurRadius4", new Vector4(ofs, ofs, 0.0f, 0.0f));
        }

        // Final composition
        if (vl.z >= 0.0f)
            sunShaftsMaterial.SetVector("_SunColor", settings.sunColor * settings.sunShaftIntensity);
        else
            sunShaftsMaterial.SetVector("_SunColor", Vector4.zero); // No backprojection

        sunShaftsMaterial.SetTexture("_ColorBuffer", lrDepthBuffer);


        // Allocate a temporary RT for the final result
        RTHandle finalResult = GetTemporaryRTHandle(cameraRenderTextureDescriptor.width / divider, cameraRenderTextureDescriptor.height / divider);

        // Blit from source to the temporary RT
        cmd.Blit(source.rt, finalResult.rt, sunShaftsMaterial,
            (settings.screenBlendMode == UniStormSunShaftsFeature.ShaftsScreenBlendMode.Screen) ? 0 : 4);

        // Blit back to the source
        cmd.Blit(finalResult.rt, source.rt);

        // Release the temporary RT
        finalResult.Release();

        /*
        // Blit the final result to the camera's color target
        cmd.Blit(source.rt, source.rt, sunShaftsMaterial,
            (settings.screenBlendMode == UniStormSunShaftsFeature.ShaftsScreenBlendMode.Screen) ? 0 : 4);
        */


        cmd.DisableShaderKeyword("STEREO_INSTANCING_ON");
        cmd.DisableShaderKeyword("STEREO_MULTIVIEW_ON");

        context.ExecuteCommandBuffer(cmd);
        cmd.Clear();

        lrDepthBuffer.Release();

        CommandBufferPool.Release(cmd);
    }

    private RTHandle GetTemporaryRTHandle(int width, int height)
    {
        RenderTextureDescriptor rtd = cameraRenderTextureDescriptor;
        rtd.width = width;
        rtd.height = height;
        rtd.depthBufferBits = 0;
        rtd.msaaSamples = 1;

        return RTHandles.Alloc(rtd);
    }

    public override void OnCameraCleanup(CommandBuffer cmd)
    {
        // No need to release source, as it's provided by the renderer
    }
}
