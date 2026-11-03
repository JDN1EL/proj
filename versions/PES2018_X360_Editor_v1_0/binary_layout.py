# -*- coding: utf-8 -*-
"""Detecção conservadora dos layouts PES 2018 Xbox 360 conhecidos."""
from __future__ import annotations
import struct
from editor_core import PLAYER_TABLE_OFFSET, PLAYER_STRIDE, PLAYER_CAPACITY, TEAM_TABLE_OFFSET, TEAM_STRIDE, ROSTER_TABLE_OFFSET, ROSTER_STRIDE, TACTICS_TABLE_OFFSET, TACTICS_STRIDE

LAYOUTS = [{
    "id": "pes2018_x360_vanilla_compatible",
    "label": "PES 2018 Xbox 360 (layout conhecido; compatível com patches que preservam offsets)",
    "player_table": PLAYER_TABLE_OFFSET,
    "player_stride": PLAYER_STRIDE,
    "team_table": TEAM_TABLE_OFFSET,
    "team_stride": TEAM_STRIDE,
    "roster_table": ROSTER_TABLE_OFFSET,
    "roster_stride": ROSTER_STRIDE,
    "tactics_table": TACTICS_TABLE_OFFSET,
    "tactics_stride": TACTICS_STRIDE,
}]

def u16(data, off): return struct.unpack_from(">H", data, off)[0]

def detect_layout(data):
    if len(data) < ROSTER_TABLE_OFFSET + 32 * ROSTER_STRIDE:
        raise ValueError("Arquivo curto demais para o layout conhecido do PES 2018 Xbox 360.")
    players, teams, rosters = u16(data, 0x60), u16(data, 0x64), u16(data, 0x70)
    if not (1 <= players <= PLAYER_CAPACITY):
        raise ValueError(f"Contagem de jogadores fora do limite esperado: {players}.")
    if not (100 <= teams <= 2048):
        raise ValueError(f"Contagem de equipes incompatível: {teams}.")
    if not (1 <= rosters <= 4096):
        raise ValueError(f"Contagem de elencos incompatível: {rosters}.")
    if PLAYER_TABLE_OFFSET + players * PLAYER_STRIDE > len(data):
        raise ValueError("Tabela de jogadores ultrapassa o arquivo.")
    if TEAM_TABLE_OFFSET + teams * TEAM_STRIDE > ROSTER_TABLE_OFFSET:
        raise ValueError("Tabela de equipes conflita com a região de elencos.")
    if ROSTER_TABLE_OFFSET + rosters * ROSTER_STRIDE > len(data):
        raise ValueError("Tabela de elencos ultrapassa o arquivo.")
    # Check a sample of player IDs for plausible non-empty table data.
    nonzero = 0
    sample = min(players, 250)
    for i in range(sample):
        ref = struct.unpack_from(">I", data, PLAYER_TABLE_OFFSET + i * PLAYER_STRIDE)[0]
        if ref: nonzero += 1
    if nonzero < max(1, sample // 20):
        raise ValueError("A tabela de jogadores não passou na validação estrutural.")
    layout = dict(LAYOUTS[0])
    layout.update({"players": players, "teams": teams, "rosters": rosters, "bytes": len(data)})
    return layout
