#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Teste rápido da interface, da ordenação e do histórico.
Execute com uma janela gráfica disponível:
    python testar_interface_PES2018_v0.4.py caminho\\data.bin
O programa abre a interface oculta, faz alterações temporárias em memória e as desfaz.
Nenhum arquivo é salvo ou modificado.
"""
from __future__ import annotations
import argparse
import importlib.util
import sys
from pathlib import Path

APP_PATH = Path(__file__).with_name("pes2018_editor_xbox360_v0_4.py")
spec = importlib.util.spec_from_file_location("pes_editor_v04", APP_PATH)
editor = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = editor
spec.loader.exec_module(editor)


class TestEditor(editor.PesEditor):
    def open_initial_file(self):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_bin", help="data.bin PES 2018 extraído/descriptografado")
    args = ap.parse_args()
    raw = Path(args.data_bin).read_bytes()
    app = TestEditor()
    app.withdraw()
    try:
        app.load_file(args.data_bin)
        assert app.parsed is not None and not app.parsed.read_only
        original = bytes(app.parsed.data)

        # Verifica a ordenação acumulativa em uma Treeview real.
        tree = app.team_tree
        tree.delete(*tree.get_children())
        for iid, name, tid, count in [
            ("a", "Zeta", 20, 2), ("b", "Alpha", 10, 3),
            ("c", "Alpha", 30, 1), ("d", "Beta", 10, 5),
        ]:
            tree.insert("", "end", iid=iid, text=name, values=(tid, count))
        app._tree_sort_state[str(tree)] = []
        app.sort_tree(tree, "#0")
        app.sort_tree(tree, "id", numeric=True)
        crit = app._tree_sort_state[str(tree)]
        assert [c[0] for c in crit] == ["id", "#0"]
        assert [tree.item(i, "text") for i in tree.get_children()] == ["Alpha", "Beta", "Zeta", "Alpha"]
        app.sort_tree(tree, "id", numeric=True)
        crit = app._tree_sort_state[str(tree)]
        assert crit[0][2] is True and crit[1][0] == "#0"

        # Recarrega a grade de times e testa histórico em dados reais.
        app.load_file(args.data_bin)
        app.active_team_index = 0
        roster = app.parsed.rosters[0]
        free_pid = next(pid for pid in app.parsed.players if pid not in roster["player_ids"])
        app.selected_library_id = free_pid
        app.number_var.set("73")
        before = bytes(app.parsed.data)
        app.add_player_to_team()
        assert free_pid in app.parsed.rosters[0]["player_ids"]
        app.undo_edit()
        assert bytes(app.parsed.data) == before
        app.redo_edit()
        assert free_pid in app.parsed.rosters[0]["player_ids"]
        app.undo_edit()
        assert bytes(app.parsed.data) == before

        # Testa alteração e reversão de nome de jogador.
        pid = next(iter(app.parsed.players))
        original_name = app.parsed.players[pid]["name"]
        app.load_player_details(pid)
        app.detail_entries["name"].set("TESTE HISTORICO PES")
        app.save_player_details()
        assert app.parsed.players[pid]["name"] == "TESTE HISTORICO PES"
        app.undo_edit()
        assert app.parsed.players[pid]["name"] == original_name
        app.redo_edit()
        assert app.parsed.players[pid]["name"] == "TESTE HISTORICO PES"
        app.undo_edit()

        # Testa a nova transferência pela interface e seu histórico.
        source_index, transfer_pid = next((i, pid) for i, r in enumerate(app.parsed.rosters)
                                          for pid in r["player_ids"] if pid)
        target_index = next(i for i, r in enumerate(app.parsed.rosters)
                            if i != source_index and 0 in r["player_ids"] and transfer_pid not in r["player_ids"])
        app.active_team_index = target_index
        app._apply_transfer(transfer_pid, source_index, target_index, None)
        assert transfer_pid not in app.parsed.rosters[source_index]["player_ids"]
        assert transfer_pid in app.parsed.rosters[target_index]["player_ids"]
        app.undo_edit()
        assert bytes(app.parsed.data) == original
        app.redo_edit()
        assert transfer_pid in app.parsed.rosters[target_index]["player_ids"]
        app.undo_edit()

        # Testa instruções contextuais para o botão de salvar.
        class Event: pass
        ev = Event(); ev.widget = app.save_button
        app._on_context_click(ev)
        assert "salvar uma cópia" in app.help_var.get().casefold()

        assert bytes(app.parsed.data) == original
        assert raw == original
        print("OK: interface, multisort, barra contextual, histórico e restauração binária.")
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
