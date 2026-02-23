using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEditor;
using UnityEditor.Callbacks;
using UnityEditor.Build; //Added namespace for NamedBuildTarget

namespace UniStorm.Utility
{
    [InitializeOnLoad]
    public class UniStormDefines
    {
        const string UniStormDefinesString = "UNISTORM_PRESENT";

        static UniStormDefines()
        {
            InitializeUniStormDefines();
        }

        static void InitializeUniStormDefines()
        {
            //Get the selected build target group
            var buildTargetGroup = EditorUserBuildSettings.selectedBuildTargetGroup;

            //Convert BuildTargetGroup to NamedBuildTarget
            var namedBuildTarget = NamedBuildTarget.FromBuildTargetGroup(buildTargetGroup);

            //Get the current scripting define symbols
            string scriptingDefines = PlayerSettings.GetScriptingDefineSymbols(namedBuildTarget);

            //Check if the UniStorm define symbol is already present
            if (!scriptingDefines.Contains(UniStormDefinesString))
            {
                if (string.IsNullOrEmpty(scriptingDefines))
                {
                    //If there are no existing symbols, set the UniStorm define symbol
                    PlayerSettings.SetScriptingDefineSymbols(namedBuildTarget, UniStormDefinesString);
                }
                else
                {
                    //Ensure the existing symbols end with a semicolon
                    if (scriptingDefines[scriptingDefines.Length - 1] != ';')
                    {
                        scriptingDefines += ';';
                    }

                    //Add the UniStorm define symbol
                    scriptingDefines += UniStormDefinesString;

                    //Set the updated scripting define symbols
                    PlayerSettings.SetScriptingDefineSymbols(namedBuildTarget, scriptingDefines);
                }
            }
        }
    }
}
