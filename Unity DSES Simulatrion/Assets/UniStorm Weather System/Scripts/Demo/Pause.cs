using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace UniStorm.CharacterController
{
    public class Pause : MonoBehaviour
    {
        UniStorm.Example.DemoUIController demoUIController;

        void Start()
        {
            demoUIController = FindAnyObjectByType<UniStorm.Example.DemoUIController>();
        }

        void Update()
        {
            if (!demoUIController)
            {
                if (UniStormSystem.Instance != null && !UniStormSystem.Instance.m_MenuToggle)
                {
                    Cursor.lockState = CursorLockMode.None;
                    Cursor.visible = true;
                    GetComponent<UniStormMouseLook>().enabled = false;
                }
                else
                {
                    Cursor.lockState = CursorLockMode.Locked;
                    Cursor.visible = false;
                    GetComponent<UniStormMouseLook>().enabled = true;
                }
            }
            else
            {
                if (demoUIController.QualityDropdown.transform.parent.gameObject.activeSelf)
                {
                    Cursor.lockState = CursorLockMode.None;
                    Cursor.visible = true;
                    GetComponent<UniStormMouseLook>().enabled = false;
                }
                else
                {
                    Cursor.lockState = CursorLockMode.Locked;
                    Cursor.visible = false;
                    GetComponent<UniStormMouseLook>().enabled = true;
                }
            }
        }
    }
}