# PES 2018 Xbox 360 Editor v0.5 - independente
import os, sys, csv, struct, shutil, tempfile, copy, json, unicodedata, re
from api_rosters import fetch_squad, norm
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

PLAYER_COUNT_OFFSET=0x60; TEAM_COUNT_OFFSET=0x64; ROSTER_COUNT_OFFSET=0x70
PLAYER_TABLE_OFFSET=0x7C; PLAYER_STRIDE=0xBC; PLAYER_CAPACITY=21000
TEAM_TABLE_OFFSET=PLAYER_TABLE_OFFSET+PLAYER_CAPACITY*PLAYER_STRIDE
TEAM_STRIDE=0x1E0; ROSTER_TABLE_OFFSET=0x46FF54; ROSTER_STRIDE=0xA4
TACTICS_TABLE_OFFSET=0x488B74; TACTICS_STRIDE=0x274
NAME_OFF=0x34; SHIRT_NAME_OFF=0x62; TEAM_NAME_OFF=0x98; TEAM_SHORT_OFF=0xDE
ROSTER_SLOTS=32

def u16(b,o): return struct.unpack_from('>H',b,o)[0]
def p16(b,o,v): struct.pack_into('>H',b,o,max(0,min(65535,int(v))))
def decode(b): return b.split(b'\0',1)[0].decode('utf-8','replace').strip()
def encode(s,n):
    raw=s.encode('utf-8')[:n]
    return raw+b'\0'*(n-len(raw))

class Editor:
 def __init__(self,root):
  self.root=root; root.title('PES 2018 Xbox 360 Editor v0.6 - APIs'); root.geometry('1180x720')
  self.data=None; self.path=None; self.undo=[]; self.redo=[]; self.players=[]; self.teams=[]; self.rosters=[]
  config_dir=os.path.join(os.environ.get('APPDATA',os.path.expanduser('~')),'PES2018_X360_Editor'); os.makedirs(config_dir,exist_ok=True)
  self.settings_path=os.path.join(config_dir,'api_settings.json'); self.state_path=os.path.join(config_dir,'manual_changes.json'); self.config_dir=config_dir
  self.api_keys={'api_football':'','sportmonks':'','football_data':''}; self.manual_ids=set(); self.aliases={}; self.sync_cursor=0; self.load_api_settings(); self.load_manual_state()
  self.build()
 def build(self):
  bar=ttk.Frame(self.root); bar.pack(fill='x',padx=8,pady=6)
  for label,cmd in [('Abrir data.bin / EDIT',self.open_file),('Salvar',self.save),('APIs / Chaves',self.api_settings),('Atualizar elencos',self.update_squads),('Desfazer',self.undo_edit),('Refazer',self.redo_edit),('Exportar CSV',self.export_csv)]: ttk.Button(bar,text=label,command=cmd).pack(side='left',padx=3)
  self.status=tk.StringVar(value='Abra um data.bin extraído do EDIT00000000.'); ttk.Label(self.root,textvariable=self.status).pack(anchor='w',padx=10)
  panes=ttk.Panedwindow(self.root,orient='horizontal'); panes.pack(fill='both',expand=True,padx=8,pady=8)
  left=ttk.Frame(panes); right=ttk.Frame(panes); panes.add(left,weight=3); panes.add(right,weight=2)
  ttk.Label(left,text='Jogadores').pack(anchor='w')
  sf=ttk.Frame(left); sf.pack(fill='x'); self.search=tk.StringVar(); self.search.trace_add('write',lambda *_:self.refresh_players())
  ttk.Entry(sf,textvariable=self.search).pack(side='left',fill='x',expand=True); ttk.Label(sf,text='Buscar nome / ID').pack(side='right')
  cols=('id','name','team'); self.tree=ttk.Treeview(left,columns=cols,show='headings',selectmode='browse')
  for c,t,w in [('id','ID',70),('name','Jogador',260),('team','Equipe',180)]: self.tree.heading(c,text=t); self.tree.column(c,width=w)
  self.tree.pack(fill='both',expand=True); self.tree.bind('<<TreeviewSelect>>',self.select_player)
  actions=ttk.Frame(left); actions.pack(fill='x',pady=5)
  for t,c in [('Transferir',self.transfer),('Adicionar jogador',self.add_player),('Remover jogador',self.remove_player),('Substituir vaga',self.replace_player)]: ttk.Button(actions,text=t,command=c).pack(side='left',padx=2)
  ttk.Label(right,text='Editor de jogador').pack(anchor='w')
  self.fields={}; form=ttk.Frame(right); form.pack(fill='x')
  fields=[('Nome', 'name'),('Nome da camisa','shirt'),('Idade','age'),('Altura','height'),('Peso','weight'),('Nacionalidade (ID)','nation'),('Pé dominante (byte 0x0E)','foot'),('Uso pé ruim (byte 0x0F)','weak_use'),('Precisão pé ruim (byte 0x10)','weak_acc'),('Resistência lesões (byte 0x11)','injury')]
  for i,(lab,key) in enumerate(fields):
   ttk.Label(form,text=lab).grid(row=i,column=0,sticky='w',pady=2); v=tk.StringVar(); self.fields[key]=v; ttk.Entry(form,textvariable=v,width=24).grid(row=i,column=1,sticky='ew',pady=2)
  ttk.Label(right,text='Atributos técnicos/físicos (bytes 0x12–0x2B)').pack(anchor='w',pady=(12,2))
  self.stats=tk.StringVar(value=''); ttk.Entry(right,textvariable=self.stats).pack(fill='x')
  ttk.Label(right,text='Digite 26 valores separados por vírgula (0–99).').pack(anchor='w')
  ttk.Label(right,text='Habilidades especiais / estilos COM (bytes 0x2C–0x33)').pack(anchor='w',pady=(10,2))
  self.skills=tk.StringVar(); ttk.Entry(right,textvariable=self.skills).pack(fill='x')
  ttk.Button(right,text='Aplicar alterações ao jogador',command=self.apply_player).pack(anchor='e',pady=8)
  ttk.Separator(right).pack(fill='x',pady=8)
  ttk.Label(right,text='Equipes').pack(anchor='w')
  self.team_list=ttk.Treeview(right,columns=('id','name','short'),show='headings',height=7)
  for c,t,w in [('id','ID',50),('name','Equipe',180),('short','Sigla',70)]: self.team_list.heading(c,text=t); self.team_list.column(c,width=w)
  self.team_list.pack(fill='x'); self.team_list.bind('<<TreeviewSelect>>',self.select_team)
  tf=ttk.Frame(right); tf.pack(fill='x',pady=4); self.tname=tk.StringVar(); self.tshort=tk.StringVar()
  ttk.Entry(tf,textvariable=self.tname,width=22).pack(side='left'); ttk.Entry(tf,textvariable=self.tshort,width=6).pack(side='left',padx=3)
  ttk.Button(tf,text='Salvar nome/sigla',command=self.apply_team).pack(side='left')
  ttk.Button(right,text='Copiar elenco + táticas para equipe...',command=self.copy_team).pack(anchor='e',pady=3)
 def load_api_settings(self):
  try:
   d=json.load(open(self.settings_path,encoding='utf-8')); self.api_keys.update(d.get('keys',{})); self.aliases=d.get('aliases',{})
  except Exception: pass
 def save_api_settings(self):
  with open(self.settings_path,'w',encoding='utf-8') as f: json.dump({'keys':self.api_keys,'aliases':self.aliases},f,ensure_ascii=False,indent=2)
 def load_manual_state(self):
  try:
   d=json.load(open(self.state_path,encoding='utf-8')); self.manual_ids=set(d.get('manual_player_ids',[])); self.sync_cursor=int(d.get('sync_cursor',0))
  except Exception:pass
 def save_manual_state(self):
  try:
   with open(self.state_path,'w',encoding='utf-8') as f:json.dump({'manual_player_ids':sorted(self.manual_ids),'sync_cursor':self.sync_cursor},f,ensure_ascii=False,indent=2)
  except Exception:pass
 def api_settings(self):
  win=tk.Toplevel(self.root);win.title('Configuração das APIs');win.transient(self.root);win.grab_set()
  ttk.Label(win,text='Insira suas chaves. Elas ficam salvas localmente neste computador.').grid(row=0,column=0,columnspan=2,padx=10,pady=8,sticky='w')
  vars={}
  for i,(k,label) in enumerate([('api_football','API-Football (x-apisports-key)'),('sportmonks','Sportmonks (api_token)'),('football_data','football-data.org (X-Auth-Token)')],1):
   ttk.Label(win,text=label).grid(row=i,column=0,padx=10,pady=4,sticky='w');v=tk.StringVar(value=self.api_keys.get(k,''));vars[k]=v;ttk.Entry(win,textvariable=v,width=48,show='*').grid(row=i,column=1,padx=10,pady=4)
  ttk.Label(win,text='As chaves são opcionais. Ordem de consulta: API-Football → Sportmonks → football-data.org.').grid(row=4,column=0,columnspan=2,padx=10,pady=6,sticky='w')
  def save():
   self.api_keys={k:v.get().strip() for k,v in vars.items()};self.save_api_settings();win.destroy();messagebox.showinfo('APIs','Chaves salvas localmente.')
  ttk.Button(win,text='Salvar',command=save).grid(row=5,column=1,padx=10,pady=10,sticky='e')
 def team_alias(self,name):
  aliases=self.aliases or {}
  return aliases.get(name,name)
 def update_squads(self):
  if self.data is None:return messagebox.showinfo('Abra o arquivo','Abra primeiro o data.bin do PES 2018.')
  if not any(self.api_keys.values()):
   self.api_settings();
   if not any(self.api_keys.values()):return
  manual_mode='keep'
  if self.manual_ids:
   choice=tk.Toplevel(self.root);choice.title('Preservar alterações manuais');choice.transient(self.root);choice.grab_set();answer=tk.StringVar(value='keep')
   ttk.Label(choice,text=f'Existem {len(self.manual_ids)} jogadores com alterações manuais registradas.').pack(padx=12,pady=8)
   ttk.Radiobutton(choice,text='Deixe-me escolher o que manter (preservar alterações manuais)',variable=answer,value='keep').pack(anchor='w',padx=12)
   ttk.Radiobutton(choice,text='Sim, substituir também as alterações manuais',variable=answer,value='replace').pack(anchor='w',padx=12)
   ttk.Radiobutton(choice,text='Não, ignorar jogadores modificados manualmente',variable=answer,value='skip').pack(anchor='w',padx=12)
   ttk.Button(choice,text='Continuar',command=choice.destroy).pack(pady=10);self.root.wait_window(choice);manual_mode=answer.get()
  # API calls are sequential to respect quotas and allow provider fallback per team.
  import tkinter.messagebox as mb
  self.snapshot(); updated=0; failed=[]; kept=0; provider_counts={}
  batch=self.teams[self.sync_cursor:self.sync_cursor+30]
  if not batch:
   self.sync_cursor=0; batch=self.teams[:30]
  for team in batch:
   alias=self.team_alias(team['name']); roster=self.find_roster(team['id'])
   if not roster: continue
   if manual_mode=='skip' and any(pid in self.manual_ids for pid in roster['ids'] if pid):
    kept+=sum(1 for pid in roster['ids'] if pid in self.manual_ids); continue
   squad,provider,errors=fetch_squad(alias,self.api_keys)
   if not squad:
    failed.append(team['name']+' ('+' | '.join(errors)+')');continue
   ids=[]
   for person in squad:
    nm=(person.get('name') or '').strip()
    if not nm:continue
    existing=next((p for p in self.players if norm(p['name'])==norm(nm) and p['name']),None)
    if existing and existing['id'] in self.manual_ids and manual_mode=='keep':
     # Keep manually changed player in their current club; do not let API transfer override it.
     current=self.team_for(existing['id'])
     if norm(current)==norm(team['name']): ids.append(existing['id'])
     kept+=1; continue
    if existing: pid=existing['id']
    else:
     pid=next((i for i in range(len(self.players)) if not self.players[i]['name']),None)
     if pid is None and len(self.players)<PLAYER_CAPACITY:
      pid=len(self.players); off=PLAYER_TABLE_OFFSET+pid*PLAYER_STRIDE; self.data[off:off+PLAYER_STRIDE]=b'\0'*PLAYER_STRIDE; p16(self.data,PLAYER_COUNT_OFFSET,pid+1); self.load_tables()
     if pid is None: continue
    off=self.players[pid]['off']; self.data[off+NAME_OFF:off+NAME_OFF+46]=encode(nm,46)
    if person.get('age'):
     try:self.data[off+8]=max(15,min(60,int(person['age'])))
     except:pass
    self.players[pid]['name']=nm;ids.append(pid)
   # remove duplicates and fit 32 slots; keep current manual IDs if preserving
   ids=list(dict.fromkeys(ids))[:ROSTER_SLOTS]
   if ids:
    roster['ids']=ids+[0]*(ROSTER_SLOTS-len(ids))
    for j,pid in enumerate(roster['ids']):p16(self.data,roster['off']+4+j*2,pid)
    updated+=1;provider_counts[provider]=provider_counts.get(provider,0)+1
  self.sync_cursor=(self.sync_cursor+len(batch))%max(1,len(self.teams));self.load_tables();self.save_manual_state();self.refresh_players()
  summary=f'Lote processado: {len(batch)} de {len(self.teams)} equipes\nClubes atualizados: {updated}\nAlterações manuais preservadas/ignoradas: {kept}\nFontes: '+', '.join(f'{k}: {v}' for k,v in provider_counts.items())
  if failed:summary+=f'\nClubes sem dados: {len(failed)} (consulte api_sync_log.txt)'
  try:open(os.path.join(self.config_dir,'api_sync_log.txt'),'w',encoding='utf-8').write('\n'.join(failed))
  except:pass
  self.status.set(summary.replace('\n',' | '));mb.showinfo('Atualização de elencos',summary+'\n\nClique novamente em Atualizar elencos para processar o próximo lote. Confira os elencos antes de salvar.')

 def snapshot(self): self.undo.append(bytes(self.data)); self.undo=self.undo[-30:]; self.redo.clear()
 def open_file(self):
  p=filedialog.askopenfilename(filetypes=[('PES data.bin / EDIT','*'),('Todos','*.*')])
  if not p:return
  try:
   raw=open(p,'rb').read()
   if raw[:4] in (b'CON ',b'LIVE',b'PIRS'):
    messagebox.showinfo('Pacote STFS','Este arquivo é um pacote STFS. Extraia o data.bin do EDIT00000000 com uma ferramenta STFS e abra o data.bin aqui. Esta versão não reempacota nem reassina CON/LIVE/PIRS.')
    return
   if len(raw)<ROSTER_TABLE_OFFSET+ROSTER_STRIDE: raise ValueError('Arquivo pequeno demais para o layout PES 2018 Xbox 360.')
   self.data=bytearray(raw); self.path=p; self.undo.clear(); self.redo.clear(); self.load_tables(); self.status.set(f'{os.path.basename(p)} | {len(raw):,} bytes | {len(self.players)} jogadores | {len(self.teams)} equipes')
   if messagebox.askyesno('Atualizar elencos','Deseja consultar as APIs e atualizar os elencos agora?\n\nSe nenhuma API responder, o editor continuará sem atualizar.'):
    self.update_squads()
  except Exception as e: messagebox.showerror('Erro ao abrir',str(e))
 def load_tables(self):
  b=self.data; pc=min(u16(b,PLAYER_COUNT_OFFSET),PLAYER_CAPACITY); tc=min(u16(b,TEAM_COUNT_OFFSET),2048); rc=min(u16(b,ROSTER_COUNT_OFFSET),4096)
  self.players=[]
  for i in range(pc):
   o=PLAYER_TABLE_OFFSET+i*PLAYER_STRIDE
   self.players.append({'id':i,'off':o,'name':decode(b[o+NAME_OFF:o+NAME_OFF+46])})
  self.teams=[]
  for i in range(tc):
   o=TEAM_TABLE_OFFSET+i*TEAM_STRIDE
   self.teams.append({'id':i,'off':o,'name':decode(b[o+TEAM_NAME_OFF:o+TEAM_NAME_OFF+70]),'short':decode(b[o+TEAM_SHORT_OFF:o+TEAM_SHORT_OFF+3])})
  self.rosters=[]
  for i in range(rc):
   o=ROSTER_TABLE_OFFSET+i*ROSTER_STRIDE
   ids=[u16(b,o+4+j*2) for j in range(ROSTER_SLOTS)]
   self.rosters.append({'team':i,'off':o,'ids':ids})
  self.refresh_players(); self.refresh_teams()
 def team_for(self,pid):
  for r in self.rosters:
   if pid in r['ids']: return self.teams[r['team']]['name'] if r['team']<len(self.teams) else str(r['team'])
  return 'Sem equipe'
 def refresh_players(self):
  if not self.data:return
  q=self.search.get().lower(); self.tree.delete(*self.tree.get_children())
  for p in self.players:
   if q and q not in p['name'].lower() and q not in str(p['id']):continue
   self.tree.insert('', 'end',iid=str(p['id']),values=(p['id'],p['name'],self.team_for(p['id'])))
 def refresh_teams(self):
  self.team_list.delete(*self.team_list.get_children())
  for t in self.teams:self.team_list.insert('','end',iid=str(t['id']),values=(t['id'],t['name'],t['short']))
 def selected_id(self):
  s=self.tree.selection(); return int(s[0]) if s else None
 def select_player(self,_=None):
  pid=self.selected_id()
  if pid is None:return
  p=self.players[pid]; o=p['off']; b=self.data
  vals={'name':decode(b[o+NAME_OFF:o+NAME_OFF+46]),'shirt':decode(b[o+SHIRT_NAME_OFF:o+SHIRT_NAME_OFF+18]),'age':b[o+8],'height':b[o+0x0C],'weight':b[o+0x0D],'nation':u16(b,o+0x0A),'foot':b[o+0x0E],'weak_use':b[o+0x0F],'weak_acc':b[o+0x10],'injury':b[o+0x11]}
  for k,v in vals.items():self.fields[k].set(str(v))
  self.stats.set(','.join(str(x) for x in b[o+0x12:o+0x2C])); self.skills.set(','.join(str(x) for x in b[o+0x2C:o+0x34]))
 def apply_player(self):
  pid=self.selected_id()
  if pid is None:return messagebox.showwarning('Selecione','Selecione um jogador.')
  try:
   v={k:x.get() for k,x in self.fields.items()}; nums={k:int(v[k]) for k in ('age','height','weight','nation','foot','weak_use','weak_acc','injury')}
   stats=[int(x.strip()) for x in self.stats.get().split(',')]; skills=[int(x.strip()) for x in self.skills.get().split(',')]
   if len(stats)!=26 or len(skills)!=8:raise ValueError('Use exatamente 26 atributos e 8 bytes de habilidades/estilos.')
   if any(x<0 or x>255 for x in stats+skills):raise ValueError('Valores de bytes devem ficar entre 0 e 255.')
   self.snapshot(); o=self.players[pid]['off']; b=self.data
   b[o+NAME_OFF:o+NAME_OFF+46]=encode(v['name'],46); b[o+SHIRT_NAME_OFF:o+SHIRT_NAME_OFF+18]=encode(v['shirt'],18)
   for k,off in [('age',8),('height',0x0C),('weight',0x0D),('foot',0x0E),('weak_use',0x0F),('weak_acc',0x10),('injury',0x11)]:b[o+off]=max(0,min(255,nums[k]))
   p16(b,o+0x0A,nums['nation']); b[o+0x12:o+0x2C]=bytes(stats); b[o+0x2C:o+0x34]=bytes(skills)
   self.players[pid]['name']=v['name']; self.manual_ids.add(pid); self.save_manual_state(); self.refresh_players(); self.tree.selection_set(str(pid)); self.status.set('Jogador atualizado em memória. Salve para gravar no arquivo.')
  except Exception as e:messagebox.showerror('Dados inválidos',str(e))
 def selected_team(self):
  s=self.team_list.selection(); return int(s[0]) if s else None
 def select_team(self,_=None):
  i=self.selected_team()
  if i is not None:self.tname.set(self.teams[i]['name']);self.tshort.set(self.teams[i]['short'])
 def apply_team(self):
  i=self.selected_team()
  if i is None:return
  self.snapshot(); t=self.teams[i]; o=t['off']; self.data[o+TEAM_NAME_OFF:o+TEAM_NAME_OFF+70]=encode(self.tname.get(),70); self.data[o+TEAM_SHORT_OFF:o+TEAM_SHORT_OFF+3]=encode(self.tshort.get(),3)
  t['name']=self.tname.get();t['short']=self.tshort.get();self.refresh_teams();self.refresh_players();self.status.set('Equipe atualizada em memória.')
 def find_roster(self,team):
  return next((r for r in self.rosters if r['team']==team),None)
 def transfer(self):
  pid=self.selected_id()
  if pid is None:return
  dest=simpledialog.askinteger('Transferir','ID da equipe de destino (veja a lista Equipes):',minvalue=0,maxvalue=max(0,len(self.teams)-1))
  if dest is None:return
  rdest=self.find_roster(dest)
  if not rdest:return messagebox.showerror('Elenco','Não foi encontrado registro de elenco para essa equipe.')
  self.snapshot(); self.manual_ids.add(pid); self.save_manual_state()
  for r in self.rosters:
   if pid in r['ids']:
    j=r['ids'].index(pid);r['ids'][j]=0;p16(self.data,r['off']+4+j*2,0)
  try:j=rdest['ids'].index(0)
  except ValueError:return messagebox.showerror('Elenco cheio','A equipe de destino não tem vaga livre.')
  rdest['ids'][j]=pid;p16(self.data,rdest['off']+4+j*2,pid);self.refresh_players();self.status.set('Transferência aplicada em memória e marcada como alteração manual.')
 def add_player(self):
  name=simpledialog.askstring('Novo jogador','Nome do jogador:')
  if not name:return
  # Usa primeiro registro de jogador vazio após o contador, sem aumentar tabelas de forma especulativa.
  pid=len(self.players)
  if pid>=PLAYER_CAPACITY:return messagebox.showerror('Limite','Capacidade de jogadores atingida.')
  self.snapshot();self.manual_ids.add(pid);self.save_manual_state();o=PLAYER_TABLE_OFFSET+pid*PLAYER_STRIDE;self.data[o:o+PLAYER_STRIDE]=b'\0'*PLAYER_STRIDE;self.data[o+NAME_OFF:o+NAME_OFF+46]=encode(name,46);p16(self.data,PLAYER_COUNT_OFFSET,pid+1)
  self.load_tables();self.tree.selection_set(str(pid));self.status.set('Novo registro criado. Complete os campos e salve.')
 def remove_player(self):
  pid=self.selected_id()
  if pid is None:return
  if not messagebox.askyesno('Remover','Remover o jogador dos elencos e zerar seu registro?'):return
  self.snapshot();self.manual_ids.add(pid);self.save_manual_state();
  for r in self.rosters:
   for j,x in enumerate(r['ids']):
    if x==pid:r['ids'][j]=0;p16(self.data,r['off']+4+j*2,0)
  o=self.players[pid]['off'];self.data[o:o+PLAYER_STRIDE]=b'\0'*PLAYER_STRIDE
  self.status.set('Registro zerado e removido dos elencos. O índice/contador não é compactado para preservar IDs.')
  self.load_tables()
 def replace_player(self):
  pid=self.selected_id()
  if pid is None:return
  old=simpledialog.askinteger('Substituir vaga','ID do jogador que será substituído:',minvalue=0)
  if old is None:return
  self.snapshot();self.manual_ids.add(pid);self.save_manual_state();found=False
  for r in self.rosters:
   for j,x in enumerate(r['ids']):
    if x==old:r['ids'][j]=pid;p16(self.data,r['off']+4+j*2,pid);found=True
  if not found:messagebox.showinfo('Não encontrado','O ID informado não aparece nos elencos carregados.')
  self.refresh_players()
 def copy_team(self):
  dest=self.selected_team()
  if dest is None:return messagebox.showinfo('Equipe','Selecione a equipe de destino na lista.')
  src=simpledialog.askinteger('Copiar equipe','ID da equipe de origem:')
  if src is None or src==dest:return
  a=self.find_roster(src);b=self.find_roster(dest)
  if not a or not b:return messagebox.showerror('Elenco','Registro de elenco não encontrado.')
  self.snapshot();b['ids']=list(a['ids']);self.data[b['off']:b['off']+ROSTER_STRIDE]=self.data[a['off']:a['off']+ROSTER_STRIDE]
  if src<len(self.teams) and dest<len(self.teams):
   oa=TACTICS_TABLE_OFFSET+src*TACTICS_STRIDE;ob=TACTICS_TABLE_OFFSET+dest*TACTICS_STRIDE
   if ob+TACTICS_STRIDE<=len(self.data) and oa+TACTICS_STRIDE<=len(self.data):self.data[ob:ob+TACTICS_STRIDE]=self.data[oa:oa+TACTICS_STRIDE]
  self.refresh_players();self.status.set('Elenco e bloco de táticas copiados em memória.')
 def undo_edit(self):
  if not self.undo:return
  self.redo.append(bytes(self.data));self.data=bytearray(self.undo.pop());self.load_tables();self.status.set('Desfeito.')
 def redo_edit(self):
  if not self.redo:return
  self.undo.append(bytes(self.data));self.data=bytearray(self.redo.pop());self.load_tables();self.status.set('Refeito.')
 def save(self):
  if self.data is None:return
  p=self.path or filedialog.asksaveasfilename(defaultextension='.bin',filetypes=[('BIN','*.bin')])
  if not p:return
  try:
   if os.path.exists(p):shutil.copy2(p,p+'.bak')
   fd,tmp=tempfile.mkstemp(prefix='pes2018_',suffix='.tmp',dir=os.path.dirname(os.path.abspath(p)))
   with os.fdopen(fd,'wb') as f:f.write(self.data);f.flush();os.fsync(f.fileno())
   os.replace(tmp,p);self.path=p;self.status.set('Salvo com segurança. Backup .bak criado quando já existia arquivo.')
  except Exception as e:messagebox.showerror('Erro ao salvar',str(e))
 def export_csv(self):
  if self.data is None:return
  p=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')])
  if not p:return
  with open(p,'w',newline='',encoding='utf-8-sig') as f:
   w=csv.writer(f,delimiter=';');w.writerow(['ID','Jogador','Equipe'])
   for x in self.players:w.writerow([x['id'],x['name'],self.team_for(x['id'])])
  self.status.set('CSV exportado.')

if __name__=='__main__':
 root=tk.Tk(); app=Editor(root); root.mainloop()
