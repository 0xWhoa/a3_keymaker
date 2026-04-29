// a3_keymaker extractor — captures every Arma 3 keybinding from the
// running session and emits a combined dump to the clipboard.
//
// Five sections, all concatenated into one payload:
//   1. vanilla_categories  — UI walk of OPTIONS > CONTROLS (labels per category)
//   2. mappings            — union of every CfgDefaultKeysPresets >> Mappings entry
//   3. vanilla_engine      — actionKeysNames for the 446 engine IDs from the BIS wiki
//   4. cfg_user_actions    — every CfgUserActions class (catches mod actions with no preset default)
//   5. addons              — UI walk of CONFIGURE ADDONS (CBA-registered mod bindings)
//
// Usage:
//   1. Open Debug Console, paste, LOCAL EXEC.
//   2. Open OPTIONS > CONTROLS — script auto-walks all categories (~12s).
//   3. Click CONFIGURE ADDONS — script auto-walks all addons (~25s).
//   4. When the cycling stops, cancel the dialog and paste your clipboard.
//
// On success the clipboard holds the dump (starts with A3KM_OK).
// On failure or timeout the clipboard is left untouched.

[] spawn {
    // ──────────────────────────────────────────────────────────────────
    // Phase 1: wait for vanilla Controls dialog
    // ──────────────────────────────────────────────────────────────────
    private _catCtrl = controlNull;
    private _actCtrl = controlNull;
    private _addonsList = controlNull;
    private _disp = displayNull;
    private _waited = 0;

    private _findControls = {
        _catCtrl = controlNull;
        _actCtrl = controlNull;
        _addonsList = controlNull;
        {
            private _d = _x;
            {
                switch (ctrlClassName _x) do {
                    case "CA_ControlsPage": { _catCtrl = _x; _disp = _d };
                    case "CA_ValueKeys":   { _actCtrl = _x };
                    case "AddonsList":     { _addonsList = _x };
                };
            } forEach allControls _d;
        } forEach allDisplays;
    };

    while { (isNull _catCtrl || lbSize _catCtrl < 1) && _waited < 300 } do {
        call _findControls;
        if (isNull _catCtrl || lbSize _catCtrl < 1) then {
            uiSleep 0.5;
            _waited = _waited + 0.5;
        };
    };

    if (isNull _catCtrl || isNull _actCtrl) exitWith {};

    // ──────────────────────────────────────────────────────────────────
    // Phase 2: walk every vanilla category, capture labels
    // ──────────────────────────────────────────────────────────────────
    private _vanillaCategories = [];
    private _catCount = lbSize _catCtrl;

    for "_i" from 0 to (_catCount - 1) do {
        private _catName = _catCtrl lbText _i;
        private _catData = _catCtrl lbData _i;

        // Skip the "=== Mods ===" separator (lbData empty). Selecting it
        // doesn't repopulate the action list, so we'd dump stale data.
        if (_catData == "") then {
            _vanillaCategories pushBack [_i, _catName, _catData, 0, []];
        } else {
            _catCtrl lbSetCurSel _i;
            uiSleep 0.35;

            private _actCount = lbSize _actCtrl;
            private _rows = [];
            for "_j" from 0 to (_actCount - 1) do {
                _rows pushBack [_j, _actCtrl lbText _j, _actCtrl lbData _j];
            };

            _vanillaCategories pushBack [_i, _catName, _catData, _actCount, _rows];
        };
    };

    // ──────────────────────────────────────────────────────────────────
    // Phase 3: union Mappings across every CfgDefaultKeysPresets sibling.
    // Dedupe by id; record which preset(s) each id came from.
    // ──────────────────────────────────────────────────────────────────
    private _presets = configFile >> "CfgDefaultKeysPresets";
    private _seen = [];        // parallel to _mappings, for dedupe
    private _mappings = [];

    if (isClass _presets) then {
        for "_p" from 0 to ((count _presets) - 1) do {
            private _preset = _presets select _p;
            if (isClass _preset) then {
                private _presetName = configName _preset;
                private _maps = _preset >> "Mappings";
                if (isClass _maps) then {
                    for "_i" from 0 to ((count _maps) - 1) do {
                        private _e = _maps select _i;
                        private _id = configName _e;
                        private _idx = _seen find _id;
                        if (_idx < 0) then {
                            _seen pushBack _id;
                            _mappings pushBack [_id, actionKeysNames _id, [_presetName]];
                        } else {
                            ((_mappings select _idx) select 2) pushBack _presetName;
                        };
                    };
                };
            };
        };
    };

    // ──────────────────────────────────────────────────────────────────
    // Phase 3.5: vanilla engine actions via actionKeysNames.
    // The 446 IDs come from https://community.bistudio.com/wiki/inputAction/actions
    // (the wiki also provides each id's category + label — see
    // data/vanilla_actions.json). actionKeysNames returns the current
    // binding ("" if unbound). Duplicate IDs across categories are
    // harmless — results are identical.
    // ──────────────────────────────────────────────────────────────────
    private _vanillaActionIds = [
        "gear", "showMap", "hideMap", "diary", "tasks", "MiniMap",
        "MiniMapToggle", "uavView", "uavViewToggle", "pilotCamera", "openDlcScreen", "compass",
        "compassToggle", "watch", "watchToggle", "ListLeftVehicleDisplay", "ListRightVehicleDisplay", "ListPrevLeftVehicleDisplay",
        "ListPrevRightVehicleDisplay", "CloseLeftVehicleDisplay", "CloseRightVehicleDisplay", "NextModeLeftVehicleDisplay", "NextModeRightVehicleDisplay", "nightVision",
        "TransportNightVision", "binocular", "headlights", "prevAction", "nextAction", "Action",
        "ActionContext", "ActionInMap", "navigateMenu", "closeContext", "LiteUnitInfoToggle", "help",
        "engineToggle", "vehicleTurbo", "GetOut", "Eject", "swapGunner", "teamSwitch",
        "teamSwitchPrev", "teamSwitchNext", "timeDec", "timeInc", "copyVersion", "ingamePause",
        "defaultAction", "fire", "reloadMagazine", "SwitchPrimary", "SwitchHandgun", "SwitchSecondary",
        "SwitchWeaponGrp1", "SwitchWeaponGrp2", "SwitchWeaponGrp3", "SwitchWeaponGrp4", "nextWeapon", "prevWeapon",
        "switchWeapon", "handgun", "optics", "opticsTemp", "opticsMode", "holdBreath",
        "deployWeaponAuto", "tempRaiseWeapon", "toggleRaiseWeapon", "throw", "cycleThrownItems", "zeroingUp",
        "zeroingDown", "gunElevUp", "gunElevDown", "gunElevSlow", "gunElevAuto", "ActiveSensorsToggle",
        "lockTarget", "lockTargetToggle", "revealTarget", "lockTargets", "lockEmptyTargets", "vehLockTargets",
        "vehLockEmptyTargets", "vehLockTurretView", "switchGunnerWeapon", "heliManualFire", "launchCM", "nextCM",
        "AimUp", "AimDown", "AimLeft", "AimRight", "AimHeadUp", "AimHeadDown",
        "AimHeadLeft", "AimHeadRight", "personView", "tacticalView", "zoomTemp", "lookAround",
        "commandWatch", "lookAroundToggle", "lookLeftUp", "lookUp", "lookRightUp", "lookLeft",
        "lookCenter", "lookRight", "lookLeftDown", "lookDown", "lookRightDown", "zoomIn",
        "zoomInToggle", "zoomOut", "zoomOutToggle", "lookShiftUp", "lookShiftDown", "lookShiftForward",
        "lookShiftLeft", "lookShiftCenter", "lookShiftRight", "lookShiftBack", "lookRollLeft", "lookRollRight",
        "lookLeftCont", "lookRightCont", "lookDownCont", "lookUpCont", "zoomContIn", "zoomContOut",
        "lookShiftLeftCont", "lookShiftRightCont", "lookShiftUpCont", "lookShiftDownCont", "lookShiftForwardCont", "lookShiftBackCont",
        "lookRollLeftCont", "lookRollRightCont", "turretElevationUp", "turretElevationDown", "selectAll", "switchCommand",
        "SelectGroupUnit1", "SelectGroupUnit2", "SelectGroupUnit3", "SelectGroupUnit4", "SelectGroupUnit5", "SelectGroupUnit6",
        "SelectGroupUnit7", "SelectGroupUnit8", "SelectGroupUnit9", "SelectGroupUnit0", "GroupPagePrev", "GroupPageNext",
        "SetTeamRed", "SetTeamGreen", "SetTeamBlue", "SetTeamYellow", "SetTeamWhite", "SelectTeamRed",
        "SelectTeamGreen", "SelectTeamBlue", "SelectTeamYellow", "SelectTeamWhite", "CommandingMenu1", "CommandingMenu2",
        "CommandingMenu3", "CommandingMenu4", "CommandingMenu5", "CommandingMenu6", "CommandingMenu7", "CommandingMenu8",
        "CommandingMenu9", "CommandingMenu0", "CommandingMenuSelect1", "CommandingMenuSelect2", "CommandingMenuSelect3", "CommandingMenuSelect4",
        "CommandingMenuSelect5", "CommandingMenuSelect6", "CommandingMenuSelect7", "CommandingMenuSelect8", "CommandingMenuSelect9", "CommandingMenuSelect0",
        "commandWatch", "commandLeft", "commandRight", "commandForward", "commandBack", "commandFast",
        "commandSlow", "networkStats", "networkPlayers", "prevChannel", "nextChannel", "chat",
        "pushToTalk", "voiceOverNet", "PushToTalkAll", "PushToTalkSide", "PushToTalkCommand", "PushToTalkGroup",
        "PushToTalkVehicle", "PushToTalkDirect", "TacticalPing", "MoveForward", "MoveBack", "TurnLeft",
        "TurnRight", "MoveFastForward", "MoveSlowForward", "turbo", "TurboToggle", "MoveLeft",
        "MoveRight", "TactTemp", "TactToggle", "TactShort", "WalkRunTemp", "WalkRunToggle",
        "AdjustUp", "AdjustDown", "AdjustLeft", "AdjustRight", "Stand", "Crouch",
        "Prone", "MoveUp", "MoveDown", "SwimUp", "SwimDown", "EvasiveLeft",
        "EvasiveRight", "LeanLeft", "LeanLeftToggle", "LeanRight", "LeanRightToggle", "GetOver",
        "Salute", "SitDown", "CarForward", "CarBack", "CarLeft", "CarRight",
        "CarLinearLeft", "CarLinearRight", "CarFastForward", "CarSlowForward", "CarHandBrake", "CarWheelLeft",
        "CarWheelRight", "CarAimUp", "CarAimDown", "CarAimLeft", "CarAimRight", "TurnIn",
        "TurnOut", "HeliCyclicForward", "HeliCyclicBack", "HeliCyclicLeft", "HeliCyclicRight", "HeliCollectiveRaise",
        "HeliCollectiveLower", "HeliRudderLeft", "HeliRudderRight", "HeliLeft", "HeliRight", "AutoHover",
        "AutoHoverCancel", "LandGear", "LandGearUp", "HeliCollectiveRaiseCont", "HeliCollectiveLowerCont", "HeliWheelsBrake",
        "HelicopterTrimOn", "HelicopterTrimOff", "HeliTrimLeft", "HeliTrimRight", "HeliTrimForward", "HeliTrimBackward",
        "HeliTrimRudderLeft", "HeliTrimRudderRight", "HeliRopeAction", "HeliSlingLoadManager", "HeliForward", "HeliBack",
        "AirBankLeft", "AirBankRight", "HeliFastForward", "HeliUp", "HeliDown", "HeliThrottlePos",
        "AirPlaneBrake", "HeliRudderLeft", "HeliRudderRight", "HeliLeft", "HeliRight", "vtolVectoring",
        "vtolVectoringCancel", "LandGear", "LandGearUp", "FlapsDown", "FlapsUp", "HeliThrottleNeg",
        "submarineUp", "submarineDown", "submarineLeft", "submarineRight", "submarineForward", "submarineBack",
        "submarineCyclicForward", "submarineCyclicBack", "BuldSwitchCamera", "BuldFreeLook", "BuldSelect", "BuldResetCamera",
        "BuldMagnetizePoints", "BuldMagnetizePlanes", "BuldMagnetizeYFixed", "BuldTerrainRaise1m", "BuldTerrainRaise10cm", "BuldTerrainLower1m",
        "BuldTerrainLower10cm", "BuldTerrainRaise5m", "BuldTerrainRaise50cm", "BuldTerrainLower5m", "BuldTerrainLower50cm", "BuldTerrainShowNode",
        "BuldSelectionType", "BuldLeft", "BuldRight", "BuldForward", "BuldBack", "BuldMoveLeft",
        "BuldMoveRight", "BuldMoveForward", "BuldMoveBack", "BuldTurbo", "BuldUp", "BuldDown",
        "BuldLookLeft", "BuldLookRight", "BuldLookUp", "BuldLookDown", "BuldZoomIn", "BuldZoomOut",
        "BuldTextureInfo", "BuldBrushRatio", "BuldBrushStrength", "BuldBrushSmooth", "BuldBrushRandomize", "BuldBrushSetHeight",
        "BuldBrushOuter", "BuldUndo", "BuldRedo", "BuldCreateObj", "BuldDuplicateSel", "BuldRemoveSel",
        "BuldRotateSelX", "BuldRotateSelZ", "BuldScaleSel", "BuldElevateSel", "BuldKeepAbsoluteElevationSel", "BuldClearAllElevationLocks",
        "SeagullUp", "SeagullDown", "SeagullForward", "SeagullBack", "SeagullFastForward", "cheat1",
        "cheat2", "User1", "User2", "User3", "User4", "User5",
        "User6", "User7", "User8", "User9", "User10", "User11",
        "User12", "User13", "User14", "User15", "User16", "User17",
        "User18", "User19", "User20", "curatorInterface", "curatorRotateMod", "curatorMoveY",
        "curatorDelete", "curatorDestroy", "curatorGetOut", "curatorContentWaypoint", "curatorMoveCamTo", "curatorLockCameraTo",
        "curatorLevelObject", "curatorGroupMod", "curatorMultipleMod", "CuratorCollapseParent", "curatorNightvision", "curatorPersonView",
        "curatorPingView", "curatorToggleInterface", "curatorToggleEdit", "curatorToggleCreate", "curatorMapTextures", "curatorCompass",
        "curatorWatch", "cameraMoveForward", "cameraMoveBackward", "cameraMoveLeft", "cameraMoveRight", "cameraMoveUp",
        "cameraMoveDown", "cameraMoveTurbo1", "cameraMoveTurbo2", "cameraZoomIn", "cameraZoomOut", "cameraLookUp",
        "cameraLookDown", "cameraLookLeft", "cameraLookRight", "cameraReset", "cameraTarget", "cameraVisionMode",
        "cameraFlashlight", "cameraInterface", "editorCameraMoveForward", "editorCameraMoveBackward", "editorCameraMoveLeft", "editorCameraMoveRight",
        "editorCameraMoveUp", "editorCameraMoveDown", "editorCameraMoveTurbo", "editorCameraLookUp", "editorCameraLookDown", "editorCameraLookLeft",
        "editorCameraLookRight", "editorCameraReset"
    ];

    private _vanillaEngine = _vanillaActionIds apply { [_x, actionKeysNames _x] };

    // ──────────────────────────────────────────────────────────────────
    // Phase 3.6: walk CfgUserActions. Catches old-style mod actions that
    // ship unbound by default (no entry in any preset's Mappings) but
    // that the user has since bound. Each entry is
    // [action_id, displayName, key_text]; displayName is `localize`-
    // resolved when it begins with "$" so it matches the UI label.
    // ──────────────────────────────────────────────────────────────────
    private _userActionsCfg = "true" configClasses (configFile >> "CfgUserActions");
    private _cfgUserActions = [];
    {
        private _id = configName _x;
        private _dn = getText (_x >> "displayName");
        if (_dn != "" && {(_dn select [0,1]) == "$"}) then { _dn = localize _dn };
        _cfgUserActions pushBack [_id, _dn, actionKeysNames _id];
    } forEach _userActionsCfg;

    // ──────────────────────────────────────────────────────────────────
    // Phase 4: wait for AddonsList to become visible (user clicks
    // CONFIGURE ADDONS). AddonsList exists in vanilla view too but is
    // hidden, so use ctrlShown as the gate.
    // ──────────────────────────────────────────────────────────────────
    _waited = 0;
    while { (isNull _addonsList || !ctrlShown _addonsList) && _waited < 300 } do {
        if (isNull _addonsList) then { call _findControls };
        if (isNull _addonsList || !ctrlShown _addonsList) then {
            uiSleep 0.5;
            _waited = _waited + 0.5;
        };
    };

    private _addonResult = [];
    private _addonsTimedOut = false;

    if (isNull _addonsList || !ctrlShown _addonsList) then {
        _addonsTimedOut = true;
    } else {
        // ──────────────────────────────────────────────────────────────
        // Phase 5: walk every addon
        // ──────────────────────────────────────────────────────────────
        private _addonCount = lbSize _addonsList;
        for "_i" from 0 to (_addonCount - 1) do {
            private _addonName = _addonsList lbText _i;
            private _addonData = _addonsList lbData _i;
            _addonsList lbSetCurSel _i;
            uiSleep 0.7; // CBA needs time to rebuild per-row controls

            private _labels = [];
            private _keys = [];
            {
                private _c = _x;
                if (ctrlClassName _c == "EditButton"  && ctrlIDC _c == 9002) then {
                    _labels pushBack ctrlText _c;
                };
                if (ctrlClassName _c == "AssignedKey" && ctrlIDC _c == 9003) then {
                    _keys pushBack ctrlText _c;
                };
            } forEach allControls _disp;

            private _bindings = [];
            private _pairCount = (count _labels) min (count _keys);
            for "_j" from 0 to (_pairCount - 1) do {
                _bindings pushBack [_labels select _j, _keys select _j];
            };

            _addonResult pushBack [_i, _addonName, _addonData, count _bindings, _bindings];
        };
    };

    // ──────────────────────────────────────────────────────────────────
    // Phase 6: emit combined payload
    // ──────────────────────────────────────────────────────────────────
    private _status = if (_addonsTimedOut) then { "A3KM_OK_NO_ADDONS" } else { "A3KM_OK" };

    copyToClipboard format [
        "%1%2vanilla_categories=%3%2mappings=%4%2vanilla_engine=%5%2cfg_user_actions=%6%2addons=%7",
        _status,
        endl,
        str _vanillaCategories,
        str _mappings,
        str _vanillaEngine,
        str _cfgUserActions,
        str _addonResult
    ];
};
