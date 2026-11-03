#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PES 2018 Xbox 360 Editor v1.0 — base offline, elencos e nomes históricos."""
from __future__ import annotations
import csv, json, os, sys, struct, hashlib, threading, webbrowser, unicodedata, re, queue
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from editor_core import EditorCore as BaseEditor, u16, p16, decode, encode
from playersdb_local import load_dataset, download_latest, norm as db_norm
from official_names import TEAM_NAMES, COMPETITION_NAMES, NATIONAL_TEAM_IDS, CLASSIC_TEAM_IDS, team_category, norm as name_norm
from pes2018_stfs import STFSReader, STFSFormatError
from binary_layout import detect_layout
from historical_names import CLASSIC_FAKE_NAMES
from transfer_data import load_transfermarkt_files, download_transfermarkt, analyze_roster_updates, apply_roster_plan, SNAPSHOT_DATE

U32_MAX=0xFFFFFFFF
COMPETITION_TABLE_OFFSET=0x41C78C
COMPETITION_STRIDE=0x7C
COMPETITION_COUNT=50
COMPETITION_NAME_REL=0x0E
COMPETITION_NAME_SIZE=COMPETITION_STRIDE-COMPETITION_NAME_REL


def u32(buf, off): return struct.unpack_from('>I',buf,off)[0]
def p32(buf, off, value): struct.pack_into('>I',buf,off,int(value)&U32_MAX)

class EditorV10(BaseEditor):
    def __init__(self, root):
        self.source_container=None
        self.competitions=[]
        self.player_index_by_ref={}
        self.roster_integrity={"nonzero":0,"valid":0,"invalid":0,"ratio":1.0,"safe":True}
        self.current_team_id=None
        self.current_comp_row=None
        self.player_selection_source="global"
        self.tm_data=None
        self.tm_path=None
        self.transfer_report=None
        self.transfer_plan=[]
        self.tm_queue=queue.Queue()
        self.tm_thread=None
        self.layout_info=None
        self.sync_queue=queue.Queue()
        super().__init__(root)
        # EditorCore initializa a fila antiga como None; v1.0 mantém sua própria fila.
        self.sync_queue=queue.Queue()

    # ---------- Visual ----------
    def build(self):
        self.root.title("PES 2018 XBOX 360 EDITOR  |  v1.0")
        self.root.geometry("1240x820")
        self.root.minsize(1000,680)
        self.root.configure(bg="#0d141c")
        style=ttk.Style(self.root)
        try: style.theme_use("clam")
        except tk.TclError: pass
        style.configure(".",background="#101b26",foreground="#e8eef4",font=("Segoe UI",9))
        style.configure("TFrame",background="#101b26")
        style.configure("TLabel",background="#101b26",foreground="#dfe7ee")
        style.configure("Title.TLabel",font=("Segoe UI",16,"bold"),foreground="#ffffff")
        style.configure("Sub.TLabel",font=("Segoe UI",9),foreground="#9fb0bf")
        style.configure("TButton",background="#26394a",foreground="#f2f6f9",padding=(10,6),borderwidth=0)
        style.map("TButton",background=[("active","#36536b"),("pressed","#1e3445")],foreground=[("disabled","#72808d")])
        style.configure("Accent.TButton",background="#83b943",foreground="#0c151b",font=("Segoe UI",9,"bold"))
        style.map("Accent.TButton",background=[("active","#9bd45a")])
        style.configure("TEntry",fieldbackground="#172533",foreground="#f4f7fa",insertcolor="#ffffff",padding=6)
        style.configure("TCombobox",fieldbackground="#172533",background="#26394a",foreground="#f4f7fa",padding=5)
        style.map("TCombobox",fieldbackground=[("readonly","#172533")],foreground=[("readonly","#f4f7fa")])
        style.configure("TNotebook",background="#101b26",borderwidth=0)
        style.configure("TNotebook.Tab",background="#1b2a38",foreground="#aebdca",padding=(18,10),font=("Segoe UI",10,"bold"))
        style.map("TNotebook.Tab",background=[("selected","#30475b")],foreground=[("selected","#ffffff")])
        style.configure("Treeview",background="#142230",fieldbackground="#142230",foreground="#e8eef4",rowheight=27,borderwidth=0)
        style.configure("Treeview.Heading",background="#26394a",foreground="#ffffff",font=("Segoe UI",9,"bold"),padding=7)
        style.map("Treeview",background=[("selected","#47734b")],foreground=[("selected","#ffffff")])
        style.configure("Horizontal.TProgressbar",background="#83b943",troughcolor="#1a2835",bordercolor="#1a2835")

        top=ttk.Frame(self.root,padding=(12,10,12,6)); top.pack(fill="x")
        ttk.Label(top,text="PES 2018",style="Title.TLabel").pack(side="left")
        ttk.Label(top,text="  XBOX 360 EDITOR  /  OPTION FILE",style="Sub.TLabel").pack(side="left",pady=(7,0))
        toolbar=ttk.Frame(self.root,padding=(10,2,10,7)); toolbar.pack(fill="x")
        self.main_buttons=[]
        buttons=[
            ("Abrir BIN / EDIT",self.open_file,"Abre data.bin ou extrai data.bin de um pacote EDIT STFS, validando hashes."),
            ("Salvar como…",self.save,"Salva uma nova cópia do data.bin, cria backup .bak e verifica o conteúdo gravado."),
            ("Baixar PlayersDB",self.force_download_playersdb,"Baixa a versão mais recente do PlayersDB em segundo plano; se falhar, mostra o site e permite carregar manualmente."),
            ("Carregar CSV / JSONL",self.load_playersdb,"Abre um arquivo PlayersDB CSV ou JSONL já baixado no computador."),
            ("Corrigir nomes",self.apply_official_names,"Corrige nomes fictícios conhecidos de clubes e competições, somente quando ID e nome de origem conferem."),
            ("Desfazer",self.undo_edit,"Desfaz a última alteração feita nesta sessão."),
            ("Refazer",self.redo_edit,"Refaz a última alteração desfeita."),
            ("Exportar jogadores",self.export_csv,"Exporta jogadores e seus IDs Konami para CSV."),
            ("Logs",self.open_logs_folder,"Abre os relatórios e o histórico de operações gerados automaticamente."),
        ]
        for i,(label,cmd,hint) in enumerate(buttons):
            btn=ttk.Button(toolbar,text=label,command=cmd,style="Accent.TButton" if i in (0,3) else "TButton")
            btn.pack(side="left",padx=(0,5)); self.main_buttons.append(btn); self._hint(btn,hint)

        status_row=ttk.Frame(self.root,padding=(12,0,12,6)); status_row.pack(fill="x")
        self.status=tk.StringVar(value="Abra seu data.bin ou EDIT00000000 para começar.")
        ttk.Label(status_row,textvariable=self.status).pack(side="left",fill="x",expand=True)
        self.db_status=tk.StringVar(value="PlayersDB: não carregado")
        ttk.Label(status_row,textvariable=self.db_status,style="Sub.TLabel").pack(side="right",padx=(8,8))
        self.progress=ttk.Progressbar(status_row,mode="determinate",maximum=1,value=0,length=150)
        self.progress.pack(side="right",padx=(8,0))
        self.progress_text=tk.StringVar(value="Pronto")
        ttk.Label(status_row,textvariable=self.progress_text,width=20,anchor="e",style="Sub.TLabel").pack(side="right")

        # Ilha de ajuda é criada antes do notebook e fica fixa no rodapé.
        help_frame=ttk.Frame(self.root,padding=(12,7),relief="ridge")
        self.help_frame=help_frame
        help_frame.pack(side="bottom",fill="x",padx=10,pady=(0,8))
        self.help_var=tk.StringVar(value="AJUDA  •  Passe o mouse ou clique em qualquer controle para ver uma explicação nesta faixa.")
        ttk.Label(help_frame,textvariable=self.help_var,anchor="w",font=("Segoe UI",9,"bold"),foreground="#d7edb6").pack(fill="x")

        self.notebook=ttk.Notebook(self.root); self.notebook.pack(fill="both",expand=True,padx=10,pady=(0,8))
        self.players_tab=ttk.Frame(self.notebook,padding=9)
        self.clubs_tab=ttk.Frame(self.notebook,padding=9)
        self.comps_tab=ttk.Frame(self.notebook,padding=9)
        self.notebook.add(self.players_tab,text="JOGADORES")
        self.notebook.add(self.clubs_tab,text="CLUBES  /  SELEÇÕES")
        self.notebook.add(self.comps_tab,text="COMPETIÇÕES")
        self.transfers_tab=ttk.Frame(self.notebook,padding=9)
        self.notebook.add(self.transfers_tab,text="ATUALIZAR ELENCOS")
        self.notebook.bind("<<NotebookTabChanged>>",lambda e:self._hint_text("Aba principal: selecione Jogadores, Clubes/Seleções ou Competições."))
        self._build_players_tab(); self._build_clubs_tab(); self._build_competitions_tab(); self._build_transfers_tab()
        self._install_fallback_hints(self.root)

    def _hint(self, widget, text):
        widget._pes_help=True
        widget.bind("<Enter>",lambda e,msg=text:self._hint_text(msg),add="+")
        widget.bind("<Button-1>",lambda e,msg=text:self._hint_text(msg),add="+")
        widget.bind("<FocusIn>",lambda e,msg=text:self._hint_text(msg),add="+")
    def _install_fallback_hints(self,parent):
        for widget in parent.winfo_children():
            if not getattr(widget,"_pes_help",False):
                if isinstance(widget,ttk.Treeview): msg="Tabela: clique em uma linha para selecionar o registro; os detalhes aparecem no painel ao lado."
                elif isinstance(widget,ttk.Entry): msg="Campo de texto: digite o termo ou o novo nome e use o botão de aplicar/salvar."
                elif isinstance(widget,ttk.Combobox): msg="Filtro: escolha uma categoria para limitar as equipes mostradas."
                elif isinstance(widget,ttk.Notebook): msg="Navegação: selecione uma das abas do editor."
                elif isinstance(widget,ttk.Button): msg="Botão: executa a ação indicada no texto."
                else: msg="Área do editor: passe o mouse sobre os controles para ver a função."
                if isinstance(widget,(ttk.Treeview,ttk.Entry,ttk.Combobox,ttk.Notebook,ttk.Button)):
                    self._hint(widget,msg)
            self._install_fallback_hints(widget)
    def _hint_text(self,msg):
        if hasattr(self,"help_var"): self.help_var.set("AJUDA  •  "+msg)

    def _build_transfers_tab(self):
        top=ttk.Frame(self.transfers_tab); top.pack(fill="x",pady=(0,8))
        ttk.Label(top,text="ATUALIZAÇÃO OFFLINE DE ELENCOS",font=("Segoe UI",12,"bold")).pack(anchor="w")
        ttk.Label(top,text="PlayersDB = identidade/ID Konami  •  Transfermarkt = clube atual e vínculo de seleção (não é lista de convocados por partida)",style="Sub.TLabel").pack(anchor="w",pady=(2,7))
        actions=ttk.Frame(self.transfers_tab); actions.pack(fill="x",pady=(0,8))
        btns=[
            ("BAIXAR BASE ESTÁTICA",self.download_tm_data,"Baixa CSV.GZ estáticos. Não consulta API. Snapshot disponível até 06/07/2026."),
            ("CARREGAR CSV / ZIP",self.load_tm_files,"Carrega players.csv.gz e clubs.csv.gz; national_teams.csv.gz e transfers.csv.gz são opcionais. Também aceita ZIP."),
            ("ANALISAR ELENCOS",self.analyze_transfer_updates,"Compara Konami IDs, nascimento, nacionalidade, clube atual e vagas. Apenas prévia; não altera o data.bin."),
            ("APLICAR PLANO",self.apply_transfer_updates,"Aplica transferências seguras e sugestões de vínculo com seleções; revise a prévia, pois o campo da base não garante convocação oficial para uma data."),
        ]
        for i,(label,cmd,hint) in enumerate(btns):
            b=ttk.Button(actions,text=label,command=cmd,style="Accent.TButton" if i in (2,3) else "TButton")
            b.pack(side="left",padx=(0,6)); self._hint(b,hint)
        self.include_callups=tk.BooleanVar(value=False)
        check=ttk.Checkbutton(self.transfers_tab,text="Incluir sugestões de vínculo com seleções (revisar; não são convocados oficiais)",variable=self.include_callups)
        check.pack(anchor="w",pady=(0,5)); self._hint(check,"Por segurança, as sugestões de seleção não são aplicadas por padrão. Marque apenas depois de revisar a lista; a fonte não fornece convocados oficiais de uma data específica.")
        self.tm_status=tk.StringVar(value="Base Transfermarkt: não carregada")
        ttk.Label(self.transfers_tab,textvariable=self.tm_status,style="Sub.TLabel").pack(anchor="w",pady=(0,5))
        self.transfer_summary=tk.StringVar(value="Abra um arquivo, carregue PlayersDB e a base estática de clubes. Depois clique em Analisar elencos.")
        ttk.Label(self.transfers_tab,textvariable=self.transfer_summary,wraplength=1120,justify="left").pack(fill="x",pady=(0,6))
        columns=("op","id","player","source","destination","confidence")
        self.transfer_tree=ttk.Treeview(self.transfers_tab,columns=columns,show="headings",height=16)
        specs=[("op","OPERAÇÃO",110),("id","ID KONAMI",100),("player","JOGADOR",220),("source","CLUBE / ORIGEM",220),("destination","DESTINO",240),("confidence","CONFIANÇA",100)]
        for col,title,width in specs:
            self.transfer_tree.heading(col,text=title,command=lambda c=col:self.sort_tree(self.transfer_tree,c)); self.transfer_tree.column(col,width=width,anchor="w")
        self.transfer_tree.pack(fill="both",expand=True)
        self.transfer_tree.tag_configure("transfer",foreground="#e8f2ff")
        self.transfer_tree.tag_configure("callup",foreground="#bce5ff")
        self._hint(self.transfer_tree,"Prévia das mudanças propostas. Linhas não exibidas continuam no relatório TXT/JSON completo.")
        ttk.Label(self.transfers_tab,text=("Segurança: IDs desconhecidos no elenco são preservados e contam como vagas ocupadas. "
            "Transferências não removem seleções. Sugestões nacionais vêm do vínculo no perfil, não de uma convocação oficial por data. "
            "A base pública estática disponível termina em 06/07/2026; não inclui elencos 2026/27."),
            style="Sub.TLabel",wraplength=1120,justify="left").pack(anchor="w",pady=(7,0))

    def _team_aliases_for_analysis(self):
        aliases={}
        for tid, pair in TEAM_NAMES.items():
            aliases[str(tid)]=[pair[0],pair[1]]
        for filename in ("team_aliases.csv","national_team_aliases.csv"):
            file=self._app_dir()/filename
            if not file.exists(): continue
            try:
                with file.open("r",encoding="utf-8-sig",newline="") as f:
                    for row in csv.DictReader(f,delimiter=";"):
                        tid=str(row.get("team_id","")).strip(); alias=str(row.get("alias","")).strip()
                        official=str(row.get("official_name","")).strip()
                        if tid.isdigit() and alias:
                            aliases.setdefault(tid,[]).append(alias)
                            if official: aliases.setdefault(tid,[]).append(official)
            except Exception as exc:
                self._write_log("erro_alias_equipes",{"file":filename,"error":str(exc)})
        return aliases

    def _player_aliases_for_analysis(self):
        aliases={}
        file=self._app_dir()/"player_name_aliases.csv"
        if not file.exists(): return aliases
        try:
            with file.open("r",encoding="utf-8-sig",newline="") as f:
                for row in csv.DictReader(f,delimiter=";"):
                    raw_id=str(row.get("konami_id","")).strip()
                    alias=str(row.get("alias","")).strip()
                    if raw_id.isdigit() and alias:
                        aliases.setdefault(int(raw_id),[]).append(alias)
        except Exception as exc:
            self._write_log("erro_alias_jogadores",{"error":str(exc)})
        return aliases

    def load_tm_files(self):
        paths=filedialog.askopenfilenames(title="Selecione players.csv.gz e clubs.csv.gz (ou ZIP)",filetypes=[("Transfermarkt CSV / ZIP","*.csv *.csv.gz *.zip"),("Todos os arquivos","*.*")])
        if not paths: return
        if self.tm_thread and self.tm_thread.is_alive(): return messagebox.showinfo("Carregamento","Já existe uma leitura de base em andamento.")
        self.tm_status.set("Lendo arquivos Transfermarkt…")
        def worker():
            try:
                data=load_transfermarkt_files(paths)
                self.tm_queue.put({"type":"loaded","data":data,"paths":list(paths)})
            except Exception as exc:
                self.tm_queue.put({"type":"error","error":f"{type(exc).__name__}: {exc}"})
        self.tm_thread=threading.Thread(target=worker,name="Transfermarkt-Load",daemon=True); self.tm_thread.start()
        self.root.after(200,self._poll_tm_queue)

    def download_tm_data(self):
        if self.tm_thread and self.tm_thread.is_alive(): return messagebox.showinfo("Download","Já existe um download/carregamento em andamento.")
        self.tm_status.set("Baixando arquivos CSV.GZ estáticos…")
        self.progress.configure(maximum=1,value=0); self.progress_text.set("Base de clubes")
        def worker():
            try:
                paths=download_transfermarkt(self.database_dir,progress=lambda key,got,total:self.tm_queue.put({"type":"progress","key":key,"got":got,"total":total}))
                data=load_transfermarkt_files(paths)
                self.tm_queue.put({"type":"loaded","data":data,"paths":[str(x) for x in paths],"downloaded":True})
            except Exception as exc:
                self.tm_queue.put({"type":"download_error","error":f"{type(exc).__name__}: {exc}"})
        self.tm_thread=threading.Thread(target=worker,name="Transfermarkt-Download",daemon=True); self.tm_thread.start()
        self.root.after(200,self._poll_tm_queue)

    def _poll_tm_queue(self):
        try:
            while True:
                ev=self.tm_queue.get_nowait(); typ=ev.get("type")
                if typ=="progress":
                    total=ev.get("total") or 0; got=ev.get("got") or 0
                    self.progress.configure(value=(got/total if total else 0)); self.progress_text.set(f"{ev.get('key','')}: {got//1024} KB")
                elif typ=="loaded":
                    self.tm_data=ev["data"]; self.tm_path=";".join(ev.get("paths",[]))
                    self.tm_status.set(f"Transfermarkt: {len(self.tm_data['players']):,} jogadores | {len(self.tm_data['clubs']):,} clubes | snapshot {self.tm_data['snapshot_date']}")
                    self.progress.configure(value=1); self.progress_text.set("Base carregada")
                    self._write_log("base_transfermarkt_carregada",{"players":len(self.tm_data['players']),"clubs":len(self.tm_data['clubs']),"national_teams":len(self.tm_data['national_teams']),"transfers":len(self.tm_data['transfers']),"snapshot_date":self.tm_data['snapshot_date'],"paths":ev.get("paths",[])})
                    self.status.set("Base estática carregada. Agora analise os elencos; nenhuma alteração foi aplicada ainda.")
                    messagebox.showinfo("Base carregada",f"Jogadores Transfermarkt: {len(self.tm_data['players']):,}\nClubes: {len(self.tm_data['clubs']):,}\nSeleções: {len(self.tm_data['national_teams']):,}\nHistórico de transferências: {len(self.tm_data['transfers']):,}\nSnapshot: {self.tm_data['snapshot_date']}\n\nA base estática está carregada. Clique em Analisar elencos.")
                elif typ=="error":
                    self.tm_status.set("Falha ao ler os CSVs Transfermarkt")
                    self._write_log("erro_base_transfermarkt",{"error":ev["error"]})
                    messagebox.showerror("Base inválida",ev["error"])
                elif typ=="download_error":
                    self.tm_status.set("Download indisponível; use carregamento manual")
                    self._write_log("download_transfermarkt_falhou",{"error":ev["error"]})
                    messagebox.showwarning("Download indisponível",f"Não foi possível baixar os CSV.GZ automaticamente.\n\n{ev['error']}\n\nBaixe players.csv.gz, clubs.csv.gz e, se disponível, national_teams.csv.gz e transfers.csv.gz no repositório público:\nhttps://github.com/dcaribou/transfermarkt-datasets\n\nDepois use CARREGAR CSV / ZIP.")
                    webbrowser.open("https://github.com/dcaribou/transfermarkt-datasets")
        except queue.Empty:
            pass
        if self.tm_thread and self.tm_thread.is_alive(): self.root.after(200,self._poll_tm_queue)

    def analyze_transfer_updates(self):
        if self.data is None: return messagebox.showwarning("Arquivo", "Abra primeiro um data.bin ou pacote EDIT compatível.")
        if not self._require_roster_integrity(): return
        if not self.playersdb_entries: return messagebox.showwarning("PlayersDB", "Carregue o CSV/JSONL PlayersDB antes de analisar transferências.")
        if not self.tm_data: return messagebox.showwarning("Base de clubes", "Carregue a base estática Transfermarkt antes de analisar transferências.")
        try:
            report=analyze_roster_updates(self.players,self.rosters,self.teams,self.playersdb_entries,self.tm_data,self._team_aliases_for_analysis(),self._player_aliases_for_analysis())
            self.transfer_report=report; self.transfer_plan=report["plans"]
            stats=report["stats"]
            self.transfer_tree.delete(*self.transfer_tree.get_children())
            for i,item in enumerate(self.transfer_plan[:2500]):
                op={"transfer":"TRANSFERIR","add_to_club":"ADICIONAR","callup":"SUGESTÃO SELEÇÃO"}.get(item["operation"],item["operation"])
                tag="callup" if item["operation"]=="callup" else "transfer"
                self.transfer_tree.insert("","end",iid=str(i),values=(op,item["konami_id"],item["player"],item["from_team"],item["to_team"],item["confidence"]),tags=(tag,))
            summary=(f"Prévia {report['snapshot_date']} | IDs PlayersDB↔Transfermarkt: {stats['playersdb_tm_matched']:,} | "
                f"Clubes Transfermarkt mapeados: {stats['club_names_mapped']:,} | Transferências/adições: {stats['planned_transfers']:,} | "
                f"Sugestões de seleção (revisar): {stats['planned_callups']:,} | Já corretos: {stats['already_correct']:,} | "
                f"Sem clube PES correspondente: {stats['no_pes_club']:,} | Ambíguos: {stats['ambiguous_roster']:,} | "
                f"Vagas insuficientes: {stats['full']:,} | Sem correspondência jogador: {stats['no_transfermarkt_match']:,}")
            self.transfer_summary.set(summary)
            self._write_transfer_csv(self.transfer_plan)
            self._write_log("analise_elencos_concluida",{"snapshot_date":report["snapshot_date"],"stats":stats,"preview_count":len(self.transfer_plan),"sample":self.transfer_plan[:100]})
            self.status.set(f"Análise concluída: {len(self.transfer_plan):,} operações propostas. Nada foi gravado.")
            if self.transfer_plan:
                messagebox.showinfo("Análise concluída",f"Operações propostas: {len(self.transfer_plan):,}\nTransferências/adições: {stats['planned_transfers']:,}\nSugestões de seleção: {stats['planned_callups']:,}\nCorrespondências jogador↔Transfermarkt: {stats['playersdb_tm_matched']:,}\n\nRevise as sugestões de seleção: a fonte indica vínculo no perfil, não convocação oficial para uma data específica. Use Aplicar plano para alterar a memória e Salvar como para criar outro data.bin.")
            else:
                messagebox.showwarning("Nenhuma transferência segura",self.transfer_summary.get()+"\n\nNenhuma alteração foi aplicada.")
        except Exception as exc:
            self._write_log("erro_analise_elencos",{"error":f"{type(exc).__name__}: {exc}"})
            messagebox.showerror("Erro na análise",str(exc))

    def _write_transfer_csv(self, plan):
        try:
            path=self.logs_dir/"previa_transferencias.csv"
            fields=["operation","konami_id","player","from_team_id","from_team","to_team_id","to_team","tm_player_id","confidence","reason"]
            with path.open("w",encoding="utf-8-sig",newline="") as f:
                w=csv.DictWriter(f,fieldnames=fields,delimiter=";"); w.writeheader()
                for row in plan: w.writerow({k:row.get(k,"") for k in fields})
            self.status.set(f"Prévia exportada: {path}")
        except Exception as exc:
            self._write_log("erro_exportar_previa_transferencias",{"error":str(exc)})

    def apply_transfer_updates(self):
        if self.data is None or not self.transfer_plan: return messagebox.showwarning("Plano", "Não há operações aprovadas. Faça uma análise primeiro.")
        if not self._require_roster_integrity(): return
        active_plan=[p for p in self.transfer_plan if p["operation"]!="callup" or self.include_callups.get()]
        if not active_plan:
            return messagebox.showinfo("Plano", "Nenhuma transferência/adição está disponível para aplicar. Para incluir sugestões de seleção, marque a opção correspondente depois de revisar a prévia.")
        transfers=sum(1 for p in active_plan if p["operation"] in ("transfer","add_to_club"))
        callups=sum(1 for p in active_plan if p["operation"]=="callup")
        if not messagebox.askyesno("Confirmar atualização",f"Aplicar {transfers:,} transferências/adições e {callups:,} sugestões de vínculo com seleções?\n\nAs sugestões não representam convocação oficial de uma data específica. IDs desconhecidos serão preservados e vínculos nacionais existentes não serão removidos. A origem ficará intacta até Salvar como."):
            return
        try:
            before=bytes(self.data)
            new_data=apply_roster_plan(self.data,self.rosters,active_plan)
            if new_data==before:
                return messagebox.showinfo("Sem mudanças", "O plano não gerou alterações binárias.")
            self.snapshot(); self.data=new_data; self.load_tables()
            self._write_log("transferencias_aplicadas",{"snapshot_date":self.transfer_report.get("snapshot_date"),"operations":len(active_plan),"transfers_additions":transfers,"callup_suggestions_applied":callups,"items":active_plan})
            self.transfer_plan=[]; self.transfer_tree.delete(*self.transfer_tree.get_children())
            self.transfer_summary.set("Plano aplicado em memória. Salve como um novo data.bin para persistir as alterações.")
            self.status.set("Transferências aplicadas em memória; arquivo original não foi alterado.")
            messagebox.showinfo("Atualização aplicada",f"Transferências/adições: {transfers:,}\nSugestões de seleção aplicadas: {callups:,}\n\nSalve como um novo data.bin. O pacote EDIT/STFS não é reassinado pelo editor.")
        except Exception as exc:
            self._write_log("erro_aplicar_transferencias",{"error":f"{type(exc).__name__}: {exc}"})
            messagebox.showerror("Plano rejeitado",f"Nenhum plano parcial foi aplicado.\n\n{exc}")

    def _build_players_tab(self):
        pane=ttk.Panedwindow(self.players_tab,orient="horizontal"); pane.pack(fill="both",expand=True)
        left=ttk.Frame(pane,padding=5); right=ttk.Frame(pane,padding=10)
        pane.add(left,weight=3); pane.add(right,weight=2)
        ttk.Label(left,text="BANCO DE JOGADORES",font=("Segoe UI",12,"bold")).pack(anchor="w",pady=(0,7))
        searchrow=ttk.Frame(left); searchrow.pack(fill="x",pady=(0,6))
        self.search=tk.StringVar(); ent=ttk.Entry(searchrow,textvariable=self.search); ent.pack(side="left",fill="x",expand=True)
        ttk.Label(searchrow,text="Buscar nome / ID Konami",style="Sub.TLabel").pack(side="right",padx=7)
        self.search.trace_add("write",lambda *_:self.refresh_players())
        self.tree=ttk.Treeview(left,columns=("id","name","team"),show="headings",selectmode="browse")
        for col,title,width in [("id","ID KONAMI",100),("name","JOGADOR",290),("team","EQUIPE",220)]:
            self.tree.heading(col,text=title,command=lambda c=col:self.sort_tree(self.tree,c)); self.tree.column(col,width=width,anchor="w")
        self.tree.pack(fill="both",expand=True)
        self.tree.bind("<<TreeviewSelect>>",self.select_player)
        ttk.Label(right,text="FICHA DO JOGADOR",font=("Segoe UI",12,"bold")).pack(anchor="w",pady=(0,9))
        self.fields={}
        form=ttk.Frame(right); form.pack(fill="x")
        rows=[("Nome exibido","name"),("Nome da camisa","shirt"),("Idade","age"),("Altura","height"),("Peso","weight"),("Nacionalidade ID","nation"),("Pé dominante","foot"),("Uso pé ruim","weak_use"),("Precisão pé ruim","weak_acc"),("Resistência lesões","injury")]
        for i,(label,key) in enumerate(rows):
            ttk.Label(form,text=label).grid(row=i,column=0,sticky="w",pady=3,padx=(0,9))
            var=tk.StringVar(); self.fields[key]=var
            entry=ttk.Entry(form,textvariable=var); entry.grid(row=i,column=1,sticky="ew",pady=3)
            self._hint(entry,"Edita o campo "+label+" do jogador selecionado.")
        form.columnconfigure(1,weight=1)
        ttk.Label(right,text="26 atributos técnicos/físicos (bytes 0x12–0x2B)").pack(anchor="w",pady=(12,3))
        self.stats=tk.StringVar(); stats_entry=ttk.Entry(right,textvariable=self.stats); stats_entry.pack(fill="x")
        self._hint(stats_entry,"Informe exatamente 26 valores separados por vírgula, de 0 a 255.")
        ttk.Label(right,text="8 bytes de habilidades / estilos (0x2C–0x33)").pack(anchor="w",pady=(10,3))
        self.skills=tk.StringVar(); skills_entry=ttk.Entry(right,textvariable=self.skills); skills_entry.pack(fill="x")
        self._hint(skills_entry,"Informe exatamente 8 valores separados por vírgula, de 0 a 255.")
        player_actions=ttk.Frame(right); player_actions.pack(fill="x",pady=13)
        apply=ttk.Button(player_actions,text="APLICAR ALTERAÇÕES",command=self.apply_player,style="Accent.TButton"); apply.pack(side="left",padx=(0,6))
        remove=ttk.Button(player_actions,text="REMOVER JOGADOR",command=self.remove_player); remove.pack(side="left",padx=4)
        replace=ttk.Button(player_actions,text="SUBSTITUIR VAGA",command=self.replace_player); replace.pack(side="left",padx=4)
        self._hint(apply,"Valida e aplica os campos na memória. Use Salvar como para gravar um novo data.bin.")
        self._hint(remove,"Remove o jogador selecionado dos elencos e zera seu registro. Exige integridade completa dos IDs.")
        self._hint(replace,"Substitui nos elencos todas as ocorrências de um ID Konami antigo pelo jogador selecionado.")
        ttk.Label(right,text="O ID Konami do jogador é preservado. O índice da linha não é usado como ID do elenco.",style="Sub.TLabel",wraplength=390).pack(anchor="w")
        self._hint(self.tree,"Lista global de jogadores. O ID mostrado é o Konami ID, não a posição da linha no arquivo.")

    def _build_clubs_tab(self):
        toolbar=ttk.Frame(self.clubs_tab); toolbar.pack(fill="x",pady=(0,7))
        ttk.Label(toolbar,text="EQUIPES",font=("Segoe UI",12,"bold")).pack(side="left",padx=(0,15))
        self.team_filter=tk.StringVar(value="Todos")
        cat=ttk.Combobox(toolbar,textvariable=self.team_filter,state="readonly",values=["Todos","Clubes","Seleções","Clássicos"],width=14)
        cat.pack(side="left",padx=4); cat.bind("<<ComboboxSelected>>",lambda e:self.refresh_club_tab()); self._hint(cat,"Filtra as 508 equipes entre clubes, seleções nacionais e equipes clássicas.")
        self.team_search=tk.StringVar(); ts=ttk.Entry(toolbar,textvariable=self.team_search,width=34); ts.pack(side="left",padx=5)
        self.team_search.trace_add("write",lambda *_:self.refresh_club_tab())
        ttk.Label(toolbar,text="Buscar clube / seleção / ID",style="Sub.TLabel").pack(side="left")
        pane=ttk.Panedwindow(self.clubs_tab,orient="horizontal"); pane.pack(fill="both",expand=True)
        left=ttk.Frame(pane,padding=4); right=ttk.Frame(pane,padding=8)
        pane.add(left,weight=2); pane.add(right,weight=3)
        self.club_tree=ttk.Treeview(left,columns=("id","type","name"),show="headings",selectmode="browse")
        for col,title,width in [("id","ID",52),("type","TIPO",88),("name","EQUIPE",245)]:
            self.club_tree.heading(col,text=title); self.club_tree.column(col,width=width,anchor="w")
        self.club_tree.tag_configure("selection",foreground="#bce5ff")
        self.club_tree.tag_configure("classic",foreground="#e6cb95")
        self.club_tree.pack(fill="both",expand=True)
        self.club_tree.bind("<<TreeviewSelect>>",self.select_club_tab)
        self._hint(self.club_tree,"Lista completa de equipes. Selecione uma para ver e editar o nome, a sigla e o elenco.")
        ttk.Label(right,text="EQUIPE SELECIONADA",font=("Segoe UI",12,"bold")).pack(anchor="w",pady=(0,6))
        form=ttk.Frame(right); form.pack(fill="x",pady=(0,8))
        self.tname=tk.StringVar(); self.tshort=tk.StringVar(); self.team_id_label=tk.StringVar(value="ID: —")
        ttk.Label(form,textvariable=self.team_id_label,style="Sub.TLabel").grid(row=0,column=0,sticky="w",rowspan=2,padx=(0,12))
        ttk.Label(form,text="Nome oficial / exibido").grid(row=0,column=1,sticky="w")
        tn=ttk.Entry(form,textvariable=self.tname); tn.grid(row=1,column=1,sticky="ew",padx=(0,8))
        ttk.Label(form,text="Sigla").grid(row=0,column=2,sticky="w")
        tsig=ttk.Entry(form,textvariable=self.tshort,width=8); tsig.grid(row=1,column=2,sticky="ew")
        form.columnconfigure(1,weight=1)
        save=ttk.Button(form,text="SALVAR",command=self.apply_team,style="Accent.TButton"); save.grid(row=1,column=3,padx=8)
        self._hint(tn,"Edite o nome oficial da equipe. O campo aceita até 70 bytes no formato do jogo.")
        self._hint(tsig,"Edite a sigla exibida para a equipe; limite de 3 bytes no arquivo.")
        self._hint(save,"Grava o novo nome e sigla na memória e gera um registro de log.")
        actions=ttk.Frame(right); actions.pack(fill="x",pady=(0,5))
        action_items=[
            ("TRANSFERIR JOGADOR…",self.transfer_to_selected_club,"Seleciona um jogador e escolhe o clube de destino; retira o jogador do clube anterior, preservando convocações."),
            ("CONVOCAR PARA SELEÇÃO…",self.call_up_to_selected_team,"Escolhe uma seleção nacional e adiciona o jogador sem removê-lo do clube."),
            ("ADICIONAR AO CLUBE",self.add_selected_player_to_club,"Adiciona o jogador selecionado ao elenco desta equipe, se houver uma vaga livre."),
            ("COPIAR ELENCO + TÁTICAS…",self.copy_team,"Copia o elenco e o bloco tático da equipe de origem para a equipe selecionada."),
        ]
        for i,(label,cmd,hint) in enumerate(action_items):
            b=ttk.Button(actions,text=label,command=cmd,style="Accent.TButton" if i==0 else "TButton")
            b.grid(row=i//2,column=i%2,sticky="ew",padx=3,pady=2); self.main_buttons.append(b); self._hint(b,hint)
        actions.columnconfigure(0,weight=1); actions.columnconfigure(1,weight=1)
        ttk.Label(right,text="ELENCO ATUAL  •  até 32 vagas",font=("Segoe UI",10,"bold")).pack(anchor="w",pady=(3,4))
        self.club_roster_tree=ttk.Treeview(right,columns=("id","name","shirt"),show="headings",height=12,selectmode="browse")
        for col,title,width in [("id","ID KONAMI",100),("name","JOGADOR",350),("shirt","CAMISA",80)]:
            self.club_roster_tree.heading(col,text=title); self.club_roster_tree.column(col,width=width,anchor="w")
        self.club_roster_tree.pack(fill="both",expand=True)
        self.club_roster_tree.bind("<<TreeviewSelect>>",self.select_roster_player)
        self._hint(self.club_roster_tree,"Jogadores vinculados à equipe. Selecione um jogador para transferi-lo ou convocá-lo.")
        self.team_integrity_var=tk.StringVar(value="Integridade dos elencos: aguardando arquivo")
        ttk.Label(right,textvariable=self.team_integrity_var,style="Sub.TLabel").pack(anchor="w",pady=(4,0))

    def _build_competitions_tab(self):
        pane=ttk.Panedwindow(self.comps_tab,orient="horizontal"); pane.pack(fill="both",expand=True)
        left=ttk.Frame(pane,padding=5); right=ttk.Frame(pane,padding=12)
        pane.add(left,weight=2); pane.add(right,weight=1)
        ttk.Label(left,text="NOMES DE COMPETIÇÕES NO SAVE",font=("Segoe UI",12,"bold")).pack(anchor="w",pady=(0,7))
        self.comp_tree=ttk.Treeview(left,columns=("id","name"),show="headings",selectmode="browse")
        self.comp_tree.heading("id",text="ID"); self.comp_tree.column("id",width=80)
        self.comp_tree.heading("name",text="COMPETIÇÃO"); self.comp_tree.column("name",width=480)
        self.comp_tree.pack(fill="both",expand=True); self.comp_tree.bind("<<TreeviewSelect>>",self.select_competition)
        self._hint(self.comp_tree,"Lista as competições identificadas na tabela binária do PES 2018. Selecione uma para editar o nome.")
        ttk.Label(right,text="EDITAR COMPETIÇÃO",font=("Segoe UI",12,"bold")).pack(anchor="w",pady=(0,9))
        self.comp_id_label=tk.StringVar(value="ID: —"); ttk.Label(right,textvariable=self.comp_id_label,style="Sub.TLabel").pack(anchor="w")
        self.comp_name=tk.StringVar(); comp_entry=ttk.Entry(right,textvariable=self.comp_name); comp_entry.pack(fill="x",pady=8)
        self._hint(comp_entry,"Edite o nome desta competição. O programa preserva os 14 bytes de metadados do registro.")
        apply=ttk.Button(right,text="SALVAR NOME DA COMPETIÇÃO",command=self.apply_competition,style="Accent.TButton"); apply.pack(anchor="e")
        self._hint(apply,"Altera somente a string da competição selecionada e registra a mudança nos logs.")
        ttk.Label(right,text="Aviso: PEU, PLA, PAS e KONAMI são ligas/copas genéricas. O editor não inventa um nome real sem um patch que identifique qual competição elas representam.",style="Sub.TLabel",wraplength=290).pack(anchor="w",pady=15)

    # ---------- Logs ----------
    def open_logs_folder(self):
        self.logs_dir.mkdir(parents=True,exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(self.logs_dir))
            elif sys.platform == "darwin":
                import subprocess; subprocess.Popen(["open",str(self.logs_dir)])
            else:
                import subprocess; subprocess.Popen(["xdg-open",str(self.logs_dir)])
        except Exception as exc:
            messagebox.showerror("Pasta de logs",f"Não foi possível abrir a pasta automaticamente:\n{self.logs_dir}\n\n{exc}")

    def _write_log(self,event,payload):
        try:
            self.logs_dir.mkdir(parents=True,exist_ok=True)
            record={"timestamp":datetime.now().astimezone().isoformat(timespec="seconds"),"event":event,"source":self.path,"payload":payload}
            with (self.logs_dir/"editor_events.jsonl").open("a",encoding="utf-8") as f: f.write(json.dumps(record,ensure_ascii=False)+"\n")
            stamp=datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            (self.logs_dir/f"{stamp}_{event}.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
            lines=[f"PES 2018 X360 Editor v1.0",f"Data: {record['timestamp']}",f"Evento: {event}",f"Arquivo: {self.path or '-'}",json.dumps(payload,ensure_ascii=False,indent=2)]
            (self.logs_dir/f"{stamp}_{event}.txt").write_text("\n".join(lines),encoding="utf-8")
        except Exception as exc:
            try: self.status.set(f"Aviso: não foi possível gerar log: {exc}")
            except Exception: pass

    # ---------- File IO and validation ----------
    def open_file(self):
        path=filedialog.askopenfilename(title="Abrir data.bin ou pacote EDIT00000000",filetypes=[("PES data.bin","*.bin"),("Todos os arquivos (inclui EDIT00000000)","*.*")])
        if not path: return
        try:
            source=Path(path).read_bytes(); new_container=None
            if source[:4] in (b"CON ",b"LIVE",b"PIRS"):
                reader=STFSReader(path)
                entries,_=reader.list_entries(verify_hash=True)
                item=next((e for e in entries if e["name"].casefold()=="data.bin" and not e["is_dir"]),None)
                if item is None: raise ValueError("O pacote STFS não contém data.bin.")
                raw,_=reader.read_chain(item["start_block"],item["size"],item["allocated_blocks"],verify_hash=True)
                new_container={"path":path,"magic":reader.magic,"hash_verified":True,"entry_size":len(raw)}
            else: raw=source
            self.layout_info=detect_layout(raw)
            if self.data is not None and self.dirty and not messagebox.askyesno("Abrir outro arquivo","Descartar as alterações ainda não salvas?"): return
            self.source_container=new_container
            self.data=bytearray(raw); self.path=os.path.abspath(path); self.undo.clear(); self.redo.clear(); self.dirty=False
            self.load_tables()
            correction=self.apply_official_names(show_result=False)
            counts=self.roster_integrity
            summary=f"{Path(path).name} | {len(self.players):,} jogadores | {len(self.teams)} equipes | {len(self.competitions)} competições"
            if counts["invalid"]:
                summary+=f" | {counts['invalid']:,} refs. desconhecidas preservadas (não serão sobrescritas)"
            if self.source_container: summary+=" | STFS verificado / leitura extraída"
            self.status.set(summary)
            if hasattr(self,"team_integrity_var"): self.team_integrity_var.set(self._integrity_text())
            self._write_log("arquivo_aberto",{"bytes":len(raw),"players":len(self.players),"teams":len(self.teams),"competitions":len(self.competitions),"roster_integrity":self.roster_integrity,"layout":self.layout_info,"stfs":self.source_container,"auto_corrections":correction})
            self.progress_text.set("Arquivo carregado")
            historical=self.apply_historical_names(show_result=False)
            if correction["teams"] or correction["competitions"] or historical:
                messagebox.showinfo("Correções iniciais",f"Correção automática aplicada em memória:\n\nClubes / seleções: {correction['teams']}\nCompetições: {correction['competitions']}\nJogadores clássicos: {historical}\n\nUse Salvar como para gravar uma nova cópia.")
            self.auto_prepare_playersdb()
        except Exception as exc:
            self._write_log("erro_ao_abrir",{"error":f"{type(exc).__name__}: {exc}"})
            messagebox.showerror("Erro ao abrir",str(exc))

    def load_tables(self):
        if self.data is None: return
        b=self.data
        pc=min(u16(b,0x60),21000); tc=min(u16(b,0x64),2048); rc=min(u16(b,0x70),4096)
        from editor_core import PLAYER_TABLE_OFFSET,PLAYER_STRIDE,PLAYER_NAME_REL,PLAYER_NAME_SIZE,TEAM_TABLE_OFFSET,TEAM_STRIDE,TEAM_NAME_REL,TEAM_NAME_SIZE,TEAM_SHORT_REL,TEAM_SHORT_SIZE,ROSTER_TABLE_OFFSET,ROSTER_STRIDE,ROSTER_PLAYER_REL,ROSTER_PLAYER_COUNT,ROSTER_NUMBERS_REL
        if PLAYER_TABLE_OFFSET+pc*PLAYER_STRIDE>len(b): raise ValueError("Tabela de jogadores ultrapassa o arquivo.")
        if TEAM_TABLE_OFFSET+tc*TEAM_STRIDE>len(b): raise ValueError("Tabela de equipes ultrapassa o arquivo.")
        if ROSTER_TABLE_OFFSET+rc*ROSTER_STRIDE>len(b): raise ValueError("Tabela de elencos ultrapassa o arquivo.")
        self.players=[]; self.player_index_by_ref={}; duplicate_refs=[]
        for i in range(pc):
            off=PLAYER_TABLE_OFFSET+i*PLAYER_STRIDE; ref=u32(b,off)
            name=decode(b[off+PLAYER_NAME_REL:off+PLAYER_NAME_REL+PLAYER_NAME_SIZE])
            self.players.append({"id":i,"off":off,"konami_id":ref,"name":name})
            if ref:
                if ref in self.player_index_by_ref: duplicate_refs.append(ref)
                else: self.player_index_by_ref[ref]=i
        self.teams=[]
        for i in range(tc):
            off=TEAM_TABLE_OFFSET+i*TEAM_STRIDE
            self.teams.append({"id":i,"off":off,"name":decode(b[off+TEAM_NAME_REL:off+TEAM_NAME_REL+TEAM_NAME_SIZE]),"short":decode(b[off+TEAM_SHORT_REL:off+TEAM_SHORT_REL+TEAM_SHORT_SIZE])})
        self.rosters=[]; nonzero=valid=invalid=0
        for i in range(rc):
            off=ROSTER_TABLE_OFFSET+i*ROSTER_STRIDE
            ids=[u32(b,off+ROSTER_PLAYER_REL+j*4) for j in range(ROSTER_PLAYER_COUNT)]
            nums=[b[off+ROSTER_NUMBERS_REL+j] for j in range(ROSTER_PLAYER_COUNT)]
            for ref in ids:
                if ref:
                    nonzero+=1
                    if ref in self.player_index_by_ref: valid+=1
                    else: invalid+=1
            self.rosters.append({"team":i,"off":off,"ids":ids,"numbers":nums})
        # IDs que não existem na tabela podem pertencer a patch/mod anterior: ocupam vaga e são preservados.
        # Bloqueia somente duplicidade de Konami ID na tabela de jogadores, que torna a origem ambígua.
        ratio=(valid/nonzero) if nonzero else 1.0
        self.roster_integrity={"nonzero":nonzero,"valid":valid,"invalid":invalid,"ratio":ratio,"safe":not duplicate_refs,"duplicate_player_ids":len(duplicate_refs),"unknown_refs_preserved":True}
        self.competitions=[]
        if COMPETITION_TABLE_OFFSET+COMPETITION_COUNT*COMPETITION_STRIDE<=len(b):
            for i in range(COMPETITION_COUNT):
                off=COMPETITION_TABLE_OFFSET+i*COMPETITION_STRIDE; cid=u16(b,off)
                if cid==0xFFFF: continue
                name=decode(b[off+COMPETITION_NAME_REL:off+COMPETITION_STRIDE])
                self.competitions.append({"row":i,"id":cid,"off":off,"name":name})
        self.refresh_players(); self.refresh_teams(); self.refresh_club_tab(); self.refresh_competitions()
        if hasattr(self,"team_integrity_var"): self.team_integrity_var.set(self._integrity_text())

    def _integrity_text(self):
        q=self.roster_integrity
        if q["safe"]:
            return f"IDs únicos: OK — {q['valid']:,} refs. reconhecidas; {q['invalid']:,} refs. desconhecidas preservadas. Elencos editáveis com proteção de slots."
        return f"IDs duplicados na base: {q['duplicate_player_ids']:,}. Transferências bloqueadas por ambiguidade; nomes continuam editáveis."

    def _require_roster_integrity(self):
        if self.roster_integrity.get("safe",False): return True
        messagebox.showwarning("IDs duplicados",f"A tabela de jogadores contém {self.roster_integrity['duplicate_player_ids']:,} IDs Konami duplicados. A origem de um jogador não é única.\n\nAções de elenco bloqueadas até corrigir essa ambiguidade. Referências não reconhecidas permanecem preservadas.")
        return False

    # ---------- Name correction ----------
    def apply_historical_names(self,show_result=True):
        if self.data is None: return 0
        from editor_core import PLAYER_NAME_REL, PLAYER_NAME_SIZE
        planned=[]
        for p in self.players:
            real=CLASSIC_FAKE_NAMES.get(p["name"].strip().upper())
            if real and name_norm(real)!=name_norm(p["name"]):
                planned.append((p,real))
        if planned:
            self.snapshot()
            for p,new in planned:
                self.data[p["off"]+PLAYER_NAME_REL:p["off"]+PLAYER_NAME_REL+PLAYER_NAME_SIZE]=encode(new,PLAYER_NAME_SIZE)
            self.load_tables()
            self._write_log("nomes_classicos_corrigidos",{"count":len(planned),"changes":[{"konami_id":p["konami_id"],"old":p["name"],"new":new} for p,new in planned]})
        if show_result:
            messagebox.showinfo("Nomes históricos",f"Nomes fictícios de jogadores clássicos corrigidos: {len(planned)}")
        return len(planned)

    def apply_official_names(self,show_result=True):
        if self.data is None: return {"teams":0,"competitions":0,"team_changes":[],"competition_changes":[]}
        from editor_core import TEAM_NAME_REL,TEAM_NAME_SIZE
        team_alias_map={}
        for tid,(old,official) in TEAM_NAMES.items():
            team_alias_map.setdefault(int(tid),[]).append((old,official))
        for filename in ("team_aliases.csv","national_team_aliases.csv"):
            file=self._app_dir()/filename
            if not file.exists(): continue
            try:
                with file.open("r",encoding="utf-8-sig",newline="") as f:
                    for row in csv.DictReader(f,delimiter=";"):
                        tid=str(row.get("team_id","")).strip(); alias=str(row.get("alias","")).strip()
                        official=str(row.get("official_name","")).strip()
                        if tid.isdigit() and alias:
                            if not official and int(tid) in TEAM_NAMES: official=TEAM_NAMES[int(tid)][1]
                            if official: team_alias_map.setdefault(int(tid),[]).append((alias,official))
            except Exception as exc:
                self._write_log("erro_mapa_nome_equipes",{"file":filename,"error":str(exc)})
        competition_alias_map={}
        for cid,(old,official) in COMPETITION_NAMES.items():
            competition_alias_map.setdefault(int(cid),[]).append((old,official))
        file=self._app_dir()/"competition_aliases.csv"
        if file.exists():
            try:
                with file.open("r",encoding="utf-8-sig",newline="") as f:
                    for row in csv.DictReader(f,delimiter=";"):
                        raw_id=str(row.get("competition_id","")).strip(); alias=str(row.get("alias","")).strip()
                        official=str(row.get("official_name","")).strip()
                        if raw_id.isdigit() and alias and official:
                            competition_alias_map.setdefault(int(raw_id),[]).append((alias,official))
            except Exception as exc:
                self._write_log("erro_mapa_nome_competicoes",{"error":str(exc)})
        planned_t=[]; planned_c=[]
        for t in self.teams:
            matches={name_norm(official) for alias,official in team_alias_map.get(int(t["id"]),[]) if name_norm(t["name"])==name_norm(alias) and name_norm(official)}
            if len(matches)==1:
                official=next(official for alias,official in team_alias_map[int(t["id"])] if name_norm(t["name"])==name_norm(alias) and name_norm(official) in matches)
                if name_norm(t["name"])!=name_norm(official): planned_t.append((t,official))
        for c in self.competitions:
            matches={name_norm(official) for alias,official in competition_alias_map.get(int(c["id"]),[]) if name_norm(c["name"])==name_norm(alias) and name_norm(official)}
            if len(matches)==1:
                official=next(official for alias,official in competition_alias_map[int(c["id"])] if name_norm(c["name"])==name_norm(alias) and name_norm(official) in matches)
                if name_norm(c["name"])!=name_norm(official): planned_c.append((c,official))
        changes_t=[]; changes_c=[]
        if planned_t or planned_c:
            before=bytes(self.data)
            self.undo.append(before); self.undo=self.undo[-30:]; self.redo.clear(); self.dirty=True
        for t,official in planned_t:
            old=t["name"]
            self.data[t["off"]+TEAM_NAME_REL:t["off"]+TEAM_NAME_REL+TEAM_NAME_SIZE]=encode(official,TEAM_NAME_SIZE)
            changes_t.append({"id":t["id"],"old":old,"new":official}); t["name"]=official
        for c,official in planned_c:
            old=c["name"]
            self.data[c["off"]+COMPETITION_NAME_REL:c["off"]+COMPETITION_STRIDE]=encode(official,COMPETITION_NAME_SIZE)
            changes_c.append({"id":c["id"],"old":old,"new":official}); c["name"]=official
        if changes_t or changes_c:
            self.refresh_players(); self.refresh_club_tab(); self.refresh_competitions()
            self._write_log("nomes_oficiais_corrigidos",{"clubes_selecoes":changes_t,"competicoes":changes_c})
        result={"teams":len(changes_t),"competitions":len(changes_c),"team_changes":changes_t,"competition_changes":changes_c}
        if show_result:
            messagebox.showinfo("Correção de nomes",f"Clubes / seleções corrigidos: {result['teams']}\nCompetições corrigidas: {result['competitions']}\n\nOs mapas são vinculados pelo ID e por nomes/aliases verificados. Ligas genéricas dependentes do patch permanecem sem alteração automática.")
        return result

    # ---------- Table refresh ----------
    def refresh_players(self):
        if self.data is None or not hasattr(self,"tree"): return
        query=self.search.get().casefold().strip()
        self.tree.delete(*self.tree.get_children())
        for p in self.players:
            if query and query not in p["name"].casefold() and query not in str(p["konami_id"]): continue
            self.tree.insert("","end",iid=str(p["id"]),values=(p["konami_id"],p["name"],self.team_for(p["id"]) ))

    def refresh_teams(self):
        self.refresh_club_tab()

    def refresh_club_tab(self):
        if not hasattr(self,"club_tree"): return
        selected=self.club_tree.selection(); keep=selected[0] if selected else None
        self.club_tree.delete(*self.club_tree.get_children())
        filt=self.team_filter.get() if hasattr(self,"team_filter") else "Todos"
        query=self.team_search.get().casefold().strip() if hasattr(self,"team_search") else ""
        for t in self.teams:
            cat=team_category(t["id"])
            if filt=="Clubes" and cat!="Clube": continue
            if filt=="Seleções" and cat!="Seleção": continue
            if filt=="Clássicos" and cat!="Clássicos": continue
            if query and query not in t["name"].casefold() and query not in str(t["id"]): continue
            tag="selection" if cat=="Seleção" else ("classic" if cat=="Clássicos" else "")
            self.club_tree.insert("","end",iid=str(t["id"]),values=(t["id"],cat,t["name"]),tags=(tag,) if tag else ())
        if keep and self.club_tree.exists(keep): self.club_tree.selection_set(keep)
        elif self.club_tree.get_children() and not self.club_tree.selection(): self.club_tree.selection_set(self.club_tree.get_children()[0])
        self.select_club_tab()

    def refresh_club_roster(self):
        if not hasattr(self,"club_roster_tree"): return
        self.club_roster_tree.delete(*self.club_roster_tree.get_children())
        sel=self.club_tree.selection()
        if not sel: return
        team_id=int(sel[0]); r=self.find_roster(team_id)
        if not r: return
        for ref,shirt in zip(r["ids"],r["numbers"]):
            if not ref: continue
            idx=self.player_index_by_ref.get(ref)
            if idx is None:
                self.club_roster_tree.insert("","end",iid=f"bad_{ref}",values=(ref,"REFERÊNCIA INVÁLIDA",shirt),tags=("classic",))
            else:
                self.club_roster_tree.insert("","end",iid=str(ref),values=(ref,self.players[idx]["name"],shirt))

    def refresh_competitions(self):
        if not hasattr(self,"comp_tree"): return
        keep=self.comp_tree.selection(); selected=keep[0] if keep else None
        self.comp_tree.delete(*self.comp_tree.get_children())
        for c in self.competitions: self.comp_tree.insert("","end",iid=str(c["row"]),values=(c["id"],c["name"]))
        if selected and self.comp_tree.exists(selected): self.comp_tree.selection_set(selected)

    def team_for(self,player_index):
        if not isinstance(player_index,int) or player_index<0 or player_index>=len(self.players): return "—"
        ref=self.players[player_index]["konami_id"]
        if not ref: return "Sem ID Konami"
        hits=[]
        for r in self.rosters:
            if ref in r["ids"]: hits.append(r["team"])
        if not hits: return "Sem equipe"
        hits.sort(key=lambda tid:(team_category(tid)!="Clube",tid))
        tid=hits[0]
        return self.teams[tid]["name"] if tid<len(self.teams) else str(tid)

    def selected_team(self):
        s=self.club_tree.selection() if hasattr(self,"club_tree") else ()
        return int(s[0]) if s else None

    def select_club_tab(self,_event=None):
        tid=self.selected_team()
        self.current_team_id=tid
        if tid is not None and tid<len(self.teams):
            t=self.teams[tid]; self.team_id_label.set(f"ID {tid}  •  {team_category(tid)}")
            self.tname.set(t["name"]); self.tshort.set(t["short"])
        else:
            self.team_id_label.set("ID: —"); self.tname.set(""); self.tshort.set("")
        self.refresh_club_roster()

    def select_team(self,_event=None): self.select_club_tab(_event)

    def apply_team(self):
        tid=self.selected_team()
        if tid is None or self.data is None: return
        from editor_core import TEAM_NAME_REL,TEAM_NAME_SIZE,TEAM_SHORT_REL,TEAM_SHORT_SIZE
        name=self.tname.get().strip(); short=self.tshort.get().strip()
        if not name: return messagebox.showwarning("Nome vazio","Informe o nome da equipe.")
        self.snapshot(); t=self.teams[tid]
        self.data[t["off"]+TEAM_NAME_REL:t["off"]+TEAM_NAME_REL+TEAM_NAME_SIZE]=encode(name,TEAM_NAME_SIZE)
        self.data[t["off"]+TEAM_SHORT_REL:t["off"]+TEAM_SHORT_REL+TEAM_SHORT_SIZE]=encode(short,TEAM_SHORT_SIZE)
        old=t["name"]; t["name"]=name; t["short"]=short
        self.refresh_club_tab(); self.refresh_players()
        self.status.set(f"Equipe {tid} renomeada em memória.")
        self._write_log("equipe_renomeada",{"team_id":tid,"old_name":old,"new_name":name,"short":short})

    def find_roster(self,team_id): return next((r for r in self.rosters if r["team"]==team_id),None)

    def select_player(self,_event=None):
        self.player_selection_source="global"
        return BaseEditor.select_player(self,_event)

    def select_roster_player(self,_event=None):
        sel=self.club_roster_tree.selection()
        if not sel: return
        iid=sel[0]
        if iid.startswith("bad_"): return
        ref=int(iid); idx=self.player_index_by_ref.get(ref)
        if idx is not None:
            if self.tree.exists(str(idx)):
                self.tree.selection_set(str(idx)); self.tree.see(str(idx))
            self.player_selection_source="roster"
            BaseEditor.select_player(self)
            self.root.after_idle(lambda: setattr(self,"player_selection_source","roster"))

    def get_selected_player_index(self):
        if self.player_selection_source=="roster" and hasattr(self,"club_roster_tree"):
            s=self.club_roster_tree.selection()
            if s and not s[0].startswith("bad_"):
                idx=self.player_index_by_ref.get(int(s[0]))
                if idx is not None: return idx
        s=self.tree.selection() if hasattr(self,"tree") else ()
        return int(s[0]) if s else None

    def transfer(self):
        self.transfer_to_selected_club()

    def add_player(self):
        messagebox.showinfo("Inclusão de jogador","O CSV/JSONL do PlayersDB não contém os atributos PES completos para criar um novo registro com segurança. Nesta versão, adicione ao elenco jogadores que já existem na tabela global. Para cadastrar um jogador realmente novo, é necessário importar um registro PES completo de outro save/patch compatível.")

    # ---------- Competitions ----------
    def select_competition(self,_event=None):
        s=self.comp_tree.selection()
        if not s: return
        row=int(s[0]); c=next((x for x in self.competitions if x["row"]==row),None)
        if c:
            self.current_comp_row=row; self.comp_id_label.set(f"ID {c['id']}  •  registro {row}"); self.comp_name.set(c["name"])

    def apply_competition(self):
        if self.current_comp_row is None or self.data is None: return
        c=next((x for x in self.competitions if x["row"]==self.current_comp_row),None)
        if not c: return
        name=self.comp_name.get().strip()
        if not name: return messagebox.showwarning("Nome vazio","Informe o nome da competição.")
        old=c["name"]
        self.snapshot(); self.data[c["off"]+COMPETITION_NAME_REL:c["off"]+COMPETITION_STRIDE]=encode(name,COMPETITION_NAME_SIZE); c["name"]=name
        self.refresh_competitions(); self.status.set(f"Competição {c['id']} atualizada em memória.")
        self._write_log("competicao_renomeada",{"competition_id":c["id"],"old_name":old,"new_name":name})

    # ---------- Safe roster editing: 32-bit Konami IDs ----------
    def _selected_player_and_club(self):
        idx=self.get_selected_player_index(); dest=self.selected_team()
        if idx is None: messagebox.showinfo("Jogador","Selecione um jogador na tabela de jogadores ou no elenco da equipe."); return None,None
        if dest is None: messagebox.showinfo("Equipe","Selecione uma equipe na lista."); return None,None
        return idx,dest

    def choose_team_dialog(self,category):
        win=tk.Toplevel(self.root); win.title("Selecionar "+category.lower()); win.geometry("520x570"); win.transient(self.root); win.grab_set()
        holder={"id":None}; frame=ttk.Frame(win,padding=10); frame.pack(fill="both",expand=True)
        ttk.Label(frame,text="Buscar equipe por nome ou ID").pack(anchor="w")
        query=tk.StringVar(); entry=ttk.Entry(frame,textvariable=query); entry.pack(fill="x",pady=6); entry.focus_set()
        tree=ttk.Treeview(frame,columns=("id","name"),show="headings",height=20); tree.heading("id",text="ID"); tree.column("id",width=55); tree.heading("name",text="Equipe"); tree.column("name",width=380); tree.pack(fill="both",expand=True)
        def fill(*_):
            tree.delete(*tree.get_children())
            for t in self.teams:
                if category=="Clube" and team_category(t["id"])!="Clube": continue
                if category=="Seleção" and team_category(t["id"])!="Seleção": continue
                q=query.get().casefold()
                if q and q not in t["name"].casefold() and q not in str(t["id"]): continue
                tree.insert("","end",iid=str(t["id"]),values=(t["id"],t["name"]))
        def choose(_=None):
            s=tree.selection()
            if s: holder["id"]=int(s[0]); win.destroy()
        query.trace_add("write",fill); tree.bind("<Double-1>",choose)
        btn=ttk.Button(frame,text="Selecionar equipe",command=choose,style="Accent.TButton"); btn.pack(anchor="e",pady=8)
        self._hint(btn,"Confirma a equipe de destino da operação selecionada.")
        fill(); win.wait_window(); return holder["id"]

    def _place_player(self,player_index,dest,remove_previous):
        if self.data is None or not self._require_roster_integrity(): return False
        if player_index is None or player_index<0 or player_index>=len(self.players): return False
        ref=self.players[player_index]["konami_id"]
        if not ref: return messagebox.showwarning("ID ausente","O registro não tem ID Konami válido; não pode ser inserido em um elenco.")
        roster=self.find_roster(dest)
        if not roster: return messagebox.showerror("Elenco","Registro de elenco não encontrado para esta equipe.")
        if ref in roster["ids"]: return messagebox.showinfo("Elenco","O jogador já está nesta equipe.")
        try: slot=roster["ids"].index(0)
        except ValueError: return messagebox.showwarning("Elenco cheio","A equipe já tem 32 jogadores. Não foi feita nenhuma alteração.")
        default_shirt=0
        for r in self.rosters:
            if ref in r["ids"]: default_shirt=r["numbers"][r["ids"].index(ref)]; break
        shirt=simpledialog.askinteger("Número da camisa","Número desejado (0 a 99):",initialvalue=default_shirt,minvalue=0,maxvalue=99)
        if shirt is None: return False
        self.snapshot(); touched=[]
        if remove_previous:
            for r in self.rosters:
                if team_category(r["team"])=="Seleção": continue
                for j,value in enumerate(r["ids"]):
                    if value==ref:
                        r["ids"][j]=0; r["numbers"][j]=0
                        p32(self.data,r["off"]+4+j*4,0); self.data[r["off"]+0x84+j]=0; touched.append(r["team"])
        roster["ids"][slot]=ref; roster["numbers"][slot]=shirt
        p32(self.data,roster["off"]+4+slot*4,ref); self.data[roster["off"]+0x84+slot]=shirt
        self.manual_ids.add(ref); self.save_manual_state(); self.load_tables()
        self.status.set("Elenco atualizado em memória. Salve como novo data.bin para gravar.")
        self._write_log("jogador_inserido_elenco",{"konami_id":ref,"player":self.players[self.player_index_by_ref[ref]]["name"],"destination_team":dest,"destination_name":self.teams[dest]["name"],"removed_from_teams":touched,"shirt":shirt,"operation":"transferencia" if remove_previous else "convocacao/inclusao"})
        return True

    def transfer_to_selected_club(self):
        if not self._require_roster_integrity(): return
        idx=self.get_selected_player_index()
        if idx is None: return messagebox.showinfo("Jogador","Selecione um jogador.")
        dest=self.choose_team_dialog("Clube")
        if dest is not None: self._place_player(idx,dest,True)

    def call_up_to_selected_team(self):
        if not self._require_roster_integrity(): return
        idx=self.get_selected_player_index()
        if idx is None: return messagebox.showinfo("Jogador","Selecione um jogador.")
        dest=self.choose_team_dialog("Seleção")
        if dest is not None: self._place_player(idx,dest,False)

    def add_selected_player_to_club(self):
        if not self._require_roster_integrity(): return
        idx=self.get_selected_player_index(); dest=self.selected_team()
        if idx is None or dest is None: return messagebox.showinfo("Seleção","Selecione um jogador e a equipe de destino.")
        if team_category(dest)!="Clube": return messagebox.showwarning("Equipe","Escolha um clube. Para seleções, use Convocar.")
        ref=self.players[idx]["konami_id"]
        current=[r["team"] for r in self.rosters if team_category(r["team"])=="Clube" and ref in r["ids"] and r["team"]!=dest]
        if current: return messagebox.showwarning("Jogador em outro clube",f"O jogador já está no clube ID {current[0]}. Use Transferir para mudar de clube.")
        self._place_player(idx,dest,False)

    def remove_player(self):
        idx=self.get_selected_player_index()
        if idx is None or self.data is None: return
        if not self._require_roster_integrity(): return
        ref=self.players[idx]["konami_id"]
        if not messagebox.askyesno("Remover jogador","Remover o jogador de todos os elencos e zerar seu registro?"): return
        self.snapshot()
        for r in self.rosters:
            for j,x in enumerate(r["ids"]):
                if x==ref: r["ids"][j]=0; r["numbers"][j]=0; p32(self.data,r["off"]+4+j*4,0); self.data[r["off"]+0x84+j]=0
        off=self.players[idx]["off"]; self.data[off:off+0xBC]=b"\0"*0xBC
        self.load_tables(); self._write_log("jogador_removido",{"konami_id":ref}); self.status.set("Jogador removido em memória.")

    def replace_player(self):
        new_idx=self.get_selected_player_index()
        if new_idx is None or self.data is None: return
        if not self._require_roster_integrity(): return
        old_ref=simpledialog.askinteger("Substituir jogador","Informe o ID Konami do jogador que será substituído:",minvalue=1,maxvalue=U32_MAX)
        if old_ref is None: return
        new_ref=self.players[new_idx]["konami_id"]
        if old_ref==new_ref: return
        found=[(r,j) for r in self.rosters for j,x in enumerate(r["ids"]) if x==old_ref]
        if not found: return messagebox.showinfo("Não encontrado","Esse ID Konami não aparece nos elencos.")
        self.snapshot()
        occupied={(r["team"],j) for r,j in found}
        for r in self.rosters:
            for j,x in enumerate(r["ids"]):
                if x==new_ref and (r["team"],j) not in occupied: r["ids"][j]=0; r["numbers"][j]=0; p32(self.data,r["off"]+4+j*4,0); self.data[r["off"]+0x84+j]=0
        for r,j in found: r["ids"][j]=new_ref; p32(self.data,r["off"]+4+j*4,new_ref)
        self.load_tables(); self._write_log("vaga_substituida",{"old_konami_id":old_ref,"new_konami_id":new_ref})

    # ---------- PlayersDB: schema-aware, no invented team affiliation ----------
    def apply_playersdb_names_and_squads(self):
        if self.data is None or not self.playersdb_entries:
            return {"player_names":0,"shirt_names":0,"team_names":0,"rosters":0,"unmatched":0,"id_matches":0,"fake_name_matches":0,"historical":0}
        by_id={}
        for e in self.playersdb_entries:
            kid=e.get("konami_id")
            if kid is not None and e.get("name") and "PES 2018" in e.get("game_versions",[]):
                by_id.setdefault(int(kid),[]).append(e)
        id_matches=changed=exact_fake=duplicates=shirt_changed=0; planned=[]
        for p in self.players:
            ref=p["konami_id"]; candidates=by_id.get(ref,[]) if ref else []
            if len(candidates)>1:
                sig={(db_norm(x.get("name")),x.get("birthdate")) for x in candidates}
                if len(sig)>1: duplicates+=1; continue
            if not candidates: continue
            e=candidates[0]; id_matches+=1
            if e.get("name") and db_norm(p["name"])!=db_norm(e.get("name")):
                reason="fakeName do PlayersDB" if e.get("fake_name") and db_norm(p["name"])==db_norm(e.get("fake_name")) else "Konami ID + presença PES 2018"
                planned.append((p,"name",e["name"],reason));
                if reason=="fakeName do PlayersDB": exact_fake+=1
            # Nome de camisa é corrigido separadamente e somente pelo fakeShirtName explícito.
            current_shirt=decode(self.data[p["off"]+0x62:p["off"]+0x62+18])
            fake_shirts={db_norm(x) for x in e.get("fake_shirt_names",[]) if db_norm(x)}
            if current_shirt and db_norm(current_shirt) in fake_shirts and e.get("shirt_names"):
                canonical=e["shirt_names"][0]
                if db_norm(current_shirt)!=db_norm(canonical): planned.append((p,"shirt",canonical,"fake_shirt"))
        audit_rows=[]
        if planned:
            self.snapshot()
            for p,field,new_value,reason in planned:
                if field=="name":
                    old_name=p["name"]
                    self.data[p["off"]+0x34:p["off"]+0x34+46]=encode(new_value,46); changed+=1
                    audit_rows.append({"konami_id":p["konami_id"],"nome_anterior":old_name,"nome_playersdb":new_value,"motivo":reason})
                else:
                    self.data[p["off"]+0x62:p["off"]+0x62+18]=encode(new_value,18); shirt_changed+=1
            self.load_tables()
        historical=self.apply_historical_names(show_result=False)
        audit_path=None
        if audit_rows:
            try:
                audit_path=self.logs_dir/"correcoes_nomes_jogadores.csv"
                with audit_path.open("w",encoding="utf-8-sig",newline="") as f:
                    w=csv.DictWriter(f,fieldnames=["konami_id","nome_anterior","nome_playersdb","motivo"],delimiter=";"); w.writeheader(); w.writerows(audit_rows)
            except Exception as exc:
                self._write_log("erro_relatorio_nomes_jogadores",{"error":str(exc)})
        report={"player_names":changed,"shirt_names":shirt_changed,"team_names":0,"rosters":0,"unmatched":len(self.players)-id_matches,"id_matches":id_matches,"fake_name_matches":exact_fake,"duplicate_ids":duplicates,"historical":historical,"name_audit":str(audit_path) if audit_path else None,"squad_update":"aguardando base estática de clubes/transferências; PlayersDB não contém vínculo atual"}
        self._write_log("playersdb_importado",{"path":self.playersdb_path,"entries":len(self.playersdb_entries),"report":report})
        return report

    def auto_prepare_playersdb(self):
        """Baixa a base sem bloquear a interface; falha oferece link e importação manual."""
        if self.playersdb_entries:
            self._accept_playersdb(self.playersdb_path or "PlayersDB carregado", self.playersdb_entries, automatic=False)
            return
        if self.playersdb_thread and self.playersdb_thread.is_alive():
            self.status.set("Download do PlayersDB já está em andamento.")
            return
        self.status.set("Arquivo aberto. Tentando baixar o PlayersDB em segundo plano...")
        self.progress.configure(maximum=1, value=0)
        self.progress_text.set("Baixando PlayersDB")

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
        path=filedialog.askopenfilename(title="Carregar base PlayersDB",filetypes=[("PlayersDB CSV/JSONL compactado ou não","*.csv *.jsonl *.csv.gz *.jsonl.gz"),("CSV","*.csv *.csv.gz"),("JSONL","*.jsonl *.jsonl.gz"),("Todos os arquivos","*.*")])
        if not path: return
        try:
            entries=load_dataset(path)
            self._accept_playersdb(path,entries,automatic=False)
        except Exception as exc:
            self._write_log("erro_importar_playersdb",{"path":path,"error":f"{type(exc).__name__}: {exc}"})
            messagebox.showerror("Arquivo PlayersDB inválido",str(exc))

    def _poll_playersdb_queue(self):
        try:
            while True:
                event=self.sync_queue.get_nowait()
                if event.get("type")=="playersdb_loaded":
                    self._accept_playersdb(event["path"],event["entries"],event.get("automatic",False))
                elif event.get("type")=="playersdb_download_error":
                    self.progress_text.set("Download automático indisponível")
                    self.status.set("Download automático falhou; selecione o CSV/JSONL manualmente.")
                    self._write_log("download_playersdb_falhou",{"error":event["error"]})
                    manual=messagebox.askyesno("PlayersDB indisponível",f"Não consegui baixar o arquivo automaticamente.\n\nErro: {event['error']}\n\nAbrir o site para baixar CSV/JSONL e carregar manualmente?\n\nhttps://playersdb.app/")
                    if manual:
                        webbrowser.open("https://playersdb.app/")
                        self.load_playersdb()
        except queue.Empty:
            pass
        if self.playersdb_thread and self.playersdb_thread.is_alive():
            self.root.after(200,self._poll_playersdb_queue)

    def _accept_playersdb(self,path,entries,automatic=False):
        self.playersdb_path=path; self.playersdb_entries=entries
        self.db_status.set(f"PlayersDB: {len(entries):,} registros | {Path(path).name}")
        self.progress.configure(value=1); self.progress_text.set(f"Base local carregada: {len(entries):,}")
        report=self.apply_playersdb_names_and_squads()
        text=(f"PlayersDB carregado: {len(entries):,} registros.\n\n"
              f"IDs Konami correspondentes no arquivo: {report['id_matches']:,}\n"
              f"Nomes corrigidos por ID Konami/PES 2018: {report['player_names']:,}\n"
              f"Nomes de camisa corrigidos: {report['shirt_names']:,}\n"
              f"Aliases clássicos corrigidos: {report['historical']:,}\n\n"
              "O PlayersDB identifica jogadores; para transferências, carregue também a base estática de clubes/transferências na aba ATUALIZAR ELENCOS.")
        if automatic: self.status.set(text.replace("\n"," | "))
        else: messagebox.showinfo("PlayersDB processado",text)

    def force_download_playersdb(self):
        if self.playersdb_thread and self.playersdb_thread.is_alive():
            return messagebox.showinfo("Download em andamento","A transferência do PlayersDB já está em execução.")
        self.playersdb_entries=[]
        self.auto_prepare_playersdb()

    def update_squads(self):
        if not self.playersdb_entries: return self.load_playersdb()
        report=self.apply_playersdb_names_and_squads()
        messagebox.showinfo("PlayersDB",f"IDs Konami correspondentes: {report['id_matches']:,}\nNomes corrigidos por ID Konami/PES 2018: {report['player_names']}\nElencos reconstruídos: 0\n\nO PlayersDB corrige identidades e nomes, mas não contém clube atual. Para atualizar transferências, carregue a base estática Transfermarkt na aba ATUALIZAR ELENCOS.")

    def apply_player(self):
        before=bytes(self.data) if self.data is not None else None
        super().apply_player()
        if before is not None and self.data is not None and bytes(self.data)!=before:
            idx=self.selected_id(); ref=self.players[idx]["konami_id"] if idx is not None and idx<len(self.players) else None
            self._write_log("jogador_editado",{"konami_id":ref,"player_index":idx})

    def copy_team(self):
        dest=self.selected_team()
        if dest is None or self.data is None: return messagebox.showinfo("Equipe","Selecione a equipe de destino.")
        source=simpledialog.askinteger("Copiar equipe","ID da equipe de origem (0–507):",minvalue=0,maxvalue=max(0,len(self.teams)-1))
        if source is None or source==dest: return
        src_roster=self.find_roster(source); dst_roster=self.find_roster(dest)
        if not src_roster or not dst_roster: return messagebox.showerror("Elenco","Registro de elenco não encontrado.")
        self.snapshot()
        # Preserve o cabeçalho/ID próprio da linha de destino; copia apenas elenco e camisas.
        self.data[dst_roster["off"]+4:dst_roster["off"]+0xA4]=self.data[src_roster["off"]+4:src_roster["off"]+0xA4]
        from editor_core import TACTICS_TABLE_OFFSET,TACTICS_STRIDE
        src_t=TACTICS_TABLE_OFFSET+source*TACTICS_STRIDE; dst_t=TACTICS_TABLE_OFFSET+dest*TACTICS_STRIDE
        if src_t+TACTICS_STRIDE<=len(self.data) and dst_t+TACTICS_STRIDE<=len(self.data):
            self.data[dst_t:dst_t+TACTICS_STRIDE]=self.data[src_t:src_t+TACTICS_STRIDE]
        self.load_tables(); self._write_log("elenco_taticas_copiados",{"source_team":source,"destination_team":dest})
        self.status.set("Elenco e táticas copiados em memória.")

    def undo_edit(self):
        before=bytes(self.data) if self.data is not None else None
        super().undo_edit()
        if before is not None and self.data is not None and bytes(self.data)!=before: self._write_log("desfazer",{})

    def redo_edit(self):
        before=bytes(self.data) if self.data is not None else None
        super().redo_edit()
        if before is not None and self.data is not None and bytes(self.data)!=before: self._write_log("refazer",{})

    def export_csv(self):
        if self.data is None: return
        path=filedialog.asksaveasfilename(defaultextension=".csv",filetypes=[("CSV","*.csv")])
        if not path: return
        with open(path,"w",newline="",encoding="utf-8-sig") as f:
            w=csv.writer(f,delimiter=";"); w.writerow(["Indice interno","Konami ID","Jogador","Equipe"])
            for p in self.players: w.writerow([p["id"],p["konami_id"],p["name"],self.team_for(p["id"])])
        self._write_log("csv_exportado",{"path":path,"players":len(self.players)}); self.status.set("CSV de jogadores exportado.")

    def save(self):
        if self.data is None:
            return messagebox.showwarning("Nenhum arquivo","Abra e valide um data.bin ou pacote EDIT primeiro.")
        initial="data_EDITADO.bin" if self.source_container else (Path(self.path).name if self.path else "data_EDITADO.bin")
        initial_dir=str(Path(self.path).resolve().parent) if self.path else str(Path.home())
        target=filedialog.asksaveasfilename(title="Salvar cópia do data.bin editado",initialdir=initial_dir,initialfile=initial,defaultextension=".bin",filetypes=[("Arquivo de dados PES","*.bin"),("Todos os arquivos","*.*")])
        if not target: return
        if Path(target).exists() and not messagebox.askyesno("Confirmar substituição",f"O arquivo já existe:\n{target}\n\nSubstituir? Um backup .bak será criado."): return
        try: self._atomic_save(target)
        except Exception as exc: messagebox.showerror("Erro ao salvar",str(exc))

    def _atomic_save(self,out_path):
        super()._atomic_save(out_path)
        self._write_log("arquivo_salvo",{"path":out_path,"bytes":len(self.data),"sha256":hashlib.sha256(bytes(self.data)).hexdigest(),"backup":str(Path(out_path).with_name(Path(out_path).name+'.bak'))})
        if self.source_container:
            self.status.set("BIN salvo. Reimporte o data.bin em ferramenta STFS/Horizon: este editor não reempacota nem reassina CON/LIVE/PIRS.")


def main():
    root=tk.Tk(); EditorV10(root); root.mainloop()

if __name__=="__main__": main()
