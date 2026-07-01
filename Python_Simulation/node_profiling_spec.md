# Node Profiling Spec for Python Reconstruction

    This document collects the node profiling values extracted from Unity and the export schema required for Python reconstruction.

    ## Layer Definitions

    | layer | metric | value | unit | notes |
| --- | --- | --- | --- | --- |
| DeepSleep | power_mw | 0.05 | mW | minimum-power sleep state |
| Idle | power_mw | 434.85 | mW | active standby |
| Sensing | power_mw | 505.95 | mW | sensor acquisition |
| Computing | power_mw | 490 | mW | CNN / inference budget |
| Transmitting | power_mw | 800 | mW | wireless offload / transfer |
| Idle | duration_s | 1 | s | state duration |
| Sensing | duration_s | 3 | s | state duration |
| Computing | duration_s | 12 | s | state duration |
| Transmitting | duration_s | 0.1 | s | state duration |
| Battery | max_joules | 594 | J | battery capacity |
| Battery | initial_ratio | 0.5 | ratio | initial charge ratio |
| Battery | wake_threshold | 118.8 | J | wake-up threshold |
| Battery | sleep_threshold | 5.94 | J | deep sleep threshold |
| Solar | solar_constant | 1361 | W/m^2 | top-of-atmosphere solar irradiance |
| Solar | clear_sky_transmittance | 0.7 | ratio | clear-sky attenuation |
| Solar | diffuse_ratio | 0.15 | ratio | diffuse irradiance fraction |
| Solar | panel_conversion_factor | 3e-07 | scale | harvest scaling factor |

    ## Energy Calculation Rules

    - Harvested energy is computed from irradiance, direct occlusion, sky view factor, and weather attenuation.
    - Consumed energy is computed from the active state power in mW and the simulation time step.
    - Net energy per window is `harvested - consumed`.
    - Energy neutrality is reported as `harvested / consumed * 100` when consumed energy is greater than zero.

    ## Charging Policy

    - The node starts at `initial_battery_ratio = 0.5` of the maximum battery capacity.
    - The node wakes from DeepSleep when battery reaches `wake_up_threshold`.
    - The node returns to DeepSleep when battery falls below `sleep_threshold`.
    - Solar charging uses the same physical parameters as the Unity runtime:
      - solar constant
      - clear sky transmittance
      - diffuse ratio
      - panel conversion factor
      - optional weather attenuation

    ## Export Artifacts

    - `heightmap.csv` / `heightmap.npy`
    - `trees.json`
    - `nodes.csv`
    - `manifest.json`

    ## Notes

    - This file is intended to replace the Unity-side profile and monitor documentation.
    - If the Unity runtime is changed, regenerate this document from the notebook.
