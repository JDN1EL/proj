#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes adicionais da Beta: transferir, adicionar, convocar e abrir EDIT."""
from __future__ import annotations
import argparse
import hashlib
import sys
import unittest
from pathlib import Path

import pes2018_editor_xbox360_v0_4 as editor
from pes2018_stfs import STFSReader

class BetaOperations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = Path(cls.data_path).read_bytes()
        cls.base = editor.parse_file(cls.raw)

    def clone(self):
        return editor.parse_file(bytearray(self.raw))

    def test_add_preserves_existing_associations(self):
        parsed = self.clone()
        source_idx, pid = next((i, pid) for i, r in enumerate(parsed.rosters)
                               for pid in r['player_ids'] if pid)
        target_idx = next(i for i, r in enumerate(parsed.rosters)
                          if i != source_idx and 0 in r['player_ids'] and pid not in r['player_ids'])
        original_teams = [i for i, r in enumerate(parsed.rosters) if pid in r['player_ids']]
        slot = editor.add_player_to_roster(parsed, target_idx, pid, 77)
        self.assertEqual(parsed.rosters[target_idx]['player_ids'][slot], pid)
        self.assertEqual(set(i for i, r in enumerate(parsed.rosters) if pid in r['player_ids']), set(original_teams + [target_idx]))
        self.assertEqual(parsed.rosters[target_idx]['numbers'][slot], 77)
        reparsed = editor.parse_file(parsed.data)
        self.assertIn(pid, reparsed.rosters[target_idx]['player_ids'])

    def test_transfer_removes_source_and_adds_destination(self):
        parsed = self.clone()
        source_idx, pid = next((i, pid) for i, r in enumerate(parsed.rosters)
                               for pid in r['player_ids'] if pid)
        target_idx = next(i for i, r in enumerate(parsed.rosters)
                          if i != source_idx and 0 in r['player_ids'] and pid not in r['player_ids'])
        before_players = bytes(parsed.data[editor.PLAYER_TABLE_OFFSET:editor.TEAM_TABLE_OFFSET])
        before_teams = bytes(parsed.data[editor.TEAM_TABLE_OFFSET:editor.ROSTER_TABLE_OFFSET])
        before_tactics = bytes(parsed.data[editor.TACTICS_TABLE_OFFSET:])
        before_all = bytes(parsed.data)
        editor.transfer_player_between_teams(parsed, source_idx, target_idx, pid, 23)
        changed = [i for i, (a, b) in enumerate(zip(before_all, parsed.data)) if a != b]
        self.assertTrue(changed)
        self.assertTrue(all(editor.ROSTER_TABLE_OFFSET <= i < editor.TACTICS_TABLE_OFFSET for i in changed),
                        "A operação de elenco alterou bytes fora da tabela de elencos")
        self.assertNotIn(pid, parsed.rosters[source_idx]['player_ids'])
        self.assertIn(pid, parsed.rosters[target_idx]['player_ids'])
        self.assertEqual(bytes(parsed.data[editor.PLAYER_TABLE_OFFSET:editor.TEAM_TABLE_OFFSET]), before_players)
        self.assertEqual(bytes(parsed.data[editor.TEAM_TABLE_OFFSET:editor.ROSTER_TABLE_OFFSET]), before_teams)
        self.assertEqual(bytes(parsed.data[editor.TACTICS_TABLE_OFFSET:]), before_tactics)
        reparsed = editor.parse_file(parsed.data)
        self.assertNotIn(pid, reparsed.rosters[source_idx]['player_ids'])
        self.assertIn(pid, reparsed.rosters[target_idx]['player_ids'])

    def test_call_up_is_additive_and_preserves_source(self):
        parsed = self.clone()
        source_idx, pid = next((i, pid) for i, r in enumerate(parsed.rosters)
                               for pid in r['player_ids'] if pid)
        target_idx = next(i for i, r in enumerate(parsed.rosters)
                          if i != source_idx and 0 in r['player_ids'] and pid not in r['player_ids'])
        editor.add_player_to_roster(parsed, target_idx, pid, 12)  # mesma gravação de roster usada pela convocação
        self.assertIn(pid, parsed.rosters[source_idx]['player_ids'])
        self.assertIn(pid, parsed.rosters[target_idx]['player_ids'])

    def test_alphabetical_key_ignores_accents_and_case(self):
        self.assertEqual(editor.alphabetical_key("ÁLVAREZ"), editor.alphabetical_key("alvarez"))
        self.assertLess(editor.alphabetical_key("Álvaro"), editor.alphabetical_key("Zidane"))

    def test_free_agent_can_be_added(self):
        parsed = self.clone()
        assigned = {pid for r in parsed.rosters for pid in r['player_ids'] if pid}
        pid = next(pid for pid in parsed.players if pid not in assigned)
        target_idx = next(i for i, r in enumerate(parsed.rosters) if 0 in r['player_ids'])
        editor.add_player_to_roster(parsed, target_idx, pid, 0)
        self.assertIn(pid, parsed.rosters[target_idx]['player_ids'])

    def test_transfer_preserves_shirt_number_when_unspecified(self):
        parsed = self.clone()
        source_idx, pid = next((i, pid) for i, r in enumerate(parsed.rosters)
                               for slot, pid in enumerate(r['player_ids']) if pid and r['numbers'][slot] != 0)
        source_slot = parsed.rosters[source_idx]['player_ids'].index(pid)
        old_number = parsed.rosters[source_idx]['numbers'][source_slot]
        target_idx = next(i for i, r in enumerate(parsed.rosters)
                          if i != source_idx and 0 in r['player_ids'] and pid not in r['player_ids'])
        new_slot = editor.transfer_player_between_teams(parsed, source_idx, target_idx, pid, None)
        self.assertEqual(parsed.rosters[target_idx]['numbers'][new_slot], old_number)

    def test_failed_transfer_is_atomic(self):
        parsed = self.clone()
        source_idx, pid = next((i, pid) for i, r in enumerate(parsed.rosters)
                               for pid in r['player_ids'] if pid)
        before = bytes(parsed.data)
        with self.assertRaises(ValueError):
            editor.transfer_player_between_teams(parsed, source_idx, source_idx, pid)
        self.assertEqual(bytes(parsed.data), before)

    def test_edit_package_contains_readable_data_bin(self):
        reader = STFSReader(self.edit_path)
        entries, _ = reader.list_entries(verify_hash=True)
        item = next(e for e in entries if not e['is_dir'] and e['name'].casefold() == 'data.bin')
        raw, _ = reader.read_chain(item['start_block'], item['size'], item['allocated_blocks'], verify_hash=True)
        parsed = editor.parse_file(raw)
        self.assertEqual(len(raw), 5_203_344)
        self.assertFalse(parsed.read_only)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('data_bin')
    ap.add_argument('--edit', help='Pacote EDIT00000000 CON para validar extração')
    args = ap.parse_args()
    BetaOperations.data_path = args.data_bin
    BetaOperations.edit_path = args.edit
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BetaOperations)
    if not args.edit:
        suite = unittest.TestSuite(t for t in suite if t._testMethodName != 'test_edit_package_contains_readable_data_bin')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)

if __name__ == '__main__':
    main()
