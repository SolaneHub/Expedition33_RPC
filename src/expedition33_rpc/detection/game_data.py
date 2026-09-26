import re
import unicodedata

TARGET_PROCESS_NAMES = {
    "sandfall-win64-shipping.exe",
    "sandfall-shipping.exe",
    "expedition33_steam.exe",
    "expedition33.exe",
    "sandfall.exe",
}


def strip_accents(text: str) -> str:
    """Removes diacritics/accents from text for consistent cross-matching (e.g. 'Sirène' -> 'Sirene')."""
    if not text:
        return ""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


# Exact Endless Tower trials definition directly from official Fextralife Wiki
ENDLESS_TOWER_TRIALS = [
    # Thank You Update Super Bosses
    ("Super Boss", "Simon the Divergent Star", [["Simon the Divergent Star", "Simon"]]),
    ("Super Boss", "Clea Unleashed", [["Clea Unleashed", "Clea"]]),
    ("Super Boss", "Duollistes", [["Duollistes", "Duallistes", "Duolliste x2", "Dualliste x2"]]),
    ("Super Boss", "Chromatic Lampmaster", [["Chromatic Lampmaster"]]),
    # Stage 11
    ((11, 3), "Painted Love", [["Painted Love"]]),
    ((11, 2), None, [["Lampmaster"], ["Creation"], ["Chromatic Clair Obscur"]]),
    (
        ((11, 1)),
        None,
        [["Chromatic Moissonneuse", "Chromatic Moissoneusse"], ["Dualliste"], ["Mask Keeper"]],
    ),
    # Stage 10
    ((10, 3), None, [["Chromatic Chalier"], ["Chromatic Jar"], ["Obscur"]]),
    (
        ((10, 2)),
        None,
        [
            ["Chromatic Gold Chevaliere"],
            ["Chromatic Steel Chevaliere"],
            ["Chromatic Ceramic Chevaliere"],
        ],
    ),
    ((10, 1), None, [["Chromatic Portier"], ["Chromatic Demineur"], ["Clair"]]),
    # Stage 9
    ((9, 3), None, [["Flame Eveque"], ["Frost Eveque"], ["Chromatic Danseuse"]]),
    ((9, 2), None, [["Thunder Eveque"], ["Chromatic Demineur"], ["Stalact"]]),
    ((9, 1), None, [["Eveque"], ["Chromatic Cultist"], ["Luster"]]),
    # Stage 8
    ((8, 3), None, [["Chromatic Sakapatate"], ["Boucheclier", "Bouchelier"], ["Gault"]]),
    ((8, 2), None, [["Glaise"], ["Moissonneuse"], ["Hexga"]]),
    ((8, 1), None, [["Bruler"], ["Chapelier"], ["Benisseur"]]),
    # Stage 7
    ((7, 3), None, [["Gold Chevaliere"], ["Steel Chevaliere"], ["Ceramic Chevaliere"]]),
    ((7, 2), None, [["Portier"], ["Petank"], ["Chapelier"]]),
    ((7, 1), None, [["Luster"], ["Sakapatate"], ["Orphelin"]]),
    # Stage 6
    ((6, 3), None, [["Demineur"], ["Benisseur"], ["Troubadour"]]),
    ((6, 2), None, [["Boucheclier", "Bouchelier"], ["Gross Tete", "Grosstete"], ["Echassier"]]),
    ((6, 1), None, [["Greatsword Cultist"], ["Reaper Cultist"], ["Cultist"]]),
    # Stage 5
    ((5, 3), None, [["Chromatic Bourgeon"], ["Volester"], ["Flan"]]),
    ((5, 2), None, [["Chromatic Greatsword Cultist"], ["Orphelin"], ["Sapling"]]),
    ((5, 1), None, [["Chromatic Veilleur"], ["Bruler"], ["Orphelin"]]),
    # Stage 4
    ((4, 3), None, [["Chromatic Echassier"], ["Moissonneuse"], ["Catapult Sakapatate"]]),
    ((4, 2), None, [["Bourgeon"], ["Jar"], ["Rocher"]]),
    ((4, 1), None, [["Chromatic Orphelin"], ["Ceramic Chevaliere"], ["Cruler"]]),
    # Stage 3
    ((3, 3), None, [["Chromatic Abbest"], ["Goblu"], ["Troubadour"]]),
    ((3, 2), None, [["Chromatic Benisseur"], ["Boucheclier", "Bouchelier"], ["Clair"]]),
    ((3, 1), None, [["Gault"], ["Hexga"], ["Cruler"]]),
    # Stage 2
    ((2, 3), None, [["Lampmaster"], ["Potier"], ["Echassier"]]),
    ((2, 2), None, [["Reaper Cultist"], ["Ballet"], ["Chapelier"]]),
    ((2, 1), None, [["Demineur"], ["Benisseur"], ["Volester"]]),
    # Stage 1
    ((1, 3), None, [["Dualliste"], ["Luster"], ["Troubadour"]]),
    (
        ((1, 2)),
        None,
        [["Potier"], ["Steel Chevaliere", "Ceramic Chevaliere"], ["Greatsword Cultist"]],
    ),
    ((1, 1), None, [["Gault"], ["Luster"], ["Ramasseur"]]),
]

# Zone name overrides mapping raw internal names to official titles
ZONE_NAME_OVERRIDES_EN: dict[str, str] = {
    "goblu": "Flying Waters",
    "seacliff": "Stone Wave Cliffs",
    "sea cliff": "Stone Wave Cliffs",
    "lumiereact03": "Old Lumiere",
    "lumiere act03": "Old Lumiere",
    "lumiere act 03": "Old Lumiere",
    "lumiere act 3": "Old Lumiere",
    "cleasflyinghouse": "Flying Manor",
    "cleas flying house": "Flying Manor",
    "flyinghouse": "Flying Manor",
    "cleastower": "Endless Tower",
    "cleas tower": "Endless Tower",
    "simonarea": "The Abyss",
    "simon area": "The Abyss",
    "simon": "The Abyss",
    "thecanvas": "Painting Workshop",
    "canvas": "Painting Workshop",
    "cleaorangeforest": "Crimson Forest",
    "orangeforest": "Crimson Forest",
    "axonpath": "The Chosen Path",
    "sirenesmalllevel": "Sirene's Dress",
    "sirenedress": "Sirene's Dress",
    "esquierealcousin": "The Small Bourgeon",
    "versosdraft": "Verso's Drafts",
    "versos drafts": "Verso's Drafts",
    "monocostation": "Monoco's Station",
    "monoco": "Monoco's Station",
    "esquienest": "Esquie's Nest",
    "ancientsanctuary": "Ancient Sanctuary",
    "gestralvillage": "Gestral Village",
    "springmeadows": "Spring Meadows",
    "forgottenbattlefield": "Forgotten Battlefield",
}

ZONE_NAME_OVERRIDES_IT: dict[str, str] = {
    "goblu": "Acque Volanti",
    "flying waters": "Acque Volanti",
    "seacliff": "Scogliere dell'Onda di Pietra",
    "sea cliff": "Scogliere dell'Onda di Pietra",
    "stone wave cliffs": "Scogliere dell'Onda di Pietra",
    "lumiereact03": "Vecchia Lumière",
    "lumiere act03": "Vecchia Lumière",
    "old lumiere": "Vecchia Lumière",
    "cleasflyinghouse": "Maniero Volante",
    "cleas flying house": "Maniero Volante",
    "flyinghouse": "Maniero Volante",
    "flying manor": "Maniero Volante",
    "cleastower": "Torre Infinita",
    "cleas tower": "Torre Infinita",
    "endless tower": "Torre Infinita",
    "simonarea": "L'Abisso",
    "simon area": "L'Abisso",
    "the abyss": "L'Abisso",
    "thecanvas": "Laboratorio di Pittura",
    "painting workshop": "Laboratorio di Pittura",
    "cleaorangeforest": "Foresta Cremisi",
    "crimson forest": "Foresta Cremisi",
    "axonpath": "Il Sentiero Prescelto",
    "the chosen path": "Il Sentiero Prescelto",
    "sirenesmalllevel": "Abito di Sirène",
    "sirene's dress": "Abito di Sirène",
    "sirenedress": "Abito di Sirène",
    "esquierealcousin": "Il Piccolo Bourgeon",
    "the small bourgeon": "Il Piccolo Bourgeon",
    "versosdraft": "Bozze di Verso",
    "verso's drafts": "Bozze di Verso",
    "monocostation": "Stazione di Monoco",
    "monoco's station": "Stazione di Monoco",
    "esquienest": "Nido di Esquie",
    "esquie's nest": "Nido di Esquie",
    "ancientsanctuary": "Antico Santuario",
    "ancient sanctuary": "Antico Santuario",
    "gestralvillage": "Villaggio dei Gestral",
    "gestral village": "Villaggio dei Gestral",
    "springmeadows": "Prati Primaverili",
    "spring meadows": "Prati Primaverili",
    "forgottenbattlefield": "Campo di Battaglia Dimenticato",
    "forgotten battlefield": "Campo di Battaglia Dimenticato",
    "abbest cave": "Grotta di Abbest",
    "red woods": "Boschi Rossi",
    "hidden gestral arena": "Arena Nascosta dei Gestral",
    "esoteric ruins": "Rovine Esoteriche",
    "yellow harvest": "Raccolto Giallo",
    "dark shores": "Rive Oscure",
    "crushing cavern": "Caverna Frastornante",
    "stone quarry": "Cava di Pietra",
    "coastal cave": "Grotta Costiera",
    "frozen hearts": "Cuori Ghiacciati",
    "the carousel": "La Giostra",
    "stone wave cliffs cave": "Grotta delle Scogliere dell'Onda di Pietra",
    "falling leaves": "Foglie Cadenti",
    "sinister cave": "Grotta Sinistra",
    "renoir's drafts": "Bozze di Renoir",
    "the crows": "I Corvi",
    "dark gestral arena": "Arena Oscura dei Gestral",
    "the fountain": "La Fontana",
    "flying casino": "Casinò Volante",
    "floating cemetery": "Cimitero Galleggiante",
    "sky island": "Isola del Cielo",
    "endless night sanctuary": "Santuario della Notte Eterna",
    "sunless cliffs": "Scogliere Senza Sole",
    "the reacher": "Lo Scalatore",
    "isle of the eyes": "Isola degli Occhi",
    "the manor": "Il Maniero",
}

# Complete in-game Expedition Flag names (English)
CHECKPOINT_NAMES_EN: dict[str, str] = {
    # Generic & Common Fallbacks
    "Camp.Entry": "Campfire",
    "Camp": "Campfire",
    "Entry": "Entrance",
    "Entrance": "Entrance",
    "Plazza": "Plazza",
    "Plaza": "Central Plaza",
    "Center": "Central Plaza",
    "PlazaTeleport": "Central Plaza",
    # The Manor
    "Manor.Entrance": "Entry Hall",
    "Manor.EntryHall": "Entry Hall",
    "EntryHall": "Entry Hall",
    # Spring Meadows
    "SpringMeadows.MeadowsCorridor": "Meadows Corridor",
    "SpringMeadows.Entry": "Meadows Corridor",
    "SpringMeadows.Entrance": "Meadows Corridor",
    "MeadowsCorridor": "Meadows Corridor",
    "SpringMeadows.GrandArea": "Grand Meadow",
    "SpringMeadows.GrandMeadow": "Grand Meadow",
    "GrandArea": "Grand Meadow",
    "GrandMeadow": "Grand Meadow",
    "SpringMeadows.AbandonedCamp": "Abandoned Expeditioner Camp",
    "SpringMeadows.AbandonedExpeditionerCamp": "Abandoned Expeditioner Camp",
    "AbandonedCamp": "Abandoned Expeditioner Camp",
    "AbandonedExpeditionerCamp": "Abandoned Expeditioner Camp",
    "SpringMeadows.BlueTree": "The Indigo Tree",
    "SpringMeadows.IndigoTree": "The Indigo Tree",
    "SpringMeadows.TheIndigoTree": "The Indigo Tree",
    "SpringMeadows.Eveque": "The Indigo Tree",
    "BlueTree": "The Indigo Tree",
    "IndigoTree": "The Indigo Tree",
    "TheIndigoTree": "The Indigo Tree",
    "Eveque": "The Indigo Tree",
    # Flying Waters
    "Goblu.LimonsolHome": "Noco's Hut",
    "FlyingWaters.NocosHut": "Noco's Hut",
    "LimonsolHome": "Noco's Hut",
    "NocosHut": "Noco's Hut",
    "NocoHut": "Noco's Hut",
    "Goblu.CrulerCave": "Coral Cave",
    "FlyingWaters.CoralCave": "Coral Cave",
    "CrulerCave": "Coral Cave",
    "CoralCave": "Coral Cave",
    "Goblu.LumiereStreet": "Lumieran Streets",
    "FlyingWaters.LumieranStreets": "Lumieran Streets",
    "LumiereStreet": "Lumieran Streets",
    "LumieranStreets": "Lumieran Streets",
    "Goblu.GobluArena": "Flower Field",
    "FlyingWaters.FlowerField": "Flower Field",
    "GobluArena": "Flower Field",
    "FlowerField": "Flower Field",
    # Ancient Sanctuary
    "AncientSanctuary.Entrance": "Entrance",
    "AncientSanctuary.Entry": "Entrance",
    "AncientSanctuary.SanctuaryMaze": "Sanctuary Maze",
    "AncientSanctuary.RedForest": "Sanctuary Maze",
    "SanctuaryMaze": "Sanctuary Maze",
    "RedForest": "Sanctuary Maze",
    "AncientSanctuary.GiantBellAlley": "Giant Bell Alley",
    "AncientSanctuary.TanksArena": "Giant Bell Alley",
    "GiantBellAlley": "Giant Bell Alley",
    "TanksArena": "Giant Bell Alley",
    "AncientSanctuary.GestralTotem": "Gestral Totem",
    "GestralTotem": "Gestral Totem",
    # Gestral Village
    "GestralVillage.Entrance": "Entrance",
    "GestralVillage.Entry": "Entrance",
    "GestralVillage.GestralArena": "Gestral Arena",
    "GestralArena": "Gestral Arena",
    # Esquie's Nest
    "EsquieNest.Entrance": "Entrance",
    "EsquieNest.Entry": "Entrance",
    "EsquieNest.Francois": "Francois' Cave",
    "EsquieNest.FrancoisCave": "Francois' Cave",
    "Francois": "Francois' Cave",
    "FrancoisCave": "Francois' Cave",
    # Stone Wave Cliffs
    "SeaCliff.Entrance": "Entrance",
    "SeaCliff.Entry": "Entrance",
    "StoneWaveCliffs.Entrance": "Entrance",
    "StoneWaveCliffs.Entry": "Entrance",
    "SeaCliff.PaintressShrine": "Paintress Shrine",
    "StoneWaveCliffs.PaintressShrine": "Paintress Shrine",
    "PaintressShrine": "Paintress Shrine",
    "SeaCliff.OldFarm": "Old Farm",
    "StoneWaveCliffs.OldFarm": "Old Farm",
    "OldFarm": "Old Farm",
    "SeaCliff.TideCaverns": "Tide Caverns",
    "StoneWaveCliffs.TideCaverns": "Tide Caverns",
    "TideCaverns": "Tide Caverns",
    "SeaCliff.BasaltWaves": "Basalt Waves",
    "StoneWaveCliffs.BasaltWaves": "Basalt Waves",
    "BasaltWaves": "Basalt Waves",
    "SeaCliff.FloodedBuildings": "Flooded Buildings",
    "StoneWaveCliffs.FloodedBuildings": "Flooded Buildings",
    "FloodedBuildings": "Flooded Buildings",
    # Forgotten Battlefield
    "ForgottenBattlefield.MainGate": "Main Gate",
    "ForgottenBattlefield.Entry": "Main Gate",
    "ForgottenBattlefield.Entrance": "Main Gate",
    "MainGate": "Main Gate",
    "ForgottenBattlefield.ForgottenRuins": "Forgotten Ruins",
    "ForgottenBattlefield.FortRuins": "Forgotten Ruins",
    "ForgottenRuins": "Forgotten Ruins",
    "FortRuins": "Forgotten Ruins",
    "ForgottenBattlefield.VanguardPoint": "Vanguard Point",
    "VanguardPoint": "Vanguard Point",
    "ForgottenBattlefield.Battlefield": "Battlefield",
    "ForgottenBattlefield.DuallistArena": "Battlefield",
    "Battlefield": "Battlefield",
    "DuallistArena": "Battlefield",
    "ForgottenBattlefield.AncientBridge": "Ancient Bridge",
    "AncientBridge": "Ancient Bridge",
    # Monoco's Station
    "MonocoStation.IceCorridor": "Ice Corridor",
    "MonocoStation.Entry": "Ice Corridor",
    "MonocoStation.Entrance": "Ice Corridor",
    "IceCorridor": "Ice Corridor",
    "MonocoStation.Station": "Monoco's Station",
    "MonocoStation.MonocoStation": "Monoco's Station",
    "MonocoStation": "Monoco's Station",
    # Old Lumiere
    "LumiereAct03.Entrance": "Entrance",
    "LumiereAct03.Entry": "Entrance",
    "OldLumiere.Entrance": "Entrance",
    "OldLumiere.Entry": "Entrance",
    "LumiereAct03.RightStreet": "Right Street",
    "RightStreet": "Right Street",
    "LumiereAct03.LeftStreet": "Left Street",
    "LeftStreet": "Left Street",
    "LumiereAct03.Gardens": "Manor Gardens",
    "LumiereAct03.ManorGardens": "Manor Gardens",
    "ManorGardens": "Manor Gardens",
    "LumiereAct03.Curator": "Train Station Ruins",
    "LumiereAct03.TrainStationRuins": "Train Station Ruins",
    "TrainStationRuins": "Train Station Ruins",
    "Curator": "Train Station Ruins",
    # Visages
    "SmallLevelVisages.Entry": "Plazza",
    "Visages.Plazza": "Plazza",
    "Visages.Entry": "Plazza",
    "Visages.Entrance": "Plazza",
    "Visages.JoyVale": "Joy Vale",
    "Visages.JoyfulVale": "Joy Vale",
    "JoyVale": "Joy Vale",
    "JoyfulVale": "Joy Vale",
    "Visages.SadnessVale": "Sadness Vale",
    "SadnessVale": "Sadness Vale",
    "Visages.AngerVale": "Anger Vale",
    "AngerVale": "Anger Vale",
    "Visages.Peaks": "Peaks",
    "Peaks": "Peaks",
    # Sirene
    "Sirene.Ballet": "Dancing Classes",
    "Sirene.DancingClasses": "Dancing Classes",
    "Sirene.Entry": "Dancing Classes",
    "Sirene.Entrance": "Dancing Classes",
    "Ballet": "Dancing Classes",
    "DancingClasses": "Dancing Classes",
    "Sirene.Couturier": "Sewing Atelier",
    "Sirene.SewingAtelier": "Sewing Atelier",
    "Couturier": "Sewing Atelier",
    "SewingAtelier": "Sewing Atelier",
    "Sirene.Glissando": "Crumbling Path",
    "Sirene.CrumblingPath": "Crumbling Path",
    "CrumblingPath": "Crumbling Path",
    "Sirene.SirenArena": "Dancing Arena",
    "Sirene.DancingArena": "Dancing Arena",
    "SirenArena": "Dancing Arena",
    "DancingArena": "Dancing Arena",
    # The Monolith
    "MonolithExterior.Entry": "Entrance (Monolith)",
    "MonolithExterior.Entrance": "Entrance (Monolith)",
    "Monolith.Entrance": "Entrance (Monolith)",
    "MonolithInterior.PaintressIntro.Entry": "Entrance (Inside the Monolith)",
    "MonolithInterior.Climb.Entry": "Entrance (Inside the Monolith)",
    "MonolithInterior.Entrance": "Entrance (Inside the Monolith)",
    "Monolith.TaintedMeadows": "Tainted Meadows",
    "TaintedMeadows": "Tainted Meadows",
    "Monolith.TaintedWaters": "Tainted Waters",
    "TaintedWaters": "Tainted Waters",
    "Monolith.TaintedSanctuary": "Tainted Sanctuary",
    "TaintedSanctuary": "Tainted Sanctuary",
    "Monolith.TaintedCliffs": "Tainted Cliffs",
    "TaintedCliffs": "Tainted Cliffs",
    "Monolith.TaintedBattlefield": "Tainted Battlefield",
    "TaintedBattlefield": "Tainted Battlefield",
    "Monolith.TaintedHearts": "Tainted Hearts",
    "TaintedHearts": "Tainted Hearts",
    "Monolith.TaintedLumiere": "Tainted Lumiere",
    "TaintedLumiere": "Tainted Lumiere",
    "MonolithInterior.Climb.RenoirArena": "Tower Peak",
    "Monolith.TowerPeak": "Tower Peak",
    "RenoirArena": "Tower Peak",
    "TowerPeak": "Tower Peak",
    "MonolithExterior.Peak.Entry": "Entrance (Monolith Peak)",
    "MonolithExterior.Peak.Entrance": "Entrance (Monolith Peak)",
    "MonolithPeak.Entrance": "Entrance (Monolith Peak)",
    # Lumiere
    "Lumiere.Harbour": "Harbour",
    "Lumiere.Entry": "Harbour",
    "Lumiere.Entrance": "Harbour",
    "Harbour": "Harbour",
    "Lumiere.CentralPlaza": "Central Plaza",
    "CentralPlaza": "Central Plaza",
    "Lumiere.ShatteredAlley": "Shattered Alley",
    "ShatteredAlley": "Shattered Alley",
    "Lumiere.OperaHouse": "Opera House",
    "OperaHouse": "Opera House",
    "Lumiere.LumieresGardens": "Lumiere's Gardens",
    "Lumiere.Gardens": "Lumiere's Gardens",
    "LumieresGardens": "Lumiere's Gardens",
    "Lumiere.CrookedTowerWalkway": "Crooked Tower Walkway",
    "CrookedTowerWalkway": "Crooked Tower Walkway",
    # Single-entrance areas & caverns
    "AbbestCave.Entrance": "Entrance",
    "RedWoods.Entrance": "Entrance",
    "SmallBourgeon.Entrance": "Entrance",
    "TheSmallBourgeon.Entrance": "Entrance",
    "HiddenGestralArena.Entrance": "Entrance",
    "CrushingCavern.Entrance": "Entrance",
    "StoneQuarry.Entrance": "Entrance",
    "TheCarousel.Entrance": "Entrance",
    "Carousel.Entrance": "Entrance",
    "StoneWaveCliffsCave.Entrance": "Entrance",
    "SinisterCave.Entrance": "Entrance",
    "TheCrows.Entrance": "Entrance",
    "Crows.Entrance": "Entrance",
    "DarkGestralArena.Entrance": "Entrance",
    "TheFountain.Entrance": "Entrance",
    "Fountain.Entrance": "Entrance",
    "FlyingCasino.Entrance": "Entrance",
    "FloatingCemetery.Entrance": "Entrance",
    "SkyIsland.Entrance": "Entrance",
    "TheChosenPath.Entrance": "Entrance",
    "AxonPath.VistaEntrance": "Entrance",
    "AxonPath.SavepointEnd": "Entrance",
    "IsleOfTheEyes.Entrance": "Entrance",
    "IsleOfEyes.Entrance": "Entrance",
    "EndlessTower.Entrance": "Entrance",
    "CleasTower.Entrance": "Entrance",
    # Esoteric Ruins
    "EsotericRuins.LumiereWrecks": "Lumiere Wrecks",
    "EsotericRuins.Entry": "Lumiere Wrecks",
    "EsotericRuins.Entrance": "Lumiere Wrecks",
    "EsotericRuins": "Lumiere Wrecks",
    "LumiereWrecks": "Lumiere Wrecks",
    # Yellow Harvest
    "YellowHarvest.YellowHarvest": "Yellow Harvest",
    "YellowHarvest.Entry": "Yellow Harvest",
    "YellowHarvest.Entrance": "Yellow Harvest",
    "YellowHarvest": "Yellow Harvest",
    "YellowHarvest.HarvestersHollow": "Harvester's Hollow",
    "HarvestersHollow": "Harvester's Hollow",
    "HarvesterHollow": "Harvester's Hollow",
    "YellowHarvest.YellowSpireWrecks": "Yellow Spire Wrecks",
    "YellowSpireWrecks": "Yellow Spire Wrecks",
    # Dark Shores
    "DarkShores.BloodiedBeach": "Bloodied Beach",
    "DarkShores.Entry": "Bloodied Beach",
    "DarkShores.Entrance": "Bloodied Beach",
    "DarkShores": "Bloodied Beach",
    "BloodiedBeach": "Bloodied Beach",
    # Coastal Cave
    "CoastalCave.Forge": "Forge",
    "CoastalCave.Entry": "Forge",
    "CoastalCave.Entrance": "Forge",
    "CoastalCave": "Forge",
    "Forge": "Forge",
    # Frozen Hearts
    "FrozenHearts.IceboundTrainStation": "Icebound Train Station",
    "FrozenHearts.Entry": "Icebound Train Station",
    "FrozenHearts.Entrance": "Icebound Train Station",
    "IceboundTrainStation": "Icebound Train Station",
    "FrozenHearts.GlacialFalls": "Glacial Falls",
    "GlacialFalls": "Glacial Falls",
    "FrozenHearts.IcedHeart": "Iced Heart",
    "IcedHeart": "Iced Heart",
    "FrozenHearts.IceboundTerminal": "Icebound Terminal",
    "IceboundTerminal": "Icebound Terminal",
    # Falling Leaves
    "FallingLeaves.ResinveilGrove": "Resinveil Grove",
    "FallingLeaves.Entry": "Resinveil Grove",
    "FallingLeaves.Entrance": "Resinveil Grove",
    "ResinveilGrove": "Resinveil Grove",
    "FallingLeaves.Scavenger": "Scavenger",
    "Scavenger": "Scavenger",
    # Renoir's Drafts
    "RenoirsDrafts.GoldenTree": "Golden Tree",
    "GoldenTree": "Golden Tree",
    # Crimson Forest
    "CrimsonForest.CrimsonPerch": "Crimson Perch",
    "CrimsonForest.Entry": "Crimson Perch",
    "CrimsonForest.Entrance": "Crimson Perch",
    "CleaOrangeForest.Entry": "Crimson Perch",
    "CleaOrangeForest.Entrance": "Crimson Perch",
    "CrimsonPerch": "Crimson Perch",
    "CrimsonForest.TheThreeBlades": "The Three Blades",
    "CrimsonForest.ThreeBlades": "The Three Blades",
    "TheThreeBlades": "The Three Blades",
    "ThreeBlades": "The Three Blades",
    "CleaOrangeForest.CenterPlazza": "Crimson Perch",
    # Endless Night Sanctuary
    "EndlessNightSanctuary.WarriorsRoute": "Warrior's Route",
    "WarriorsRoute": "Warrior's Route",
    "EndlessNightSanctuary.NightTotem": "Night Totem",
    "NightTotem": "Night Totem",
    # Sunless Cliffs
    "SunlessCliffs.ChromaPortal": "Chroma Portal",
    "SunlessCliffs.Entry": "Chroma Portal",
    "SunlessCliffs.Entrance": "Chroma Portal",
    "SunlessCliffs": "Chroma Portal",
    "ChromaPortal": "Chroma Portal",
    # Sirene's Dress
    "SireneDress.Entrance": "Entrance",
    "SireneSmallLevel.Entry": "Entrance",
    "SireneDress.Glissando": "Glissando",
    # The Reacher
    "TheReacher.Mountain": "Mountain",
    "Mountain": "Mountain",
    "TheReacher.LadderArea": "Ladder Area",
    "LadderArea": "Ladder Area",
    "TheReacher.FoggyArea": "Foggy Area",
    "FoggyArea": "Foggy Area",
    "TheReacher.Peak": "Peak",
    "TheReacher.Alicia": "Alicia",
    "Alicia": "Alicia",
    # The Abyss
    "TheAbyss.Simon": "Simon",
    "TheAbyss.Entry": "Simon",
    "TheAbyss.Entrance": "Simon",
    "TheAbyss": "Simon",
    "SimonArea.Abyss": "Simon",
    "SimonArea.Entry": "Simon",
    "SimonArea.Entrance": "Simon",
    "Simon": "Simon",
    # Flying Manor
    "FlyingManor.CentralPlaza": "Central Plaza",
    "CleasFlyingHouse.Center": "Central Plaza",
    # Painting Workshop
    "PaintingWorkshop.BrokenConception": "Broken Conception",
    "PaintingWorkshop.Entry": "Broken Conception",
    "PaintingWorkshop.Entrance": "Broken Conception",
    "PaintingWorkshop": "Broken Conception",
    "TheCanvas.Entry": "Broken Conception",
    "TheCanvas.Entrance": "Broken Conception",
    "BrokenConception": "Broken Conception",
    # Verso's Drafts
    "VersosDraft.OpenPlayground": "Open Playground",
    "VersosDraft.Entry": "Open Playground",
    "VersosDraft.Entrance": "Open Playground",
    "VersosDraft.OpenField": "Open Playground",
    "OpenPlayground": "Open Playground",
    "OpenField": "Open Playground",
    "VersosDraft.GestralBaths": "Gestral Baths",
    "GestralBaths": "Gestral Baths",
    "VersosDraft.CandyLand": "Candy Land",
    "CandyLand": "Candy Land",
    "VersosDraft.ReveriePath": "Reverie Path",
    "VersosDraft.GooglyEyesDoor": "Reverie Path",
    "ReveriePath": "Reverie Path",
    "GooglyEyesDoor": "Reverie Path",
    "VersosDraft.LicornapiedsStation": "Licornapieds Station",
    "LicornapiedsStation": "Licornapieds Station",
    "WorldMap.VersosDraftEntry": "Open Playground",
}

# In-game Expedition Flag names (Italian)
CHECKPOINT_NAMES_IT: dict[str, str] = {
    # Generic & Common Fallbacks
    "Camp.Entry": "Falò",
    "Camp": "Falò",
    "Entry": "Entrata",
    "Entrance": "Entrata",
    "Plazza": "Piazza",
    "Plaza": "Piazza Centrale",
    "Center": "Piazza Centrale",
    "PlazaTeleport": "Piazza Centrale",
    # The Manor
    "Manor.Entrance": "Atrio d'Ingresso",
    "Manor.EntryHall": "Atrio d'Ingresso",
    "EntryHall": "Atrio d'Ingresso",
    # Spring Meadows
    "SpringMeadows.MeadowsCorridor": "Corridoio dei Prati",
    "SpringMeadows.Entry": "Corridoio dei Prati",
    "SpringMeadows.Entrance": "Corridoio dei Prati",
    "MeadowsCorridor": "Corridoio dei Prati",
    "SpringMeadows.GrandArea": "Grande Prato",
    "SpringMeadows.GrandMeadow": "Grande Prato",
    "GrandArea": "Grande Prato",
    "GrandMeadow": "Grande Prato",
    "SpringMeadows.AbandonedCamp": "Accampamento Abbandonato",
    "SpringMeadows.AbandonedExpeditionerCamp": "Accampamento Abbandonato",
    "AbandonedCamp": "Accampamento Abbandonato",
    "AbandonedExpeditionerCamp": "Accampamento Abbandonato",
    "SpringMeadows.BlueTree": "L'Albero Indaco",
    "SpringMeadows.IndigoTree": "L'Albero Indaco",
    "SpringMeadows.TheIndigoTree": "L'Albero Indaco",
    "SpringMeadows.Eveque": "L'Albero Indaco",
    "BlueTree": "L'Albero Indaco",
    "IndigoTree": "L'Albero Indaco",
    "TheIndigoTree": "L'Albero Indaco",
    "Eveque": "L'Albero Indaco",
    # Flying Waters
    "Goblu.LimonsolHome": "Capanna di Noco",
    "FlyingWaters.NocosHut": "Capanna di Noco",
    "LimonsolHome": "Capanna di Noco",
    "NocosHut": "Capanna di Noco",
    "NocoHut": "Capanna di Noco",
    "Goblu.CrulerCave": "Caverna di Corallo",
    "FlyingWaters.CoralCave": "Caverna di Corallo",
    "CrulerCave": "Caverna di Corallo",
    "CoralCave": "Caverna di Corallo",
    "Goblu.LumiereStreet": "Strade di Lumière",
    "FlyingWaters.LumieranStreets": "Strade di Lumière",
    "LumiereStreet": "Strade di Lumière",
    "LumieranStreets": "Strade di Lumière",
    "Goblu.GobluArena": "Campo dei Fiori",
    "FlyingWaters.FlowerField": "Campo dei Fiori",
    "GobluArena": "Campo dei Fiori",
    "FlowerField": "Campo dei Fiori",
    # Ancient Sanctuary
    "AncientSanctuary.Entrance": "Entrata",
    "AncientSanctuary.Entry": "Entrata",
    "AncientSanctuary.SanctuaryMaze": "Labirinto del Santuario",
    "AncientSanctuary.RedForest": "Labirinto del Santuario",
    "SanctuaryMaze": "Labirinto del Santuario",
    "RedForest": "Labirinto del Santuario",
    "AncientSanctuary.GiantBellAlley": "Vicolo della Grande Campana",
    "AncientSanctuary.TanksArena": "Vicolo della Grande Campana",
    "GiantBellAlley": "Vicolo della Grande Campana",
    "TanksArena": "Vicolo della Grande Campana",
    "AncientSanctuary.GestralTotem": "Totem Gestral",
    "GestralTotem": "Totem Gestral",
    # Gestral Village
    "GestralVillage.Entrance": "Entrata",
    "GestralVillage.Entry": "Entrata",
    "GestralVillage.GestralArena": "Arena dei Gestral",
    "GestralArena": "Arena dei Gestral",
    # Esquie's Nest
    "EsquieNest.Entrance": "Entrata",
    "EsquieNest.Entry": "Entrata",
    "EsquieNest.Francois": "Grotta di François",
    "EsquieNest.FrancoisCave": "Grotta di François",
    "Francois": "Grotta di François",
    "FrancoisCave": "Grotta di François",
    # Stone Wave Cliffs
    "SeaCliff.Entrance": "Entrata",
    "SeaCliff.Entry": "Entrata",
    "StoneWaveCliffs.Entrance": "Entrata",
    "StoneWaveCliffs.Entry": "Entrata",
    "SeaCliff.PaintressShrine": "Santuario della Pittrice",
    "StoneWaveCliffs.PaintressShrine": "Santuario della Pittrice",
    "PaintressShrine": "Santuario della Pittrice",
    "SeaCliff.OldFarm": "Vecchia Fattoria",
    "StoneWaveCliffs.OldFarm": "Vecchia Fattoria",
    "OldFarm": "Vecchia Fattoria",
    "SeaCliff.TideCaverns": "Caverne della Marea",
    "StoneWaveCliffs.TideCaverns": "Caverne della Marea",
    "TideCaverns": "Caverne della Marea",
    "SeaCliff.BasaltWaves": "Onde di Basalto",
    "StoneWaveCliffs.BasaltWaves": "Onde di Basalto",
    "BasaltWaves": "Onde di Basalto",
    "SeaCliff.FloodedBuildings": "Edifici Sommersi",
    "StoneWaveCliffs.FloodedBuildings": "Edifici Sommersi",
    "FloodedBuildings": "Edifici Sommersi",
    # Forgotten Battlefield
    "ForgottenBattlefield.MainGate": "Cancello Principale",
    "ForgottenBattlefield.Entry": "Cancello Principale",
    "ForgottenBattlefield.Entrance": "Cancello Principale",
    "MainGate": "Cancello Principale",
    "ForgottenBattlefield.ForgottenRuins": "Rovine Dimenticate",
    "ForgottenBattlefield.FortRuins": "Rovine Dimenticate",
    "ForgottenRuins": "Rovine Dimenticate",
    "FortRuins": "Rovine Dimenticate",
    "ForgottenBattlefield.VanguardPoint": "Punto di Avanguardia",
    "VanguardPoint": "Punto di Avanguardia",
    "ForgottenBattlefield.Battlefield": "Campo di Battaglia",
    "ForgottenBattlefield.DuallistArena": "Campo di Battaglia",
    "Battlefield": "Campo di Battaglia",
    "DuallistArena": "Campo di Battaglia",
    "ForgottenBattlefield.AncientBridge": "Ponte Antico",
    "AncientBridge": "Ponte Antico",
    # Monoco's Station
    "MonocoStation.IceCorridor": "Corridoio di Ghiaccio",
    "MonocoStation.Entry": "Corridoio di Ghiaccio",
    "MonocoStation.Entrance": "Corridoio di Ghiaccio",
    "IceCorridor": "Corridoio di Ghiaccio",
    "MonocoStation.Station": "Stazione di Monoco",
    "MonocoStation.MonocoStation": "Stazione di Monoco",
    "MonocoStation": "Stazione di Monoco",
    # Old Lumiere
    "LumiereAct03.Entrance": "Entrata",
    "LumiereAct03.Entry": "Entrata",
    "OldLumiere.Entrance": "Entrata",
    "OldLumiere.Entry": "Entrata",
    "LumiereAct03.RightStreet": "Via Destra",
    "RightStreet": "Via Destra",
    "LumiereAct03.LeftStreet": "Via Sinistra",
    "LeftStreet": "Via Sinistra",
    "LumiereAct03.Gardens": "Giardini del Maniero",
    "LumiereAct03.ManorGardens": "Giardini del Maniero",
    "ManorGardens": "Giardini del Maniero",
    "LumiereAct03.Curator": "Rovine della Stazione",
    "LumiereAct03.TrainStationRuins": "Rovine della Stazione",
    "TrainStationRuins": "Rovine della Stazione",
    "Curator": "Rovine della Stazione",
    # Visages
    "SmallLevelVisages.Entry": "Piazza",
    "Visages.Plazza": "Piazza",
    "Visages.Entry": "Piazza",
    "Visages.Entrance": "Piazza",
    "Visages.JoyVale": "Valle della Gioia",
    "Visages.JoyfulVale": "Valle della Gioia",
    "JoyVale": "Valle della Gioia",
    "JoyfulVale": "Valle della Gioia",
    "Visages.SadnessVale": "Valle della Tristezza",
    "SadnessVale": "Valle della Tristezza",
    "Visages.AngerVale": "Valle della Rabbia",
    "AngerVale": "Valle della Rabbia",
    "Visages.Peaks": "Picchi",
    "Peaks": "Picchi",
    # Sirene (in-game Italian preserves official zone flag titles)
    "Sirene.Ballet": "Dancing Classes",
    "Sirene.DancingClasses": "Dancing Classes",
    "Sirene.Entry": "Dancing Classes",
    "Sirene.Entrance": "Dancing Classes",
    "Ballet": "Dancing Classes",
    "DancingClasses": "Dancing Classes",
    "Sirene.Couturier": "Sewing Atelier",
    "Sirene.SewingAtelier": "Sewing Atelier",
    "Couturier": "Sewing Atelier",
    "SewingAtelier": "Sewing Atelier",
    "Sirene.Glissando": "Crumbling Path",
    "Sirene.CrumblingPath": "Crumbling Path",
    "CrumblingPath": "Crumbling Path",
    "Sirene.SirenArena": "Dancing Arena",
    "Sirene.DancingArena": "Dancing Arena",
    "SirenArena": "Dancing Arena",
    "DancingArena": "Dancing Arena",
    # The Monolith
    "MonolithExterior.Entry": "Entrata (Monolite)",
    "MonolithExterior.Entrance": "Entrata (Monolite)",
    "Monolith.Entrance": "Entrata (Monolite)",
    "MonolithInterior.PaintressIntro.Entry": "Entrata (Dentro il Monolite)",
    "MonolithInterior.Climb.Entry": "Entrata (Dentro il Monolite)",
    "MonolithInterior.Entrance": "Entrata (Dentro il Monolite)",
    "Monolith.TaintedMeadows": "Prati Corrotti",
    "TaintedMeadows": "Prati Corrotti",
    "Monolith.TaintedWaters": "Acque Corrotte",
    "TaintedWaters": "Acque Corrotte",
    "Monolith.TaintedSanctuary": "Santuario Corrotto",
    "TaintedSanctuary": "Santuario Corrotto",
    "Monolith.TaintedCliffs": "Scogliere Corrotte",
    "TaintedCliffs": "Scogliere Corrotte",
    "Monolith.TaintedBattlefield": "Campo di Battaglia Corrotto",
    "TaintedBattlefield": "Campo di Battaglia Corrotto",
    "Monolith.TaintedHearts": "Cuori Corrotti",
    "TaintedHearts": "Cuori Corrotti",
    "Monolith.TaintedLumiere": "Lumière Corrotta",
    "TaintedLumiere": "Lumière Corrotta",
    "MonolithInterior.Climb.RenoirArena": "Cima della Torre",
    "Monolith.TowerPeak": "Cima della Torre",
    "RenoirArena": "Cima della Torre",
    "TowerPeak": "Cima della Torre",
    "MonolithExterior.Peak.Entry": "Entrata (Cima del Monolite)",
    "MonolithExterior.Peak.Entrance": "Entrata (Cima del Monolite)",
    "MonolithPeak.Entrance": "Entrata (Cima del Monolite)",
    # Lumiere
    "Lumiere.Harbour": "Porto",
    "Lumiere.Entry": "Porto",
    "Lumiere.Entrance": "Porto",
    "Harbour": "Porto",
    "Lumiere.CentralPlaza": "Piazza Centrale",
    "CentralPlaza": "Piazza Centrale",
    "Lumiere.ShatteredAlley": "Vicolo Frantumato",
    "ShatteredAlley": "Vicolo Frantumato",
    "Lumiere.OperaHouse": "Teatro dell'Opera",
    "OperaHouse": "Teatro dell'Opera",
    "Lumiere.LumieresGardens": "Giardini di Lumière",
    "Lumiere.Gardens": "Giardini di Lumière",
    "LumieresGardens": "Giardini di Lumière",
    "Lumiere.CrookedTowerWalkway": "Passerella della Torre Storta",
    "CrookedTowerWalkway": "Passerella della Torre Storta",
    # Single-entrance areas & caverns
    "AbbestCave.Entrance": "Entrata",
    "RedWoods.Entrance": "Entrata",
    "SmallBourgeon.Entrance": "Entrata",
    "TheSmallBourgeon.Entrance": "Entrata",
    "HiddenGestralArena.Entrance": "Entrata",
    "CrushingCavern.Entrance": "Entrata",
    "StoneQuarry.Entrance": "Entrata",
    "TheCarousel.Entrance": "Entrata",
    "Carousel.Entrance": "Entrata",
    "StoneWaveCliffsCave.Entrance": "Entrata",
    "SinisterCave.Entrance": "Entrata",
    "TheCrows.Entrance": "Entrata",
    "Crows.Entrance": "Entrata",
    "DarkGestralArena.Entrance": "Entrata",
    "TheFountain.Entrance": "Entrata",
    "Fountain.Entrance": "Entrata",
    "FlyingCasino.Entrance": "Entrata",
    "FloatingCemetery.Entrance": "Entrata",
    "SkyIsland.Entrance": "Entrata",
    "TheChosenPath.Entrance": "Entrata",
    "AxonPath.VistaEntrance": "Entrata",
    "AxonPath.SavepointEnd": "Entrata",
    "IsleOfTheEyes.Entrance": "Entrata",
    "IsleOfEyes.Entrance": "Entrata",
    "EndlessTower.Entrance": "Entrata",
    "CleasTower.Entrance": "Entrata",
    # Esoteric Ruins
    "EsotericRuins.LumiereWrecks": "Relitti di Lumière",
    "EsotericRuins.Entry": "Relitti di Lumière",
    "EsotericRuins.Entrance": "Relitti di Lumière",
    "EsotericRuins": "Relitti di Lumière",
    "LumiereWrecks": "Relitti di Lumière",
    # Yellow Harvest
    "YellowHarvest.YellowHarvest": "Raccolto Giallo",
    "YellowHarvest.Entry": "Raccolto Giallo",
    "YellowHarvest.Entrance": "Raccolto Giallo",
    "YellowHarvest": "Raccolto Giallo",
    "YellowHarvest.HarvestersHollow": "Conca del Mietitore",
    "HarvestersHollow": "Conca del Mietitore",
    "HarvesterHollow": "Conca del Mietitore",
    "YellowHarvest.YellowSpireWrecks": "Relitti della Guglia Gialla",
    "YellowSpireWrecks": "Relitti della Guglia Gialla",
    # Dark Shores
    "DarkShores.BloodiedBeach": "Spiaggia Insanguinata",
    "DarkShores.Entry": "Spiaggia Insanguinata",
    "DarkShores.Entrance": "Spiaggia Insanguinata",
    "DarkShores": "Spiaggia Insanguinata",
    "BloodiedBeach": "Spiaggia Insanguinata",
    # Coastal Cave
    "CoastalCave.Forge": "Forgia",
    "CoastalCave.Entry": "Forgia",
    "CoastalCave.Entrance": "Forgia",
    "CoastalCave": "Forgia",
    "Forge": "Forgia",
    # Frozen Hearts
    "FrozenHearts.IceboundTrainStation": "Stazione Ferroviaria Ghiacciata",
    "FrozenHearts.Entry": "Stazione Ferroviaria Ghiacciata",
    "FrozenHearts.Entrance": "Stazione Ferroviaria Ghiacciata",
    "IceboundTrainStation": "Stazione Ferroviaria Ghiacciata",
    "FrozenHearts.GlacialFalls": "Cascate Glaciali",
    "GlacialFalls": "Cascate Glaciali",
    "FrozenHearts.IcedHeart": "Cuore Ghiacciato",
    "IcedHeart": "Cuore Ghiacciato",
    "FrozenHearts.IceboundTerminal": "Capolinea Ghiacciato",
    "IceboundTerminal": "Capolinea Ghiacciato",
    # Falling Leaves
    "FallingLeaves.ResinveilGrove": "Boschetto del Velo di Resina",
    "FallingLeaves.Entry": "Boschetto del Velo di Resina",
    "FallingLeaves.Entrance": "Boschetto del Velo di Resina",
    "ResinveilGrove": "Boschetto del Velo di Resina",
    "FallingLeaves.Scavenger": "Spazzino",
    "Scavenger": "Spazzino",
    # Renoir's Drafts
    "RenoirsDrafts.GoldenTree": "Albero Dorato",
    "GoldenTree": "Albero Dorato",
    # Crimson Forest
    "CrimsonForest.CrimsonPerch": "Posatoio Cremisi",
    "CrimsonForest.Entry": "Posatoio Cremisi",
    "CrimsonForest.Entrance": "Posatoio Cremisi",
    "CleaOrangeForest.Entry": "Posatoio Cremisi",
    "CleaOrangeForest.Entrance": "Posatoio Cremisi",
    "CrimsonPerch": "Posatoio Cremisi",
    "CrimsonForest.TheThreeBlades": "Le Tre Lame",
    "CrimsonForest.ThreeBlades": "Le Tre Lame",
    "TheThreeBlades": "Le Tre Lame",
    "ThreeBlades": "Le Tre Lame",
    "CleaOrangeForest.CenterPlazza": "Posatoio Cremisi",
    # Endless Night Sanctuary
    "EndlessNightSanctuary.WarriorsRoute": "Percorso del Guerriero",
    "WarriorsRoute": "Percorso del Guerriero",
    "EndlessNightSanctuary.NightTotem": "Totem della Notte",
    "NightTotem": "Totem della Notte",
    # Sunless Cliffs
    "SunlessCliffs.ChromaPortal": "Portale Chroma",
    "SunlessCliffs.Entry": "Portale Chroma",
    "SunlessCliffs.Entrance": "Portale Chroma",
    "SunlessCliffs": "Portale Chroma",
    "ChromaPortal": "Portale Chroma",
    # Sirene's Dress
    "SireneDress.Entrance": "Entrata",
    "SireneSmallLevel.Entry": "Entrata",
    "SireneDress.Glissando": "Glissando",
    # The Reacher
    "TheReacher.Mountain": "Montagna",
    "Mountain": "Montagna",
    "TheReacher.LadderArea": "Zona della Scala",
    "LadderArea": "Zona della Scala",
    "TheReacher.FoggyArea": "Zona Nebbiosa",
    "FoggyArea": "Zona Nebbiosa",
    "TheReacher.Peak": "Cima",
    "TheReacher.Alicia": "Alicia",
    "Alicia": "Alicia",
    # The Abyss
    "TheAbyss.Simon": "Simon",
    "TheAbyss.Entry": "Simon",
    "TheAbyss.Entrance": "Simon",
    "TheAbyss": "Simon",
    "SimonArea.Abyss": "Simon",
    "SimonArea.Entry": "Simon",
    "SimonArea.Entrance": "Simon",
    "Simon": "Simon",
    # Flying Manor
    "FlyingManor.CentralPlaza": "Piazza Centrale",
    "CleasFlyingHouse.Center": "Piazza Centrale",
    # Painting Workshop
    "PaintingWorkshop.BrokenConception": "Concezione Spezzata",
    "PaintingWorkshop.Entry": "Concezione Spezzata",
    "PaintingWorkshop.Entrance": "Concezione Spezzata",
    "PaintingWorkshop": "Concezione Spezzata",
    "TheCanvas.Entry": "Concezione Spezzata",
    "TheCanvas.Entrance": "Concezione Spezzata",
    "BrokenConception": "Concezione Spezzata",
    # Verso's Drafts
    "VersosDraft.OpenPlayground": "Parco Giochi Aperto",
    "VersosDraft.Entry": "Parco Giochi Aperto",
    "VersosDraft.Entrance": "Parco Giochi Aperto",
    "VersosDraft.OpenField": "Parco Giochi Aperto",
    "OpenPlayground": "Parco Giochi Aperto",
    "OpenField": "Parco Giochi Aperto",
    "VersosDraft.GestralBaths": "Bagni Gestral",
    "GestralBaths": "Bagni Gestral",
    "VersosDraft.CandyLand": "Terra dei Dolci",
    "CandyLand": "Terra dei Dolci",
    "VersosDraft.ReveriePath": "Sentiero della Fantasia",
    "VersosDraft.GooglyEyesDoor": "Sentiero della Fantasia",
    "ReveriePath": "Sentiero della Fantasia",
    "GooglyEyesDoor": "Sentiero della Fantasia",
    "VersosDraft.LicornapiedsStation": "Stazione Licornapieds",
    "LicornapiedsStation": "Stazione Licornapieds",
    "WorldMap.VersosDraftEntry": "Parco Giochi Aperto",
}


def format_checkpoint_tag(tag: str, lang: str = "en") -> str:
    """Returns the official in-game Expedition Flag name for a given SpawnPoint tag."""
    if not tag:
        return ""
    clean_tag = tag.replace("Level.SpawnPoint.", "")
    parts = clean_tag.split(".")
    suffix = parts[-1]
    if suffix in ("WorldMap", "Generic", "Dynamic", "Editor", "todelete", "None", "Default"):
        return ""

    name_dict = CHECKPOINT_NAMES_IT if lang.startswith("it") else CHECKPOINT_NAMES_EN
    fallback_dict = CHECKPOINT_NAMES_EN

    # 1. Exact clean tag or suffix matches
    res = name_dict.get(clean_tag) or name_dict.get(suffix)
    if res:
        return res
    res = fallback_dict.get(clean_tag) or fallback_dict.get(suffix)
    if res:
        return res

    # 2. Case-insensitive lookup
    clean_tag_lower = clean_tag.lower()
    suffix_lower = suffix.lower()
    for k, v in name_dict.items():
        k_lower = k.lower()
        if k_lower in (clean_tag_lower, suffix_lower):
            return v
    for k, v in fallback_dict.items():
        k_lower = k.lower()
        if k_lower in (clean_tag_lower, suffix_lower):
            return v

    # 3. CamelCase spacing fallback for unmapped clean names
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", suffix)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced).strip()
    if spaced.lower() in ("entry", "entrance"):
        return "Entrata" if lang.startswith("it") else "Entrance"
    return spaced


def format_zone_name(raw_name: str, lang: str = "en") -> str:
    """Converts internal Unreal Engine map names (e.g. Level_Sirene_Main_V2) to player-friendly titles."""
    if not raw_name:
        return "In esplorazione" if lang.startswith("it") else "Exploring"

    continent_names = {
        "main",
        "worldmap",
        "world_map",
        "worldmap_main",
        "level_worldmap",
        "level_worldmap_main",
        "level_worldmap_main_v2",
    }
    if raw_name.lower().strip() in continent_names or "worldmap" in raw_name.lower():
        return "Il Continente" if lang.startswith("it") else "The Continent"

    cleaned = raw_name
    for prefix in [
        "Level_Side_",
        "Level_Small_",
        "Level_Main_",
        "Level_WorldMap_",
        "Level_",
        "SideLevel_",
        "SmallLevel_",
        "MainLevel_",
        "SubLevel_",
    ]:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break

    cleaned = re.sub(r"_V\d+$", "", cleaned)
    cleaned = re.sub(r"_C$", "", cleaned)
    cleaned = re.sub(r"_\d+$", "", cleaned)
    cleaned = re.sub(r"_Main$", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("_", " ")

    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", cleaned)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    normalized = spaced.strip().lower()

    if normalized in ("main", "world map", "worldmap"):
        return "Il Continente" if lang.startswith("it") else "The Continent"

    # Check official overrides
    if lang.startswith("it"):
        override = ZONE_NAME_OVERRIDES_IT.get(normalized) or ZONE_NAME_OVERRIDES_IT.get(
            cleaned.lower().strip()
        )
        if override:
            return override
    override = ZONE_NAME_OVERRIDES_EN.get(normalized) or ZONE_NAME_OVERRIDES_EN.get(
        cleaned.lower().strip()
    )
    if override:
        return override

    return spaced.strip()


def resolve_tower_trial(enemy_name: str) -> tuple[tuple[int, int] | str | None, str]:
    """Determines the (stage, trial) in Endless Tower and the clean boss/enemy name based on exact wiki names."""
    if not enemy_name:
        return None, enemy_name
    cleaned = re.sub(r"\(Tier \d+\)", "", enemy_name, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bT\d+\b", "", cleaned, flags=re.IGNORECASE).lower()

    for stage_info, boss_name, enemy_groups in ENDLESS_TOWER_TRIALS:
        if all(any(variant.lower() in cleaned for variant in group) for group in enemy_groups):
            final_enemy = boss_name if boss_name else enemy_name
            return stage_info, final_enemy

    return None, enemy_name
