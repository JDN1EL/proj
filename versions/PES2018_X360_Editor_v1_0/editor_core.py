# -*- coding: utf-8 -*-
"""Núcleo comum do PES 2018 X360 Editor v1.0; não contém lógica antiga de elenco/API."""
from __future__ import annotations
import hashlib, json, os, shutil, sys, tempfile
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

PLAYER_COUNT_OFFSET=0x60
TEAM_COUNT_OFFSET=0x64
ROSTER_COUNT_OFFSET=0x70
PLAYER_TABLE_OFFSET=0x7C
PLAYER_STRIDE=0xBC
PLAYER_CAPACITY=21000
TEAM_TABLE_OFFSET=PLAYER_TABLE_OFFSET+PLAYER_CAPACITY*PLAYER_STRIDE
TEAM_STRIDE=0x1E0
ROSTER_TABLE_OFFSET=0x46FF54
ROSTER_STRIDE=0xA4
ROSTER_PLAYER_REL=0x04
ROSTER_PLAYER_COUNT=32
ROSTER_NUMBERS_REL=0x84
TACTICS_TABLE_OFFSET=0x488B74
TACTICS_STRIDE=0x274
TEAM_NAME_REL=0x98
TEAM_NAME_SIZE=70
TEAM_SHORT_REL=0xDE
TEAM_SHORT_SIZE=3
PLAYER_NAME_REL=0x34
PLAYER_NAME_SIZE=46
PLAYER_SHIRT_REL=0x62
PLAYER_SHIRT_SIZE=18

def u16(buf,off): return int.from_bytes(buf[off:off+2],'big')
def p16(buf,off,value): buf[off:off+2]=max(0,min(65535,int(value))).to_bytes(2,'big')
def decode(raw): return bytes(raw).split(b'\0',1)[0].decode('utf-8','replace').strip()
def encode(text,size):
    raw=str(text).encode('utf-8')[:size]
    while True:
        try: raw.decode('utf-8'); break
        except UnicodeDecodeError: raw=raw[:-1]
    return raw+b'\0'*(size-len(raw))

class EditorCore:
    def __init__(self,root):
        self.root=root; self.data=None; self.path=None; self.dirty=False
        self.undo=[]; self.redo=[]; self.players=[]; self.teams=[]; self.rosters=[]
        self.competitions=[]; self.playersdb_entries=[]; self.playersdb_path=None
        self.playersdb_thread=None; self.sync_queue=None; self.manual_ids=set()
        appdata=os.environ.get('APPDATA',str(Path.home()))
        self.config_dir=Path(appdata)/'PES2018_X360_Editor'; self.config_dir.mkdir(parents=True,exist_ok=True)
        self.database_dir=self.config_dir/'database'; self.database_dir.mkdir(parents=True,exist_ok=True)
        self.state_path=self.config_dir/'manual_changes.json'
        self.logs_dir=self._resolve_logs_dir(); self.load_manual_state()
        self.build(); self.root.protocol('WM_DELETE_WINDOW',self.on_close)

    def build(self): raise NotImplementedError
    def _app_dir(self):
        if getattr(sys,'frozen',False): return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent
    def _resolve_logs_dir(self):
        preferred=self._app_dir()/'logs'
        try:
            preferred.mkdir(parents=True,exist_ok=True); test=preferred/'.write_test'; test.write_text('ok',encoding='utf-8'); test.unlink(missing_ok=True); return preferred
        except OSError:
            fallback=self.config_dir/'logs'; fallback.mkdir(parents=True,exist_ok=True); return fallback
    def load_manual_state(self):
        try:
            d=json.loads(self.state_path.read_text(encoding='utf-8')); self.manual_ids={int(x) for x in d.get('manual_player_ids',[])}
        except Exception: self.manual_ids=set()
    def save_manual_state(self):
        try:
            tmp=self.state_path.with_suffix('.tmp'); tmp.write_text(json.dumps({'manual_player_ids':sorted(self.manual_ids)},ensure_ascii=False,indent=2),encoding='utf-8'); os.replace(tmp,self.state_path)
        except Exception as exc:
            try: self.status.set(f'Não foi possível gravar estado manual: {exc}')
            except Exception: pass
    def snapshot(self):
        if self.data is None: return
        self.undo.append(bytes(self.data)); self.undo=self.undo[-30:]; self.redo.clear(); self.dirty=True
    def selected_id(self):
        s=self.tree.selection() if hasattr(self,'tree') else ()
        return int(s[0]) if s else None
    def sort_tree(self,tree,column):
        items=[(tree.set(i,column),i) for i in tree.get_children('')]
        reverse=getattr(tree,'_sort_reverse',{}).get(column,False)
        try: items.sort(key=lambda x:int(x[0]),reverse=reverse)
        except (ValueError,TypeError): items.sort(key=lambda x:x[0].casefold(),reverse=reverse)
        tree._sort_reverse=getattr(tree,'_sort_reverse',{}); tree._sort_reverse[column]=not reverse
        for pos,(_,iid) in enumerate(items): tree.move(iid,'',pos)
    def select_player(self,_event=None):
        idx=self.selected_id()
        if idx is None or self.data is None or idx>=len(self.players): return
        p=self.players[idx]; off=p['off']; b=self.data
        from_vals={'name':decode(b[off+PLAYER_NAME_REL:off+PLAYER_NAME_REL+PLAYER_NAME_SIZE]),'shirt':decode(b[off+PLAYER_SHIRT_REL:off+PLAYER_SHIRT_REL+PLAYER_SHIRT_SIZE]),'age':b[off+8],'height':b[off+0x0C],'weight':b[off+0x0D],'nation':u16(b,off+0x0A),'foot':b[off+0x0E],'weak_use':b[off+0x0F],'weak_acc':b[off+0x10],'injury':b[off+0x11]}
        for k,v in from_vals.items(): self.fields[k].set(str(v))
        self.stats.set(','.join(str(x) for x in b[off+0x12:off+0x2C]))
        self.skills.set(','.join(str(x) for x in b[off+0x2C:off+0x34]))
    def apply_player(self):
        idx=self.selected_id()
        if idx is None or self.data is None: return messagebox.showwarning('Selecione','Selecione um jogador.')
        try:
            values={k:v.get().strip() for k,v in self.fields.items()}
            nums={k:int(values[k]) for k in ('age','height','weight','nation','foot','weak_use','weak_acc','injury')}
            stats=[int(x.strip()) for x in self.stats.get().split(',')]
            skills=[int(x.strip()) for x in self.skills.get().split(',')]
            if len(stats)!=26 or len(skills)!=8: raise ValueError('Use exatamente 26 atributos e 8 bytes de habilidades/estilos.')
            if any(x<0 or x>255 for x in stats+skills): raise ValueError('Valores devem ficar entre 0 e 255.')
            self.snapshot(); off=self.players[idx]['off']; b=self.data
            b[off+PLAYER_NAME_REL:off+PLAYER_NAME_REL+PLAYER_NAME_SIZE]=encode(values['name'],PLAYER_NAME_SIZE)
            b[off+PLAYER_SHIRT_REL:off+PLAYER_SHIRT_REL+PLAYER_SHIRT_SIZE]=encode(values['shirt'],PLAYER_SHIRT_SIZE)
            for key,rel in [('age',8),('height',0x0C),('weight',0x0D),('foot',0x0E),('weak_use',0x0F),('weak_acc',0x10),('injury',0x11)]: b[off+rel]=max(0,min(255,nums[key]))
            p16(b,off+0x0A,nums['nation']); b[off+0x12:off+0x2C]=bytes(stats); b[off+0x2C:off+0x34]=bytes(skills)
            self.manual_ids.add(idx); self.save_manual_state(); self.load_tables()
            if self.tree.exists(str(idx)): self.tree.selection_set(str(idx))
            self.status.set('Jogador atualizado em memória. Salve para gravar no arquivo.')
        except Exception as exc: messagebox.showerror('Dados inválidos',str(exc))
    def undo_edit(self):
        if not self.undo or self.data is None: return
        self.redo.append(bytes(self.data)); self.data=bytearray(self.undo.pop()); self.dirty=True; self.load_tables(); self.status.set('Desfeito.')
    def redo_edit(self):
        if not self.redo or self.data is None: return
        self.undo.append(bytes(self.data)); self.data=bytearray(self.redo.pop()); self.dirty=True; self.load_tables(); self.status.set('Refeito.')
    def _atomic_save(self,out_path):
        if self.data is None: raise ValueError('Nenhum data.bin carregado.')
        target=Path(out_path).resolve(); target.parent.mkdir(parents=True,exist_ok=True)
        backup=target.with_name(target.name+'.bak'); tmp_path=None; backup_tmp=None
        try:
            if target.exists():
                fd_bak,backup_tmp=tempfile.mkstemp(prefix=backup.name+'.',suffix='.tmp',dir=str(target.parent)); os.close(fd_bak); shutil.copy2(target,backup_tmp)
            fd,tmp_path=tempfile.mkstemp(prefix=target.name+'.',suffix='.tmp',dir=str(target.parent))
            with os.fdopen(fd,'wb') as f: f.write(self.data); f.flush(); os.fsync(f.fileno())
            check=Path(tmp_path).read_bytes()
            if len(check)!=len(self.data) or hashlib.sha256(check).digest()!=hashlib.sha256(self.data).digest(): raise IOError('Verificação do arquivo temporário falhou.')
            if backup_tmp: os.replace(backup_tmp,backup); backup_tmp=None
            os.replace(tmp_path,target); tmp_path=None
            readback=target.read_bytes()
            if readback!=bytes(self.data):
                if backup.exists(): shutil.copy2(backup,target)
                raise IOError('Verificação após gravação falhou; backup restaurado quando disponível.')
            self.path=str(target); self.dirty=False
            self.status.set(f'Salvo e verificado: {target}')
            messagebox.showinfo('Arquivo salvo',f'Arquivo gravado e verificado.\n\n{target}\n\nBackup: {backup if backup.exists() else "não havia arquivo anterior"}\n\nSe a origem foi um pacote EDIT/STFS, reimporte o data.bin em ferramenta compatível; o editor não reassina nem reempacota o pacote.')
        finally:
            for temp in (tmp_path,backup_tmp):
                if temp and os.path.exists(temp):
                    try: os.unlink(temp)
                    except OSError: pass
    def on_close(self):
        if self.playersdb_thread and self.playersdb_thread.is_alive():
            if not messagebox.askyesno('Download em andamento','O download do PlayersDB ainda está em andamento. Fechar mesmo assim?'): return
        self.root.destroy()
