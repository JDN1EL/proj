#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PES 2018 Xbox 360 Editor v0.8 — edição local PlayersDB, elencos e salvamento seguro.

Edita somente data.bin extraído. Não descriptografa, reempacota ou reassina STFS.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import queue
import shutil
import struct
import sys
import tempfile
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from playersdb_local import load_dataset, download_latest, norm as db_norm
import webbrowser

PLAYER_COUNT_OFFSET = 0x60
TEAM_COUNT_OFFSET = 0x64
ROSTER_COUNT_OFFSET = 0x70
PLAYER_TABLE_OFFSET = 0x7C
PLAYER_STRIDE = 0xBC
PLAYER_CAPACITY = 21000
TEAM_TABLE_OFFSET = PLAYER_TABLE_OFFSET + PLAYER_CAPACITY * PLAYER_STRIDE
TEAM_STRIDE = 0x1E0
ROSTER_TABLE_OFFSET = 0x46FF54
ROSTER_STRIDE = 0xA4
TACTICS_TABLE_OFFSET = 0x488B74
TACTICS_STRIDE = 0x274
TEAM_NAME_REL = 0x98
TEAM_NAME_SIZE = 70
TEAM_SHORT_REL = 0xDE
TEAM_SHORT_SIZE = 3
ROSTER_PLAYER_REL = 0x04
ROSTER_PLAYER_COUNT = 32
ROSTER_NUMBERS_REL = 0x84
PLAYER_NAME_REL = 0x34
PLAYER_NAME_SIZE = 46
PLAYER_SHIRT_REL = 0x62
PLAYER_SHIRT_SIZE = 18


def u16(buf: bytes | bytearray, off: int) -> int:
    return struct.unpack_from(">H", buf, off)[0]


def p16(buf: bytearray, off: int, value: int) -> None:
    struct.pack_into(">H", buf, off, max(0, min(65535, int(value))))


def decode(raw: bytes | bytearray) -> str:
    return bytes(raw).split(b"\0", 1)[0].decode("utf-8", "replace").strip()


def encode(text: str, size: int) -> bytes:
    raw = str(text).encode("utf-8")[:size]
    while True:
        try:
            raw.decode("utf-8")
            break
        except UnicodeDecodeError:
            raw = raw[:-1]
    return raw + b"\0" * (size - len(raw))


class Editor:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("PES 2018 Xbox 360 Editor v0.8")
        root.geometry("1240x780")
        root.minsize(1050, 650)
        self.data: bytearray | None = None
        self.path: str | None = None
        self.dirty = False
        self.undo: list[bytes] = []
        self.redo: list[bytes] = []
        self.players: list[dict] = []
        self.teams: list[dict] = []
        self.rosters: list[dict] = []
        self.playersdb_entries: list[dict] = []
        self.playersdb_path: str | None = None
        self.playersdb_thread: threading.Thread | None = None
        self.manual_ids: set[int] = set()
        self.sync_queue: queue.Queue = queue.Queue()
        self.busy_states = {}

        appdata = os.environ.get("APPDATA", str(Path.home()))
        self.config_dir = Path(appdata) / "PES2018_X360_Editor"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.database_dir = self.config_dir / "database"
        self.state_path = self.config_dir / "manual_changes.json"
        self.logs_dir = self._resolve_logs_dir()
        self.load_manual_state()
        self.build()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _app_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent

    def _resolve_logs_dir(self) -> Path:
        preferred = self._app_dir() / "logs"
        try:
            preferred.mkdir(parents=True, exist_ok=True)
            test = preferred / ".write_test"
            test.write_text("ok", encoding="utf-8")
            test.unlink(missing_ok=True)
            return preferred
        except OSError:
            fallback = self.config_dir / "logs"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback

    def load_manual_state(self) -> None:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.manual_ids = {int(x) for x in data.get("manual_player_ids", [])}
        except Exception:
            self.manual_ids = set()

    def save_manual_state(self) -> None:
        try:
            payload = {"manual_player_ids": sorted(self.manual_ids)}
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except Exception as exc:
            self.status.set(f"Aviso: não foi possível salvar estado manual: {exc}")

    def build(self) -> None:
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=8, pady=6)
        self.main_buttons = []
        for label, command in [
            ("Abrir data.bin", self.open_file),
            ("Salvar como...", self.save),
            ("Baixar / carregar PlayersDB", self.load_playersdb),
            ("Atualizar elencos pelo arquivo", self.update_squads),
            ("Desfazer", self.undo_edit),
            ("Refazer", self.redo_edit),
            ("Exportar CSV", self.export_csv),
            ("Abrir pasta logs", self.open_logs_folder),
        ]:
            button = ttk.Button(bar, text=label, command=command)
            button.pack(side="left", padx=3)
            self.main_buttons.append(button)

        self.status = tk.StringVar(value="Abra um data.bin extraído do EDIT00000000.")
        ttk.Label(self.root, textvariable=self.status).pack(anchor="w", padx=10)
        progress_frame = ttk.Frame(self.root)
        progress_frame.pack(fill="x", padx=10, pady=(3, 0))
        self.progress = ttk.Progressbar(progress_frame, mode="determinate", maximum=1, value=0)
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress_text = tk.StringVar(value="Aguardando base local PlayersDB.")
        ttk.Label(progress_frame, textvariable=self.progress_text, width=52, anchor="e").pack(side="left", padx=8)

        panes = ttk.Panedwindow(self.root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=8, pady=8)
        left_container = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left_container, weight=3)
        panes.add(right, weight=2)
        notebook = ttk.Notebook(left_container)
        notebook.pack(fill="both", expand=True)
        left = ttk.Frame(notebook)
        notebook.add(left, text="Jogadores")
        self.clubs_tab = ttk.Frame(notebook)
        notebook.add(self.clubs_tab, text="Clubes / Seleções")
        ttk.Label(left, text="Jogadores").pack(anchor="w")
        search_frame = ttk.Frame(left)
        search_frame.pack(fill="x")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.refresh_players())
        search_entry = ttk.Entry(search_frame, textvariable=self.search)
        search_entry.pack(side="left", fill="x", expand=True)
        ttk.Label(search_frame, text="Buscar nome / ID").pack(side="right")
        self.tree = ttk.Treeview(left, columns=("id", "name", "team"), show="headings", selectmode="browse")
        for col, title, width in [("id", "ID", 70), ("name", "Jogador", 260), ("team", "Equipe", 190)]:
            self.tree.heading(col, text=title, command=lambda c=col: self.sort_tree(self.tree, c))
            self.tree.column(col, width=width)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.select_player)
        actions = ttk.Frame(left)
        actions.pack(fill="x", pady=5)
        for title, command in [("Transferir", self.transfer), ("Adicionar jogador", self.add_player), ("Remover jogador", self.remove_player), ("Substituir vaga", self.replace_player)]:
            b = ttk.Button(actions, text=title, command=command)
            b.pack(side="left", padx=2)
            self.main_buttons.append(b)

        ttk.Label(self.clubs_tab, text="Selecione uma equipe e veja o elenco atual.").pack(anchor="w", padx=6, pady=(6, 2))
        club_pane = ttk.Panedwindow(self.clubs_tab, orient="vertical")
        club_pane.pack(fill="both", expand=True, padx=6, pady=4)
        club_top = ttk.Frame(club_pane)
        club_bottom = ttk.Frame(club_pane)
        club_pane.add(club_top, weight=1)
        club_pane.add(club_bottom, weight=2)
        ttk.Label(club_top, text="Clubes e seleções").pack(anchor="w")
        self.club_tree = ttk.Treeview(club_top, columns=("id", "name"), show="headings", height=7)
        self.club_tree.heading("id", text="ID"); self.club_tree.column("id", width=55)
        self.club_tree.heading("name", text="Equipe"); self.club_tree.column("name", width=360)
        self.club_tree.pack(fill="both", expand=True)
        self.club_tree.bind("<<TreeviewSelect>>", self.select_club_tab)
        ttk.Label(club_bottom, text="Jogadores da equipe selecionada").pack(anchor="w")
        self.club_roster_tree = ttk.Treeview(club_bottom, columns=("id", "name", "shirt"), show="headings", height=9)
        for col, title, width in [("id", "ID", 55), ("name", "Jogador", 280), ("shirt", "Camisa", 65)]:
            self.club_roster_tree.heading(col, text=title); self.club_roster_tree.column(col, width=width)
        self.club_roster_tree.pack(fill="both", expand=True)
        club_actions = ttk.Frame(club_bottom); club_actions.pack(fill="x", pady=5)
        for title, command in [("Transferir jogador selecionado", self.transfer_to_selected_club), ("Convocar para seleção", self.call_up_to_selected_team), ("Adicionar jogador ao elenco", self.add_selected_player_to_club)]:
            btn=ttk.Button(club_actions, text=title, command=command); btn.pack(side="left", padx=2); self.main_buttons.append(btn)
        ttk.Label(self.clubs_tab, text="Competições: a tabela/offset ainda não foi identificado com segurança; esta versão não altera esses nomes.", foreground="#9a5b00").pack(anchor="w", padx=8, pady=(4, 2))
        self.db_status = tk.StringVar(value="PlayersDB: ainda não carregado")
        ttk.Label(self.clubs_tab, textvariable=self.db_status).pack(anchor="w", padx=8, pady=(0, 5))

        ttk.Label(right, text="Editor de jogador").pack(anchor="w")
        self.fields = {}
        form = ttk.Frame(right)
        form.pack(fill="x")
        field_rows = [
            ("Nome", "name"), ("Nome da camisa", "shirt"), ("Idade", "age"),
            ("Altura", "height"), ("Peso", "weight"), ("Nacionalidade (ID)", "nation"),
            ("Pé dominante (byte 0x0E)", "foot"), ("Uso pé ruim (byte 0x0F)", "weak_use"),
            ("Precisão pé ruim (byte 0x10)", "weak_acc"), ("Resistência lesões (byte 0x11)", "injury"),
        ]
        for i, (label, key) in enumerate(field_rows):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", pady=2)
            value = tk.StringVar()
            self.fields[key] = value
            ttk.Entry(form, textvariable=value, width=24).grid(row=i, column=1, sticky="ew", pady=2)
        ttk.Label(right, text="Atributos técnicos/físicos (26 bytes: 0x12–0x2B)").pack(anchor="w", pady=(12, 2))
        self.stats = tk.StringVar(value="")
        ttk.Entry(right, textvariable=self.stats).pack(fill="x")
        ttk.Label(right, text="Digite 26 valores separados por vírgula (0–255).").pack(anchor="w")
        ttk.Label(right, text="Habilidades especiais / estilos COM (8 bytes: 0x2C–0x33)").pack(anchor="w", pady=(10, 2))
        self.skills = tk.StringVar(value="")
        ttk.Entry(right, textvariable=self.skills).pack(fill="x")
        b = ttk.Button(right, text="Aplicar alterações ao jogador", command=self.apply_player)
        b.pack(anchor="e", pady=8)
        self.main_buttons.append(b)

        ttk.Separator(right).pack(fill="x", pady=8)
        ttk.Label(right, text="Equipes").pack(anchor="w")
        self.team_list = ttk.Treeview(right, columns=("id", "name", "short"), show="headings", height=7)
        for col, title, width in [("id", "ID", 50), ("name", "Equipe", 180), ("short", "Sigla", 70)]:
            self.team_list.heading(col, text=title, command=lambda c=col: self.sort_tree(self.team_list, c))
            self.team_list.column(col, width=width)
        self.team_list.pack(fill="x")
        self.team_list.bind("<<TreeviewSelect>>", self.select_team)
        team_frame = ttk.Frame(right)
        team_frame.pack(fill="x", pady=4)
        self.tname = tk.StringVar()
        self.tshort = tk.StringVar()
        ttk.Entry(team_frame, textvariable=self.tname, width=22).pack(side="left")
        ttk.Entry(team_frame, textvariable=self.tshort, width=6).pack(side="left", padx=3)
        b = ttk.Button(team_frame, text="Salvar nome/sigla", command=self.apply_team)
        b.pack(side="left")
        self.main_buttons.append(b)
        b = ttk.Button(right, text="Copiar elenco + táticas para equipe...", command=self.copy_team)
        b.pack(anchor="e", pady=3)
        self.main_buttons.append(b)
        self._busy_widget_candidates = []
        self.help_var = tk.StringVar(value="Dica: passe o mouse ou clique em um controle para ver o que ele faz.")
        help_frame=ttk.Frame(self.root, relief="ridge", padding=(10,5))
        help_frame.pack(side="bottom", fill="x", padx=8, pady=(0,7))
        ttk.Label(help_frame, textvariable=self.help_var, anchor="center").pack(fill="x")
        self._install_help_hints()

    def _install_help_hints(self):
        descriptions={
            "Abrir data.bin":"Abre o arquivo de dados extraído do EDIT00000000; não abre nem reempacota o STFS.",
            "Salvar como...":"Grava uma cópia do data.bin; cria backup .bak e verifica o arquivo gravado.",
            "Baixar / carregar PlayersDB":"Baixa o CSV/JSONL do PlayersDB ou permite selecionar um arquivo já baixado.",
            "Atualizar elencos pelo arquivo":"Usa somente o PlayersDB local para corrigir nomes e reconstruir elencos com correspondências seguras.",
            "Desfazer":"Reverte a última alteração feita nesta sessão.",
            "Refazer":"Restaura a alteração desfeita.",
            "Exportar CSV":"Exporta a lista de jogadores do data.bin para CSV.",
            "Abrir pasta logs":"Abre a pasta de relatórios e diagnósticos.",
            "Transferir jogador selecionado":"Move o jogador selecionado na aba Jogadores para a equipe selecionada, removendo-o do elenco anterior.",
            "Convocar para seleção":"Adiciona o jogador à seleção selecionada sem removê-lo do clube. A faixa de seleções identificada é 0–54.",
            "Adicionar jogador ao elenco":"Adiciona o jogador selecionado ao elenco da equipe, sem removê-lo de outro elenco. Exige vaga livre.",
            "Aplicar alterações ao jogador":"Grava os campos editados na memória; use Salvar como para persistir no arquivo.",
            "Salvar nome/sigla":"Altera o nome e a sigla da equipe selecionada.",
        }
        for widget in self._walk_widgets(self.root):
            try:
                label=str(widget.cget("text"))
            except Exception: label=""
            hint=descriptions.get(label)
            if hint:
                widget.bind("<Enter>",lambda _e,msg=hint:self.help_var.set(msg),add="+")
                widget.bind("<Button-1>",lambda _e,msg=hint:self.help_var.set(msg),add="+")
            else:
                if isinstance(widget,ttk.Treeview):
                    generic="Tabela: selecione uma linha para ver os dados e usar as ações da aba."
                elif isinstance(widget,(ttk.Entry,tk.Entry,tk.Text)):
                    generic="Campo de edição: informe o valor desejado; depois aplique ou salve."
                elif isinstance(widget,ttk.Notebook):
                    generic="Aba do editor: alterne entre jogadores e clubes/seleções."
                else:
                    generic="Área do editor: use os controles desta seção; passe o mouse para ver a função específica."
                widget.bind("<Enter>",lambda _e,msg=generic:self.help_var.set(msg),add="+")
                widget.bind("<Button-1>",lambda _e,msg=generic:self.help_var.set(msg),add="+")

    def sort_tree(self, tree: ttk.Treeview, column: str) -> None:
        items = [(tree.set(iid, column), iid) for iid in tree.get_children("")]
        reverse = getattr(tree, "_sort_reverse", {}).get(column, False) if hasattr(tree, "_sort_reverse") else False
        try:
            items.sort(key=lambda x: int(x[0]), reverse=reverse)
        except (ValueError, TypeError):
            items.sort(key=lambda x: x[0].casefold(), reverse=reverse)
        tree._sort_reverse = getattr(tree, "_sort_reverse", {})
        tree._sort_reverse[column] = not reverse
        for pos, (_, iid) in enumerate(items):
            tree.move(iid, "", pos)

    def snapshot(self) -> None:
        if self.data is None:
            return
        self.undo.append(bytes(self.data))
        self.undo = self.undo[-30:]
        self.redo.clear()
        self.dirty = True

    def open_file(self) -> None:
        path = filedialog.askopenfilename(title="Abrir data.bin extraído", filetypes=[("PES data.bin", "*.bin"), ("Todos os arquivos", "*.*")])
        if not path:
            return
        try:
            raw = Path(path).read_bytes()
            if raw[:4] in (b"CON ", b"LIVE", b"PIRS"):
                messagebox.showinfo("Pacote STFS", "Este arquivo é um pacote Xbox 360 (STFS). Extraia o data.bin do EDIT00000000 e abra esse arquivo aqui. Esta versão não reempacota nem reassina CON/LIVE/PIRS.")
                return
            if len(raw) < ROSTER_TABLE_OFFSET + ROSTER_STRIDE:
                raise ValueError("Arquivo pequeno demais para o layout PES 2018 Xbox 360.")
            if self.data is not None and self.dirty and not messagebox.askyesno("Abrir outro arquivo", "Descartar as alterações ainda não salvas e abrir outro arquivo?"):
                return
            self.data = bytearray(raw)
            self.path = os.path.abspath(path)
            self.undo.clear()
            self.redo.clear()
            self.dirty = False
            self.load_tables()
            self.status.set(f"{os.path.basename(path)} | {len(raw):,} bytes | {len(self.players)} jogadores | {len(self.teams)} equipes")
            self.auto_prepare_playersdb()
        except Exception as exc:
            messagebox.showerror("Erro ao abrir", str(exc))

    def load_tables(self) -> None:
        if self.data is None:
            return
        b = self.data
        if len(b) < max(PLAYER_COUNT_OFFSET + 2, TEAM_COUNT_OFFSET + 2, ROSTER_COUNT_OFFSET + 2):
            raise ValueError("Cabeçalho incompleto.")
        player_count = min(u16(b, PLAYER_COUNT_OFFSET), PLAYER_CAPACITY)
        team_count = min(u16(b, TEAM_COUNT_OFFSET), 2048)
        roster_count = min(u16(b, ROSTER_COUNT_OFFSET), 4096)
        if PLAYER_TABLE_OFFSET + player_count * PLAYER_STRIDE > len(b):
            raise ValueError("Tabela de jogadores ultrapassa o tamanho do arquivo.")
        if TEAM_TABLE_OFFSET + team_count * TEAM_STRIDE > len(b):
            raise ValueError("Tabela de equipes ultrapassa o tamanho do arquivo.")
        if ROSTER_TABLE_OFFSET + roster_count * ROSTER_STRIDE > len(b):
            raise ValueError("Tabela de elencos ultrapassa o tamanho do arquivo.")
        self.players = []
        for i in range(player_count):
            off = PLAYER_TABLE_OFFSET + i * PLAYER_STRIDE
            self.players.append({"id": i, "off": off, "name": decode(b[off + PLAYER_NAME_REL:off + PLAYER_NAME_REL + PLAYER_NAME_SIZE])})
        self.teams = []
        for i in range(team_count):
            off = TEAM_TABLE_OFFSET + i * TEAM_STRIDE
            self.teams.append({"id": i, "off": off, "name": decode(b[off + TEAM_NAME_REL:off + TEAM_NAME_REL + TEAM_NAME_SIZE]), "short": decode(b[off + TEAM_SHORT_REL:off + TEAM_SHORT_REL + TEAM_SHORT_SIZE])})
        self.rosters = []
        for i in range(roster_count):
            off = ROSTER_TABLE_OFFSET + i * ROSTER_STRIDE
            ids = [u16(b, off + ROSTER_PLAYER_REL + j * 2) for j in range(ROSTER_PLAYER_COUNT)]
            numbers = [b[off + ROSTER_NUMBERS_REL + j] for j in range(ROSTER_PLAYER_COUNT)]
            self.rosters.append({"team": i, "off": off, "ids": ids, "numbers": numbers})
        self.refresh_players()
        self.refresh_teams()
        self.refresh_club_tab()

    def team_for(self, pid: int) -> str:
        # A tabela lista clubes primeiro; seleção fica como fallback para o jogador convocado.
        for roster in sorted(self.rosters, key=lambda r: r["team"] <= 54):
            if pid in roster["ids"]:
                team_id = roster["team"]
                return self.teams[team_id]["name"] if team_id < len(self.teams) else str(team_id)
        return "Sem equipe"

    def refresh_players(self) -> None:
        if self.data is None or not hasattr(self, "tree"):
            return
        query = self.search.get().casefold()
        self.tree.delete(*self.tree.get_children())
        for player in self.players:
            name = player["name"]
            if query and query not in name.casefold() and query not in str(player["id"]):
                continue
            self.tree.insert("", "end", iid=str(player["id"]), values=(player["id"], name, self.team_for(player["id"])))

    def refresh_teams(self) -> None:
        if not hasattr(self, "team_list"):
            return
        self.team_list.delete(*self.team_list.get_children())
        for team in self.teams:
            self.team_list.insert("", "end", iid=str(team["id"]), values=(team["id"], team["name"], team["short"]))
        self.refresh_club_tab()

    def refresh_club_tab(self):
        if not hasattr(self, "club_tree"):
            return
        selected=self.club_tree.selection()
        keep=selected[0] if selected else None
        self.club_tree.delete(*self.club_tree.get_children())
        for team in self.teams:
            self.club_tree.insert("", "end", iid=str(team["id"]), values=(team["id"], team["name"]))
        if keep and self.club_tree.exists(keep): self.club_tree.selection_set(keep)
        self.refresh_club_roster()

    def select_club_tab(self, _event=None):
        self.refresh_club_roster()

    def refresh_club_roster(self):
        if not hasattr(self, "club_roster_tree"):
            return
        self.club_roster_tree.delete(*self.club_roster_tree.get_children())
        sel=self.club_tree.selection()
        if not sel: return
        team_id=int(sel[0]); roster=self.find_roster(team_id)
        if not roster: return
        for pid,shirt in zip(roster["ids"],roster["numbers"]):
            if pid and pid < len(self.players):
                self.club_roster_tree.insert("", "end", iid=str(pid), values=(pid,self.players[pid]["name"],shirt))

    def selected_id(self) -> int | None:
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def select_player(self, _event=None) -> None:
        pid = self.selected_id()
        if pid is None or self.data is None:
            return
        player = self.players[pid]
        off = player["off"]
        b = self.data
        values = {
            "name": decode(b[off + PLAYER_NAME_REL:off + PLAYER_NAME_REL + PLAYER_NAME_SIZE]),
            "shirt": decode(b[off + PLAYER_SHIRT_REL:off + PLAYER_SHIRT_REL + PLAYER_SHIRT_SIZE]),
            "age": b[off + 8], "height": b[off + 0x0C], "weight": b[off + 0x0D],
            "nation": u16(b, off + 0x0A), "foot": b[off + 0x0E], "weak_use": b[off + 0x0F],
            "weak_acc": b[off + 0x10], "injury": b[off + 0x11],
        }
        for key, value in values.items():
            self.fields[key].set(str(value))
        self.stats.set(",".join(str(x) for x in b[off + 0x12:off + 0x2C]))
        self.skills.set(",".join(str(x) for x in b[off + 0x2C:off + 0x34]))

    def apply_player(self) -> None:
        pid = self.selected_id()
        if pid is None or self.data is None:
            return messagebox.showwarning("Selecione", "Selecione um jogador.")
        try:
            values = {key: var.get().strip() for key, var in self.fields.items()}
            nums = {key: int(values[key]) for key in ("age", "height", "weight", "nation", "foot", "weak_use", "weak_acc", "injury")}
            stats = [int(x.strip()) for x in self.stats.get().split(",")]
            skills = [int(x.strip()) for x in self.skills.get().split(",")]
            if len(stats) != 26 or len(skills) != 8:
                raise ValueError("Use exatamente 26 atributos e 8 bytes de habilidades/estilos.")
            if any(x < 0 or x > 255 for x in stats + skills):
                raise ValueError("Os valores dos atributos devem ficar entre 0 e 255.")
            self.snapshot()
            off = self.players[pid]["off"]
            self.data[off + PLAYER_NAME_REL:off + PLAYER_NAME_REL + PLAYER_NAME_SIZE] = encode(values["name"], PLAYER_NAME_SIZE)
            self.data[off + PLAYER_SHIRT_REL:off + PLAYER_SHIRT_REL + PLAYER_SHIRT_SIZE] = encode(values["shirt"], PLAYER_SHIRT_SIZE)
            for key, rel in [("age", 8), ("height", 0x0C), ("weight", 0x0D), ("foot", 0x0E), ("weak_use", 0x0F), ("weak_acc", 0x10), ("injury", 0x11)]:
                self.data[off + rel] = max(0, min(255, nums[key]))
            p16(self.data, off + 0x0A, nums["nation"])
            self.data[off + 0x12:off + 0x2C] = bytes(stats)
            self.data[off + 0x2C:off + 0x34] = bytes(skills)
            self.manual_ids.add(pid)
            self.save_manual_state()
            self.load_tables()
            self.tree.selection_set(str(pid))
            self.status.set("Jogador atualizado em memória. Salve para gravar no arquivo.")
        except Exception as exc:
            messagebox.showerror("Dados inválidos", str(exc))

    def selected_team(self) -> int | None:
        selection = self.team_list.selection()
        return int(selection[0]) if selection else None

    def select_team(self, _event=None) -> None:
        index = self.selected_team()
        if index is not None:
            self.tname.set(self.teams[index]["name"])
            self.tshort.set(self.teams[index]["short"])

    def apply_team(self) -> None:
        index = self.selected_team()
        if index is None or self.data is None:
            return
        self.snapshot()
        team = self.teams[index]
        off = team["off"]
        self.data[off + TEAM_NAME_REL:off + TEAM_NAME_REL + TEAM_NAME_SIZE] = encode(self.tname.get(), TEAM_NAME_SIZE)
        self.data[off + TEAM_SHORT_REL:off + TEAM_SHORT_REL + TEAM_SHORT_SIZE] = encode(self.tshort.get(), TEAM_SHORT_SIZE)
        team["name"] = self.tname.get()
        team["short"] = self.tshort.get()
        self.refresh_teams()
        self.refresh_players()
        self.status.set("Equipe atualizada em memória.")

    def find_roster(self, team_id: int):
        return next((r for r in self.rosters if r["team"] == team_id), None)

    def transfer(self) -> None:
        pid=self.selected_id()
        if pid is None or self.data is None: return
        dest=simpledialog.askinteger("Transferir jogador","ID do clube de destino (IDs 0–54 são seleções):",minvalue=55,maxvalue=max(55,len(self.teams)-1))
        if dest is None: return
        self._place_player(pid,dest,True)

    def add_player(self) -> None:
        if self.data is None:
            return
        name = simpledialog.askstring("Novo jogador", "Nome do jogador:")
        if not name:
            return
        pid = next((p["id"] for p in self.players if not p["name"] and p["id"] != 0), len(self.players))
        if pid >= PLAYER_CAPACITY:
            return messagebox.showerror("Limite", "Capacidade de jogadores atingida.")
        off = PLAYER_TABLE_OFFSET + pid * PLAYER_STRIDE
        if off + PLAYER_STRIDE > len(self.data):
            return messagebox.showerror("Limite", "Não há espaço físico reservado para outro registro de jogador neste arquivo.")
        self.snapshot()
        self.data[off:off + PLAYER_STRIDE] = b"\0" * PLAYER_STRIDE
        self.data[off + PLAYER_NAME_REL:off + PLAYER_NAME_REL + PLAYER_NAME_SIZE] = encode(name, PLAYER_NAME_SIZE)
        p16(self.data, PLAYER_COUNT_OFFSET, max(u16(self.data, PLAYER_COUNT_OFFSET), pid + 1))
        self.manual_ids.add(pid)
        self.save_manual_state()
        self.load_tables()
        self.tree.selection_set(str(pid))
        self.status.set("Novo registro criado. Complete os campos do jogador e salve.")

    def remove_player(self) -> None:
        pid = self.selected_id()
        if pid is None or self.data is None:
            return
        if not messagebox.askyesno("Remover", "Remover o jogador de todos os elencos e zerar seu registro?"):
            return
        self.snapshot()
        self.manual_ids.add(pid)
        for roster in self.rosters:
            for j, existing in enumerate(roster["ids"]):
                if existing == pid:
                    roster["ids"][j] = 0
                    roster["numbers"][j] = 0
                    p16(self.data, roster["off"] + ROSTER_PLAYER_REL + j * 2, 0)
                    self.data[roster["off"] + ROSTER_NUMBERS_REL + j] = 0
        off = self.players[pid]["off"]
        self.data[off:off + PLAYER_STRIDE] = b"\0" * PLAYER_STRIDE
        self.save_manual_state()
        self.load_tables()
        self.status.set("Registro zerado e removido dos elencos. IDs não são compactados.")

    def replace_player(self) -> None:
        pid = self.selected_id()
        if pid is None or self.data is None:
            return
        old = simpledialog.askinteger("Substituir vaga", "ID do jogador que será substituído:", minvalue=0)
        if old is None or old == pid:
            return
        found = [(r, j) for r in self.rosters for j, existing in enumerate(r["ids"]) if existing == old]
        if not found:
            return messagebox.showinfo("Não encontrado", "O ID informado não aparece nos elencos carregados.")
        self.snapshot()
        self.manual_ids.add(pid)
        target_slots = {(roster["team"], j) for roster, j in found}
        for roster in self.rosters:
            for j, existing in enumerate(roster["ids"]):
                if existing == pid and (roster["team"], j) not in target_slots:
                    roster["ids"][j] = 0
                    roster["numbers"][j] = 0
                    p16(self.data, roster["off"] + ROSTER_PLAYER_REL + j * 2, 0)
                    self.data[roster["off"] + ROSTER_NUMBERS_REL + j] = 0
        for roster, j in found:
            roster["ids"][j] = pid
            p16(self.data, roster["off"] + ROSTER_PLAYER_REL + j * 2, pid)
        self.save_manual_state()
        self.refresh_players()
        self.status.set("Vaga substituída. A alteração foi marcada como manual.")

    def copy_team(self) -> None:
        dest = self.selected_team()
        if dest is None or self.data is None:
            return messagebox.showinfo("Equipe", "Selecione a equipe de destino na lista.")
        source = simpledialog.askinteger("Copiar equipe", "ID da equipe de origem:", minvalue=0, maxvalue=max(0, len(self.teams) - 1))
        if source is None or source == dest:
            return
        source_roster = self.find_roster(source)
        dest_roster = self.find_roster(dest)
        if not source_roster or not dest_roster:
            return messagebox.showerror("Elenco", "Registro de elenco não encontrado.")
        self.snapshot()
        self.data[dest_roster["off"]:dest_roster["off"] + ROSTER_STRIDE] = self.data[source_roster["off"]:source_roster["off"] + ROSTER_STRIDE]
        source_tactics = TACTICS_TABLE_OFFSET + source * TACTICS_STRIDE
        dest_tactics = TACTICS_TABLE_OFFSET + dest * TACTICS_STRIDE
        if source_tactics + TACTICS_STRIDE <= len(self.data) and dest_tactics + TACTICS_STRIDE <= len(self.data):
            self.data[dest_tactics:dest_tactics + TACTICS_STRIDE] = self.data[source_tactics:source_tactics + TACTICS_STRIDE]
        self.load_tables()
        self.status.set("Elenco e bloco de táticas copiados em memória.")

    def undo_edit(self) -> None:
        if not self.undo or self.data is None:
            return
        self.redo.append(bytes(self.data))
        self.data = bytearray(self.undo.pop())
        self.dirty = True
        self.load_tables()
        self.status.set("Desfeito.")

    def redo_edit(self) -> None:
        if not self.redo or self.data is None:
            return
        self.undo.append(bytes(self.data))
        self.data = bytearray(self.redo.pop())
        self.dirty = True
        self.load_tables()
        self.status.set("Refeito.")

    def _atomic_save(self, out_path: str) -> None:
        if self.data is None:
            raise ValueError("Nenhum data.bin carregado.")
        target = Path(out_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        backup = target.with_name(target.name + ".bak")
        tmp_path = None
        backup_tmp = None
        try:
            if target.exists():
                fd_bak, backup_tmp = tempfile.mkstemp(prefix=backup.name + ".", suffix=".tmp", dir=str(target.parent))
                os.close(fd_bak)
                shutil.copy2(target, backup_tmp)
            fd, tmp_path = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
            with os.fdopen(fd, "wb") as f:
                f.write(self.data)
                f.flush()
                os.fsync(f.fileno())
            check = Path(tmp_path).read_bytes()
            if len(check) != len(self.data) or hashlib.sha256(check).digest() != hashlib.sha256(self.data).digest():
                raise IOError("A verificação do arquivo temporário não conferiu.")
            if backup_tmp:
                os.replace(backup_tmp, backup)
                backup_tmp = None
            os.replace(tmp_path, target)
            tmp_path = None
            readback = target.read_bytes()
            if readback != bytes(self.data):
                if backup.exists():
                    shutil.copy2(backup, target)
                raise IOError("A verificação após gravação falhou; o backup anterior foi restaurado quando disponível.")
            self.path = str(target)
            self.dirty = False
            self.status.set(f"Salvo e verificado: {target} | backup: {backup if backup.exists() else 'não necessário'}")
            messagebox.showinfo("Arquivo salvo", f"Arquivo gravado e verificado.\n\n{target}\n\nBackup anterior: {backup if backup.exists() else 'não havia arquivo anterior'}\n\nO arquivo salvo é o data.bin extraído. Para EDIT/STFS, reimporte-o com ferramenta externa; este editor não assina nem reempacota o contêiner.")
        finally:
            for temp in (tmp_path, backup_tmp):
                if temp and os.path.exists(temp):
                    try:
                        os.unlink(temp)
                    except OSError:
                        pass

    def save(self) -> None:
        if self.data is None:
            return messagebox.showwarning("Nenhum arquivo", "Abra e valide um data.bin primeiro.")
        initial = os.path.basename(self.path) if self.path else "data_EDITADO.bin"
        initial_dir = os.path.dirname(self.path) if self.path else str(Path.home())
        # Sempre abre o diálogo; o usuário escolhe o destino em cada salvamento.
        path = filedialog.asksaveasfilename(title="Escolha onde salvar o data.bin editado", initialdir=initial_dir, initialfile=initial, defaultextension=".bin", filetypes=[("Arquivo BIN", "*.bin"), ("Todos os arquivos", "*.*")])
        if not path:
            return
        if os.path.exists(path) and not messagebox.askyesno("Confirmar substituição", f"O arquivo já existe:\n{path}\n\nSubstituir? Um backup .bak será criado antes da gravação."):
            return
        try:
            self._atomic_save(path)
        except Exception as exc:
            messagebox.showerror("Erro ao salvar", str(exc))

    def auto_prepare_playersdb(self):
        """Tenta baixar a base sem bloquear a interface; falha oferece importação manual."""
        if self.playersdb_entries:
            self._accept_playersdb(self.playersdb_path or "PlayersDB já carregado", self.playersdb_entries, automatic=False)
            return
        self.status.set("Arquivo aberto. Tentando baixar a base PlayersDB...")
        self.progress.configure(maximum=1, value=0)
        self.progress_text.set("Baixando e lendo CSV/JSONL do PlayersDB")
        def worker():
            try:
                path=download_latest(self.database_dir)
                entries=load_dataset(path)
                self.sync_queue.put({"type":"playersdb_loaded","path":str(path),"entries":entries,"automatic":True})
            except Exception as exc:
                self.sync_queue.put({"type":"playersdb_download_error","error":f"{type(exc).__name__}: {exc}"})
        self.playersdb_thread=threading.Thread(target=worker,name="PlayersDB-Download",daemon=True)
        self.playersdb_thread.start()
        self.root.after(200,self._poll_playersdb_queue)

    def load_playersdb(self):
        path=filedialog.askopenfilename(title="Carregar base PlayersDB",filetypes=[("PlayersDB CSV/JSONL","*.csv *.jsonl"),("CSV","*.csv"),("JSONL","*.jsonl")])
        if not path: return
        try:
            entries=load_dataset(path)
            self._accept_playersdb(path,entries,automatic=False)
        except Exception as exc: messagebox.showerror("Arquivo PlayersDB inválido",str(exc))

    def _poll_playersdb_queue(self):
        try:
            while True:
                event=self.sync_queue.get_nowait()
                if event.get("type")=="playersdb_loaded":
                    self._accept_playersdb(event["path"],event["entries"],event.get("automatic",False))
                elif event.get("type")=="playersdb_download_error":
                    self.progress_text.set("Download automático indisponível")
                    self.status.set("Não foi possível baixar a base automaticamente.")
                    manual=messagebox.askyesno("PlayersDB indisponível",f"Não consegui baixar o arquivo automaticamente.\n\nErro: {event['error']}\n\nAbra o site PlayersDB para baixar CSV ou JSONL e depois carregue o arquivo manualmente?\n\nhttps://playersdb.app/")
                    if manual:
                        webbrowser.open("https://playersdb.app/")
                        self.load_playersdb()
        except queue.Empty: pass
        if self.playersdb_thread and self.playersdb_thread.is_alive(): self.root.after(200,self._poll_playersdb_queue)

    def _accept_playersdb(self,path,entries,automatic=False):
        self.playersdb_path=path; self.playersdb_entries=entries
        self.db_status.set(f"PlayersDB carregado: {len(entries):,} jogadores | {Path(path).name}")
        self.progress.configure(value=1); self.progress_text.set(f"Base carregada: {len(entries):,} jogadores")
        if self.data is not None:
            report=self.apply_playersdb_names_and_squads()
            msg=(f"Base PlayersDB carregada: {len(entries):,} registros.\n\n"
                 f"Nomes de jogadores corrigidos: {report['player_names']}\n"
                 f"Clubes renomeados por correspondência: {report['team_names']}\n"
                 f"Elencos reconstruídos: {report['rosters']}\nJogadores novos cadastrados: {report.get('new_records',0)}\n"
                 f"Equipes sem correspondência segura: {report['unmatched']}\n\n"
                 "A base contém jogadores de várias versões. Foram aplicadas apenas correspondências exatas/fortes. Salve como um novo data.bin após revisar.")
            messagebox.showinfo("PlayersDB processado",msg)

    def apply_playersdb_names_and_squads(self):
        """Usa IDs PES e vínculos de equipe do arquivo local; não faz fuzzy matching global."""
        from collections import Counter, defaultdict
        entries=self.playersdb_entries
        by_name=defaultdict(list); by_pes_id=defaultdict(list); entries_by_team=defaultdict(list)
        for e in entries:
            by_name[db_norm(e["name"])].append(e)
            if e.get("pes_id") is not None: by_pes_id[e["pes_id"]].append(e)
            for team_name in e["teams"]: entries_by_team[db_norm(team_name)].append(e)
        # IDs Konami/PES são a melhor chave; nome exato é o fallback quando não há ID.
        def entry_for_pid(pid):
            candidates=by_pes_id.get(pid,[])
            if len(candidates)==1: return candidates[0]
            if len(candidates)>1: return None
            if pid<len(self.players):
                matches=by_name.get(db_norm(self.players[pid]["name"]),[])
                return matches[0] if len(matches)==1 else None
            return None
        inferred={}; unmatched=0
        for team in self.teams:
            roster=self.find_roster(team["id"])
            if not roster: unmatched+=1; continue
            votes=Counter()
            for pid in roster["ids"]:
                if pid:
                    e=entry_for_pid(pid)
                    if e:
                        for official in e["teams"]: votes[official]+=1
            ranked=votes.most_common()
            if ranked and ranked[0][1]>=3 and ranked[0][1]/max(1,sum(votes.values()))>=0.40 and (len(ranked)==1 or ranked[0][1]-ranked[1][1]>=2):
                inferred[team["id"]]=ranked[0][0]
        if not messagebox.askyesno("Aplicar base PlayersDB",f"Foram identificados {len(inferred)} nomes de equipes por votação dos jogadores já presentes nos elencos.\n\nAplicar correções de nomes e atualizar os elencos com os jogadores associados a cada equipe no PlayersDB?\n\nApenas IDs PES válidos e correspondências seguras serão usados. Nomes de competições serão preservados: o offset da tabela de competições ainda não foi identificado com segurança no data.bin."):
            return {"player_names":0,"team_names":0,"rosters":0,"unmatched":unmatched}
        self.snapshot(); b=self.data
        name_changes=0; team_changes=0; roster_changes=0; new_records=0; created_ids=[]
        # Corrige nomes somente para jogadores ativos em uma equipe reconhecida
        # e quando o registro PlayersDB aponta para a mesma equipe oficial.
        player_count=u16(b,PLAYER_COUNT_OFFSET)
        active_team_by_pid=defaultdict(set)
        for tid,official in inferred.items():
            r=self.find_roster(tid)
            if r:
                for pid in r["ids"]:
                    if pid: active_team_by_pid[pid].add(db_norm(official))
        for pid,team_names in active_team_by_pid.items():
            if pid<=0 or pid>=min(player_count,PLAYER_CAPACITY): continue
            candidates=by_pes_id.get(pid,[])
            if len(candidates)!=1 or not candidates[0]["name"]: continue
            if not (set(db_norm(x) for x in candidates[0]["teams"]) & team_names): continue
            off=PLAYER_TABLE_OFFSET+pid*PLAYER_STRIDE
            old=decode(b[off+PLAYER_NAME_REL:off+PLAYER_NAME_REL+PLAYER_NAME_SIZE])
            new_name=candidates[0]["name"]
            if new_name!=old:
                b[off+PLAYER_NAME_REL:off+PLAYER_NAME_REL+PLAYER_NAME_SIZE]=encode(new_name,PLAYER_NAME_SIZE); name_changes+=1
        # Renomeia as equipes por consenso de pelo menos 3 jogadores e margem mínima.
        for team in self.teams:
            official=inferred.get(team["id"])
            if official and official!=team["name"]:
                off=team["off"]; b[off+TEAM_NAME_REL:off+TEAM_NAME_REL+TEAM_NAME_SIZE]=encode(official,TEAM_NAME_SIZE); team_changes+=1
                team["name"]=official
        # Monta os elencos com IDs do próprio PlayersDB; nunca excede 32 vagas.
        for team_id,official in inferred.items():
            roster=self.find_roster(team_id)
            if not roster: continue
            wanted=[]
            for e in entries_by_team.get(db_norm(official),[]):
                pid=e.get("pes_id")
                if pid is None:
                    # fallback apenas por nome exato único na base atual
                    matches=by_name.get(db_norm(e["name"]),[])
                    if len(matches)!=1: continue
                    local=[p["id"] for p in self.players if db_norm(p["name"])==db_norm(e["name"])]
                    pid=local[0] if len(local)==1 else None
                if pid is None or pid<=0 or pid>=PLAYER_CAPACITY or pid in wanted: continue
                off=PLAYER_TABLE_OFFSET+pid*PLAYER_STRIDE
                if off+PLAYER_STRIDE>len(b): continue
                existing=decode(b[off+PLAYER_NAME_REL:off+PLAYER_NAME_REL+PLAYER_NAME_SIZE])
                # Registro ocupado só entra se o nome já coincide; evita associar IDs incompatíveis.
                if existing and db_norm(existing)!=db_norm(e["name"]): continue
                if not existing:
                    if not e["name"]: continue
                    b[off:off+PLAYER_STRIDE]=b"\0"*PLAYER_STRIDE
                    b[off+PLAYER_NAME_REL:off+PLAYER_NAME_REL+PLAYER_NAME_SIZE]=encode(e["name"],PLAYER_NAME_SIZE)
                    if e.get("height") is not None: b[off+0x0C]=max(0,min(255,e["height"]))
                    if e.get("weight") is not None: b[off+0x0D]=max(0,min(255,e["weight"]))
                    if e.get("age") is not None: b[off+8]=max(0,min(255,e["age"]))
                    new_records+=1; created_ids.append(pid)
                wanted.append(pid)
            if len(wanted)>=8:
                wanted=wanted[:32]
                ids=wanted+[0]*(32-len(wanted))
                if ids!=roster["ids"]:
                    roster["ids"]=ids; roster["numbers"]=[0]*32
                    off=roster["off"]
                    for i,pid in enumerate(ids): p16(b,off+ROSTER_PLAYER_REL+i*2,pid)
                    b[off+ROSTER_NUMBERS_REL:off+ROSTER_NUMBERS_REL+32]=bytes(32)
                    roster_changes+=1
        # Atualiza contador somente quando um novo ID foi efetivamente criado.
        if created_ids:
            p16(b,PLAYER_COUNT_OFFSET,max(player_count,max(created_ids)+1))
        self.load_tables(); self.dirty=True
        return {"player_names":name_changes,"team_names":team_changes,"rosters":roster_changes,"new_records":new_records,"unmatched":unmatched}

    def update_squads(self) -> None:
        if not self.playersdb_entries:
            return messagebox.showinfo("PlayersDB não carregado","Baixe ou carregue primeiro o arquivo CSV/JSONL do PlayersDB.")
        report=self.apply_playersdb_names_and_squads()
        messagebox.showinfo("Atualização local concluída",str(report)+"\n\nRevise os resultados e salve como novo data.bin.")

    def _selected_player_and_club(self):
        pid=self.selected_id(); selection=self.club_tree.selection() if hasattr(self,"club_tree") else ()
        if pid is None: messagebox.showinfo("Jogador","Selecione um jogador na aba Jogadores."); return None,None
        if not selection: messagebox.showinfo("Equipe","Selecione uma equipe na aba Clubes / Seleções."); return None,None
        return pid,int(selection[0])

    def _place_player(self,pid,dest,remove_previous):
        if self.data is None: return False
        roster=self.find_roster(dest)
        if not roster: messagebox.showerror("Elenco","Registro de elenco não encontrado."); return False
        if pid in roster["ids"]: messagebox.showinfo("Elenco","O jogador já está nessa equipe."); return False
        try: slot=roster["ids"].index(0)
        except ValueError: messagebox.showwarning("Elenco cheio","A equipe já tem 32 jogadores; não há vaga."); return False
        shirt=simpledialog.askinteger("Número da camisa","Número desejado (0 a 99):",minvalue=0,maxvalue=99)
        if shirt is None: return False
        self.snapshot()
        if remove_previous:
            for r in self.rosters:
                if r["team"]<=54:  # mantém convocações nacionais ao transferir entre clubes
                    continue
                for j,value in enumerate(r["ids"]):
                    if value==pid:
                        r["ids"][j]=0; r["numbers"][j]=0
                        p16(self.data,r["off"]+ROSTER_PLAYER_REL+j*2,0); self.data[r["off"]+ROSTER_NUMBERS_REL+j]=0
        roster["ids"][slot]=pid; roster["numbers"][slot]=shirt
        p16(self.data,roster["off"]+ROSTER_PLAYER_REL+slot*2,pid); self.data[roster["off"]+ROSTER_NUMBERS_REL+slot]=shirt
        self.manual_ids.add(pid); self.save_manual_state(); self.load_tables()
        self.status.set("Alteração de elenco aplicada em memória. Salve para gravar.")
        return True

    def transfer_to_selected_club(self):
        pid,dest=self._selected_player_and_club()
        if pid is None: return
        if dest<=54: return messagebox.showwarning("Transferência","Selecione um clube, não uma seleção. Para seleção use Convocar para seleção.")
        self._place_player(pid,dest,True)

    def call_up_to_selected_team(self):
        pid,dest=self._selected_player_and_club()
        if pid is None: return
        if dest>54: return messagebox.showwarning("Seleção","O ID selecionado não está na faixa de seleções nacionais identificada (0–54). Confira a equipe antes de convocar.")
        self._place_player(pid,dest,False)

    def add_selected_player_to_club(self):
        pid,dest=self._selected_player_and_club()
        if pid is None: return
        if dest<=54: return messagebox.showwarning("Adicionar jogador","Selecione um clube. Para convocar, use Convocar para seleção.")
        current=[r["team"] for r in self.rosters if r["team"]>54 and pid in r["ids"] and r["team"]!=dest]
        if current:
            return messagebox.showwarning("Jogador vinculado a outro clube",f"Este jogador já está em outro clube (ID {current[0]}). Use Transferir jogador selecionado.")
        self._place_player(pid,dest,False)

    def _walk_widgets(self, parent):
        for child in parent.winfo_children():
            yield child
            yield from self._walk_widgets(child)

    def open_logs_folder(self) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(self.logs_dir))
            elif sys.platform == "darwin":
                os.system(f'open "{self.logs_dir}"')
            else:
                os.system(f'xdg-open "{self.logs_dir}"')
        except Exception as exc:
            messagebox.showinfo("Pasta de logs", f"Logs em:\n{self.logs_dir}\n\n{exc}")

    def export_csv(self) -> None:
        if self.data is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["ID", "Jogador", "Equipe"])
            for player in self.players:
                writer.writerow([player["id"], player["name"], self.team_for(player["id"])])
        self.status.set(f"CSV exportado: {path}")

    def on_close(self) -> None:
        if self.playersdb_thread and self.playersdb_thread.is_alive():
            if not messagebox.askyesno("Download em andamento", "O download/leitura da base ainda está em andamento. Fechar mesmo assim?"):
                return
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    Editor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
