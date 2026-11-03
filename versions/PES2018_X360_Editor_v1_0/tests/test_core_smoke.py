import sys, csv, json, tempfile, struct, unittest
from pathlib import Path
from unittest.mock import patch
import tkinter as tk
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pes2018_editor_xbox360_v1_0 import EditorV10, COMPETITION_TABLE_OFFSET, COMPETITION_STRIDE, COMPETITION_NAME_REL
from playersdb_local import load_dataset
from official_names import NATIONAL_TEAM_IDS

PLAYER_TABLE=0x7C; PLAYER_STRIDE=0xBC
TEAM_TABLE=PLAYER_TABLE+21000*PLAYER_STRIDE; TEAM_STRIDE=0x1E0
ROSTER_TABLE=0x46FF54; ROSTER_STRIDE=0xA4

def make_fixture():
    b=bytearray(5_203_344)
    struct.pack_into('>H',b,0x60,2); struct.pack_into('>H',b,0x64,508); struct.pack_into('>H',b,0x70,508)
    for idx,(kid,name) in enumerate([(111001,'PLAYER ONE'),(222002,'PLAYER TWO')]):
        off=PLAYER_TABLE+idx*PLAYER_STRIDE; struct.pack_into('>I',b,off,kid)
        raw=name.encode(); b[off+0x34:off+0x34+len(raw)]=raw
    for tid,alias in [(55,'MAN RED'),(57,'LONDON FC'),(64,'MD WHITE')]:
        off=TEAM_TABLE+tid*TEAM_STRIDE+0x98; raw=alias.encode(); b[off:off+len(raw)]=raw
    # roster 55 starts with player 111001; roster 57 has a free slot.
    r0=ROSTER_TABLE+55*ROSTER_STRIDE; struct.pack_into('>I',b,r0+4,111001); b[r0+0x84]=7
    # valid competition row
    c=COMPETITION_TABLE_OFFSET; struct.pack_into('>H',b,c,9); raw=b'Liga inglesa'; b[c+COMPETITION_NAME_REL:c+COMPETITION_NAME_REL+len(raw)]=raw
    for i in range(1,50): struct.pack_into('>H',b,COMPETITION_TABLE_OFFSET+i*COMPETITION_STRIDE,0xFFFF)
    return b

class TestV10(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk(); self.root.withdraw()
        self.app=EditorV10(self.root)
        self.app.logs_dir=Path(tempfile.mkdtemp(prefix='pes10_logs_'))
        self.app.data=make_fixture(); self.app.path='fixture.bin'; self.app.load_tables()
    def tearDown(self): self.root.destroy()

    def test_ui_and_team_catalog(self):
        self.root.deiconify(); self.root.update_idletasks()
        self.assertEqual(len(self.app.teams),508)
        self.assertEqual(len(self.app.club_tree.get_children()),508)
        self.assertFalse(hasattr(self.app,'team_list'))
        self.assertTrue(self.app.help_frame.winfo_ismapped())
        self.app.team_filter.set('Seleções'); self.app.refresh_club_tab()
        self.assertEqual(len(self.app.club_tree.get_children()),len(NATIONAL_TEAM_IDS))

    def test_official_names_and_undo(self):
        report=self.app.apply_official_names(False)
        self.assertEqual(report['teams'],3)
        self.assertEqual(report['competitions'],1)
        self.assertEqual(self.app.teams[55]['name'],'Manchester United')
        self.assertEqual(self.app.teams[57]['name'],'Chelsea FC')
        self.assertEqual(self.app.teams[64]['name'],'Real Madrid')
        self.assertEqual(self.app.competitions[0]['name'],'Premier League')
        self.app.undo_edit()
        self.assertEqual(self.app.teams[55]['name'],'MAN RED')
        self.assertEqual(self.app.competitions[0]['name'],'Liga inglesa')

    def test_transfer_and_callup_use_32bit_konami_ids(self):
        with patch('pes2018_editor_xbox360_v1_0.simpledialog.askinteger',return_value=18):
            self.assertTrue(self.app._place_player(0,57,True))
        self.assertNotIn(111001,self.app.find_roster(55)['ids'])
        self.assertIn(111001,self.app.find_roster(57)['ids'])
        slot=self.app.find_roster(57)['ids'].index(111001)
        off=self.app.find_roster(57)['off']+4+slot*4
        self.assertEqual(struct.unpack_from('>I',self.app.data,off)[0],111001)
        with patch('pes2018_editor_xbox360_v1_0.simpledialog.askinteger',return_value=7):
            self.assertTrue(self.app._place_player(0,42,False))
        self.assertIn(111001,self.app.find_roster(57)['ids'])
        self.assertIn(111001,self.app.find_roster(42)['ids'])

    def test_copy_team_preserves_roster_header(self):
        from unittest.mock import patch
        from editor_core import ROSTER_TABLE_OFFSET, ROSTER_STRIDE
        # Cabeçalhos são identificadores próprios do registro de destino.
        struct.pack_into('>I',self.app.data,ROSTER_TABLE_OFFSET+55*ROSTER_STRIDE,100)
        struct.pack_into('>I',self.app.data,ROSTER_TABLE_OFFSET+57*ROSTER_STRIDE,102)
        # Copia equipe 55 para a equipe selecionada 57.
        self.app.club_tree.selection_set('57')
        with patch('pes2018_editor_xbox360_v1_0.simpledialog.askinteger',return_value=55):
            self.app.copy_team()
        self.assertEqual(struct.unpack_from('>I',self.app.data,ROSTER_TABLE_OFFSET+57*ROSTER_STRIDE)[0],102)
        self.assertEqual(struct.unpack_from('>I',self.app.data,ROSTER_TABLE_OFFSET+57*ROSTER_STRIDE+4)[0],111001)

    def test_playersdb_real_headers(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'players.csv'
            with p.open('w',encoding='utf-8',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['konamiID','playerName','fakeName','game_versions','youthClub']); w.writeheader()
                w.writerow({'konamiID':'111001','playerName':'Player One','fakeName':'PLAYER ONE','game_versions':'["PES 2018"]','youthClub':'123'})
            entries=load_dataset(p)
            self.assertEqual(entries[0]['konami_id'],111001)
            self.assertEqual(entries[0]['name'],'Player One')
            self.assertIn('PES 2018',entries[0]['game_versions'])

    def test_playersdb_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'players.jsonl'
            p.write_text(json.dumps({"konamiID":222002,"playerName":"Player Two","fakeName":"PLAYER TWO","game_versions":["PES 2018"]})+"\n",encoding='utf-8')
            entries=load_dataset(p)
            self.assertEqual(len(entries),1)
            self.assertEqual(entries[0]['konami_id'],222002)

    def test_playersdb_queue_result(self):
        sample=[{"konami_id":111001,"name":"Player One","fake_name":"PLAYER ONE","game_versions":["PES 2018"],"teams":[]}]
        self.app.sync_queue.put({"type":"playersdb_loaded","path":"players.csv","entries":sample,"automatic":True})
        self.app.playersdb_thread=None
        self.app._poll_playersdb_queue()
        self.assertEqual(len(self.app.playersdb_entries),1)
        self.assertEqual(self.app.playersdb_path,"players.csv")

    def test_logs_created(self):
        self.app._write_log('test_event',{'ok':True})
        self.assertTrue((self.app.logs_dir/'editor_events.jsonl').exists())
        self.assertTrue(list(self.app.logs_dir.glob('*_test_event.txt')))

if __name__=='__main__': unittest.main(verbosity=2)
