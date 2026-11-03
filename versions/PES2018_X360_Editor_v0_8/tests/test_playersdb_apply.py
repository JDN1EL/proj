import struct
import pes2018_editor_xbox360_v0_8 as app

class Dummy:
    pass

def main():
    ask=app.messagebox.askyesno
    app.messagebox.askyesno=lambda *a,**k: True
    try:
        e=app.Editor.__new__(app.Editor)
        size=app.ROSTER_TABLE_OFFSET+app.ROSTER_STRIDE+64
        e.data=bytearray(size); e.dirty=False; e.undo=[]; e.redo=[]
        struct.pack_into('>H',e.data,app.PLAYER_COUNT_OFFSET,18)
        struct.pack_into('>H',e.data,app.TEAM_COUNT_OFFSET,1)
        struct.pack_into('>H',e.data,app.ROSTER_COUNT_OFFSET,1)
        teamoff=app.TEAM_TABLE_OFFSET
        e.teams=[{'id':0,'off':teamoff,'name':'NORTH LONDON','short':'NLO'}]
        e.data[teamoff+app.TEAM_NAME_REL:teamoff+app.TEAM_NAME_REL+app.TEAM_NAME_SIZE]=app.encode('NORTH LONDON',app.TEAM_NAME_SIZE)
        players=[]
        for pid in range(18):
            off=app.PLAYER_TABLE_OFFSET+pid*app.PLAYER_STRIDE
            name=f'Player {pid}' if pid>=10 else f'Other {pid}'
            e.data[off+app.PLAYER_NAME_REL:off+app.PLAYER_NAME_REL+app.PLAYER_NAME_SIZE]=app.encode(name,app.PLAYER_NAME_SIZE)
            players.append({'id':pid,'off':off,'name':name})
        e.players=players
        roff=app.ROSTER_TABLE_OFFSET
        ids=list(range(10,18))+[0]*24
        for i,pid in enumerate(ids): struct.pack_into('>H',e.data,roff+app.ROSTER_PLAYER_REL+i*2,pid)
        e.rosters=[{'team':0,'off':roff,'ids':ids,'numbers':[0]*32}]
        e.playersdb_entries=[{'pes_id':pid,'name':f'Player {pid}','teams':['Arsenal FC'],'age':22,'height':180,'weight':75,'position':'CMF','nationality':'England'} for pid in range(10,19)]
        e.find_roster=lambda tid: next((r for r in e.rosters if r['team']==tid),None)
        e.load_tables=lambda: None
        e.snapshot=app.Editor.snapshot.__get__(e,app.Editor)
        report=app.Editor.apply_playersdb_names_and_squads(e)
        assert report['team_names']==1 and report['rosters']==1 and report['new_records']==1
        assert app.decode(e.data[teamoff+app.TEAM_NAME_REL:teamoff+app.TEAM_NAME_REL+app.TEAM_NAME_SIZE])=='Arsenal FC'
        assert e.rosters[0]['ids'][8]==18
        off=app.PLAYER_TABLE_OFFSET+18*app.PLAYER_STRIDE
        assert app.decode(e.data[off+app.PLAYER_NAME_REL:off+app.PLAYER_NAME_REL+app.PLAYER_NAME_SIZE])=='Player 18'
        print('PASS: associação por ID PES, renomeação segura de clube, preenchimento de registro vazio e elenco local.')
    finally:
        app.messagebox.askyesno=ask

if __name__=='__main__': main()
