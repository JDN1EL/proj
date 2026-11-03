#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes binários para uma ou mais variantes de data.bin PES 2018.
Uso: python testar_editor_PES2018.py data_original.bin data_modificado.bin
"""
from __future__ import annotations
import argparse
import struct
import unittest
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location('editor_v04', str(Path(__file__).with_name('pes2018_editor_xbox360_v0_4.py')))
editor = importlib.util.module_from_spec(spec)
import sys
sys.modules['editor_v04'] = editor
spec.loader.exec_module(editor)


class BinaryVariantTests(unittest.TestCase):
    def test_counts_and_layout(self):
        s = editor.summarize(self.parsed)
        self.assertGreater(self.parsed.player_count, 0)
        self.assertGreater(self.parsed.team_count, 0)
        self.assertEqual(self.parsed.team_count, self.parsed.roster_count)
        self.assertFalse(self.parsed.warnings, self.parsed.warnings)
        self.assertFalse(self.parsed.read_only)
        self.assertEqual(len(self.parsed.teams), self.parsed.team_count)
        self.assertEqual(len(self.parsed.rosters), self.parsed.team_count)
        self.assertEqual(len(self.parsed.tactics), self.parsed.team_count)
        self.assertTrue(s["team_roster_ids_match"])

    def test_team_roster_and_tactics_link_by_id(self):
        for team, roster in zip(self.parsed.teams, self.parsed.rosters):
            self.assertEqual(team["id"], roster["team_id"])
            self.assertIn(team["id"], self.parsed.tactics)
            self.assertEqual(team["id"], self.parsed.tactics[team["id"]]["team_id"])
        for roster in self.parsed.rosters:
            seen_empty = False
            for pid in roster["player_ids"]:
                if not pid:
                    seen_empty = True
                else:
                    self.assertFalse(seen_empty, "Elenco contém lacuna antes de jogador")
                    self.assertIn(pid, self.parsed.players)

    def test_tactics_record_has_three_plans_and_nine_formations(self):
        first = self.parsed.tactics[self.parsed.teams[0]["id"]]
        self.assertEqual(len(first["presets"]), 3)
        self.assertTrue(all(len(p["formations"]) == 3 for p in first["presets"]))
        self.assertTrue(all(len(f["x"]) == 11 and len(f["y"]) == 11 and len(f["positions"]) == 11
                            for p in first["presets"] for f in p["formations"]))

    def test_roundtrip_without_changes(self):
        editor.validate_roundtrip(self.parsed)
        self.assertEqual(bytes(self.parsed.data), self.raw)

    def test_copy_tactics_and_roster_as_template(self):
        if self.parsed.team_count < 2:
            self.skipTest("Arquivo tem menos de duas equipes")
        data = bytearray(self.raw)
        clone = editor.parse_file(data)
        editor.copy_team_roster_and_tactics(clone, 0, 1)
        self.assertEqual(clone.rosters[0]["player_ids"], clone.rosters[1]["player_ids"])
        self.assertEqual(clone.rosters[0]["numbers"], clone.rosters[1]["numbers"])
        target_id = clone.teams[0]["id"]
        source_id = clone.teams[1]["id"]
        self.assertEqual(clone.tactics[target_id]["team_id"], target_id)
        self.assertEqual(clone.tactics[target_id]["raw"][4:], clone.tactics[source_id]["raw"][4:])
        reparsed = editor.parse_file(clone.data)
        self.assertEqual(reparsed.rosters[0]["player_ids"], reparsed.rosters[1]["player_ids"])
        self.assertFalse(reparsed.warnings, reparsed.warnings)


    def test_multicolumn_sort_keeps_previous_criteria(self):
        rows = [
            {"name": "Zeta", "id": 20},
            {"name": "Alpha", "id": 10},
            {"name": "Alpha", "id": 30},
            {"name": "Beta", "id": 10},
        ]
        # ID foi clicado depois de Nome: ID é principal e Nome continua
        # como critério secundário, sem ser perdido.
        ordered = editor.stable_multisort(rows, lambda row, col: row[col], [("id", False), ("name", False)])
        self.assertEqual([(r["id"], r["name"]) for r in ordered], [(10, "Alpha"), (10, "Beta"), (20, "Zeta"), (30, "Alpha")])
        # Reverter ID não remove o critério Nome.
        ordered = editor.stable_multisort(rows, lambda row, col: row[col], [("id", True), ("name", False)])
        self.assertEqual([(r["id"], r["name"]) for r in ordered], [(30, "Alpha"), (20, "Zeta"), (10, "Alpha"), (10, "Beta")])

    def test_force_open_recovery_marks_read_only(self):
        damaged = bytearray(self.raw)
        struct.pack_into(">H", damaged, editor.TEAM_COUNT_OFFSET, 0)
        with self.assertRaises(ValueError):
            editor.parse_file(damaged)
        recovered = editor.parse_file(damaged, recover=True)
        self.assertTrue(recovered.read_only)
        self.assertTrue(recovered.warnings)

    def test_mismatched_roster_count_is_recoverable(self):
        if self.parsed.roster_count < 2:
            self.skipTest("Poucos elencos")
        damaged = bytearray(self.raw)
        struct.pack_into(">H", damaged, editor.ROSTER_COUNT_OFFSET, self.parsed.roster_count - 1)
        recovered = editor.parse_file(damaged)
        self.assertTrue(recovered.read_only)
        self.assertTrue(any("contagens diferentes" in w for w in recovered.warnings))


class VariantSuite(unittest.TestSuite):
    def __init__(self, paths):
        tests = []
        for path in paths:
            raw = Path(path).read_bytes()
            parsed = editor.parse_file(raw)
            case = type(f"Tests_{Path(path).stem}", (BinaryVariantTests,), {})
            case.raw = raw
            case.parsed = parsed
            tests.extend(unittest.defaultTestLoader.loadTestsFromTestCase(case))
        super().__init__(tests)


def main():
    ap = argparse.ArgumentParser(description="Valida compatibilidade de um ou mais data.bin PES 2018")
    ap.add_argument("data_bin", nargs="+", help="um ou mais arquivos data.bin extraídos/descriptografados")
    args = ap.parse_args()
    suite = VariantSuite(args.data_bin)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
