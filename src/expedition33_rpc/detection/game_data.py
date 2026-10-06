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
    (
        "Super Boss",
        "Alpha Lampmaster",
        [["Alpha Lampmaster", "Chromatic Lampmaster", "Lampmaster Alpha"]],
    ),
    # Stage 11
    ((11, 3), "Painted Love", [["Painted Love"]]),
    (
        (11, 2),
        None,
        [
            ["Lampmaster"],
            ["Creation"],
            ["Alpha Clair Obscur", "Chromatic Clair Obscur", "Clair Obscur Alpha"],
        ],
    ),
    (
        (11, 1),
        None,
        [
            [
                "Alpha Moissonneuse",
                "Chromatic Moissonneuse",
                "Moissonneuse Alpha",
                "Alpha Moissoneusse",
                "Chromatic Moissoneusse",
            ],
            ["Dualliste"],
            ["Mask Keeper"],
        ],
    ),
    # Stage 10
    (
        (10, 3),
        None,
        [
            [
                "Alpha Chapelier",
                "Chromatic Chapelier",
                "Chapelier Alpha",
                "Alpha Chalier",
                "Chromatic Chalier",
            ],
            ["Alpha Jar", "Chromatic Jar", "Jar Alpha"],
            ["Obscur"],
        ],
    ),
    (
        (10, 2),
        None,
        [
            ["Alpha Gold Chevaliere", "Chromatic Gold Chevaliere", "Gold Chevaliere Alpha"],
            ["Alpha Steel Chevaliere", "Chromatic Steel Chevaliere", "Steel Chevaliere Alpha"],
            [
                "Alpha Ceramic Chevaliere",
                "Chromatic Ceramic Chevaliere",
                "Ceramic Chevaliere Alpha",
            ],
        ],
    ),
    (
        (10, 1),
        None,
        [
            ["Alpha Portier", "Chromatic Portier", "Portier Alpha"],
            ["Alpha Demineur", "Chromatic Demineur", "Demineur Alpha"],
            ["Clair"],
        ],
    ),
    # Stage 9
    (
        (9, 3),
        None,
        [
            ["Flame Eveque"],
            ["Frost Eveque"],
            ["Alpha Danseuse", "Chromatic Danseuse", "Danseuse Alpha"],
        ],
    ),
    (
        (9, 2),
        None,
        [
            ["Thunder Eveque"],
            ["Alpha Demineur", "Chromatic Demineur", "Demineur Alpha"],
            ["Stalact"],
        ],
    ),
    (
        (9, 1),
        None,
        [["Eveque"], ["Alpha Cultist", "Chromatic Cultist", "Cultist Alpha"], ["Luster"]],
    ),
    # Stage 8
    (
        (8, 3),
        None,
        [
            ["Alpha Sakapatate", "Chromatic Sakapatate", "Sakapatate Alpha"],
            ["Boucheclier", "Bouchelier"],
            ["Gault"],
        ],
    ),
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
    (
        (5, 3),
        None,
        [["Alpha Bourgeon", "Chromatic Bourgeon", "Bourgeon Alpha"], ["Volester"], ["Flan"]],
    ),
    (
        (5, 2),
        None,
        [
            [
                "Alpha Greatsword Cultist",
                "Chromatic Greatsword Cultist",
                "Greatsword Cultist Alpha",
            ],
            ["Orphelin"],
            ["Sapling"],
        ],
    ),
    (
        (5, 1),
        None,
        [["Alpha Veilleur", "Chromatic Veilleur", "Veilleur Alpha"], ["Bruler"], ["Orphelin"]],
    ),
    # Stage 4
    (
        (4, 3),
        None,
        [
            ["Alpha Echassier", "Chromatic Echassier", "Echassier Alpha"],
            ["Moissonneuse"],
            ["Catapult Sakapatate"],
        ],
    ),
    ((4, 2), None, [["Bourgeon"], ["Jar"], ["Rocher"]]),
    (
        (4, 1),
        None,
        [
            ["Alpha Orphelin", "Chromatic Orphelin", "Orphelin Alpha"],
            ["Ceramic Chevaliere"],
            ["Cruler"],
        ],
    ),
    # Stage 3
    (
        (3, 3),
        None,
        [["Alpha Abbest", "Chromatic Abbest", "Abbest Alpha"], ["Goblu"], ["Troubadour"]],
    ),
    (
        (3, 2),
        None,
        [
            ["Alpha Benisseur", "Chromatic Benisseur", "Benisseur Alpha"],
            ["Boucheclier", "Bouchelier"],
            ["Clair"],
        ],
    ),
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
    "cleasworkshop": "Painting Workshop",
    "cleas workshop": "Painting Workshop",
    "paintingworkshop": "Painting Workshop",
    "painting workshop": "Painting Workshop",
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
    "yellowforest": "Yellow Harvest",
    "yellow forest": "Yellow Harvest",
    "chromazoneentrance": "Sunless Cliffs",
    "chroma zone entrance": "Sunless Cliffs",
    "chromazone": "Sunless Cliffs",
    "stonewavecliffscave": "Stone Wave Cliffs Cave",
    "stone wave cliffs cave": "Stone Wave Cliffs Cave",
    "esotericruins": "Esoteric Ruins",
    "esoteric ruins": "Esoteric Ruins",
    "endlessnightsanctuary": "Endless Night Sanctuary",
    "endless night sanctuary": "Endless Night Sanctuary",
    "twilightsanctuary": "Endless Night Sanctuary",
    "twilight sanctuary": "Endless Night Sanctuary",
    "redforest": "Renoir's Drafts",
    "red forest": "Renoir's Drafts",
    "renoirdraft": "Renoir's Drafts",
    "renoirdrafts": "Renoir's Drafts",
    "renoir's drafts": "Renoir's Drafts",
    "renoirs drafts": "Renoir's Drafts",
    "caveabbestalpha": "Abbest Cave",
    "cave abbest alpha": "Abbest Cave",
    "abbestalpha": "Abbest Cave",
    "abbest alpha": "Abbest Cave",
    "invisiblecave": "Sinister Cave",
    "invisible cave": "Sinister Cave",
    "carrousel": "The Carousel",
    "carousel": "The Carousel",
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
    "canvas": "Laboratorio di Pittura",
    "cleasworkshop": "Laboratorio di Pittura",
    "cleas workshop": "Laboratorio di Pittura",
    "painting workshop": "Laboratorio di Pittura",
    "cleaorangeforest": "Foresta Cremisi",
    "orangeforest": "Foresta Cremisi",
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
    "yellowforest": "Raccolto Giallo",
    "yellow forest": "Raccolto Giallo",
    "chromazoneentrance": "Scogliere Senza Sole",
    "chroma zone entrance": "Scogliere Senza Sole",
    "chromazone": "Scogliere Senza Sole",
    "abbest cave": "Grotta di Abbest",
    "caveabbestalpha": "Grotta di Abbest",
    "cave abbest alpha": "Grotta di Abbest",
    "abbestalpha": "Grotta di Abbest",
    "abbest alpha": "Grotta di Abbest",
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
    "carrousel": "La Giostra",
    "carousel": "La Giostra",
    "stonewavecliffscave": "Grotta delle Scogliere dell'Onda di Pietra",
    "stone wave cliffs cave": "Grotta delle Scogliere dell'Onda di Pietra",
    "falling leaves": "Foglie Cadenti",
    "sinister cave": "Grotta Sinistra",
    "invisiblecave": "Grotta Sinistra",
    "invisible cave": "Grotta Sinistra",
    "redforest": "Bozze di Renoir",
    "red forest": "Bozze di Renoir",
    "renoirdraft": "Bozze di Renoir",
    "renoirdrafts": "Bozze di Renoir",
    "renoir's drafts": "Bozze di Renoir",
    "renoirs drafts": "Bozze di Renoir",
    "the crows": "I Corvi",
    "dark gestral arena": "Arena Oscura dei Gestral",
    "the fountain": "La Fontana",
    "flying casino": "Casinò Volante",
    "floating cemetery": "Cimitero Galleggiante",
    "sky island": "Isola del Cielo",
    "endless night sanctuary": "Santuario della Notte Eterna",
    "twilightsanctuary": "Santuario della Notte Eterna",
    "twilight sanctuary": "Santuario della Notte Eterna",
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
    "SpringMeadows.OldExpeditionnerCamp": "Abandoned Expeditioner Camp",
    "SpringMeadows.OldExpeditionerCamp": "Abandoned Expeditioner Camp",
    "OldExpeditionnerCamp": "Abandoned Expeditioner Camp",
    "OldExpeditionerCamp": "Abandoned Expeditioner Camp",
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
    "AncientSanctuary.RedForest": "Entrance",
    "AncientSanctuary.Entrance": "Entrance",
    "AncientSanctuary.Entry": "Entrance",
    "AncientSanctuary.SanctuaryMaze": "Sanctuary Maze",
    "AncientSanctuary.GiantBellAlley": "Sanctuary Maze",
    "AncientSanctuary.TanksArena": "Giant Bell Alley",
    "AncientSanctuary.Arena": "Giant Bell Alley",
    "TanksArena": "Giant Bell Alley",
    "AncientSanctuary.GestralTotem": "Gestral Totem",
    "GestralTotem": "Gestral Totem",
    # Gestral Village
    "GestralVillage.VillageEntry": "Entrance",
    "GestralVillage.Entrance": "Entrance",
    "GestralVillage.Entry": "Entrance",
    "VillageEntry": "Entrance",
    "GestralVillage.GestralArena": "Gestral Arena",
    "GestralArena": "Gestral Arena",
    # Esquie's Nest
    "EsquieNest.GestralEntry": "Entrance",
    "EsquieNest.Entrance": "Entrance",
    "EsquieNest.Entry": "Entrance",
    "GestralEntry": "Entrance",
    "EsquieNest.Francois": "Francois' Cave",
    "EsquieNest.FrancoisCave": "Francois' Cave",
    "Francois": "Francois' Cave",
    "FrancoisCave": "Francois' Cave",
    # Stone Wave Cliffs
    "SeaCliff.ZeppelinEntry": "Entrance",
    "StoneWaveCliffs.ZeppelinEntry": "Entrance",
    "ZeppelinEntry": "Entrance",
    "SeaCliff.Entrance": "Entrance",
    "SeaCliff.Entry": "Entrance",
    "StoneWaveCliffs.Entrance": "Entrance",
    "StoneWaveCliffs.Entry": "Entrance",
    "SeaCliff.PaintressShrine": "Paintress Shrine",
    "StoneWaveCliffs.PaintressShrine": "Paintress Shrine",
    "PaintressShrine": "Paintress Shrine",
    "SeaCliff.Village": "Old Farm",
    "StoneWaveCliffs.Village": "Old Farm",
    "SeaCliff.OldFarm": "Old Farm",
    "StoneWaveCliffs.OldFarm": "Old Farm",
    "OldFarm": "Old Farm",
    "SeaCliff.Caves": "Tide Caverns",
    "StoneWaveCliffs.Caves": "Tide Caverns",
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
    "ForgottenBattlefield.MainRuins": "Fort Ruins",
    "MainRuins": "Fort Ruins",
    "ForgottenBattlefield.FortRuins": "Fort Ruins",
    "FortRuins": "Fort Ruins",
    "ForgottenBattlefield.Battlefield": "Vanguard Point",
    "ForgottenBattlefield.VanguardPoint": "Vanguard Point",
    "VanguardPoint": "Vanguard Point",
    "ForgottenBattlefield.SideBattlefield": "Battlefield",
    "SideBattlefield": "Battlefield",
    "ForgottenBattlefield.DuallistArena": "Ancient Bridge",
    "DuallistArena": "Ancient Bridge",
    "ForgottenBattlefield.AncientBridge": "Ancient Bridge",
    "AncientBridge": "Ancient Bridge",
    # Monoco's Station
    "MonocoStation.IceCorridor": "Ice Corridor",
    "MonocoStation.Entry": "Ice Corridor",
    "MonocoStation.Entrance": "Ice Corridor",
    "IceCorridor": "Ice Corridor",
    "MonocoStation.InsideStation": "Monoco's Station",
    "MonocoStation.Station": "Monoco's Station",
    "MonocoStation.MonocoStation": "Monoco's Station",
    "InsideStation": "Monoco's Station",
    "MonocoStation": "Monoco's Station",
    # Old Lumiere
    "OldLumiere.BrokenBuildings": "Entrance",
    "BrokenBuildings": "Entrance",
    "OldLumiere.Entrance": "Entrance",
    "OldLumiere.Entry": "Entrance",
    "LumiereAct03.Entrance": "Entrance",
    "LumiereAct03.Entry": "Entrance",
    "OldLumiere.ManorArena": "Manor Gardens",
    "ManorArena": "Manor Gardens",
    "OldLumiere.LunePath": "Right Street",
    "LunePath": "Right Street",
    "OldLumiere.RightStreet": "Right Street",
    "LumiereAct03.RightStreet": "Right Street",
    "RightStreet": "Right Street",
    "OldLumiere.MaellePath": "Left Street",
    "MaellePath": "Left Street",
    "OldLumiere.LeftStreet": "Left Street",
    "LumiereAct03.LeftStreet": "Left Street",
    "LeftStreet": "Left Street",
    "OldLumiere.AlphaArea": "Train Station Ruins",
    "OldLumiere.AlphaArena": "Train Station Ruins",
    "AlphaArea": "Train Station Ruins",
    "AlphaArena": "Train Station Ruins",
    "OldLumiere.TrainStationRuins": "Train Station Ruins",
    # Visages
    "SmallLevelVisages.Entry": "Plazza",
    "Visages.Plazza": "Plazza",
    "Visages.Entry": "Plazza",
    "Visages.Entrance": "Plazza",
    "Visages.Joy": "Joy Vale",
    "Visages.JoyVale": "Joy Vale",
    "Visages.JoyfulVale": "Joy Vale",
    "Joy": "Joy Vale",
    "JoyVale": "Joy Vale",
    "JoyfulVale": "Joy Vale",
    "Visages.Sadness": "Sadness Vale",
    "Visages.SadnessVale": "Sadness Vale",
    "Sadness": "Sadness Vale",
    "SadnessVale": "Sadness Vale",
    "Visages.Anger": "Anger Vale",
    "Visages.AngerVale": "Anger Vale",
    "Anger": "Anger Vale",
    "AngerVale": "Anger Vale",
    "Visages.VisagesArena": "Peak",
    "VisagesArena": "Peak",
    "Visages.Peaks": "Peak",
    "Peaks": "Peak",
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
    "MonolithInterior.Climb.SpringMeadows": "Tainted Meadows",
    "Monolith.TaintedMeadows": "Tainted Meadows",
    "TaintedMeadows": "Tainted Meadows",
    "MonolithInterior.Climb.Goblu": "Tainted Waters",
    "Monolith.TaintedWaters": "Tainted Waters",
    "TaintedWaters": "Tainted Waters",
    "MonolithInterior.Climb.AncientSanctuary": "Tainted Sanctuary",
    "Monolith.TaintedSanctuary": "Tainted Sanctuary",
    "TaintedSanctuary": "Tainted Sanctuary",
    "MonolithInterior.Climb.SeaCliff": "Tainted Cliffs",
    "Monolith.TaintedCliffs": "Tainted Cliffs",
    "TaintedCliffs": "Tainted Cliffs",
    "MonolithInterior.Climb.ForgottenBattlefield": "Tainted Battlefield",
    "Monolith.TaintedBattlefield": "Tainted Battlefield",
    "TaintedBattlefield": "Tainted Battlefield",
    "MonolithInterior.Climb.MonocoMountain": "Tainted Hearts",
    "Monolith.TaintedHearts": "Tainted Hearts",
    "TaintedHearts": "Tainted Hearts",
    "MonolithInterior.Climb.Lumiere": "Tainted Lumiere",
    "Monolith.TaintedLumiere": "Tainted Lumiere",
    "TaintedLumiere": "Tainted Lumiere",
    "MonolithInterior.Climb.RenoirArena": "Tower Peak",
    "Monolith.TowerPeak": "Tower Peak",
    "RenoirArena": "Tower Peak",
    "TowerPeak": "Tower Peak",
    "MonolithExterior.Peak.Entry": "Entrance (Monolith Peak)",
    "MonolithExterior.Peak.Entrance": "Entrance (Monolith Peak)",
    "MonolithPeak.Entrance": "Entrance (Monolith Peak)",
    # Lumiere (Act 3)
    "LumiereAct03.Dock": "Harbour",
    "Lumiere.Harbour": "Harbour",
    "Lumiere.Dock": "Harbour",
    "Lumiere.Entry": "Harbour",
    "Lumiere.Entrance": "Harbour",
    "Dock": "Harbour",
    "Harbour": "Harbour",
    "LumiereAct03.BigPlazza": "Central Plaza",
    "Lumiere.CentralPlaza": "Central Plaza",
    "BigPlazza": "Central Plaza",
    "CentralPlaza": "Central Plaza",
    "LumiereAct03.CrumblingBuildings": "Shattered Alley",
    "Lumiere.ShatteredAlley": "Shattered Alley",
    "CrumblingBuildings": "Shattered Alley",
    "ShatteredAlley": "Shattered Alley",
    "LumiereAct03.Opera": "Opera House",
    "Lumiere.OperaHouse": "Opera House",
    "Opera": "Opera House",
    "OperaHouse": "Opera House",
    "LumiereAct03.Gardens": "Lumiere's Gardens",
    "LumiereAct03.LumieresGardens": "Lumiere's Gardens",
    "Lumiere.LumieresGardens": "Lumiere's Gardens",
    "LumieresGardens": "Lumiere's Gardens",
    "LumiereAct03.Curator": "Crooked Tower Walkway",
    "LumiereAct03.CrookedTowerWalkway": "Crooked Tower Walkway",
    "Lumiere.CrookedTowerWalkway": "Crooked Tower Walkway",
    "CrookedTowerWalkway": "Crooked Tower Walkway",
    # Single-entrance areas & caverns
    "AbbestCave.Arena": "Entrance",
    "Abbest.Arena": "Entrance",
    "AbbestCave.Entrance": "Entrance",
    "AbbestCave.Entry": "Entrance",
    "RedWoods.Entrance": "Entrance",
    "SmallBourgeon.Entrance": "Entrance",
    "TheSmallBourgeon.Entrance": "Entrance",
    "HiddenGestralArena.Entrance": "Entrance",
    "CrushingCavern.Entrance": "Entrance",
    "StoneQuarry.Entrance": "Entrance",
    "StoneQuarry.Entry": "Entrance",
    "TheCarousel.Entrance": "Entrance",
    "Carousel.Entrance": "Entrance",
    "StonewaveCliffsCave.Vista": "Entrance",
    "StoneWaveCliffsCave.Vista": "Entrance",
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
    "EsotericRuins.CliffBottom": "Lumiere's Wrecks",
    "CliffBottom": "Lumiere's Wrecks",
    "EsotericRuins.LumiereWrecks": "Lumiere's Wrecks",
    "EsotericRuins.Entry": "Lumiere's Wrecks",
    "EsotericRuins.Entrance": "Lumiere's Wrecks",
    "EsotericRuins": "Lumiere's Wrecks",
    "LumiereWrecks": "Lumiere's Wrecks",
    # Yellow Harvest
    "YellowForest.Lake": "Harvester's Hollow",
    "YellowHarvest.Lake": "Harvester's Hollow",
    "Lake": "Harvester's Hollow",
    "YellowHarvest.HarvestersHollow": "Harvester's Hollow",
    "HarvestersHollow": "Harvester's Hollow",
    "HarvesterHollow": "Harvester's Hollow",
    "YellowForest.Arena": "Yellow Spire Wrecks",
    "YellowHarvest.Arena": "Yellow Spire Wrecks",
    "YellowHarvest.YellowSpireWrecks": "Yellow Spire Wrecks",
    "YellowSpireWrecks": "Yellow Spire Wrecks",
    "YellowForest.Entry": "Yellow Harvest",
    "YellowHarvest.Entry": "Yellow Harvest",
    "YellowHarvest.Entrance": "Yellow Harvest",
    "YellowHarvest.YellowHarvest": "Yellow Harvest",
    "YellowHarvest": "Yellow Harvest",
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
    "FrozenHearts.CaveStation": "Icebound Terminal",
    "CaveStation": "Icebound Terminal",
    "FrozenHearts.IceboundTerminal": "Icebound Terminal",
    "IceboundTerminal": "Icebound Terminal",
    "FrozenHearts.CaveForest": "Iced Heart",
    "CaveForest": "Iced Heart",
    "FrozenHearts.IcedHeart": "Iced Heart",
    "IcedHeart": "Iced Heart",
    "FrozenHearts.TrainStation": "Icebound Train Station",
    "TrainStation": "Icebound Train Station",
    "FrozenHearts.IceboundTrainStation": "Icebound Train Station",
    "IceboundTrainStation": "Icebound Train Station",
    "FrozenHearts.Frozenlakes": "Glacial Falls",
    "Frozenlakes": "Glacial Falls",
    "FrozenHearts.GlacialFalls": "Glacial Falls",
    "GlacialFalls": "Glacial Falls",
    "FrozenHearts.Entry": "Icebound Train Station",
    "FrozenHearts.Entrance": "Icebound Train Station",
    # Falling Leaves
    "FallingLeaves.ResinveilGrove": "Resinveil Grove",
    "FallingLeaves.CrimsonPerch": "Resinveil Grove",
    "FallingLeaves.CenterPlazza": "Resinveil Grove",
    "FallingLeaves.Plazza": "Resinveil Grove",
    "FallingLeaves.Entry": "Resinveil Grove",
    "FallingLeaves.Entrance": "Resinveil Grove",
    "ResinveilGrove": "Resinveil Grove",
    "FallingLeaves.Scavenger": "Scavenger",
    "Scavenger": "Scavenger",
    # Renoir's Drafts
    "RenoirsDrafts.GoldenTree": "Golden Tree",
    "RenoirsDraft.GoldenTree": "Golden Tree",
    "RenoirDraft.GoldenTree": "Golden Tree",
    "GoldenTree": "Golden Tree",
    "RenoirsDrafts.Entrance": "Golden Tree",
    "RenoirsDraft.Entrance": "Golden Tree",
    "RenoirDraft.Entrance": "Golden Tree",
    "RenoirsDrafts.Entry": "Entrance",
    "RenoirsDraft.Entry": "Entrance",
    "RenoirDraft.Entry": "Entrance",
    "WorldMap.RenoirsDraftEntry": "Entrance",
    "WorldMap.RenoirDraftEntry": "Entrance",
    # Crimson Forest
    "CleaOrangeForest.CenterPlazza": "Crimson Perch",
    "CleaOrangeForest.Plazza": "Crimson Perch",
    "CrimsonForest.CenterPlazza": "Crimson Perch",
    "CrimsonForest.Plazza": "Crimson Perch",
    "CrimsonForest.Plaza": "Crimson Perch",
    "CenterPlazza": "Crimson Perch",
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
    # Endless Night Sanctuary
    "EndlessNightSanctuary.Arena": "Warrior's Route",
    "EndlessNightSanctuary.WarriorsRoute": "Warrior's Route",
    "WarriorsRoute": "Warrior's Route",
    "EndlessNightSanctuary.Totem": "Night Totem",
    "EndlessNightSanctuary.NightTotem": "Night Totem",
    "NightTotem": "Night Totem",
    # Sunless Cliffs
    "ChromaZoneEntrance.Cave": "Chroma Portal",
    "SunlessCliffs.Cave": "Chroma Portal",
    "SunlessCliffs.ChromaPortal": "Chroma Portal",
    "SunlessCliffs.Entry": "Chroma Portal",
    "SunlessCliffs.Entrance": "Chroma Portal",
    "SunlessCliffs": "Chroma Portal",
    "ChromaPortal": "Chroma Portal",
    # Sirene's Dress
    "SireneSmallLevel.Inside": "Glissando",
    "SireneDress.Inside": "Glissando",
    "Sirene.Inside": "Glissando",
    "SireneDress.Entrance": "Entrance",
    "SireneSmallLevel.Entry": "Entrance",
    "SireneDress.Glissando": "Glissando",
    # The Reacher
    "Reacher.Mountain": "Mountain",
    "TheReacher.Mountain": "Mountain",
    "Mountain": "Mountain",
    "Reacher.LadderArea": "Ladder Area",
    "TheReacher.LadderArea": "Ladder Area",
    "LadderArea": "Ladder Area",
    "Reacher.FogArea": "Foggy Area",
    "TheReacher.FogArea": "Foggy Area",
    "FogArea": "Foggy Area",
    "TheReacher.FoggyArea": "Foggy Area",
    "FoggyArea": "Foggy Area",
    "Reacher.MountainTop": "Peak",
    "TheReacher.MountainTop": "Peak",
    "MountainTop": "Peak",
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
    "CleaWorkshop.BrokenLampmaster": "Broken Conception",
    "PaintingWorkshop.BrokenLampmaster": "Broken Conception",
    "BrokenLampmaster": "Broken Conception",
    "PaintingWorkshop.BrokenConception": "Broken Conception",
    "PaintingWorkshop.Entry": "Broken Conception",
    "PaintingWorkshop.Entrance": "Broken Conception",
    "PaintingWorkshop": "Broken Conception",
    "TheCanvas.Entry": "Entrance",
    "TheCanvas.Entrance": "Entrance",
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
    "SpringMeadows.OldExpeditionnerCamp": "Accampamento Abbandonato",
    "SpringMeadows.OldExpeditionerCamp": "Accampamento Abbandonato",
    "OldExpeditionnerCamp": "Accampamento Abbandonato",
    "OldExpeditionerCamp": "Accampamento Abbandonato",
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
    "AncientSanctuary.RedForest": "Entrata",
    "AncientSanctuary.Entrance": "Entrata",
    "AncientSanctuary.Entry": "Entrata",
    "AncientSanctuary.SanctuaryMaze": "Labirinto del Santuario",
    "AncientSanctuary.GiantBellAlley": "Labirinto del Santuario",
    "AncientSanctuary.TanksArena": "Vicolo della Grande Campana",
    "AncientSanctuary.Arena": "Vicolo della Grande Campana",
    "TanksArena": "Vicolo della Grande Campana",
    "AncientSanctuary.GestralTotem": "Totem Gestral",
    "GestralTotem": "Totem Gestral",
    # Gestral Village
    "GestralVillage.VillageEntry": "Entrata",
    "GestralVillage.Entrance": "Entrata",
    "GestralVillage.Entry": "Entrata",
    "VillageEntry": "Entrata",
    "GestralVillage.GestralArena": "Arena dei Gestral",
    "GestralArena": "Arena dei Gestral",
    # Esquie's Nest
    "EsquieNest.GestralEntry": "Entrata",
    "EsquieNest.Entrance": "Entrata",
    "EsquieNest.Entry": "Entrata",
    "GestralEntry": "Entrata",
    "EsquieNest.Francois": "Grotta di François",
    "EsquieNest.FrancoisCave": "Grotta di François",
    "Francois": "Grotta di François",
    "FrancoisCave": "Grotta di François",
    # Stone Wave Cliffs
    "SeaCliff.ZeppelinEntry": "Entrata",
    "StoneWaveCliffs.ZeppelinEntry": "Entrata",
    "ZeppelinEntry": "Entrata",
    "SeaCliff.Entrance": "Entrata",
    "SeaCliff.Entry": "Entrata",
    "StoneWaveCliffs.Entrance": "Entrata",
    "StoneWaveCliffs.Entry": "Entrata",
    "SeaCliff.PaintressShrine": "Santuario della Pittrice",
    "StoneWaveCliffs.PaintressShrine": "Santuario della Pittrice",
    "PaintressShrine": "Santuario della Pittrice",
    "SeaCliff.Village": "Vecchia Fattoria",
    "StoneWaveCliffs.Village": "Vecchia Fattoria",
    "SeaCliff.OldFarm": "Vecchia Fattoria",
    "StoneWaveCliffs.OldFarm": "Vecchia Fattoria",
    "OldFarm": "Vecchia Fattoria",
    "SeaCliff.Caves": "Caverne della Marea",
    "StoneWaveCliffs.Caves": "Caverne della Marea",
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
    "ForgottenBattlefield.MainRuins": "Rovine del Forte",
    "MainRuins": "Rovine del Forte",
    "ForgottenBattlefield.FortRuins": "Rovine del Forte",
    "FortRuins": "Rovine del Forte",
    "ForgottenBattlefield.Battlefield": "Punto di Avanguardia",
    "ForgottenBattlefield.VanguardPoint": "Punto di Avanguardia",
    "VanguardPoint": "Punto di Avanguardia",
    "ForgottenBattlefield.SideBattlefield": "Campo di Battaglia",
    "SideBattlefield": "Campo di Battaglia",
    "ForgottenBattlefield.DuallistArena": "Ponte Antico",
    "DuallistArena": "Ponte Antico",
    "ForgottenBattlefield.AncientBridge": "Ponte Antico",
    "AncientBridge": "Ponte Antico",
    # Monoco's Station
    "MonocoStation.IceCorridor": "Corridoio di Ghiaccio",
    "MonocoStation.Entry": "Corridoio di Ghiaccio",
    "MonocoStation.Entrance": "Corridoio di Ghiaccio",
    "IceCorridor": "Corridoio di Ghiaccio",
    "MonocoStation.InsideStation": "Stazione di Monoco",
    "MonocoStation.Station": "Stazione di Monoco",
    "MonocoStation.MonocoStation": "Stazione di Monoco",
    "InsideStation": "Stazione di Monoco",
    "MonocoStation": "Stazione di Monoco",
    # Old Lumiere
    "OldLumiere.BrokenBuildings": "Entrata",
    "BrokenBuildings": "Entrata",
    "OldLumiere.Entrance": "Entrata",
    "OldLumiere.Entry": "Entrata",
    "LumiereAct03.Entrance": "Entrata",
    "LumiereAct03.Entry": "Entrata",
    "OldLumiere.ManorArena": "Giardini del Maniero",
    "ManorArena": "Giardini del Maniero",
    "OldLumiere.LunePath": "Via Destra",
    "LunePath": "Via Destra",
    "OldLumiere.RightStreet": "Via Destra",
    "LumiereAct03.RightStreet": "Via Destra",
    "RightStreet": "Via Destra",
    "OldLumiere.MaellePath": "Via Sinistra",
    "MaellePath": "Via Sinistra",
    "OldLumiere.LeftStreet": "Via Sinistra",
    "LumiereAct03.LeftStreet": "Via Sinistra",
    "LeftStreet": "Via Sinistra",
    "OldLumiere.AlphaArea": "Rovine della Stazione",
    "OldLumiere.AlphaArena": "Rovine della Stazione",
    "AlphaArea": "Rovine della Stazione",
    "AlphaArena": "Rovine della Stazione",
    "OldLumiere.TrainStationRuins": "Rovine della Stazione",
    # Visages
    "SmallLevelVisages.Entry": "Piazza",
    "Visages.Plazza": "Piazza",
    "Visages.Entry": "Piazza",
    "Visages.Entrance": "Piazza",
    "Visages.Joy": "Valle della Gioia",
    "Visages.JoyVale": "Valle della Gioia",
    "Visages.JoyfulVale": "Valle della Gioia",
    "Joy": "Valle della Gioia",
    "JoyVale": "Valle della Gioia",
    "JoyfulVale": "Valle della Gioia",
    "Visages.Sadness": "Valle della Tristezza",
    "Visages.SadnessVale": "Valle della Tristezza",
    "Sadness": "Valle della Tristezza",
    "SadnessVale": "Valle della Tristezza",
    "Visages.Anger": "Valle della Rabbia",
    "Visages.AngerVale": "Valle della Rabbia",
    "Anger": "Valle della Rabbia",
    "AngerVale": "Valle della Rabbia",
    "Visages.VisagesArena": "Picco",
    "VisagesArena": "Picco",
    "Visages.Peaks": "Picco",
    "Peaks": "Picco",
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
    "MonolithInterior.Climb.SpringMeadows": "Prati Corrotti",
    "Monolith.TaintedMeadows": "Prati Corrotti",
    "TaintedMeadows": "Prati Corrotti",
    "MonolithInterior.Climb.Goblu": "Acque Corrotte",
    "Monolith.TaintedWaters": "Acque Corrotte",
    "TaintedWaters": "Acque Corrotte",
    "MonolithInterior.Climb.AncientSanctuary": "Santuario Corrotto",
    "Monolith.TaintedSanctuary": "Santuario Corrotto",
    "TaintedSanctuary": "Santuario Corrotto",
    "MonolithInterior.Climb.SeaCliff": "Scogliere Corrotte",
    "Monolith.TaintedCliffs": "Scogliere Corrotte",
    "TaintedCliffs": "Scogliere Corrotte",
    "MonolithInterior.Climb.ForgottenBattlefield": "Campo di Battaglia Corrotto",
    "Monolith.TaintedBattlefield": "Campo di Battaglia Corrotto",
    "TaintedBattlefield": "Campo di Battaglia Corrotto",
    "MonolithInterior.Climb.MonocoMountain": "Cuori Corrotti",
    "Monolith.TaintedHearts": "Cuori Corrotti",
    "TaintedHearts": "Cuori Corrotti",
    "MonolithInterior.Climb.Lumiere": "Lumière Corrotta",
    "Monolith.TaintedLumiere": "Lumière Corrotta",
    "TaintedLumiere": "Lumière Corrotta",
    "MonolithInterior.Climb.RenoirArena": "Cima della Torre",
    "Monolith.TowerPeak": "Cima della Torre",
    "RenoirArena": "Cima della Torre",
    "TowerPeak": "Cima della Torre",
    "MonolithExterior.Peak.Entry": "Entrata (Cima del Monolite)",
    "MonolithExterior.Peak.Entrance": "Entrata (Cima del Monolite)",
    "MonolithPeak.Entrance": "Entrata (Cima del Monolite)",
    # Lumiere (Act 3)
    "LumiereAct03.Dock": "Porto",
    "Lumiere.Harbour": "Porto",
    "Lumiere.Dock": "Porto",
    "Lumiere.Entry": "Porto",
    "Lumiere.Entrance": "Porto",
    "Dock": "Porto",
    "Harbour": "Porto",
    "LumiereAct03.BigPlazza": "Piazza Centrale",
    "Lumiere.CentralPlaza": "Piazza Centrale",
    "BigPlazza": "Piazza Centrale",
    "CentralPlaza": "Piazza Centrale",
    "LumiereAct03.CrumblingBuildings": "Vicolo Frantumato",
    "Lumiere.ShatteredAlley": "Vicolo Frantumato",
    "CrumblingBuildings": "Vicolo Frantumato",
    "ShatteredAlley": "Vicolo Frantumato",
    "LumiereAct03.Opera": "Teatro dell'Opera",
    "Lumiere.OperaHouse": "Teatro dell'Opera",
    "Opera": "Teatro dell'Opera",
    "OperaHouse": "Teatro dell'Opera",
    "LumiereAct03.Gardens": "Giardini di Lumière",
    "LumiereAct03.LumieresGardens": "Giardini di Lumière",
    "Lumiere.LumieresGardens": "Giardini di Lumière",
    "LumieresGardens": "Giardini di Lumière",
    "LumiereAct03.Curator": "Passerella della Torre Storta",
    "LumiereAct03.CrookedTowerWalkway": "Passerella della Torre Storta",
    "Lumiere.CrookedTowerWalkway": "Passerella della Torre Storta",
    "CrookedTowerWalkway": "Passerella della Torre Storta",
    # Single-entrance areas & caverns
    "AbbestCave.Arena": "Entrata",
    "Abbest.Arena": "Entrata",
    "AbbestCave.Entrance": "Entrata",
    "AbbestCave.Entry": "Entrata",
    "RedWoods.Entrance": "Entrata",
    "SmallBourgeon.Entrance": "Entrata",
    "TheSmallBourgeon.Entrance": "Entrata",
    "HiddenGestralArena.Entrance": "Entrata",
    "CrushingCavern.Entrance": "Entrata",
    "StoneQuarry.Entrance": "Entrata",
    "StoneQuarry.Entry": "Entrata",
    "TheCarousel.Entrance": "Entrata",
    "Carousel.Entrance": "Entrata",
    "StonewaveCliffsCave.Vista": "Entrata",
    "StoneWaveCliffsCave.Vista": "Entrata",
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
    "EsotericRuins.CliffBottom": "Relitti di Lumière",
    "CliffBottom": "Relitti di Lumière",
    "EsotericRuins.LumiereWrecks": "Relitti di Lumière",
    "EsotericRuins.Entry": "Relitti di Lumière",
    "EsotericRuins.Entrance": "Relitti di Lumière",
    "EsotericRuins": "Relitti di Lumière",
    "LumiereWrecks": "Relitti di Lumière",
    # Yellow Harvest
    "YellowForest.Lake": "Conca del Mietitore",
    "YellowHarvest.Lake": "Conca del Mietitore",
    "Lake": "Conca del Mietitore",
    "YellowHarvest.HarvestersHollow": "Conca del Mietitore",
    "HarvestersHollow": "Conca del Mietitore",
    "HarvesterHollow": "Conca del Mietitore",
    "YellowForest.Arena": "Relitti della Guglia Gialla",
    "YellowHarvest.Arena": "Relitti della Guglia Gialla",
    "YellowHarvest.YellowSpireWrecks": "Relitti della Guglia Gialla",
    "YellowSpireWrecks": "Relitti della Guglia Gialla",
    "YellowForest.Entry": "Raccolto Giallo",
    "YellowHarvest.Entry": "Raccolto Giallo",
    "YellowHarvest.Entrance": "Raccolto Giallo",
    "YellowHarvest.YellowHarvest": "Raccolto Giallo",
    "YellowHarvest": "Raccolto Giallo",
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
    "FrozenHearts.CaveStation": "Capolinea Ghiacciato",
    "CaveStation": "Capolinea Ghiacciato",
    "FrozenHearts.IceboundTerminal": "Capolinea Ghiacciato",
    "IceboundTerminal": "Capolinea Ghiacciato",
    "FrozenHearts.CaveForest": "Cuore Ghiacciato",
    "CaveForest": "Cuore Ghiacciato",
    "FrozenHearts.IcedHeart": "Cuore Ghiacciato",
    "IcedHeart": "Cuore Ghiacciato",
    "FrozenHearts.TrainStation": "Stazione Ferroviaria Ghiacciata",
    "TrainStation": "Stazione Ferroviaria Ghiacciata",
    "FrozenHearts.IceboundTrainStation": "Stazione Ferroviaria Ghiacciata",
    "IceboundTrainStation": "Stazione Ferroviaria Ghiacciata",
    "FrozenHearts.Frozenlakes": "Cascate Glaciali",
    "Frozenlakes": "Cascate Glaciali",
    "FrozenHearts.GlacialFalls": "Cascate Glaciali",
    "GlacialFalls": "Cascate Glaciali",
    "FrozenHearts.Entry": "Stazione Ferroviaria Ghiacciata",
    "FrozenHearts.Entrance": "Stazione Ferroviaria Ghiacciata",
    # Falling Leaves
    "FallingLeaves.ResinveilGrove": "Boschetto del Velo di Resina",
    "FallingLeaves.CrimsonPerch": "Boschetto del Velo di Resina",
    "FallingLeaves.CenterPlazza": "Boschetto del Velo di Resina",
    "FallingLeaves.Plazza": "Boschetto del Velo di Resina",
    "FallingLeaves.Entry": "Boschetto del Velo di Resina",
    "FallingLeaves.Entrance": "Boschetto del Velo di Resina",
    "ResinveilGrove": "Boschetto del Velo di Resina",
    "FallingLeaves.Scavenger": "Spazzino",
    "Scavenger": "Spazzino",
    # Renoir's Drafts
    "RenoirsDrafts.GoldenTree": "Albero Dorato",
    "RenoirsDraft.GoldenTree": "Albero Dorato",
    "RenoirDraft.GoldenTree": "Albero Dorato",
    "GoldenTree": "Albero Dorato",
    "RenoirsDrafts.Entrance": "Albero Dorato",
    "RenoirsDraft.Entrance": "Albero Dorato",
    "RenoirDraft.Entrance": "Albero Dorato",
    "RenoirsDrafts.Entry": "Entrata",
    "RenoirsDraft.Entry": "Entrata",
    "RenoirDraft.Entry": "Entrata",
    "WorldMap.RenoirsDraftEntry": "Entrata",
    "WorldMap.RenoirDraftEntry": "Entrata",
    # Crimson Forest
    "CleaOrangeForest.CenterPlazza": "Posatoio Cremisi",
    "CleaOrangeForest.Plazza": "Posatoio Cremisi",
    "CrimsonForest.CenterPlazza": "Posatoio Cremisi",
    "CrimsonForest.Plazza": "Posatoio Cremisi",
    "CrimsonForest.Plaza": "Posatoio Cremisi",
    "CenterPlazza": "Posatoio Cremisi",
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
    # Endless Night Sanctuary
    "EndlessNightSanctuary.Arena": "Percorso del Guerriero",
    "EndlessNightSanctuary.WarriorsRoute": "Percorso del Guerriero",
    "WarriorsRoute": "Percorso del Guerriero",
    "EndlessNightSanctuary.Totem": "Totem della Notte",
    "EndlessNightSanctuary.NightTotem": "Totem della Notte",
    "NightTotem": "Totem della Notte",
    # Sunless Cliffs
    "ChromaZoneEntrance.Cave": "Portale Chroma",
    "SunlessCliffs.Cave": "Portale Chroma",
    "SunlessCliffs.ChromaPortal": "Portale Chroma",
    "SunlessCliffs.Entry": "Portale Chroma",
    "SunlessCliffs.Entrance": "Portale Chroma",
    "SunlessCliffs": "Portale Chroma",
    "ChromaPortal": "Portale Chroma",
    # Sirene's Dress
    "SireneSmallLevel.Inside": "Glissando",
    "SireneDress.Inside": "Glissando",
    "Sirene.Inside": "Glissando",
    "SireneDress.Entrance": "Entrata",
    "SireneSmallLevel.Entry": "Entrata",
    "SireneDress.Glissando": "Glissando",
    # The Reacher
    "Reacher.Mountain": "Montagna",
    "TheReacher.Mountain": "Montagna",
    "Mountain": "Montagna",
    "Reacher.LadderArea": "Zona della Scala",
    "TheReacher.LadderArea": "Zona della Scala",
    "LadderArea": "Zona della Scala",
    "Reacher.FogArea": "Zona Nebbiosa",
    "TheReacher.FogArea": "Zona Nebbiosa",
    "FogArea": "Zona Nebbiosa",
    "TheReacher.FoggyArea": "Zona Nebbiosa",
    "FoggyArea": "Zona Nebbiosa",
    "Reacher.MountainTop": "Cima",
    "TheReacher.MountainTop": "Cima",
    "MountainTop": "Cima",
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
    "CleaWorkshop.BrokenLampmaster": "Concezione Spezzata",
    "PaintingWorkshop.BrokenLampmaster": "Concezione Spezzata",
    "BrokenLampmaster": "Concezione Spezzata",
    "PaintingWorkshop.BrokenConception": "Concezione Spezzata",
    "PaintingWorkshop.Entry": "Concezione Spezzata",
    "PaintingWorkshop.Entrance": "Concezione Spezzata",
    "PaintingWorkshop": "Concezione Spezzata",
    "TheCanvas.Entry": "Entrata",
    "TheCanvas.Entrance": "Entrata",
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


def format_checkpoint_tag(tag: str, lang: str = "en", zone: str = "") -> str:
    """Returns the official in-game Expedition Flag name for a given SpawnPoint tag."""
    if not tag:
        return ""
    clean_tag = tag.removeprefix("Level.SpawnPoint.")
    parts = clean_tag.split(".")
    suffix = parts[-1]
    if suffix in ("WorldMap", "Generic", "Dynamic", "Editor", "todelete", "None", "Default"):
        return ""

    name_dict = CHECKPOINT_NAMES_IT if lang.startswith("it") else CHECKPOINT_NAMES_EN
    fallback_dict = CHECKPOINT_NAMES_EN

    # 1. Full dotted tag lookup (e.g. AncientSanctuary.RedForest, EsquieNest.Francois)
    if "." in clean_tag:
        res = name_dict.get(clean_tag) or fallback_dict.get(clean_tag)
        if res:
            return res
        for k, v in name_dict.items():
            if k.lower() == clean_tag.lower():
                return v
        for k, v in fallback_dict.items():
            if k.lower() == clean_tag.lower():
                return v

    clean_tag_lower = clean_tag.lower()
    suffix_lower = suffix.lower()
    norm_suffix = re.sub(r"[^a-z0-9]", "", suffix_lower)
    norm_clean = re.sub(r"[^a-z0-9]", "", clean_tag_lower)

    # 2. Contextual zone matching if zone is available
    if zone:
        z_norm = strip_accents(zone).lower()

        # Zone-specific overrides
        if "abbest" in z_norm and norm_suffix == "arena":
            return "Entrata" if lang.startswith("it") else "Entrance"

        if "ancient" in z_norm or "santuario" in z_norm:
            if norm_suffix in ("redforest",):
                return "Entrata" if lang.startswith("it") else "Entrance"
            if norm_suffix in ("giantbellalley", "sanctuarymaze"):
                return "Labirinto del Santuario" if lang.startswith("it") else "Sanctuary Maze"
            if norm_suffix in ("arena", "tanksarena"):
                return (
                    "Vicolo della Grande Campana" if lang.startswith("it") else "Giant Bell Alley"
                )

        if any(k in z_norm for k in ("crimson", "orange", "cremisi")) and norm_suffix in (
            "plazza",
            "plaza",
            "centerplazza",
        ):
            return "Posatoio Cremisi" if lang.startswith("it") else "Crimson Perch"

        if any(k in z_norm for k in ("night", "notte", "twilight")):
            if norm_suffix == "arena":
                return "Percorso del Guerriero" if lang.startswith("it") else "Warrior's Route"
            if norm_suffix == "totem":
                return "Totem della Notte" if lang.startswith("it") else "Night Totem"

        if any(k in z_norm for k in ("esoteric", "esoteriche")) and norm_suffix in ("cliffbottom",):
            return "Relitti di Lumière" if lang.startswith("it") else "Lumiere's Wrecks"

        if any(k in z_norm for k in ("esquie", "nest", "nido")):
            if norm_suffix in ("gestralentry", "entrance", "entry"):
                return "Entrata" if lang.startswith("it") else "Entrance"
            if "francois" in norm_suffix:
                return "Grotta di François" if lang.startswith("it") else "Francois' Cave"

        if any(k in z_norm for k in ("leaves", "foglie")) and norm_suffix in (
            "crimsonperch",
            "plazza",
            "plaza",
            "centerplazza",
            "resinveilgrove",
        ):
            return "Boschetto del Velo di Resina" if lang.startswith("it") else "Resinveil Grove"

        if any(k in z_norm for k in ("battlefield", "campo di battaglia")):
            if norm_suffix in ("mainruins", "fortruins"):
                return "Rovine del Forte" if lang.startswith("it") else "Fort Ruins"
            if norm_suffix in ("battlefield", "vanguardpoint"):
                return "Punto di Avanguardia" if lang.startswith("it") else "Vanguard Point"
            if norm_suffix in ("sidebattlefield",):
                return "Campo di Battaglia" if lang.startswith("it") else "Battlefield"
            if norm_suffix in ("duallistarena", "ancientbridge"):
                return "Ponte Antico" if lang.startswith("it") else "Ancient Bridge"

        if any(k in z_norm for k in ("frozen", "ghiaccia")):
            if norm_suffix in ("cavestation", "iceboundterminal"):
                return "Capolinea Ghiacciato" if lang.startswith("it") else "Icebound Terminal"
            if norm_suffix in ("caveforest", "icedheart"):
                return "Cuore Ghiacciato" if lang.startswith("it") else "Iced Heart"
            if norm_suffix in ("trainstation", "iceboundtrainstation"):
                return (
                    "Stazione Ferroviaria Ghiacciata"
                    if lang.startswith("it")
                    else "Icebound Train Station"
                )
            if norm_suffix in ("frozenlakes", "glacialfalls"):
                return "Cascate Glaciali" if lang.startswith("it") else "Glacial Falls"

        if (
            "gestral" in z_norm
            and ("village" in z_norm or "villaggio" in z_norm)
            and norm_suffix in ("villageentry", "entrance", "entry", "villangeentry")
        ):
            return "Entrata" if lang.startswith("it") else "Entrance"

        if "monolith" in z_norm or "monolite" in z_norm:
            if norm_suffix in ("springmeadows", "taintedmeadows"):
                return "Prati Corrotti" if lang.startswith("it") else "Tainted Meadows"
            if norm_suffix in ("goblu", "waters", "taintedwaters"):
                return "Acque Corrotte" if lang.startswith("it") else "Tainted Waters"
            if norm_suffix in ("ancientsanctuary", "taintedsanctuary"):
                return "Santuario Corrotto" if lang.startswith("it") else "Tainted Sanctuary"
            if norm_suffix in ("seacliff", "taintedcliffs"):
                return "Scogliere Corrotte" if lang.startswith("it") else "Tainted Cliffs"
            if norm_suffix in ("forgottenbattlefield", "taintedbattlefield"):
                return (
                    "Campo di Battaglia Corrotto"
                    if lang.startswith("it")
                    else "Tainted Battlefield"
                )
            if norm_suffix in ("monocomountain", "taintedhearts"):
                return "Cuori Corrotti" if lang.startswith("it") else "Tainted Hearts"
            if norm_suffix in ("lumiere", "taintedlumiere"):
                return "Lumière Corrotta" if lang.startswith("it") else "Tainted Lumiere"

        if (
            "monoco" in z_norm
            and "mountain" not in z_norm
            and "montagna" not in z_norm
            and norm_suffix in ("insidestation", "station", "monocostation")
        ):
            return "Stazione di Monoco" if lang.startswith("it") else "Monoco's Station"

        if any(k in z_norm for k in ("siren", "dress", "abito")) and norm_suffix in (
            "inside",
            "glissando",
        ):
            return "Glissando"

        if "lumiere" in z_norm:
            if "old" in z_norm or "vecchia" in z_norm:
                if norm_suffix in ("brokenbuildings", "broken", "entrance", "entry"):
                    return "Entrata" if lang.startswith("it") else "Entrance"
                if norm_suffix in ("manorarena", "manorgardens"):
                    return "Giardini del Maniero" if lang.startswith("it") else "Manor Gardens"
                if norm_suffix in ("lunepath", "rightstreet"):
                    return "Via Destra" if lang.startswith("it") else "Right Street"
                if norm_suffix in ("maellepath", "leftstreet"):
                    return "Via Sinistra" if lang.startswith("it") else "Left Street"
                if norm_suffix in ("alphaarena", "alphaarea", "trainstationruins"):
                    return (
                        "Rovine della Stazione" if lang.startswith("it") else "Train Station Ruins"
                    )
            else:
                if norm_suffix in ("dock", "harbour"):
                    return "Porto" if lang.startswith("it") else "Harbour"
                if norm_suffix in ("bigplazza", "centralplaza", "plazza", "plaza"):
                    return "Piazza Centrale" if lang.startswith("it") else "Central Plaza"
                if norm_suffix in ("crumblingbuildings", "shatteredalley"):
                    return "Vicolo Frantumato" if lang.startswith("it") else "Shattered Alley"
                if norm_suffix in ("opera", "operahouse"):
                    return "Teatro dell'Opera" if lang.startswith("it") else "Opera House"
                if norm_suffix in ("gardens", "manorgardens", "lumieresgardens"):
                    return "Giardini di Lumière" if lang.startswith("it") else "Lumiere's Gardens"
                if norm_suffix in ("curator", "trainstationruins", "crookedtowerwalkway"):
                    return (
                        "Passerella della Torre Storta"
                        if lang.startswith("it")
                        else "Crooked Tower Walkway"
                    )

        if any(k in z_norm for k in ("workshop", "pittura", "atelier", "canvas", "tela")):
            if norm_suffix in ("brokenlampmaster", "brokenconception"):
                if "canvas" in z_norm or "tela" in z_norm:
                    return "Entrata" if lang.startswith("it") else "Entrance"
                return "Concezione Spezzata" if lang.startswith("it") else "Broken Conception"
            if ("canvas" in z_norm or "tela" in z_norm) and norm_suffix in ("entrance", "entry"):
                return "Entrata" if lang.startswith("it") else "Entrance"

        if any(k in z_norm for k in ("renoir", "draft", "bozze")):
            if norm_suffix in ("goldentree", "tree"):
                return "Albero Dorato" if lang.startswith("it") else "Golden Tree"
            if norm_suffix in ("entrance", "entry"):
                if (
                    "tree" in clean_tag_lower
                    or "golden" in clean_tag_lower
                    or "gold" in clean_tag_lower
                ):
                    return "Albero Dorato" if lang.startswith("it") else "Golden Tree"
                return "Entrata" if lang.startswith("it") else "Entrance"

        if any(k in z_norm for k in ("spring", "prati")) and norm_suffix in (
            "oldexpeditionercamp",
            "oldexpeditionnercamp",
            "abandonedcamp",
            "abandonedexpeditionercamp",
        ):
            return (
                "Accampamento Abbandonato"
                if lang.startswith("it")
                else "Abandoned Expeditioner Camp"
            )

        if any(k in z_norm for k in ("stone wave", "seacliff", "onda di pietra")):
            if "cave" in z_norm or "grotta" in z_norm:
                if norm_suffix in ("vista", "entrance", "entry"):
                    return "Entrata" if lang.startswith("it") else "Entrance"
            else:
                if norm_suffix in ("zeppelinentry", "entrance", "entry"):
                    return "Entrata" if lang.startswith("it") else "Entrance"
                if norm_suffix in ("village", "oldfarm"):
                    return "Vecchia Fattoria" if lang.startswith("it") else "Old Farm"
                if norm_suffix in ("caves", "tidecaverns"):
                    return "Caverne della Marea" if lang.startswith("it") else "Tide Caverns"

        if any(k in z_norm for k in ("sunless", "chroma", "senza sole")) and norm_suffix in (
            "cave",
            "chromaportal",
        ):
            return "Portale Chroma" if lang.startswith("it") else "Chroma Portal"

        if any(k in z_norm for k in ("reacher", "scalatore")):
            if norm_suffix in ("mountaintop", "peak"):
                return "Cima" if lang.startswith("it") else "Peak"
            if norm_suffix in ("fogarea", "foggyarea"):
                return "Zona Nebbiosa" if lang.startswith("it") else "Foggy Area"

        if "visages" in z_norm or "volti" in z_norm:
            if norm_suffix in ("visagesarena", "arena", "peak", "peaks"):
                return "Picco" if lang.startswith("it") else "Peak"
            if norm_suffix in ("sadness", "sadnessvale"):
                return "Valle della Tristezza" if lang.startswith("it") else "Sadness Vale"
            if norm_suffix in ("anger", "angervale"):
                return "Valle della Rabbia" if lang.startswith("it") else "Anger Vale"
            if norm_suffix in ("joy", "joyvale"):
                return "Valle della Gioia" if lang.startswith("it") else "Joy Vale"

        if any(k in z_norm for k in ("yellow", "harvest", "giallo")):
            if norm_suffix in ("lake", "harvestershollow"):
                return "Conca del Mietitore" if lang.startswith("it") else "Harvester's Hollow"
            if norm_suffix in ("arena", "yellowspirewrecks"):
                return (
                    "Relitti della Guglia Gialla"
                    if lang.startswith("it")
                    else "Yellow Spire Wrecks"
                )

    # 3. Direct dictionary lookup by suffix / clean_tag
    res = name_dict.get(suffix) or fallback_dict.get(suffix)
    if res:
        return res
    for k, v in name_dict.items():
        if re.sub(r"[^a-z0-9]", "", k.lower()) in (norm_suffix, norm_clean):
            return v
    for k, v in fallback_dict.items():
        if re.sub(r"[^a-z0-9]", "", k.lower()) in (norm_suffix, norm_clean):
            return v

    # 4. Spacing fallback
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", suffix)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced).strip()
    if spaced.lower() in ("entry", "entrance"):
        return "Entrata" if lang.startswith("it") else "Entrance"
    return spaced


def format_zone_name(raw_name: str, lang: str = "en") -> str:
    """Converts internal Unreal Engine map names (e.g. Level_Sirene_Main_V2) to player-friendly titles."""
    if not raw_name:
        return "In esplorazione" if lang.startswith("it") else "Exploring"

    main_menu_names = {
        "mainmenu",
        "main_menu",
        "main menu",
        "bootstrap",
        "map_game_bootstrap",
        "map game bootstrap",
        "map_mainmenu",
        "title",
        "titlescreen",
        "frontend",
        "entry",
    }
    raw_lower = raw_name.lower().strip()
    if raw_lower in main_menu_names or "bootstrap" in raw_lower or "mainmenu" in raw_lower:
        return "Nel menu principale" if lang.startswith("it") else "Main Menu"

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
            cleaned = cleaned.removeprefix(prefix)
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


def format_enemy_name(enemy_name: str) -> str:
    """Formats and normalizes enemy names, converting 'Chromatic' to in-game official 'Alpha' and tier formatting."""
    if not enemy_name:
        return ""
    if "UObject:" in enemy_name or "0x" in enemy_name:
        return ""

    formatted = enemy_name
    # Format T1 / T2 / T3 suffix as (Tier 1) / (Tier 2) / (Tier 3)
    formatted = re.sub(r"\bT(\d+)\b", r"(Tier \1)", formatted)

    # In-game chromatic variants are officially called 'Alpha'
    formatted = re.sub(r"\bChromatic\b", "Alpha", formatted, flags=re.IGNORECASE)
    formatted = re.sub(r"\bCromatic[oaie]\b", "Alpha", formatted, flags=re.IGNORECASE)

    return formatted.strip()


def resolve_tower_trial(enemy_name: str) -> tuple[tuple[int, int] | str | None, str]:
    """Determines the (stage, trial) in Endless Tower and the clean boss/enemy name based on official in-game names."""
    if not enemy_name:
        return None, enemy_name
    normalized = format_enemy_name(enemy_name)
    cleaned = re.sub(r"\(Tier \d+\)", "", normalized, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bT\d+\b", "", cleaned, flags=re.IGNORECASE).lower()

    for stage_info, boss_name, enemy_groups in ENDLESS_TOWER_TRIALS:
        if all(any(variant.lower() in cleaned for variant in group) for group in enemy_groups):
            final_enemy = boss_name if boss_name else normalized
            return stage_info, final_enemy

    return None, normalized
