print("[Expedition33RPC] Discord Rich Presence Bridge Mod Loaded! (High Performance Mode)\n")

local temp_dir = os.getenv("TEMP") or "C:\\Windows\\Temp"
local status_path = temp_dir .. "\\expedition33_status.json"
local tmp_path = status_path .. ".tmp"

local current_combat_state = false
local current_enemy_name = ""
local current_enemies = {}
local current_tower_floor = nil
local current_tower_trial = nil
local current_zone = ""
local current_checkpoint = ""
local tick_counter = 0

local current_raw_zone = ""
local current_raw_level = ""
local current_world_path = ""

local function clean_enemy_bp_name(raw)
    if not raw or raw == "" then return "" end

    local name = raw
    name = string.gsub(name, "_C_%d+", "")
    name = string.gsub(name, "_C$", "")
    name = string.gsub(name, "_%d+$", "")

    local prefixes = {
        "BP_Enemy_Battle_",
        "BP_EnemyBattle_",
        "BP_jRPG_EnemyBattle_",
        "BP_jRPG_EnemyWorld_",
        "BP_jRPG_Enemy_",
        "BP_jRPG_Boss_",
        "BP_EnemyWorld_",
        "BP_Enemy_",
        "BP_Boss_",
        "BP_Minion_",
        "BP_",
        "Default__",
    }
    for _, p in ipairs(prefixes) do
        if string.sub(name, 1, #p) == p then
            name = string.sub(name, #p + 1)
            break
        end
    end

    name = string.gsub(name, "_[A-Za-z]$", "")
    name = string.gsub(name, "_%d+$", "")
    name = string.gsub(name, "_", " ")
    name = string.gsub(name, "(%l)(%u)", "%1 %2")
    name = string.gsub(name, "(%u)(%u%l)", "%1 %2")
    name = string.gsub(name, "Chromatic", "Alpha")
    name = string.gsub(name, "chromatic", "Alpha")

    return (string.match(name, "^%s*(.-)%s*$") or name)
end

local function clean_level_name(raw)
    if not raw or raw == "" then return "" end

    local name = raw
    name = string.gsub(name, "_C$", "")
    name = string.gsub(name, "_%d+$", "")

    local prefixes = {
        "Level_Side_",
        "Level_Main_",
        "Level_Small_",
        "Level_WorldMap_",
        "SideLevel_",
        "MainLevel_",
        "SmallLevel_",
        "Level_",
    }
    for _, p in ipairs(prefixes) do
        if string.sub(name, 1, #p) == p then
            name = string.sub(name, #p + 1)
            break
        end
    end

    name = string.gsub(name, "_V%d+$", "")
    name = string.gsub(name, "_", " ")
    name = string.gsub(name, "(%l)(%u)", "%1 %2")
    name = string.gsub(name, "(%u)(%u%l)", "%1 %2")
    name = string.match(name, "^%s*(.-)%s*$") or name
    if name == "Main" or string.find(string.lower(raw), "worldmap") then
        return "The Continent"
    end
    if string.find(string.lower(raw), "mainmenu") then
        return "Level_MainMenu"
    end
    return name
end

local function format_enemy_summary(enemy_list)
    if not enemy_list or #enemy_list == 0 then
        return ""
    end

    local counts = {}
    local order = {}
    for _, name in ipairs(enemy_list) do
        if name and name ~= "" then
            if not counts[name] then
                counts[name] = 0
                table.insert(order, name)
            end
            counts[name] = counts[name] + 1
        end
    end

    if #order == 0 then
        return ""
    end

    local parts = {}
    for _, name in ipairs(order) do
        local c = counts[name]
        if c > 1 then
            table.insert(parts, string.format("%s x%d", name, c))
        else
            table.insert(parts, name)
        end
    end

    local summary = table.concat(parts, ", ")
    if #summary > 50 then
        if #order > 1 then
            local first = parts[1]
            local remaining = 0
            for i = 2, #order do
                remaining = remaining + counts[order[i]]
            end
            summary = string.format("%s (+%d)", first, remaining)
        else
            summary = string.sub(summary, 1, 47) .. "..."
        end
    end

    return summary
end

local function json_escape(s)
    if not s then return "" end
    s = tostring(s)
    s = string.gsub(s, "\\", "\\\\")
    s = string.gsub(s, '"', '\\"')
    s = string.gsub(s, "\b", "\\b")
    s = string.gsub(s, "\f", "\\f")
    s = string.gsub(s, "\n", "\\n")
    s = string.gsub(s, "\r", "\\r")
    s = string.gsub(s, "\t", "\\t")
    s = string.gsub(s, "[%z\1-\31]", function(c)
        return string.format("\\u%04x", string.byte(c))
    end)
    return s
end

local function write_status(in_combat, enemy_name, zone, checkpoint, enemies, tower_floor, tower_trial, raw_zone_in, raw_level_in, world_path_in)
    enemy_name = enemy_name or current_enemy_name or ""
    zone = zone or current_zone or ""
    enemies = enemies or current_enemies or {}
    local raw_z = raw_zone_in or current_raw_zone or zone or ""
    local raw_l = raw_level_in or current_raw_level or ""
    local w_path = world_path_in or current_world_path or ""
    if tower_floor == nil then tower_floor = current_tower_floor end
    if tower_trial == nil then tower_trial = current_tower_trial end

    local is_continent = (zone == "The Continent" or string.find(string.lower(zone), "continent"))
    local is_menu = (zone == "Level_MainMenu" or string.find(string.lower(zone), "mainmenu") or (raw_z ~= "" and string.find(string.lower(raw_z), "mainmenu")))

    if is_continent or is_menu then
        checkpoint = ""
        current_checkpoint = ""
    else
        if checkpoint == nil then
            checkpoint = current_checkpoint or ""
        end
    end

    local escaped_enemy = json_escape(enemy_name)
    local escaped_zone = json_escape(zone)
    local escaped_raw_zone = json_escape(raw_z)
    local escaped_raw_level = json_escape(raw_l)
    local escaped_world_path = json_escape(w_path)
    local escaped_checkpoint = json_escape(checkpoint)

    local enemy_items = {}
    for _, en in ipairs(enemies) do
        if en and en ~= "" then
            table.insert(enemy_items, string.format('"%s"', json_escape(en)))
        end
    end
    local enemies_json = "[" .. table.concat(enemy_items, ", ") .. "]"

    local floor_json = "null"
    if type(tower_floor) == "number" then
        floor_json = string.format("%d", tower_floor)
    end

    local trial_json = "null"
    if type(tower_trial) == "string" and tower_trial ~= "" then
        trial_json = string.format('"%s"', json_escape(tower_trial))
    elseif type(tower_trial) == "number" then
        trial_json = string.format("%d", tower_trial)
    elseif type(tower_trial) == "table" and tower_trial[1] and tower_trial[2] then
        trial_json = string.format("[%d, %d]", tower_trial[1], tower_trial[2])
    end

    local payload = string.format(
        '{"in_combat": %s, "enemy_name": "%s", "enemies": %s, "zone": "%s", "raw_zone": "%s", "raw_level": "%s", "world_path": "%s", "checkpoint": "%s", "floor": %s, "tower_floor": %s, "tower_trial": %s, "timestamp": %d}\n',
        in_combat and "true" or "false",
        escaped_enemy,
        enemies_json,
        escaped_zone,
        escaped_raw_zone,
        escaped_raw_level,
        escaped_world_path,
        escaped_checkpoint,
        floor_json,
        floor_json,
        trial_json,
        os.time()
    )

    local dst = io.open(status_path, "wb")
    if dst then
        dst:write(payload)
        dst:flush()
        dst:close()
        return
    end

    local f = io.open(tmp_path, "wb")
    if f then
        f:write(payload)
        f:flush()
        f:close()

        local renamed = false
        for _ = 1, 3 do
            os.remove(status_path)
            if os.rename(tmp_path, status_path) then
                renamed = true
                break
            end
        end

        if not renamed then
            os.remove(tmp_path)
        end
    end
end

-- Fast O(1) property check on HUD widget
local function scan_widget_text(w)
    if not w or not w:IsValid() then return nil end

    local candidate_props = {
        "LevelName", "Text_LevelName", "TextBlock_LevelName",
        "LevelTitle", "Text_LevelTitle", "TextBlock_LevelTitle",
        "ZoneName", "Text_ZoneName", "CurrentLevel", "LevelText",
        "Title", "Text_Title", "Name", "Text_Name"
    }
    for _, pname in ipairs(candidate_props) do
        local ok, val = pcall(function() return w[pname] end)
        if ok and val then
            local ok_gt, txt = pcall(function() return val:GetText():ToString() end)
            if ok_gt and txt and txt ~= "" and txt ~= "None" and not string.find(txt, "<") and #txt > 1 and #txt < 60 then
                return txt
            end
            local ok_ts, s = pcall(function() return val:ToString() end)
            if ok_ts and s and s ~= "" and s ~= "None" and not string.find(s, "<") and #s > 1 and #s < 60 then
                if not string.find(s, "/") and not string.find(s, "BP_") and not string.find(s, "_C") then
                    return s
                end
            end
        end
    end
    return nil
end

-- Ultra-lightweight Zone resolution on Game Thread (0ms overhead, zero stutter)
local function resolve_dynamic_screen_zone()
    local zone_found = nil
    local raw_level_found = ""
    local world_path_found = ""

    -- 1. Fast path: check single active announcement HUD widget if visible (FindFirstOf only)
    local ann = nil
    pcall(function() ann = FindFirstOf("WBP_HUD_LevelNameAnnounce_C") end)
    if ann and ann:IsValid() then
        local txt = scan_widget_text(ann)
        if txt and txt ~= "" then
            zone_found = txt
        end
    end

    -- 2. Fast O(1) query of UWorld and GetCurrentLevelName
    pcall(function()
        local world = nil
        local gi = FindFirstOf("GameInstance")
        if gi and gi:IsValid() then
            local ok_w, w = pcall(function() return gi:GetWorld() end)
            if ok_w and w and w:IsValid() then world = w end
        end
        if not world then
            local pc = FindFirstOf("PlayerController")
            if pc and pc:IsValid() then
                local ok_w, w = pcall(function() return pc:GetWorld() end)
                if ok_w and w and w:IsValid() then world = w end
            end
        end

        if world and world:IsValid() then
            local ok_stat, statics = pcall(function() return StaticFindObject("/Script/Engine.Default__GameplayStatics") end)
            if ok_stat and statics and statics:IsValid() and type(statics.GetCurrentLevelName) == "function" then
                local lvl_stripped = statics:GetCurrentLevelName(world, true)
                if lvl_stripped then
                    local s = lvl_stripped:ToString()
                    if s and s ~= "" and s ~= "None" then
                        raw_level_found = s
                    end
                end
            end

            if raw_level_found == "" then
                local plevel = world.PersistentLevel
                if plevel and plevel:IsValid() then
                    local pouter = plevel:GetOuter()
                    if pouter and pouter:IsValid() then
                        local s = pouter:GetFName():ToString()
                        if s and s ~= "" and s ~= "None" then
                            raw_level_found = s
                        end
                    end
                end
            end
        end
    end)

    -- Check if Main Menu
    local raw_lower = string.lower(raw_level_found)
    if string.find(raw_lower, "mainmenu") or string.find(raw_lower, "bootstrap") or raw_level_found == "Map_Game_Bootstrap" then
        zone_found = "Level_MainMenu"

        local function is_widget_visible(class_name)
            local w = nil
            pcall(function() w = FindFirstOf(class_name) end)
            if w and w:IsValid() then
                local ok, vis = pcall(function() return w:IsVisible() end)
                if ok and vis then
                    return true
                end
            end
            return false
        end

        if is_widget_visible("WBP_MM_Settings_C") or is_widget_visible("WBP_Settings_C") or is_widget_visible("WBP_Settings_Options_C") then
            raw_level_found = "WBP_MM_Settings"
        elseif is_widget_visible("WBP_MM_LoadScreen_C") or is_widget_visible("WBP_MM_SaveSlot_C") or is_widget_visible("WBP_MM_BackupSavesBox_C") or is_widget_visible("WBP_MM_BackupSaveEntry_C") then
            raw_level_found = "WBP_MM_LoadScreen"
        elseif is_widget_visible("WBP_MM_NewGame_C") or is_widget_visible("WBP_NewGame_C") then
            raw_level_found = "WBP_MM_NewGame"
        elseif is_widget_visible("WBP_MM_MainMenu_C") then
            raw_level_found = "WBP_MM_MainMenu"
        elseif is_widget_visible("WBP_MM_TitleScreen_C") then
            raw_level_found = "WBP_MM_TitleScreen"
        elseif is_widget_visible("WBP_SplashScreens_Logos_C") or is_widget_visible("WBP_SplashScreen_Epilepsy_C") or is_widget_visible("WBP_SplashScreen_SaveWarning_C") then
            raw_level_found = "WBP_SplashScreens_Logos"
        end
    elseif not zone_found and raw_level_found ~= "" then
        zone_found = clean_level_name(raw_level_found)
    end

    current_raw_level = raw_level_found
    current_raw_zone = raw_level_found
    current_world_path = world_path_found

    return zone_found, raw_level_found, world_path_found
end

-- Inspect active enemies on Game Thread (only inspects the 1-5 active battle enemies)
local function inspect_active_enemies()
    local enemy_names = {}
    local bm = FindFirstOf("AC_jRPG_BattleManager_C")
    if not bm or not bm:IsValid() then return "" end
    if not bm.Enemies or not bm.Enemies:IsValid() then return "" end

    local count = bm.Enemies:GetArrayNum()
    for i = 1, count do
        pcall(function()
            local elem = bm.Enemies[i]
            local actor = elem
            if actor and type(actor.get) == "function" then
                actor = actor:get()
            end
            if actor and actor:IsValid() then
                local ename = ""
                -- 1. Try CharacterName (FText) if valid text
                pcall(function()
                    if actor.CharacterName and type(actor.CharacterName.ToString) == "function" then
                        local s = actor.CharacterName:ToString()
                        if s and s ~= "" and s ~= "None" and not string.find(s, "<") and not string.find(s, "UObject:") and not string.find(s, "0x") and #s > 1 and #s < 50 then
                            ename = s
                        end
                    end
                end)

                -- 2. Fallback to clean blueprint name (class first, then actor FName)
                if ename == "" then
                    pcall(function()
                        local cls = actor:GetClass()
                        if cls and cls:IsValid() then
                            local raw = cls:GetFName():ToString()
                            ename = clean_enemy_bp_name(raw)
                        end
                    end)
                end

                if ename == "" then
                    pcall(function()
                        local raw = actor:GetFName():ToString()
                        ename = clean_enemy_bp_name(raw)
                    end)
                end

                if ename ~= "" and ename ~= "None" and not string.find(ename, "UObject:") and not string.find(ename, "0x") then
                    ename = string.gsub(ename, "Chromatic", "Alpha")
                    ename = string.gsub(ename, "chromatic", "Alpha")
                    table.insert(enemy_names, ename)
                end
            end
        end)
    end

    return format_enemy_summary(enemy_names), enemy_names
end

-- Initialize initial status on Game Thread
ExecuteInGameThread(function()
    current_checkpoint = ""
    local z, rl, wp = resolve_dynamic_screen_zone()
    if z and z ~= "" then
        current_zone = z
        print(string.format("[Expedition33RPC] Initial Zone: '%s' (raw: '%s')\n", current_zone, rl or ""))
    end
    write_status(false, "", current_zone, "", nil, nil, nil, rl, rl, wp)
end)

-- Hook map loads to update zone immediately
RegisterLoadMapPostHook(function(Engine, World)
    ExecuteInGameThread(function()
        local z, rl, wp = resolve_dynamic_screen_zone()
        if z and z ~= "" then
            current_zone = z
            print(string.format("[Expedition33RPC] Zone on Map Load: '%s' (raw: '%s')\n", current_zone, rl or ""))
            write_status(current_combat_state, current_enemy_name, current_zone, "", nil, nil, nil, rl, rl, wp)
        end
    end)
end)

-- Periodic monitor (Async loop only checks integer array num; NEVER accesses UObject actor pointers)
LoopAsync(1000, function()
    local is_in_combat = false
    local bm = FindFirstOf("AC_jRPG_BattleManager_C")
    if bm and bm:IsValid() then
        if bm.Enemies and bm.Enemies:IsValid() then
            local count = bm.Enemies:GetArrayNum()
            if count > 0 then
                is_in_combat = true
            end
        end
    end

    if is_in_combat ~= current_combat_state then
        current_combat_state = is_in_combat
        if current_combat_state then
            print("[Expedition33RPC] Combat started! Querying enemies on Game Thread...\n")
            ExecuteInGameThread(function()
                local summary, enemies = inspect_active_enemies()
                if summary ~= "" then
                    current_enemy_name = summary
                    current_enemies = enemies or {}
                    print(string.format("[Expedition33RPC] Enemies found: '%s'\n", current_enemy_name))
                end
                write_status(true, current_enemy_name, current_zone, current_checkpoint, current_enemies, current_tower_floor, current_tower_trial, current_raw_zone, current_raw_level, current_world_path)
            end)
        else
            print("[Expedition33RPC] Combat ended!\n")
            current_enemy_name = ""
            current_enemies = {}
            write_status(false, "", current_zone, current_checkpoint, {}, current_tower_floor, current_tower_trial, current_raw_zone, current_raw_level, current_world_path)
        end
    else
        -- While in combat, periodically re-check enemies on Game Thread (every 3 seconds)
        if current_combat_state then
            tick_counter = tick_counter + 1
            if tick_counter % 3 == 0 then
                ExecuteInGameThread(function()
                    local summary, enemies = inspect_active_enemies()
                    if summary ~= "" and summary ~= current_enemy_name then
                        current_enemy_name = summary
                        current_enemies = enemies or {}
                        print(string.format("[Expedition33RPC] Enemies updated: '%s'\n", current_enemy_name))
                    end
                    write_status(true, current_enemy_name, current_zone, current_checkpoint, current_enemies, current_tower_floor, current_tower_trial, current_raw_zone, current_raw_level, current_world_path)
                end)
            else
                write_status(true, current_enemy_name, current_zone, current_checkpoint, current_enemies, current_tower_floor, current_tower_trial, current_raw_zone, current_raw_level, current_world_path)
            end
        end
    end

    -- During exploration, periodically update zone on Game Thread
    if not current_combat_state then
        tick_counter = tick_counter + 1
        if tick_counter % 2 == 0 then
            ExecuteInGameThread(function()
                local z, rl, wp = resolve_dynamic_screen_zone()
                local changed = false
                if z and z ~= "" and z ~= current_zone then
                    current_zone = z
                    changed = true
                    print(string.format("[Expedition33RPC] Zone dynamically updated to: '%s' (raw: '%s')\n", current_zone, rl or ""))
                end

                write_status(false, "", current_zone, current_checkpoint, {}, current_tower_floor, current_tower_trial, rl, rl, wp)
            end)
        else
            write_status(false, "", current_zone, current_checkpoint, {}, current_tower_floor, current_tower_trial, current_raw_zone, current_raw_level, current_world_path)
        end
    end

    return false -- repeat every 1000ms
end)
