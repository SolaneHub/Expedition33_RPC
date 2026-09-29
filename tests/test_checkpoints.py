import unittest

from expedition33_rpc.detection.game_data import (
    format_checkpoint_tag,
)
from expedition33_rpc.detection.save_reader import SaveFileReader


class TestCheckpointMappings(unittest.TestCase):
    """Verifies all 57 user-specified checkpoint name fixes across English and Italian."""

    def test_all_57_checkpoints_en_and_it(self):
        cases = [
            # 1. Abbest Cave
            ("Abbest Cave", "Arena", "Entrance", "Entrata"),
            # 2. Ancient Sanctuary
            ("Ancient Sanctuary", "RedForest", "Entrance", "Entrata"),
            ("Ancient Sanctuary", "GiantBellAlley", "Sanctuary Maze", "Labirinto del Santuario"),
            ("Ancient Sanctuary", "Arena", "Giant Bell Alley", "Vicolo della Grande Campana"),
            # 3. Crimson Forest
            ("Crimson Forest", "Plazza", "Crimson Perch", "Posatoio Cremisi"),
            # 4. Endless Night Sanctuary
            ("Endless Night Sanctuary", "Arena", "Warrior's Route", "Percorso del Guerriero"),
            ("Endless Night Sanctuary", "Totem", "Night Totem", "Totem della Notte"),
            # 5. Esoteric Ruins
            ("Esoteric Ruins", "Cliff Bottom", "Lumiere's Wrecks", "Relitti di Lumière"),
            # 6. Esquie's Nest
            ("Esquie's Nest", "GestralEntry", "Entrance", "Entrata"),
            ("Esquie's Nest", "Francois", "Francois' Cave", "Grotta di François"),
            # 7. Falling Leaves
            ("Falling Leaves", "Crimson Perch", "Resinveil Grove", "Boschetto del Velo di Resina"),
            ("Falling Leaves", "CenterPlazza", "Resinveil Grove", "Boschetto del Velo di Resina"),
            # 8. Forgotten Battlefield
            ("Forgotten Battlefield", "Main Ruins", "Fort Ruins", "Rovine del Forte"),
            ("Forgotten Battlefield", "Battlefield", "Vanguard Point", "Punto di Avanguardia"),
            ("Forgotten Battlefield", "Side Battlefield", "Battlefield", "Campo di Battaglia"),
            ("Forgotten Battlefield", "DuallistArena", "Ancient Bridge", "Ponte Antico"),
            # 9. Frozen Hearts
            ("Frozen Hearts", "Cave Station", "Icebound Terminal", "Capolinea Ghiacciato"),
            ("Frozen Hearts", "Cave Forest", "Iced Heart", "Cuore Ghiacciato"),
            (
                "Frozen Hearts",
                "Train Station",
                "Icebound Train Station",
                "Stazione Ferroviaria Ghiacciata",
            ),
            ("Frozen Hearts", "Frozenlakes", "Glacial Falls", "Cascate Glaciali"),
            # 10. Gestral Village
            ("Gestral Village", "Village Entry", "Entrance", "Entrata"),
            # 11. Inside the Monolith
            ("Inside the Monolith", "Spring Meadows", "Tainted Meadows", "Prati Corrotti"),
            ("Inside the Monolith", "Goblu", "Tainted Waters", "Acque Corrotte"),
            ("Inside the Monolith", "Ancient Sanctuary", "Tainted Sanctuary", "Santuario Corrotto"),
            ("Inside the Monolith", "Sea Cliff", "Tainted Cliffs", "Scogliere Corrotte"),
            (
                "Inside the Monolith",
                "Forgotten Battlefield",
                "Tainted Battlefield",
                "Campo di Battaglia Corrotto",
            ),
            ("Inside the Monolith", "Monoco Mountain", "Tainted Hearts", "Cuori Corrotti"),
            ("Inside the Monolith", "Lumiere", "Tainted Lumiere", "Lumière Corrotta"),
            # 12. Lumiere Act 3
            ("Lumiere", "Dock", "Harbour", "Porto"),
            ("Lumiere", "Big Plazza", "Central Plaza", "Piazza Centrale"),
            ("Lumiere", "Crumbling Buildings", "Shattered Alley", "Vicolo Frantumato"),
            ("Lumiere", "Opera", "Opera House", "Teatro dell'Opera"),
            ("Lumiere", "Manor Gardens", "Lumiere's Gardens", "Giardini di Lumière"),
            (
                "Lumiere",
                "Train Station Ruins",
                "Crooked Tower Walkway",
                "Passerella della Torre Storta",
            ),
            # 13. Monoco's Station
            ("Monoco's Station", "Inside Station", "Monoco's Station", "Stazione di Monoco"),
            # 14. Old Lumiere
            ("Old Lumiere", "Broken Buildings", "Entrance", "Entrata"),
            ("Old Lumiere", "Manor Arena", "Manor Gardens", "Giardini del Maniero"),
            ("Old Lumiere", "Lune Path", "Right Street", "Via Destra"),
            ("Old Lumiere", "Maelle Path", "Left Street", "Via Sinistra"),
            ("Old Lumiere", "Alpha Arena", "Train Station Ruins", "Rovine della Stazione"),
            # 15. Painting Workshop
            ("Painting Workshop", "Broken Lampmaster", "Broken Conception", "Concezione Spezzata"),
            # 16. Renoir's Drafts
            ("Renoir's Drafts", "Golden Tree", "Golden Tree", "Albero Dorato"),
            # 17. Siren's Dress
            ("Siren's Dress", "Inside", "Glissando", "Glissando"),
            # 18. Spring Meadows
            (
                "Spring Meadows",
                "Old Expeditioner Camp",
                "Abandoned Expeditioner Camp",
                "Accampamento Abbandonato",
            ),
            # 19. Stone Wave Cliffs
            ("Stone Wave Cliffs", "Zeppelin Entry", "Entrance", "Entrata"),
            ("Stone Wave Cliffs", "Village", "Old Farm", "Vecchia Fattoria"),
            ("Stone Wave Cliffs", "Caves", "Tide Caverns", "Caverne della Marea"),
            # 20. Stone Wave Cliffs Cave
            ("Stone Wave Cliffs Cave", "Vista", "Entrance", "Entrata"),
            # 21. Sunless Cliffs
            ("Sunless Cliffs", "Cave", "Chroma Portal", "Portale Chroma"),
            # 22. The Canvas
            ("The Canvas", "Broken Conception", "Entrance", "Entrata"),
            # 23. The Reacher
            ("The Reacher", "Mountain Top", "Peak", "Cima"),
            ("The Reacher", "Fog Area", "Foggy Area", "Zona Nebbiosa"),
            # 24. Visages
            ("Visages", "Visages Arena", "Peak", "Picco"),
            ("Visages", "Sadness", "Sadness Vale", "Valle della Tristezza"),
            ("Visages", "Anger", "Anger Vale", "Valle della Rabbia"),
            ("Visages", "Joy", "Joy Vale", "Valle della Gioia"),
            # 25. Yellow Harvest
            ("Yellow Harvest", "Lake", "Harvester's Hollow", "Conca del Mietitore"),
            ("Yellow Harvest", "Arena", "Yellow Spire Wrecks", "Relitti della Guglia Gialla"),
        ]

        for zone, tag, expected_en, expected_it in cases:
            with self.subTest(zone=zone, tag=tag):
                res_en = format_checkpoint_tag(tag, lang="en", zone=zone)
                res_it = format_checkpoint_tag(tag, lang="it", zone=zone)
                self.assertEqual(
                    res_en,
                    expected_en,
                    f"[{zone}] {tag} (EN): got {res_en!r}, expected {expected_en!r}",
                )
                self.assertEqual(
                    res_it,
                    expected_it,
                    f"[{zone}] {tag} (IT): got {res_it!r}, expected {expected_it!r}",
                )

    def test_unreal_spawnpoint_tags(self):
        ue_cases = [
            ("Level.SpawnPoint.AbbestCave.Arena", "Abbest Cave", "Entrance", "Entrata"),
            (
                "Level.SpawnPoint.AncientSanctuary.RedForest",
                "Ancient Sanctuary",
                "Entrance",
                "Entrata",
            ),
            (
                "Level.SpawnPoint.AncientSanctuary.GiantBellAlley",
                "Ancient Sanctuary",
                "Sanctuary Maze",
                "Labirinto del Santuario",
            ),
            (
                "Level.SpawnPoint.AncientSanctuary.Arena",
                "Ancient Sanctuary",
                "Giant Bell Alley",
                "Vicolo della Grande Campana",
            ),
            ("Level.SpawnPoint.EsquieNest.GestralEntry", "Esquie's Nest", "Entrance", "Entrata"),
            (
                "Level.SpawnPoint.EsquieNest.Francois",
                "Esquie's Nest",
                "Francois' Cave",
                "Grotta di François",
            ),
            ("Level.SpawnPoint.SeaCliff.ZeppelinEntry", "Stone Wave Cliffs", "Entrance", "Entrata"),
            (
                "Level.SpawnPoint.SeaCliff.Village",
                "Stone Wave Cliffs",
                "Old Farm",
                "Vecchia Fattoria",
            ),
            (
                "Level.SpawnPoint.SeaCliff.Caves",
                "Stone Wave Cliffs",
                "Tide Caverns",
                "Caverne della Marea",
            ),
            (
                "Level.SpawnPoint.StonewaveCliffsCave.Vista",
                "Stone Wave Cliffs Cave",
                "Entrance",
                "Entrata",
            ),
            (
                "Level.SpawnPoint.ForgottenBattlefield.MainRuins",
                "Forgotten Battlefield",
                "Fort Ruins",
                "Rovine del Forte",
            ),
            (
                "Level.SpawnPoint.ForgottenBattlefield.Battlefield",
                "Forgotten Battlefield",
                "Vanguard Point",
                "Punto di Avanguardia",
            ),
            (
                "Level.SpawnPoint.ForgottenBattlefield.SideBattlefield",
                "Forgotten Battlefield",
                "Battlefield",
                "Campo di Battaglia",
            ),
            (
                "Level.SpawnPoint.ForgottenBattlefield.DuallistArena",
                "Forgotten Battlefield",
                "Ancient Bridge",
                "Ponte Antico",
            ),
            (
                "Level.SpawnPoint.FrozenHearts.CaveStation",
                "Frozen Hearts",
                "Icebound Terminal",
                "Capolinea Ghiacciato",
            ),
            (
                "Level.SpawnPoint.FrozenHearts.CaveForest",
                "Frozen Hearts",
                "Iced Heart",
                "Cuore Ghiacciato",
            ),
            (
                "Level.SpawnPoint.FrozenHearts.TrainStation",
                "Frozen Hearts",
                "Icebound Train Station",
                "Stazione Ferroviaria Ghiacciata",
            ),
            (
                "Level.SpawnPoint.FrozenHearts.Frozenlakes",
                "Frozen Hearts",
                "Glacial Falls",
                "Cascate Glaciali",
            ),
            (
                "Level.SpawnPoint.MonolithInterior.Climb.SpringMeadows",
                "Inside the Monolith",
                "Tainted Meadows",
                "Prati Corrotti",
            ),
            (
                "Level.SpawnPoint.MonolithInterior.Climb.Goblu",
                "Inside the Monolith",
                "Tainted Waters",
                "Acque Corrotte",
            ),
            (
                "Level.SpawnPoint.MonolithInterior.Climb.AncientSanctuary",
                "Inside the Monolith",
                "Tainted Sanctuary",
                "Santuario Corrotto",
            ),
            (
                "Level.SpawnPoint.MonolithInterior.Climb.SeaCliff",
                "Inside the Monolith",
                "Tainted Cliffs",
                "Scogliere Corrotte",
            ),
            (
                "Level.SpawnPoint.MonolithInterior.Climb.ForgottenBattlefield",
                "Inside the Monolith",
                "Tainted Battlefield",
                "Campo di Battaglia Corrotto",
            ),
            (
                "Level.SpawnPoint.MonolithInterior.Climb.MonocoMountain",
                "Inside the Monolith",
                "Tainted Hearts",
                "Cuori Corrotti",
            ),
            (
                "Level.SpawnPoint.MonolithInterior.Climb.Lumiere",
                "Inside the Monolith",
                "Tainted Lumiere",
                "Lumière Corrotta",
            ),
            ("Level.SpawnPoint.LumiereAct03.Dock", "Lumiere", "Harbour", "Porto"),
            (
                "Level.SpawnPoint.LumiereAct03.BigPlazza",
                "Lumiere",
                "Central Plaza",
                "Piazza Centrale",
            ),
            (
                "Level.SpawnPoint.LumiereAct03.CrumblingBuildings",
                "Lumiere",
                "Shattered Alley",
                "Vicolo Frantumato",
            ),
            ("Level.SpawnPoint.LumiereAct03.Opera", "Lumiere", "Opera House", "Teatro dell'Opera"),
            (
                "Level.SpawnPoint.LumiereAct03.Gardens",
                "Lumiere",
                "Lumiere's Gardens",
                "Giardini di Lumière",
            ),
            (
                "Level.SpawnPoint.LumiereAct03.Curator",
                "Lumiere",
                "Crooked Tower Walkway",
                "Passerella della Torre Storta",
            ),
        ]

        for tag, zone, exp_en, exp_it in ue_cases:
            with self.subTest(tag=tag, zone=zone):
                res_en = format_checkpoint_tag(tag, lang="en", zone=zone)
                res_it = format_checkpoint_tag(tag, lang="it", zone=zone)
                self.assertEqual(res_en, exp_en)
                self.assertEqual(res_it, exp_it)

    def test_save_reader_zone_matching(self):
        reader = SaveFileReader()
        # Esquie Nest matches
        self.assertTrue(
            reader.is_checkpoint_for_zone(
                "LevelMain_EsquieNest",
                "Level.SpawnPoint.EsquieNest.Francois",
                "LevelMain_EsquieNest",
                "Esquie's Nest",
            )
        )
        self.assertTrue(
            reader.is_checkpoint_for_zone(
                "LevelMain_EsquieNest",
                "Level.SpawnPoint.EsquieNest.GestralEntry",
                "LevelMain_EsquieNest",
                "Esquie's Nest",
            )
        )
        # Continent & Menu must never match checkpoints
        self.assertFalse(
            reader.is_checkpoint_for_zone(
                "Level_WorldMap",
                "Level.SpawnPoint.EsquieNest.Francois",
                "Level_WorldMap",
                "The Continent",
            )
        )
        self.assertFalse(
            reader.is_checkpoint_for_zone(
                "Level_Bootstrap",
                "Level.SpawnPoint.AncientSanctuary.RedForest",
                "Level_Bootstrap",
                "Main Menu",
            )
        )


if __name__ == "__main__":
    unittest.main()
