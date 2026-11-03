#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PES 2018 Xbox 360 — editor conservador de data.bin (layout analisado).

Requer Python 3 no Windows. Usa somente a biblioteca padrão (Tkinter).
O arquivo original nunca é sobrescrito: a gravação é sempre feita em outro caminho.
Suporta variações de PES 2018 com contagens de jogadores/equipes diferentes,
detecta divergências e oferece abertura de recuperação em modo somente leitura.
Este programa edita o data.bin já extraído/descriptografado; não reempacota,
assina nem descriptografa um save/container Xbox 360.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import tempfile
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

# Estrutura confirmada no arquivo enviado
PLAYER_COUNT_OFFSET = 0x60
TEAM_COUNT_OFFSET = 0x64
ROSTER_COUNT_OFFSET = 0x70
PLAYER_TABLE_OFFSET = 0x7C
PLAYER_STRIDE = 0xBC                 # 188 bytes: data 0x74 + appearance 0x48
PLAYER_CAPACITY = 21000
TEAM_TABLE_OFFSET = PLAYER_TABLE_OFFSET + PLAYER_CAPACITY * PLAYER_STRIDE  # 0x3C3E5C
TEAM_STRIDE = 0x1E0                  # 480 bytes
ROSTER_TABLE_OFFSET = 0x46FF54
ROSTER_STRIDE = 0xA4                  # 164 bytes
TACTICS_TABLE_OFFSET = 0x488B74       # PES 2018: configurações táticas por equipe
TACTICS_STRIDE = 0x274                # 628 bytes por equipe
MAX_TEAM_COUNT = 510                  # capacidade conhecida do layout PES 2018
TEAM_NAME_REL = 0x98
TEAM_NAME_SIZE = 70
TEAM_SHORT_REL = 0xDE
TEAM_SHORT_SIZE = 3
ROSTER_PLAYERS_REL = 0x04
ROSTER_PLAYER_COUNT = 32
ROSTER_NUMBERS_REL = 0x84
PLAYER_ID_REL = 0x00
PLAYER_COMM_ID_REL = 0x04
PLAYER_NATION_REL = 0x0A
PLAYER_HEIGHT_REL = 0x0C
PLAYER_WEIGHT_REL = 0x0D
PLAYER_NAME_REL = 0x34
PLAYER_NAME_SIZE = 46
PLAYER_SHIRT_REL = 0x62
PLAYER_SHIRT_SIZE = 18
PLAYER_STATS_REL = 0x10

# Ordem lógica dos campos no bloco compacto de 36 bytes (283 bits usados).
# Os 5 bits finais são desconhecidos e são preservados sem alteração.
FIELD_LAYOUT: List[Tuple[str, int]] = [
    ("attack", 7), ("defense", 7), ("goalkeeping", 7), ("dribbling", 7), ("fk_motion", 4),
    ("finishing", 7), ("low_pass", 7), ("lofted_pass", 7), ("header", 7), ("form", 3), ("edited_player", 1),
    ("swerve", 7), ("catching", 7), ("clearing", 7), ("reflexes", 7), ("injury_resistance", 2), ("unknown_b", 1), ("edited_basic", 1),
    ("body_control", 7), ("physical_contact", 7), ("kicking_power", 7), ("explosive_power", 7), ("unknown_motion", 3), ("edited_regpos", 1),
    ("age", 6), ("reg_pos_code", 4), ("unknown_c", 1), ("play_style", 5),
    ("ball_control", 7), ("ball_winning", 7), ("weak_foot_accuracy", 2),
    ("jump", 7), ("dribble_arm_motion", 3), ("run_arm_motion", 3), ("corner_motion", 3), ("coverage", 7), ("weak_foot_usage", 2),
    ("play_cf", 2), ("play_ss", 2), ("play_lwf", 2), ("edited_playpos", 1),
    ("play_amf", 2), ("play_dmf", 2), ("play_cmf", 2), ("play_lmf", 2),
    ("play_rmf", 2), ("play_cb", 2), ("play_lb", 2), ("play_rb", 2),
    ("play_gk", 2), ("dribble_hunch_motion", 2), ("run_hunch_motion", 2), ("pk_motion", 2),
    ("place_kicking", 7), ("edited_ability", 1), ("stamina", 7), ("play_pos3", 2), ("speed", 7),
    ("edited_skill", 1), ("edited_style", 1), ("edited_com", 1), ("edited_motion", 1), ("base_copy", 1), ("unknown_d", 1), ("strong_foot", 1), ("unknown_e", 1),
    ("com_trickster", 1), ("com_maze_run", 1), ("com_speed_bullet", 1), ("com_incisive_run", 1), ("com_lb_expert", 1), ("com_early_cross", 1), ("com_long_ranger", 1),
    ("skill_scissors", 1),
]
SKILL_NAMES = [
    "scissors_feint", "flip_flap", "marseille_turn", "sombrero", "cut_behind_turn", "scotch_move",
    "heading", "long_range_drive", "knuckle_shot", "acrobatic_finishing", "heel_trick", "first_time_shot",
    "one_touch_pass", "weighted_pass", "pinpoint_crossing", "outside_curler", "rabona", "low_lofted_pass",
    "low_punt_trajectory", "long_throw", "gk_long_throw", "malicia", "man_marking", "track_back", "acrobatic_clear",
    "captaincy", "super_sub", "fighting_spirit",
]
COM_NAMES = ["trickster", "maze_run", "speed_bullet", "incisive_run", "lb_expert", "early_cross", "long_ranger"]
PLAY_STYLE_NAMES = {
    0: "None", 1: "Goal Poacher", 2: "Dummy Runner", 3: "Fox in the Box", 4: "Prolific Winger",
    5: "Classic No. 10", 6: "Hole Player", 7: "Box to Box", 8: "Anchor Man", 9: "The Destroyer",
    10: "Extra Frontman", 11: "Offensive Fullback", 12: "Defensive Fullback", 13: "Target Man",
    14: "Creative Playmaker", 15: "Build Up", 16: "Offensive Goalkeeper", 17: "Defensive Goalkeeper",
}
PLAY_POSITION_NAMES = ["CF", "SS", "LWF", "RWF", "AMF", "DMF", "CMF", "LMF", "RMF", "CB", "LB", "RB", "GK"]
PLAY_POSITION_FIELDS = [
    # Ordem apresentada na interface; o RWF (play_pos3) fica fisicamente
    # mais adiante no bloco compactado do arquivo.
    "play_cf", "play_ss", "play_lwf", "play_pos3", "play_amf", "play_dmf", "play_cmf",
    "play_lmf", "play_rmf", "play_cb", "play_lb", "play_rb", "play_gk",
]
SKILL_PT = {
    "scissors_feint": "finta de tesoura", "flip_flap": "elástico", "marseille_turn": "giro de Marselha",
    "sombrero": "chapéu", "cut_behind_turn": "corte para trás", "scotch_move": "finta escocesa",
    "heading": "cabeceio", "long_range_drive": "chute de longa distância", "knuckle_shot": "chute sem efeito",
    "acrobatic_finishing": "finalização acrobática", "heel_trick": "toque de calcanhar", "first_time_shot": "chute de primeira",
    "one_touch_pass": "passe de primeira", "weighted_pass": "passe em profundidade", "pinpoint_crossing": "cruzamento preciso",
    "outside_curler": "chute com a parte externa", "rabona": "rabona", "low_lofted_pass": "passe alto rasteiro",
    "low_punt_trajectory": "tiro de meta rasteiro", "long_throw": "arremesso longo", "gk_long_throw": "lançamento longo do goleiro",
    "malicia": "malícia", "man_marking": "marcação individual", "track_back": "volta para marcar",
    "acrobatic_clear": "corte acrobático", "captaincy": "capitão", "super_sub": "super-reserva", "fighting_spirit": "espírito de luta",
}
COM_PT = {
    "trickster": "driblador", "maze_run": "condução em zigue-zague", "speed_bullet": "arrancada",
    "incisive_run": "infiltração", "lb_expert": "especialista em lateral", "early_cross": "cruzamento antecipado",
    "long_ranger": "chute de longe",
}

FIELD_BITS: Dict[str, Tuple[int, int]] = {}
_bit = 0
for _name, _width in FIELD_LAYOUT:
    FIELD_BITS[_name] = (_bit, _width)
    _bit += _width
for _i in range(1, 28):
    FIELD_BITS[f"skill_{_i}"] = (_bit, 1)
    _bit += 1
USED_STATS_BITS = _bit  # 283; trailing five bits are not described

ATTRIBUTE_FIELDS = [
    "attack", "defense", "goalkeeping", "dribbling", "finishing", "low_pass", "lofted_pass", "header",
    "swerve", "catching", "clearing", "reflexes", "body_control", "physical_contact", "kicking_power",
    "explosive_power", "ball_control", "ball_winning", "jump", "coverage", "place_kicking", "stamina", "speed",
]
ATTRIBUTE_LABELS = {
    "attack": "Ataque", "defense": "Defesa", "goalkeeping": "Defesa do goleiro", "dribbling": "Drible",
    "finishing": "Finalização", "low_pass": "Passe rasteiro", "lofted_pass": "Passe alto", "header": "Cabeceio",
    "swerve": "Efeito", "catching": "Defesa/encaixe", "clearing": "Rebatida", "reflexes": "Reflexos",
    "body_control": "Controle corporal", "physical_contact": "Contato físico", "kicking_power": "Potência de chute",
    "explosive_power": "Explosão", "ball_control": "Controle de bola", "ball_winning": "Desarme/roubada",
    "jump": "Impulsão", "coverage": "Cobertura", "place_kicking": "Bola parada", "stamina": "Resistência", "speed": "Velocidade",
}


def be16(buf: bytes | bytearray, off: int) -> int:
    return struct.unpack_from(">H", buf, off)[0]


def be32(buf: bytes | bytearray, off: int) -> int:
    return struct.unpack_from(">I", buf, off)[0]


def decode_text(buf: bytes | bytearray, off: int, size: int) -> str:
    raw = bytes(buf[off:off + size]).split(b"\x00", 1)[0]
    return raw.decode("utf-8", errors="replace").strip()


def encode_fixed(text: str, size: int) -> bytes:
    raw = text.encode("utf-8")
    if len(raw) > size:
        raw = raw[:size]
        while True:
            try:
                raw.decode("utf-8")
                break
            except UnicodeDecodeError:
                raw = raw[:-1]
    return raw + b"\x00" * (size - len(raw))


def get_bits_msb(buf: bytes | bytearray, byte_offset: int, bit_offset: int, width: int) -> int:
    value = 0
    for i in range(width):
        absolute = bit_offset + i
        byte = buf[byte_offset + absolute // 8]
        value = (value << 1) | ((byte >> (7 - absolute % 8)) & 1)
    return value


def set_bits_msb(buf: bytearray, byte_offset: int, bit_offset: int, width: int, value: int) -> None:
    if value < 0 or value >= (1 << width):
        raise ValueError(f"Valor {value} fora do limite de {width} bits")
    for i in range(width):
        absolute = bit_offset + i
        pos = byte_offset + absolute // 8
        bit_in_byte = 7 - absolute % 8
        source_bit = (value >> (width - 1 - i)) & 1
        mask = 1 << bit_in_byte
        buf[pos] = (buf[pos] & ~mask) | (mask if source_bit else 0)


def parse_player(buf: bytes | bytearray, index: int) -> dict:
    off = PLAYER_TABLE_OFFSET + index * PLAYER_STRIDE
    pid = be32(buf, off)
    attrs = {}
    for name, (bit, width) in FIELD_BITS.items():
        attrs[name] = get_bits_msb(buf, off + PLAYER_STATS_REL, bit, width)
    skill_values = [attrs["skill_scissors"]] + [attrs[f"skill_{i}"] for i in range(1, 28)]
    com_values = [attrs[f"com_{name}"] for name in COM_NAMES]
    skills = [name for name, value in zip(SKILL_NAMES, skill_values) if value]
    com_styles = [name for name, value in zip(COM_NAMES, com_values) if value]
    return {
        "index": index,
        "offset": off,
        "id": pid,
        "comm_id": be32(buf, off + PLAYER_COMM_ID_REL),
        "nationality_id": be16(buf, off + PLAYER_NATION_REL),
        "height": buf[off + PLAYER_HEIGHT_REL],
        "weight": buf[off + PLAYER_WEIGHT_REL],
        "name": decode_text(buf, off + PLAYER_NAME_REL, PLAYER_NAME_SIZE),
        "shirt_name": decode_text(buf, off + PLAYER_SHIRT_REL, PLAYER_SHIRT_SIZE),
        "attributes": attrs,
        "skills": skills,
        "com_styles": com_styles,
        # O bloco de aparência (0x74–0xBB) é exibido em hexadecimal, sem edição,
        # até que os subcampos específicos do dump Xbox sejam confirmados.
        "appearance_raw": bytes(buf[off + 0x74:off + PLAYER_STRIDE]).hex(" ").upper(),
        "appearance_duplicate_id": be32(buf, off + 0x74),
    }


@dataclass
class ParsedFile:
    data: bytearray
    player_count: int
    team_count: int
    roster_count: int
    players: dict
    teams: list
    rosters: list                 # alinhados à lista de equipes; vínculo por team_id
    tactics: dict                 # team_id -> registro tático (3 planos x 3 formações)
    warnings: list
    read_only: bool = False


def parse_tactics_record(buf: bytes | bytearray, index: int) -> dict:
    off = TACTICS_TABLE_OFFSET + index * TACTICS_STRIDE
    team_id = be32(buf, off)
    cur = off + 4
    presets = []
    for preset_index in range(3):
        formations = []
        for formation_index in range(3):
            positions = list(buf[cur:cur + 11]); cur += 11
            ys = list(buf[cur:cur + 11]); cur += 11
            xs = list(buf[cur:cur + 11]); cur += 11
            formations.append({"positions": positions, "y": ys, "x": xs})
        flags = list(buf[cur:cur + 7]); cur += 7
        cur += 2  # bytes desconhecidos preservados
        attacking_instructions = []
        for _ in range(2):
            instruction = buf[cur]
            player_ref = buf[cur + 4]
            attacking_instructions.append({"instruction": instruction, "player_ref": player_ref})
            cur += 8
        defensive_instructions = []
        for _ in range(2):
            instruction = buf[cur]
            player_ref = buf[cur + 4]
            defensive_instructions.append({"instruction": instruction, "player_ref": player_ref})
            cur += 8
        settings = list(buf[cur:cur + 5]); cur += 5
        cur += 11  # dados de marcação individual não interpretados
        fluid = buf[cur]; cur += 1
        cur += 3  # preenchimento desconhecido
        presets.append({
            "formations": formations,
            "flags": flags,
            "attacking_instructions": attacking_instructions,
            "defensive_instructions": defensive_instructions,
            "settings": settings,
            "fluid": fluid,
        })
    starting11 = list(buf[cur:cur + 11]); cur += 11
    bench_order = list(buf[cur:cur + 21]); cur += 21
    set_piece_takers = list(buf[cur:cur + 6]); cur += 6
    players_to_join_attack = list(buf[cur:cur + 3]); cur += 3
    captain_index = buf[cur]; cur += 1
    automation = list(buf[cur:cur + 4]); cur += 4
    # Restam 98 bytes não interpretados; são preservados sem modificação.
    if cur > off + TACTICS_STRIDE:
        raise ValueError(f"Registro tático fora do limite no índice {index}.")
    return {
        "index": index, "offset": off, "team_id": team_id,
        "presets": presets, "starting11": starting11, "bench_order": bench_order,
        "set_piece_takers": set_piece_takers, "players_to_join_attack": players_to_join_attack,
        "captain_index": captain_index, "automation": automation,
        "raw": bytes(buf[off:off + TACTICS_STRIDE]),
    }


def parse_file(raw: bytes | bytearray, recover: bool = False) -> ParsedFile:
    """Lê variações de PES 2018 com contagens diferentes.

    recover=True aceita inconsistências de cabeçalho/relacionamento quando as
    tabelas continuam dentro dos limites físicos conhecidos; o resultado abre
    em modo somente leitura para evitar gravações potencialmente perigosas.
    """
    data = bytearray(raw)
    if len(data) < TACTICS_TABLE_OFFSET:
        raise ValueError("Arquivo menor que o início da tabela tática PES 2018.")

    pc_raw = be16(data, PLAYER_COUNT_OFFSET)
    tc_raw = be16(data, TEAM_COUNT_OFFSET)
    rc_raw = be16(data, ROSTER_COUNT_OFFSET)
    warnings = []

    if not 1 <= pc_raw <= PLAYER_CAPACITY:
        if not recover:
            raise ValueError(f"Quantidade de jogadores fora do padrão: {pc_raw}.")
        pc = min(max(pc_raw, 1), PLAYER_CAPACITY)
        warnings.append(f"Contagem de jogadores do cabeçalho ajustada para leitura: {pc_raw} → {pc}.")
    else:
        pc = pc_raw

    if not 1 <= tc_raw <= MAX_TEAM_COUNT:
        if not recover:
            raise ValueError(f"Contagem de equipes inválida: {tc_raw} (limite conhecido: {MAX_TEAM_COUNT}).")
        tc = min(max(tc_raw, 1), MAX_TEAM_COUNT)
        warnings.append(f"Contagem de equipes ajustada para leitura: {tc_raw} → {tc}.")
    else:
        tc = tc_raw

    if not 1 <= rc_raw <= MAX_TEAM_COUNT:
        if not recover:
            raise ValueError(f"Contagem de elencos inválida: {rc_raw} (limite conhecido: {MAX_TEAM_COUNT}).")
        rc = min(max(rc_raw, 1), MAX_TEAM_COUNT)
        warnings.append(f"Contagem de elencos ajustada para leitura: {rc_raw} → {rc}.")
    else:
        rc = rc_raw

    # A área de jogadores termina exatamente no início fixo da tabela de equipes.
    if PLAYER_TABLE_OFFSET + pc * PLAYER_STRIDE > TEAM_TABLE_OFFSET:
        raise ValueError("A tabela de jogadores ultrapassa o espaço reservado antes das equipes.")
    max_teams_by_file = max(0, (len(data) - TEAM_TABLE_OFFSET) // TEAM_STRIDE)
    max_rosters_by_file = max(0, (TACTICS_TABLE_OFFSET - ROSTER_TABLE_OFFSET) // ROSTER_STRIDE)
    max_tactics_by_file = max(0, (len(data) - TACTICS_TABLE_OFFSET) // TACTICS_STRIDE)
    if tc > max_teams_by_file or rc > max_rosters_by_file:
        if not recover:
            raise ValueError("As contagens declaradas ultrapassam os limites físicos das tabelas.")
        old_tc, old_rc = tc, rc
        tc = min(tc, max_teams_by_file, MAX_TEAM_COUNT)
        rc = min(rc, max_rosters_by_file, MAX_TEAM_COUNT)
        warnings.append(f"Contagens limitadas pelo tamanho do arquivo: equipes {old_tc}→{tc}; elencos {old_rc}→{rc}.")
    if tc <= 0 or rc <= 0:
        raise ValueError("Não foi possível localizar pelo menos uma equipe e um elenco completos.")
    if TACTICS_TABLE_OFFSET + min(tc, rc) * TACTICS_STRIDE > len(data):
        if not recover:
            raise ValueError("A tabela tática não cabe no arquivo para a quantidade declarada.")
        warnings.append("Tabela tática incompleta; leitura de formações desativada para este arquivo.")

    if tc_raw != rc_raw:
        warnings.append(f"Cabeçalho com contagens diferentes: equipes={tc_raw}, elencos={rc_raw}. O vínculo será feito pelo ID.")

    players = {}
    for i in range(pc):
        p = parse_player(data, i)
        if p["id"] == 0:
            warnings.append(f"Registro de jogador vazio dentro da faixa ativa (índice {i}).")
            continue
        if p["id"] in players:
            warnings.append(f"ID de jogador duplicado na tabela principal: {p['id']}.")
            continue
        players[p["id"]] = p

    teams = []
    seen_team_ids = set()
    for i in range(tc):
        off = TEAM_TABLE_OFFSET + i * TEAM_STRIDE
        tid = be32(data, off)
        if tid in seen_team_ids:
            warnings.append(f"ID de equipe repetido na tabela de equipes: {tid}.")
        seen_team_ids.add(tid)
        teams.append({
            "index": i, "offset": off, "id": tid,
            "name": decode_text(data, off + TEAM_NAME_REL, TEAM_NAME_SIZE),
            "short": decode_text(data, off + TEAM_SHORT_REL, TEAM_SHORT_SIZE),
        })

    roster_records = []
    rosters_by_id = {}
    seen_roster_ids = set()
    for i in range(rc):
        off = ROSTER_TABLE_OFFSET + i * ROSTER_STRIDE
        rid = be32(data, off)
        pids = [be32(data, off + ROSTER_PLAYERS_REL + j * 4) for j in range(ROSTER_PLAYER_COUNT)]
        numbers = list(data[off + ROSTER_NUMBERS_REL:off + ROSTER_NUMBERS_REL + ROSTER_PLAYER_COUNT])
        if rid in seen_roster_ids:
            warnings.append(f"ID de elenco repetido na tabela de elencos: {rid}.")
        seen_roster_ids.add(rid)
        record = {"index": i, "offset": off, "team_id": rid, "player_ids": pids, "numbers": numbers}
        roster_records.append(record)
        rosters_by_id.setdefault(rid, record)

    # Equipes e elencos são associados pelo ID, não pela posição física na tabela.
    # Isso permite abrir arquivos em que a ordem das duas tabelas seja diferente.
    rosters = []
    team_ids = set()
    missing_roster_teams = []
    unresolved = []
    for team in teams:
        team_id = team["id"]
        team_ids.add(team_id)
        roster = rosters_by_id.get(team_id)
        if roster is None:
            missing_roster_teams.append(team_id)
            rosters.append({"index": -1, "offset": -1, "team_id": team_id,
                            "player_ids": [0] * ROSTER_PLAYER_COUNT,
                            "numbers": [0] * ROSTER_PLAYER_COUNT})
            continue
        pids = roster["player_ids"]
        seen_empty = False
        local_seen = set()
        for slot, pid in enumerate(pids):
            if pid == 0:
                seen_empty = True
            else:
                if seen_empty:
                    warnings.append(f"Elenco da equipe ID {team_id}: há jogador após vaga vazia (slot {slot + 1}).")
                if pid not in players:
                    unresolved.append((team_id, slot, pid))
                if pid in local_seen:
                    warnings.append(f"Elenco da equipe ID {team_id}: jogador repetido (ID {pid}).")
                local_seen.add(pid)
        rosters.append({**roster, "player_ids": list(pids), "numbers": list(roster["numbers"])})

    orphan_rosters = sorted(set(rosters_by_id) - team_ids)
    if missing_roster_teams:
        warnings.append(f"{len(missing_roster_teams)} equipe(s) sem registro de elenco correspondente.")
    if orphan_rosters:
        warnings.append(f"{len(orphan_rosters)} registro(s) de elenco sem equipe correspondente.")
    if unresolved:
        warnings.append(f"{len(unresolved)} referência(s) de jogador no elenco sem registro na tabela principal.")

    tactics = {}
    tactics_count = min(tc, rc, max_tactics_by_file)
    tactics_ids_seen = set()
    for i in range(tactics_count):
        tac = parse_tactics_record(data, i)
        if tac["team_id"] in tactics_ids_seen:
            warnings.append(f"ID repetido na tabela tática: {tac['team_id']}.")
        tactics_ids_seen.add(tac["team_id"])
        tactics.setdefault(tac["team_id"], tac)
    missing_tactics = sorted(team_ids - set(tactics))
    if missing_tactics:
        warnings.append(f"{len(missing_tactics)} equipe(s) sem bloco de formação/tática correspondente.")

    # Duplicidades, lacunas e referências quebradas exigem modo de segurança.
    read_only = bool(warnings)
    return ParsedFile(data, pc, tc, rc, players, teams, rosters, tactics, warnings, read_only)


def summarize(parsed: ParsedFile) -> dict:
    occupied = [pid for r in parsed.rosters for pid in r["player_ids"] if pid]
    return {
        "file_size": len(parsed.data),
        "players_active": parsed.player_count,
        "players_capacity": PLAYER_CAPACITY,
        "players_unused": PLAYER_CAPACITY - parsed.player_count,
        "teams": parsed.team_count,
        "roster_records": parsed.roster_count,
        "roster_slots_occupied": len(occupied),
        "roster_player_ids_unique": len(set(occupied)),
        "roster_duplicate_assignments": len(occupied) - len(set(occupied)),
        "team_roster_ids_match": not parsed.warnings,
        "player_ids_unresolved": sum(1 for pid in occupied if pid not in parsed.players),
        "tactics_records": len(parsed.tactics),
        "read_only": parsed.read_only,
        "warnings": parsed.warnings,
        "used_stat_bits": USED_STATS_BITS,
        "unknown_trailing_stat_bits": 36 * 8 - USED_STATS_BITS,
        "xbox360_container_integration": "NOT_IMPLEMENTED_PENDING_CONSOLE_TEST",
        "formations_and_tactics": "READ_ONLY_PREVIEW_AND_TEMPLATE_COPY_AVAILABLE",
        "appearance_fields": "RAW_READ_ONLY_UNTIL_SUBFIELDS_ARE_CONFIRMED",
    }


def validate_roundtrip(parsed: ParsedFile) -> None:
    check = parse_file(parsed.data, recover=parsed.read_only)
    if check.player_count != parsed.player_count or check.team_count != parsed.team_count or check.roster_count != parsed.roster_count:
        raise ValueError("Falha na validação pós-gravação: contagens mudaram.")


def copy_team_tactics(parsed: ParsedFile, target_team_index: int, source_team_index: int) -> None:
    target = parsed.teams[target_team_index]
    source = parsed.teams[source_team_index]
    target_tac = parsed.tactics.get(target["id"])
    source_tac = parsed.tactics.get(source["id"])
    if not target_tac or not source_tac:
        raise ValueError("Não há bloco tático válido para a equipe de origem ou destino.")
    if target_team_index == source_team_index:
        raise ValueError("Escolha uma equipe de origem diferente da equipe selecionada.")
    raw = bytearray(parsed.data[source_tac["offset"]:source_tac["offset"] + TACTICS_STRIDE])
    struct.pack_into(">I", raw, 0, target["id"])
    dest = target_tac["offset"]
    parsed.data[dest:dest + TACTICS_STRIDE] = raw
    parsed.tactics[target["id"]] = parse_tactics_record(parsed.data, target_tac["index"])


def copy_team_roster_and_tactics(parsed: ParsedFile, target_team_index: int, source_team_index: int) -> None:
    if target_team_index == source_team_index:
        raise ValueError("Escolha uma equipe de origem diferente da equipe selecionada.")
    target_r = parsed.rosters[target_team_index]
    source_r = parsed.rosters[source_team_index]
    if target_r["offset"] < 0 or source_r["offset"] < 0:
        raise ValueError("A equipe de origem ou destino não possui registro de elenco correspondente.")
    if any(pid and pid not in parsed.players for pid in source_r["player_ids"]):
        raise ValueError("O elenco de origem contém jogador sem cadastro completo.")
    copy_team_tactics(parsed, target_team_index, source_team_index)
    dest = target_r["offset"]
    for slot, pid in enumerate(source_r["player_ids"]):
        struct.pack_into(">I", parsed.data, dest + ROSTER_PLAYERS_REL + slot * 4, pid)
    parsed.data[dest + ROSTER_NUMBERS_REL:dest + ROSTER_NUMBERS_REL + ROSTER_PLAYER_COUNT] = bytes(source_r["numbers"])
    target_r["player_ids"] = list(source_r["player_ids"])
    target_r["numbers"] = list(source_r["numbers"])


class PesEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PES 2018 Xbox 360 — Editor v0.3")
        self.geometry("1280x800")
        self.minsize(920, 620)
        # Maximizado no Windows: respeita a área útil acima da barra de tarefas.
        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)
            except tk.TclError:
                pass
        self.parsed: ParsedFile | None = None
        self.source_path: str | None = None  # original aberto; nunca sobrescrito
        self.working_path: str | None = None  # cópia editada atual
        self.dirty = False
        self.active_team_index: int | None = None
        self.active_slot: int | None = None
        self.active_player_id: int | None = None
        self.detail_player_id: int | None = None
        self.selected_library_id: int | None = None
        self.player_rows = []
        self.detail_entries = {}
        self.stat_entries = {}
        self.skill_var = tk.StringVar()
        self.com_var = tk.StringVar()
        self.team_name_var = tk.StringVar()
        self.team_short_var = tk.StringVar()
        self.team_filter_var = tk.StringVar()
        self.position_var = tk.StringVar()
        self.appearance_text = None
        self.formation_canvas = None
        self.tactics_summary_var = tk.StringVar(value="Selecione uma equipe para visualizar as formações.")
        self.tactics_preset_var = tk.StringVar(value="Plano 1")
        self.tactics_formation_var = tk.StringVar(value="Formação 1")
        self.template_team_var = tk.StringVar()
        self.template_team_combo = None
        self.template_team_lookup = {}
        self._tree_sort_state = {}
        self.status_var = tk.StringVar(value="Abra o data.bin extraído/descriptografado do PES 2018.")
        self._build_ui()
        self.after(100, self.open_initial_file)

    def _build_ui(self):
        menu = tk.Menu(self)
        filemenu = tk.Menu(menu, tearoff=False)
        filemenu.add_command(label="Abrir data.bin…", command=self.open_file)
        filemenu.add_command(label="Salvar (Ctrl+S)", command=self.save_current)
        filemenu.add_command(label="Salvar cópia como…", command=self.save_as)
        filemenu.add_command(label="Exportar elenco atual para CSV…", command=self.export_current_roster)
        filemenu.add_separator()
        filemenu.add_command(label="Sair", command=self.destroy)
        menu.add_cascade(label="Arquivo", menu=filemenu)
        self.config(menu=menu)
        self.bind_all("<Control-s>", lambda _e: self.save_current())

        main = ttk.Panedwindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=8, pady=8)

        team_frame = ttk.LabelFrame(main, text="Equipes")
        roster_frame = ttk.LabelFrame(main, text="Elenco da equipe")
        library_frame = ttk.LabelFrame(main, text="Banco de jogadores")
        main.add(team_frame, weight=2)
        main.add(roster_frame, weight=3)
        main.add(library_frame, weight=4)

        team_filter = ttk.Frame(team_frame)
        team_filter.pack(fill="x", padx=5, pady=(5, 0))
        ttk.Entry(team_filter, textvariable=self.team_filter_var).pack(side="left", fill="x", expand=True)
        ttk.Button(team_filter, text="Filtrar", command=self.filter_teams).pack(side="left", padx=(4, 0))
        self.team_filter_var.trace_add("write", lambda *_: self.filter_teams())
        self.team_tree = ttk.Treeview(team_frame, columns=("id", "count"), show="tree headings", selectmode="browse")
        self.team_tree.heading("#0", text="Equipe")
        self.team_tree.heading("id", text="ID")
        self.team_tree.heading("count", text="Jogadores")
        self.team_tree.heading("#0", text="Equipe", command=lambda: self.sort_tree(self.team_tree, "#0"))
        self.team_tree.heading("id", text="ID", command=lambda: self.sort_tree(self.team_tree, "id", numeric=True))
        self.team_tree.heading("count", text="Jogadores", command=lambda: self.sort_tree(self.team_tree, "count", numeric=True))
        self.team_tree.column("#0", width=190)
        self.team_tree.column("id", width=58, anchor="center")
        self.team_tree.column("count", width=75, anchor="center")
        self.team_tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.team_tree.bind("<<TreeviewSelect>>", self.on_team_select)
        team_edit = ttk.LabelFrame(team_frame, text="Nome e sigla")
        team_edit.pack(fill="x", padx=5, pady=(0, 5))
        ttk.Label(team_edit, text="Nome:").grid(row=0, column=0, sticky="w", padx=3, pady=2)
        ttk.Entry(team_edit, textvariable=self.team_name_var).grid(row=0, column=1, sticky="ew", padx=3, pady=2)
        ttk.Label(team_edit, text="Sigla (3 bytes):").grid(row=1, column=0, sticky="w", padx=3, pady=2)
        ttk.Entry(team_edit, textvariable=self.team_short_var, width=6).grid(row=1, column=1, sticky="w", padx=3, pady=2)
        ttk.Button(team_edit, text="Aplicar equipe", command=self.save_team_details).grid(row=2, column=0, columnspan=2, sticky="ew", padx=3, pady=3)
        team_edit.columnconfigure(1, weight=1)
        template_box = ttk.LabelFrame(team_frame, text="Modelo de outra equipe")
        template_box.pack(fill="x", padx=5, pady=(0, 5))
        ttk.Label(template_box, text="Copiar de:").pack(anchor="w", padx=4, pady=(3, 0))
        self.template_team_combo = ttk.Combobox(template_box, textvariable=self.template_team_var, state="readonly")
        self.template_team_combo.pack(fill="x", padx=4, pady=2)
        ttk.Button(template_box, text="Copiar somente formação/táticas", command=self.copy_tactics_from_selected_template).pack(fill="x", padx=4, pady=2)
        ttk.Button(template_box, text="Copiar elenco + formação/táticas", command=self.copy_roster_and_tactics_from_selected_template).pack(fill="x", padx=4, pady=(2, 4))

        self.roster_tree = ttk.Treeview(roster_frame, columns=("number", "name", "pid"), show="headings", height=28, selectmode="browse")
        for col, label, width in [("number", "Camisa", 55), ("name", "Jogador", 190), ("pid", "ID", 85)]:
            self.roster_tree.heading(col, text=label, command=lambda c=col: self.sort_tree(self.roster_tree, c, numeric=(c in ("number", "pid"))))
            self.roster_tree.column(col, width=width, anchor="center" if col != "name" else "w")
        self.roster_tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.roster_tree.bind("<<TreeviewSelect>>", self.on_roster_select)

        replacebar = ttk.Frame(roster_frame)
        replacebar.pack(fill="x", padx=5, pady=(0, 5))
        ttk.Button(replacebar, text="Substituir jogador da vaga", command=self.replace_player).pack(fill="x", pady=1)
        ttk.Button(replacebar, text="Adicionar jogador do banco", command=self.add_player_to_team).pack(fill="x", pady=1)
        ttk.Button(replacebar, text="Remover jogador da equipe", command=self.remove_player_from_team).pack(fill="x", pady=1)
        numberbar = ttk.Frame(roster_frame)
        numberbar.pack(fill="x", padx=5, pady=(0, 5))
        ttk.Label(numberbar, text="Novo número:").pack(side="left")
        self.number_var = tk.StringVar()
        ttk.Entry(numberbar, textvariable=self.number_var, width=5).pack(side="left", padx=4)
        ttk.Button(numberbar, text="Aplicar camisa", command=self.change_number).pack(side="left")

        searchbar = ttk.Frame(library_frame)
        searchbar.pack(fill="x", padx=5, pady=5)
        ttk.Label(searchbar, text="Nome ou ID:").pack(side="left")
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(searchbar, textvariable=self.search_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(searchbar, text="Buscar", command=self.search_players).pack(side="left")
        search_entry.bind("<Return>", lambda _e: self.search_players())
        self.library_tree = ttk.Treeview(library_frame, columns=("id", "shirt"), show="tree headings", height=28, selectmode="browse")
        self.library_tree.heading("#0", text="Nome completo", command=lambda: self.sort_tree(self.library_tree, "#0"))
        self.library_tree.heading("id", text="ID", command=lambda: self.sort_tree(self.library_tree, "id", numeric=True))
        self.library_tree.heading("shirt", text="Nome camisa", command=lambda: self.sort_tree(self.library_tree, "shirt"))
        self.library_tree.column("#0", width=200)
        self.library_tree.column("id", width=80, anchor="center")
        self.library_tree.column("shirt", width=120)
        self.library_tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.library_tree.bind("<<TreeviewSelect>>", self.on_library_select)
        self.library_tree.bind("<Double-1>", lambda _e: self.replace_player())

        details = ttk.LabelFrame(self, text="Dados do jogador selecionado — cadastro global")
        details.pack(fill="x", padx=8, pady=(0, 8))
        self.tabs = ttk.Notebook(details)
        self.tabs.pack(fill="x", expand=True, padx=5, pady=5)
        basic = ttk.Frame(self.tabs)
        stats = ttk.Frame(self.tabs)
        self.tabs.add(basic, text="Identificação")
        self.tabs.add(stats, text="Atributos e habilidades")
        appearance = ttk.Frame(self.tabs)
        self.tabs.add(appearance, text="Aparência (inspeção)")
        formation_tab = ttk.Frame(self.tabs)
        self.tabs.add(formation_tab, text="Formações e táticas")
        self._build_formation_tab(formation_tab)

        basic_fields = [
            ("name", "Nome", 46), ("shirt_name", "Nome na camisa", 18),
            ("nationality_id", "Nacionalidade (ID)", 6), ("height", "Altura", 4),
            ("weight", "Peso", 4), ("age", "Idade", 3), ("play_style", "Estilo (0–17)", 3),
            ("form", "Forma (0–7)", 2), ("strong_foot", "Pé forte (0 dir./1 esq.)", 2),
            ("fk_motion", "Movimento de falta (0–15)", 3), ("injury_resistance", "Resistência a lesão (0–3)", 2),
            ("weak_foot_accuracy", "Precisão pé ruim (0–3)", 2), ("weak_foot_usage", "Uso pé ruim (0–3)", 2),
            ("dribble_arm_motion", "Mov. braços drible (0–7)", 2), ("run_arm_motion", "Mov. braços corrida (0–7)", 2),
            ("corner_motion", "Movimento escanteio (0–7)", 2), ("dribble_hunch_motion", "Postura drible (0–3)", 2),
            ("run_hunch_motion", "Postura corrida (0–3)", 2), ("pk_motion", "Movimento pênalti (0–3)", 2),
        ]
        for i, (key, label, width) in enumerate(basic_fields):
            row, col = divmod(i, 3)
            ttk.Label(basic, text=label).grid(row=row, column=col * 2, sticky="w", padx=5, pady=3)
            var = tk.StringVar()
            ent = ttk.Entry(basic, textvariable=var, width=width)
            ent.grid(row=row, column=col * 2 + 1, sticky="ew", padx=5, pady=3)
            self.detail_entries[key] = var
        for c in range(6):
            basic.columnconfigure(c, weight=1)
        self.player_id_label = ttk.Label(basic, text="ID: — | Código posição: —")
        self.player_id_label.grid(row=7, column=0, columnspan=6, sticky="w", padx=5, pady=5)

        ttk.Label(stats, text="Os atributos pertencem ao cadastro global do jogador: uma alteração afeta todas as equipes que utilizam esse ID.").grid(row=0, column=0, columnspan=8, sticky="w", padx=4, pady=4)
        for i, key in enumerate(ATTRIBUTE_FIELDS):
            row, col = divmod(i, 4)
            row += 1
            ttk.Label(stats, text=ATTRIBUTE_LABELS[key]).grid(row=row, column=col * 2, sticky="w", padx=4, pady=2)
            var = tk.StringVar()
            ttk.Entry(stats, textvariable=var, width=5).grid(row=row, column=col * 2 + 1, sticky="w", padx=4, pady=2)
            self.stat_entries[key] = var
        lastrow = 1 + (len(ATTRIBUTE_FIELDS) + 3) // 4
        ttk.Label(stats, text="Habilidades (nomes separados por vírgula):").grid(row=lastrow, column=0, columnspan=2, sticky="w", padx=4, pady=3)
        ttk.Entry(stats, textvariable=self.skill_var, width=110).grid(row=lastrow, column=2, columnspan=6, sticky="ew", padx=4, pady=3)
        ttk.Label(stats, text="Estilos COM (separados por vírgula):").grid(row=lastrow + 1, column=0, columnspan=2, sticky="w", padx=4, pady=3)
        ttk.Entry(stats, textvariable=self.com_var, width=110).grid(row=lastrow + 1, column=2, columnspan=6, sticky="ew", padx=4, pady=3)
        ttk.Label(stats, text="Posições jogáveis — códigos brutos somente para consulta; ordem CF, SS, LWF, RWF, AMF, DMF, CMF, LMF, RMF, CB, LB, RB, GK:").grid(row=lastrow + 2, column=0, columnspan=8, sticky="w", padx=4, pady=3)
        self.position_entry = ttk.Entry(stats, textvariable=self.position_var, width=110, state="readonly")
        self.position_entry.grid(row=lastrow + 3, column=0, columnspan=8, sticky="ew", padx=4, pady=3)
        ttk.Button(stats, text="Aplicar alterações ao jogador", command=self.save_player_details).grid(row=lastrow + 4, column=0, columnspan=8, sticky="e", padx=4, pady=5)
        ttk.Label(appearance, text="Bloco bruto de aparência — 72 bytes. Os subcampos ainda não são alterados para evitar corrupção de dados.").pack(anchor="w", padx=8, pady=8)
        self.appearance_text = tk.Text(appearance, height=5, wrap="word", state="disabled")
        self.appearance_text.pack(fill="both", expand=True, padx=8, pady=4)
        ttk.Button(basic, text="Aplicar alterações ao jogador", command=self.save_player_details).grid(row=8, column=0, columnspan=6, sticky="e", padx=5, pady=5)

        status = ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w")
        status.pack(fill="x", side="bottom")

    def _build_formation_tab(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(fill="x", padx=8, pady=6)
        ttk.Label(bar, text="Plano:").pack(side="left")
        preset = ttk.Combobox(bar, textvariable=self.tactics_preset_var, state="readonly", width=12,
                              values=["Plano 1", "Plano 2", "Plano 3"])
        preset.pack(side="left", padx=(4, 12))
        preset.bind("<<ComboboxSelected>>", lambda _e: self.refresh_formation_preview())
        ttk.Label(bar, text="Formação:").pack(side="left")
        formation = ttk.Combobox(bar, textvariable=self.tactics_formation_var, state="readonly", width=14,
                                 values=["Formação 1", "Formação 2", "Formação 3"])
        formation.pack(side="left", padx=4)
        formation.bind("<<ComboboxSelected>>", lambda _e: self.refresh_formation_preview())
        self.formation_canvas = tk.Canvas(parent, height=260, background="#e7f0e7", highlightthickness=1,
                                          highlightbackground="#9aa99a")
        self.formation_canvas.pack(fill="both", expand=True, padx=8, pady=4)
        self.formation_canvas.bind("<Configure>", lambda _e: self.refresh_formation_preview())
        ttk.Label(parent, textvariable=self.tactics_summary_var, justify="left", wraplength=1100).pack(
            fill="x", padx=8, pady=(4, 8), anchor="w")
        ttk.Label(parent, text="Pré-visualização. A cópia de configuração preserva os bytes desconhecidos; teste no console antes de usar o save.",
                  foreground="#8a5b00").pack(anchor="w", padx=8, pady=(0, 8))

    def _ask_load_anyway(self, message: str) -> bool:
        """Janela com os rótulos explícitos solicitados para recuperação."""
        win = tk.Toplevel(self)
        win.title("Arquivo com diferenças de estrutura")
        win.transient(self)
        win.resizable(True, True)
        win.grab_set()
        ttk.Label(win, text=message, justify="left", wraplength=560).pack(fill="both", expand=True, padx=14, pady=12)
        result = {"value": False}
        buttons = ttk.Frame(win)
        buttons.pack(fill="x", padx=12, pady=(0, 12))
        def accept():
            result["value"] = True
            win.destroy()
        def cancel():
            win.destroy()
        ttk.Button(buttons, text="Carregar mesmo assim", command=accept).pack(side="right", padx=4)
        ttk.Button(buttons, text="Cancelar", command=cancel).pack(side="right", padx=4)
        win.protocol("WM_DELETE_WINDOW", cancel)
        win.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - win.winfo_width()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - win.winfo_height()) // 2)
        win.geometry(f"+{x}+{y}")
        self.wait_window(win)
        return result["value"]

    def _ensure_writable(self) -> bool:
        if not self.parsed:
            messagebox.showwarning("Nenhum arquivo", "Abra um data.bin primeiro.")
            return False
        if self.parsed.read_only:
            messagebox.showwarning("Modo de segurança", "Este arquivo foi aberto com diferenças estruturais.\n\nA consulta e a exportação estão disponíveis, mas edição e gravação foram bloqueadas para evitar corrupção.")
            return False
        return True

    def sort_tree(self, tree, column: str, numeric: bool = False):
        items = list(tree.get_children(""))
        state_key = (str(tree), column)
        reverse = self._tree_sort_state.get(state_key, False)
        def value(iid):
            raw = tree.item(iid, "text") if column == "#0" else tree.set(iid, column)
            if numeric:
                try:
                    # A coluna ID do elenco mostra também o valor hexadecimal após o decimal.
                    return int(str(raw).split()[0], 10)
                except (ValueError, TypeError, IndexError):
                    return -1
            return str(raw).casefold()
        items.sort(key=value, reverse=reverse)
        for index, iid in enumerate(items):
            tree.move(iid, "", index)
        self._tree_sort_state[state_key] = not reverse

    def _refresh_template_choices(self):
        if not self.parsed or self.template_team_combo is None:
            return
        self.template_team_lookup = {}
        values = []
        for team in self.parsed.teams:
            if team["index"] == self.active_team_index:
                continue
            label = f"{team['name']} [ID {team['id']}]"
            values.append(label)
            self.template_team_lookup[label] = team["index"]
        self.template_team_combo["values"] = values
        if values:
            self.template_team_var.set(values[0])
        else:
            self.template_team_var.set("")

    def _selected_template_index(self):
        label = self.template_team_var.get()
        if label not in self.template_team_lookup:
            messagebox.showwarning("Equipe modelo", "Selecione uma equipe de origem na lista.")
            return None
        return self.template_team_lookup[label]

    def copy_tactics_from_selected_template(self):
        if not self._ensure_writable() or self.active_team_index is None:
            return
        source_index = self._selected_template_index()
        if source_index is None:
            return
        source = self.parsed.teams[source_index]
        target = self.parsed.teams[self.active_team_index]
        if not messagebox.askyesno("Copiar formação/táticas", f"Copiar os 3 planos e as 9 formações de {source['name']} para {target['name']}?\n\nA escalação será aplicada às vagas atuais do elenco de destino. Os bytes desconhecidos serão mantidos conforme o bloco de origem."):
            return
        try:
            copy_team_tactics(self.parsed, self.active_team_index, source_index)
            self.dirty = True
            self.refresh_formation_preview()
            self.status_var.set(f"Formações/táticas copiadas de {source['name']} para {target['name']}. Salve uma cópia para gravar.")
        except Exception as exc:
            messagebox.showerror("Não foi possível copiar", str(exc))

    def copy_roster_and_tactics_from_selected_template(self):
        if not self._ensure_writable() or self.active_team_index is None:
            return
        source_index = self._selected_template_index()
        if source_index is None:
            return
        source = self.parsed.teams[source_index]
        target = self.parsed.teams[self.active_team_index]
        if not messagebox.askyesno("Copiar elenco e formação", f"Substituir o elenco e as configurações táticas de {target['name']} pelos de {source['name']}?\n\nTodos os jogadores e números de camisa do destino serão substituídos. Os cadastros e atributos dos jogadores continuam globais."):
            return
        try:
            copy_team_roster_and_tactics(self.parsed, self.active_team_index, source_index)
            self.dirty = True
            self.active_slot = 0 if self.parsed.rosters[self.active_team_index]["player_ids"][0] else None
            self.active_player_id = self.parsed.rosters[self.active_team_index]["player_ids"][0] or None
            self.detail_player_id = self.active_player_id
            self.refresh_roster()
            self._update_team_count(self.active_team_index)
            if self.active_slot is not None:
                self.roster_tree.selection_set(str(self.active_slot))
                self.load_player_details(self.active_player_id)
            else:
                self._clear_player_details()
            self.refresh_formation_preview()
            self.status_var.set(f"Elenco e formações de {source['name']} copiados para {target['name']}.")
        except Exception as exc:
            messagebox.showerror("Não foi possível copiar", str(exc))

    def refresh_formation_preview(self):
        if self.formation_canvas is None:
            return
        canvas = self.formation_canvas
        canvas.delete("all")
        if not self.parsed or self.active_team_index is None:
            self.tactics_summary_var.set("Selecione uma equipe para visualizar as formações.")
            return
        team = self.parsed.teams[self.active_team_index]
        tactics = self.parsed.tactics.get(team["id"])
        if not tactics:
            self.tactics_summary_var.set(f"{team['name']}: não há registro tático identificado neste arquivo.")
            return
        preset_index = max(0, min(2, (int(self.tactics_preset_var.get()[-1]) - 1)))
        formation_index = max(0, min(2, (int(self.tactics_formation_var.get()[-1]) - 1)))
        formation = tactics["presets"][preset_index]["formations"][formation_index]
        width = max(canvas.winfo_width(), 420)
        height = max(canvas.winfo_height(), 220)
        left, top, right, bottom = 36, 18, width - 36, height - 18
        canvas.create_rectangle(left, top, right, bottom, outline="#366b43", width=2)
        mid = (top + bottom) / 2
        canvas.create_line(left, mid, right, mid, fill="#6d9272")
        canvas.create_oval((left + right) / 2 - 42, mid - 42, (left + right) / 2 + 42, mid + 42, outline="#6d9272")
        box_w, box_h = (right - left) * 0.18, (bottom - top) * 0.16
        canvas.create_rectangle((left + right - box_w) / 2, top, (left + right + box_w) / 2, top + box_h, outline="#6d9272")
        canvas.create_rectangle((left + right - box_w) / 2, bottom - box_h, (left + right + box_w) / 2, bottom, outline="#6d9272")
        for idx, (xv, yv, pos) in enumerate(zip(formation["x"], formation["y"], formation["positions"]), start=1):
            # Nos registros PES 2018 observados, x/y ficam na faixa percentual 0–100.
            px = left + (min(100, max(0, xv)) / 100.0) * (right - left)
            py = top + (min(100, max(0, yv)) / 100.0) * (bottom - top)
            canvas.create_oval(px - 11, py - 11, px + 11, py + 11, fill="#f5f7fa", outline="#163d7a", width=2)
            canvas.create_text(px, py, text=str(idx), fill="#163d7a", font=("Segoe UI", 8, "bold"))
        preset = tactics["presets"][preset_index]
        flag_labels = ["ataque", "construção", "zona ofensiva", "posicionamento", "defesa", "contenção", "pressão"]
        flags = ", ".join(f"{label}={value}" for label, value in zip(flag_labels, preset["flags"]))
        settings_labels = ["apoio", "jogadores no ataque", "linha defensiva", "compactação", "jogadores na defesa"]
        settings = ", ".join(f"{label}={value}" for label, value in zip(settings_labels, preset["settings"]))
        self.tactics_summary_var.set(
            f"{team['name']} | Plano {preset_index + 1} / Formação {formation_index + 1} | "
            f"Códigos de posição: {formation['positions']} | {flags} | {settings} | "
            f"Fluido={preset['fluid']} | Titulares (índices de vaga): {tactics['starting11']}"
        )

    def open_initial_file(self):
        import sys
        if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
            self.load_file(sys.argv[1])
        else:
            self.open_file()

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        return messagebox.askyesno("Alterações não salvas", "Existem alterações ainda não salvas. Descartá-las?")

    def open_file(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(title="Selecione o data.bin", filetypes=[("BIN", "*.bin"), ("Todos", "*.*")])
        if path:
            self.load_file(path)

    def load_file(self, path: str):
        if self.parsed and self.dirty and not self._confirm_discard():
            return
        try:
            raw = Path(path).read_bytes()
            try:
                parsed = parse_file(raw)
            except Exception as first_error:
                prompt = (
                    f"A validação normal não conseguiu confirmar todas as estruturas deste arquivo:\n\n{first_error}\n\n"
                    "Carregar mesmo assim? O editor tentará abrir somente as áreas que conseguir localizar e ativará o modo somente leitura quando houver risco estrutural."
                )
                if not self._ask_load_anyway(prompt):
                    return
                parsed = parse_file(raw, recover=True)
            if parsed.warnings:
                prompt = (
                    "Foram detectadas diferenças em relação ao layout de referência PES 2018:\n\n- "
                    + "\n- ".join(parsed.warnings[:12])
                    + ("\n- ..." if len(parsed.warnings) > 12 else "")
                    + "\n\nCarregar mesmo assim? O arquivo será aberto em modo somente leitura para evitar gravação potencialmente incompatível."
                )
                if not self._ask_load_anyway(prompt):
                    return
            self.parsed = parsed
            self.source_path = os.path.abspath(path)
            self.working_path = None
            self.dirty = False
            self.active_team_index = None
            self.active_slot = None
            self.active_player_id = None
            self.detail_player_id = None
            self._clear_player_details()
            self.team_tree.delete(*self.team_tree.get_children())
            self.roster_tree.delete(*self.roster_tree.get_children())
            self.library_tree.delete(*self.library_tree.get_children())
            for t, r in zip(parsed.teams, parsed.rosters):
                count = sum(1 for pid in r["player_ids"] if pid)
                self.team_tree.insert("", "end", iid=str(t["index"]), text=t["name"], values=(t["id"], count))
            self.player_rows = sorted(parsed.players.values(), key=lambda p: (p["name"].casefold(), p["id"]))
            summary = summarize(parsed)
            if parsed.read_only:
                self.status_var.set(f"Arquivo carregado em SOMENTE LEITURA: {parsed.player_count:,} jogadores, {parsed.team_count} equipes, {summary['roster_slots_occupied']:,} vagas.")
            else:
                self.status_var.set(f"Arquivo PES 2018 compatível: {parsed.player_count:,} jogadores, {parsed.team_count} equipes, {summary['roster_slots_occupied']:,} vagas e {len(parsed.tactics)} blocos táticos.")
            self.search_players()
            self.filter_teams()
            self._refresh_template_choices()
        except Exception as exc:
            messagebox.showerror("Não foi possível abrir", f"{exc}\n\nEste arquivo não pôde ser recuperado com segurança.")

    def filter_teams(self):
        if not hasattr(self, "team_tree") or not self.parsed:
            return
        query = self.team_filter_var.get().strip().casefold()
        keep = None
        if self.active_team_index is not None:
            keep = str(self.active_team_index)
        for t in self.parsed.teams:
            iid = str(t["index"])
            match = not query or query in t["name"].casefold() or query in t["short"].casefold() or query in str(t["id"])
            exists = self.team_tree.exists(iid)
            if match and not exists:
                r = self.parsed.rosters[t["index"]]
                count = sum(1 for pid in r["player_ids"] if pid)
                self.team_tree.insert("", "end", iid=iid, text=t["name"], values=(t["id"], count))
            elif not match and exists:
                self.team_tree.delete(iid)
        if keep and self.team_tree.exists(keep):
            self.team_tree.selection_set(keep)

    def _clear_player_details(self):
        self.detail_player_id = None
        for var in self.detail_entries.values():
            var.set("")
        for var in self.stat_entries.values():
            var.set("")
        self.position_var.set("")
        self.skill_var.set("")
        self.com_var.set("")
        self.number_var.set("")
        self.player_id_label.config(text="Nenhum jogador selecionado.")
        if self.appearance_text is not None:
            self.appearance_text.configure(state="normal")
            self.appearance_text.delete("1.0", "end")
            self.appearance_text.configure(state="disabled")

    def on_team_select(self, _event=None):
        if not self.parsed:
            return
        sel = self.team_tree.selection()
        if not sel:
            return
        self.active_team_index = int(sel[0])
        selected_team = self.parsed.teams[self.active_team_index]
        self.team_name_var.set(selected_team["name"])
        self.team_short_var.set(selected_team["short"])
        self.active_slot = None
        self.active_player_id = None
        self._clear_player_details()
        self.refresh_roster()
        self._refresh_template_choices()
        self.refresh_formation_preview()

    def refresh_roster(self):
        if not self.parsed or self.active_team_index is None:
            return
        self.roster_tree.delete(*self.roster_tree.get_children())
        t = self.parsed.teams[self.active_team_index]
        r = self.parsed.rosters[self.active_team_index]
        for slot, pid in enumerate(r["player_ids"]):
            if not pid:
                continue
            p = self.parsed.players.get(pid)
            player_name = p["name"] if p else f"ID sem cadastro ({pid})"
            self.roster_tree.insert("", "end", iid=str(slot), values=(r["numbers"][slot], player_name, f"{pid} (0x{pid:08X})"))
        self.status_var.set(f"Equipe: {t['name']} | ID {t['id']} | {sum(1 for pid in r['player_ids'] if pid)} jogadores.")

    def _update_team_count(self, team_index: int):
        if not self.parsed:
            return
        r = self.parsed.rosters[team_index]
        count = sum(1 for pid in r["player_ids"] if pid)
        iid = str(team_index)
        if self.team_tree.exists(iid):
            self.team_tree.set(iid, "count", count)

    def save_team_details(self):
        if not self._ensure_writable():
            return
        if not self.parsed or self.active_team_index is None:
            messagebox.showwarning("Seleção incompleta", "Selecione uma equipe primeiro.")
            return
        team = self.parsed.teams[self.active_team_index]
        name = self.team_name_var.get()
        short = self.team_short_var.get()
        if len(name.encode("utf-8")) > TEAM_NAME_SIZE:
            messagebox.showerror("Nome muito longo", "O nome da equipe ultrapassa 70 bytes UTF-8.")
            return
        if len(short.encode("utf-8")) > TEAM_SHORT_SIZE:
            messagebox.showerror("Sigla muito longa", "A sigla deve ocupar no máximo 3 bytes UTF-8.")
            return
        self.parsed.data[team["offset"] + TEAM_NAME_REL:team["offset"] + TEAM_NAME_REL + TEAM_NAME_SIZE] = encode_fixed(name, TEAM_NAME_SIZE)
        self.parsed.data[team["offset"] + TEAM_SHORT_REL:team["offset"] + TEAM_SHORT_REL + TEAM_SHORT_SIZE] = encode_fixed(short, TEAM_SHORT_SIZE)
        team["name"], team["short"] = name, short
        self.team_tree.item(str(self.active_team_index), text=name)
        self.filter_teams()
        self._refresh_template_choices()
        self.dirty = True
        self.status_var.set("Nome/sigla da equipe atualizados em memória. Salve para gravar.")

    def on_roster_select(self, _event=None):
        if not self.parsed or self.active_team_index is None:
            return
        sel = self.roster_tree.selection()
        if not sel:
            return
        self.active_slot = int(sel[0])
        r = self.parsed.rosters[self.active_team_index]
        pid = r["player_ids"][self.active_slot]
        self.active_player_id = pid
        self.number_var.set(str(r["numbers"][self.active_slot]))
        self.load_player_details(pid)

    def on_library_select(self, _event=None):
        sel = self.library_tree.selection()
        if sel:
            self.selected_library_id = int(sel[0])
            # A seleção no banco também carrega os dados do jogador para consulta/edição,
            # mesmo que ele não esteja no elenco atualmente selecionado.
            self.load_player_details(self.selected_library_id)

    def search_players(self):
        if not self.parsed:
            return
        query = self.search_var.get().strip().casefold()
        self.library_tree.delete(*self.library_tree.get_children())
        found = 0
        for p in self.player_rows:
            if query:
                if query not in p["name"].casefold() and query not in p["shirt_name"].casefold() and query not in str(p["id"]):
                    continue
            self.library_tree.insert("", "end", iid=str(p["id"]), text=p["name"], values=(p["id"], p["shirt_name"]))
            found += 1
            if found >= 400:
                break
        self.status_var.set(f"Busca: {found} resultado(s) exibido(s). Digite parte do nome ou o ID para filtrar.")
        self.selected_library_id = None

    def replace_player(self):
        if not self._ensure_writable():
            return
        if not self.parsed or self.active_team_index is None or self.active_slot is None or self.selected_library_id is None:
            messagebox.showwarning("Seleção incompleta", "Selecione uma equipe, uma vaga do elenco e um jogador no banco.")
            return
        pid = self.selected_library_id
        r = self.parsed.rosters[self.active_team_index]
        if pid in r["player_ids"] and r["player_ids"][self.active_slot] != pid:
            messagebox.showwarning("Jogador duplicado", "Esse jogador já está neste elenco. A substituição foi cancelada.")
            return
        old = r["player_ids"][self.active_slot]
        slot_off = r["offset"] + ROSTER_PLAYERS_REL + self.active_slot * 4
        struct.pack_into(">I", self.parsed.data, slot_off, pid)
        r["player_ids"][self.active_slot] = pid
        self.active_player_id = pid
        self.refresh_roster()
        self.roster_tree.selection_set(str(self.active_slot))
        self.load_player_details(pid)
        self.dirty = True
        self.status_var.set(f"Vaga {self.active_slot + 1}: {old} → {pid}. Número da camisa preservado.")


    def add_player_to_team(self):
        if not self._ensure_writable():
            return
        if not self.parsed or self.active_team_index is None or self.selected_library_id is None:
            messagebox.showwarning("Seleção incompleta", "Selecione uma equipe e um jogador no banco.")
            return
        r = self.parsed.rosters[self.active_team_index]
        pid = self.selected_library_id
        if pid in r["player_ids"]:
            messagebox.showwarning("Jogador já presente", "Esse jogador já faz parte deste elenco.")
            return
        try:
            number_text = self.number_var.get().strip()
            shirt_number = int(number_text) if number_text else 0
            if not 0 <= shirt_number <= 99:
                raise ValueError
        except ValueError:
            messagebox.showerror("Número inválido", "O número da camisa deve estar entre 0 e 99.")
            return
        try:
            slot = r["player_ids"].index(0)
        except ValueError:
            messagebox.showwarning("Elenco cheio", "A equipe já ocupa as 32 vagas disponíveis.")
            return
        slot_off = r["offset"] + ROSTER_PLAYERS_REL + slot * 4
        struct.pack_into(">I", self.parsed.data, slot_off, pid)
        self.parsed.data[r["offset"] + ROSTER_NUMBERS_REL + slot] = shirt_number
        r["player_ids"][slot] = pid
        r["numbers"][slot] = shirt_number
        self.active_slot = slot
        self.active_player_id = pid
        self.dirty = True
        self.refresh_roster()
        self._update_team_count(self.active_team_index)
        self.roster_tree.selection_set(str(slot))
        self.load_player_details(pid)
        self.status_var.set(f"{self.parsed.players[pid]['name']} adicionado à equipe na vaga {slot + 1}.")

    def remove_player_from_team(self):
        if not self._ensure_writable():
            return
        if not self.parsed or self.active_team_index is None or self.active_slot is None:
            messagebox.showwarning("Seleção incompleta", "Selecione um jogador do elenco para remover.")
            return
        r = self.parsed.rosters[self.active_team_index]
        old_slot = self.active_slot
        old_pid = r["player_ids"][old_slot]
        if not old_pid:
            return
        new_ids = [pid for i, pid in enumerate(r["player_ids"]) if pid and i != old_slot]
        new_numbers = [num for i, num in enumerate(r["numbers"]) if r["player_ids"][i] and i != old_slot]
        new_ids += [0] * (ROSTER_PLAYER_COUNT - len(new_ids))
        new_numbers += [0] * (ROSTER_PLAYER_COUNT - len(new_numbers))
        for slot, pid in enumerate(new_ids):
            struct.pack_into(">I", self.parsed.data, r["offset"] + ROSTER_PLAYERS_REL + slot * 4, pid)
        self.parsed.data[r["offset"] + ROSTER_NUMBERS_REL:r["offset"] + ROSTER_NUMBERS_REL + ROSTER_PLAYER_COUNT] = bytes(new_numbers)
        r["player_ids"] = new_ids
        r["numbers"] = new_numbers
        self.dirty = True
        self.active_slot = min(old_slot, len([pid for pid in new_ids if pid]) - 1) if any(new_ids) else None
        self.active_player_id = new_ids[self.active_slot] if self.active_slot is not None else None
        self.refresh_roster()
        self._update_team_count(self.active_team_index)
        if self.active_slot is not None:
            self.roster_tree.selection_set(str(self.active_slot))
            self.load_player_details(self.active_player_id)
        else:
            self._clear_player_details()
        self.status_var.set(f"Jogador ID {old_pid} removido. Os demais foram reorganizados sem lacunas.")

    def change_number(self):
        if not self._ensure_writable():
            return
        if not self.parsed or self.active_team_index is None or self.active_slot is None:
            messagebox.showwarning("Seleção incompleta", "Selecione uma vaga do elenco primeiro.")
            return
        try:
            val = int(self.number_var.get())
            if not 0 <= val <= 99:
                raise ValueError
        except ValueError:
            messagebox.showerror("Número inválido", "O número da camisa deve estar entre 0 e 99.")
            return
        r = self.parsed.rosters[self.active_team_index]
        self.parsed.data[r["offset"] + ROSTER_NUMBERS_REL + self.active_slot] = val
        r["numbers"][self.active_slot] = val
        self.refresh_roster()
        self.roster_tree.selection_set(str(self.active_slot))
        self.dirty = True
        self.status_var.set(f"Número da camisa da vaga {self.active_slot + 1} atualizado para {val}.")

    def load_player_details(self, pid: int):
        if not self.parsed or pid not in self.parsed.players:
            self.detail_player_id = None
            return
        self.detail_player_id = pid
        p = parse_player(self.parsed.data, self.parsed.players[pid]["index"])
        self.parsed.players[pid] = p
        a = p["attributes"]
        basics = {
            "name": p["name"], "shirt_name": p["shirt_name"], "nationality_id": p["nationality_id"],
            "height": p["height"], "weight": p["weight"], "age": a["age"],
            "play_style": a["play_style"], "form": a["form"], "strong_foot": a["strong_foot"],
            "fk_motion": a["fk_motion"], "injury_resistance": a["injury_resistance"],
            "weak_foot_accuracy": a["weak_foot_accuracy"], "weak_foot_usage": a["weak_foot_usage"],
            "dribble_arm_motion": a["dribble_arm_motion"], "run_arm_motion": a["run_arm_motion"],
            "corner_motion": a["corner_motion"], "dribble_hunch_motion": a["dribble_hunch_motion"],
            "run_hunch_motion": a["run_hunch_motion"], "pk_motion": a["pk_motion"],
        }
        for k, v in basics.items():
            self.detail_entries[k].set(str(v))
        for k in ATTRIBUTE_FIELDS:
            self.stat_entries[k].set(str(a[k]))
        self.skill_var.set(", ".join(SKILL_PT.get(name, name) for name in p["skills"]))
        self.com_var.set(", ".join(COM_PT.get(name, name) for name in p["com_styles"]))
        self.position_var.set(", ".join(str(a[field]) for field in PLAY_POSITION_FIELDS))
        if self.appearance_text is not None:
            self.appearance_text.configure(state="normal")
            self.appearance_text.delete("1.0", "end")
            self.appearance_text.insert("1.0", p["appearance_raw"])
            self.appearance_text.configure(state="disabled")
        self.player_id_label.config(text=f"ID: {pid} (0x{pid:08X}) | Registro: 0x{p['offset']:X} | Código de posição não interpretado: {a['reg_pos_code']}")

    def save_player_details(self):
        if not self._ensure_writable():
            return
        if not self.parsed or self.detail_player_id is None:
            messagebox.showwarning("Seleção incompleta", "Selecione um jogador no elenco ou no banco de jogadores.")
            return
        editing_player_id = self.detail_player_id
        p = self.parsed.players[editing_player_id]
        off = PLAYER_TABLE_OFFSET + p["index"] * PLAYER_STRIDE
        try:
            name = self.detail_entries["name"].get()
            shirt = self.detail_entries["shirt_name"].get()
            nation = int(self.detail_entries["nationality_id"].get())
            height = int(self.detail_entries["height"].get())
            weight = int(self.detail_entries["weight"].get())
            age = int(self.detail_entries["age"].get())
            style = int(self.detail_entries["play_style"].get())
            form = int(self.detail_entries["form"].get())
            foot = int(self.detail_entries["strong_foot"].get())
            if not 0 <= nation <= 65535: raise ValueError("Nacionalidade deve ser 0–65535.")
            if not 130 <= height <= 230: raise ValueError("Altura deve ficar entre 130 e 230 cm.")
            if not 30 <= weight <= 150: raise ValueError("Peso deve ficar entre 30 e 150 kg.")
            if not 15 <= age <= 50: raise ValueError("Idade deve estar entre 15 e 50.")
            if not 0 <= style <= 17: raise ValueError("Estilo deve estar entre 0 e 17.")
            if not 0 <= form <= 7: raise ValueError("Forma deve estar entre 0 e 7.")
            if foot not in (0, 1): raise ValueError("Pé forte deve ser 0 (direito) ou 1 (esquerdo).")
            other_ranges = {"fk_motion": (0, 15), "injury_resistance": (0, 3), "weak_foot_accuracy": (0, 3), "weak_foot_usage": (0, 3), "dribble_arm_motion": (0, 7), "run_arm_motion": (0, 7), "corner_motion": (0, 7), "dribble_hunch_motion": (0, 3), "run_hunch_motion": (0, 3), "pk_motion": (0, 3)}
            other_values = {}
            for key, (lo, hi) in other_ranges.items():
                val = int(self.detail_entries[key].get())
                if not lo <= val <= hi:
                    raise ValueError(f"{key} deve estar entre {lo} e {hi}.")
                other_values[key] = val
            changed = {}
            for key in ATTRIBUTE_FIELDS:
                val = int(self.stat_entries[key].get())
                if not 40 <= val <= 99:
                    raise ValueError(f"{ATTRIBUTE_LABELS[key]} deve estar entre 40 e 99.")
                changed[key] = val
            skills_input_raw = [x.strip().casefold() for x in self.skill_var.get().split(",") if x.strip()]
            com_input_raw = [x.strip().casefold() for x in self.com_var.get().split(",") if x.strip()]
            skill_aliases = {x.casefold(): x for x in SKILL_NAMES}
            skill_aliases.update({v.casefold(): k for k, v in SKILL_PT.items()})
            com_aliases = {x.casefold(): x for x in COM_NAMES}
            com_aliases.update({v.casefold(): k for k, v in COM_PT.items()})
            skills_input = [skill_aliases.get(x, x) for x in skills_input_raw]
            com_input = [com_aliases.get(x, x) for x in com_input_raw]
            bad_skills = [x for x in skills_input if x not in skill_aliases]
            bad_com = [x for x in com_input if x not in com_aliases]
            if bad_skills: raise ValueError("Habilidade desconhecida: " + ", ".join(bad_skills))
            if bad_com: raise ValueError("Estilo COM desconhecido: " + ", ".join(bad_com))
            if len(set(skills_input)) > 10: raise ValueError("O jogo admite no máximo 10 habilidades nesta estrutura.")
            if len(set(com_input)) > 5: raise ValueError("O jogo admite no máximo 5 estilos COM nesta estrutura.")
        except ValueError as exc:
            messagebox.showerror("Valor inválido", str(exc))
            return

        self.parsed.data[off + PLAYER_NAME_REL:off + PLAYER_NAME_REL + PLAYER_NAME_SIZE] = encode_fixed(name, PLAYER_NAME_SIZE)
        self.parsed.data[off + PLAYER_SHIRT_REL:off + PLAYER_SHIRT_REL + PLAYER_SHIRT_SIZE] = encode_fixed(shirt, PLAYER_SHIRT_SIZE)
        struct.pack_into(">H", self.parsed.data, off + PLAYER_NATION_REL, nation)
        self.parsed.data[off + PLAYER_HEIGHT_REL] = height
        self.parsed.data[off + PLAYER_WEIGHT_REL] = weight
        for k, v in changed.items():
            bit, width = FIELD_BITS[k]
            set_bits_msb(self.parsed.data, off + PLAYER_STATS_REL, bit, width, v)
        for k, v in [("age", age), ("play_style", style), ("form", form), ("strong_foot", foot), *other_values.items()]:
            bit, width = FIELD_BITS[k]
            set_bits_msb(self.parsed.data, off + PLAYER_STATS_REL, bit, width, v)
        for i, skill in enumerate(SKILL_NAMES):
            key = "skill_scissors" if i == 0 else f"skill_{i}"
            bit, width = FIELD_BITS[key]
            set_bits_msb(self.parsed.data, off + PLAYER_STATS_REL, bit, width, 1 if skill in skills_input else 0)
        for name in COM_NAMES:
            bit, width = FIELD_BITS[f"com_{name}"]
            set_bits_msb(self.parsed.data, off + PLAYER_STATS_REL, bit, width, 1 if name in com_input else 0)
        self.parsed.players[editing_player_id] = parse_player(self.parsed.data, p["index"])
        # Atualiza também a lista global de pesquisa após uma renomeação.
        self.player_rows = sorted(self.parsed.players.values(), key=lambda item: (item["name"].casefold(), item["id"]))
        # refresh name visible in team list
        if self.active_team_index is not None:
            self.refresh_roster()
            current_roster = self.parsed.rosters[self.active_team_index]
            if self.active_slot is not None and current_roster["player_ids"][self.active_slot] == editing_player_id:
                self.roster_tree.selection_set(str(self.active_slot))
        self.load_player_details(editing_player_id)
        self.search_players()
        self.dirty = True
        self.status_var.set("Cadastro global do jogador atualizado. A alteração afeta todas as equipes que usam esse ID; salve uma cópia para gravar.")

    def _atomic_write(self, out: str):
        target = Path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        backup_path = None
        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup_path = target.with_name(target.name + f".{stamp}.bak")
            shutil.copy2(target, backup_path)
        temp_path = None
        replaced = False
        try:
            with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(target.parent), prefix=target.name + ".", suffix=".tmp") as tmp:
                tmp.write(self.parsed.data)
                tmp.flush()
                os.fsync(tmp.fileno())
                temp_path = tmp.name
            os.replace(temp_path, out)
            replaced = True
            verified = parse_file(target.read_bytes())
            self.parsed = verified
            self.dirty = False
            self.working_path = out
            self.status_var.set(f"Cópia salva e validada: {out}")
            backup_note = f"\nBackup anterior: {backup_path}" if backup_path else ""
            messagebox.showinfo("Arquivo salvo", "Cópia gravada e validada. O arquivo original foi preservado." + backup_note + "\n\nA integração/criptografia do save do Xbox 360 continua desativada até o primeiro teste no console.")
        except Exception:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            if replaced:
                if backup_path and backup_path.exists():
                    shutil.copy2(backup_path, target)
                elif target.exists():
                    target.unlink()
            raise

    def save_current(self):
        if not self._ensure_writable():
            return
        if not self.parsed:
            messagebox.showwarning("Nenhum arquivo", "Abra e valide um data.bin primeiro.")
            return
        if not self.dirty and self.working_path:
            self.status_var.set("Nenhuma alteração nova para salvar.")
            return
        if self.working_path:
            try:
                if self.source_path and os.path.abspath(self.working_path) == self.source_path:
                    messagebox.showerror("Proteção do original", "A gravação direta no arquivo original está bloqueada.")
                    return
                self._atomic_write(self.working_path)
            except Exception as exc:
                messagebox.showerror("Falha ao salvar", str(exc))
        else:
            self.save_as()

    def save_as(self):
        if not self._ensure_writable():
            return
        if not self.parsed or not self.source_path:
            messagebox.showwarning("Nenhum arquivo", "Abra e valide um data.bin primeiro.")
            return
        path = filedialog.asksaveasfilename(title="Salvar cópia editada", defaultextension=".bin", filetypes=[("BIN", "*.bin"), ("Todos", "*.*")])
        if not path:
            return
        out = os.path.abspath(path)
        if out == self.source_path:
            messagebox.showerror("Proteção do original", "Escolha outro nome/caminho. O arquivo original nunca será sobrescrito.")
            return
        if os.path.exists(out) and not messagebox.askyesno("Substituir arquivo?", "O destino já existe. Será criado um backup .bak antes da substituição. Continuar?"):
            return
        try:
            validate_roundtrip(self.parsed)
            self._atomic_write(out)
        except Exception as exc:
            messagebox.showerror("Falha ao salvar", str(exc))

    def export_current_roster(self):
        if not self.parsed or self.active_team_index is None:
            messagebox.showwarning("Seleção incompleta", "Selecione uma equipe primeiro.")
            return
        path = filedialog.asksaveasfilename(title="Exportar elenco para CSV", defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        import csv
        t = self.parsed.teams[self.active_team_index]
        r = self.parsed.rosters[self.active_team_index]
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["equipe", "team_id", "slot", "camisa", "player_id", "nome", "nome_camisa", "idade", "codigo_posicao"])
                for slot, pid in enumerate(r["player_ids"]):
                    if not pid:
                        continue
                    p = parse_player(self.parsed.data, self.parsed.players[pid]["index"])
                    a = p["attributes"]
                    w.writerow([t["name"], t["id"], slot + 1, r["numbers"][slot], pid, p["name"], p["shirt_name"], a["age"], a["reg_pos_code"]])
            messagebox.showinfo("Exportação concluída", f"Elenco exportado para:\n{path}")
        except Exception as exc:
            messagebox.showerror("Falha na exportação", str(exc))

    def destroy(self):
        if getattr(self, "dirty", False) and not self._confirm_discard():
            return
        super().destroy()


def main():
    parser = argparse.ArgumentParser(description="Editor conservador de elencos PES 2018 Xbox 360")
    parser.add_argument("file", nargs="?", help="caminho do data.bin validado")
    parser.add_argument("--validate", action="store_true", help="apenas validar e imprimir relatório JSON")
    args = parser.parse_args()
    if args.validate:
        if not args.file:
            parser.error("Informe o caminho do data.bin após --validate")
        parsed = parse_file(Path(args.file).read_bytes())
        print(json.dumps(summarize(parsed), ensure_ascii=False, indent=2))
        return
    app = PesEditor()
    app.mainloop()

if __name__ == "__main__":
    main()
