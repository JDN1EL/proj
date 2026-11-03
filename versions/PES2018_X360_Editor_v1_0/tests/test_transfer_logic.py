import csv, gzip, json, struct, sys, tempfile, unittest, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from transfer_data import load_transfermarkt_files, analyze_roster_updates, apply_roster_plan, match_playersdb_to_transfermarkt, map_transfermarkt_clubs_to_pes, map_national_teams_to_pes
from binary_layout import detect_layout
from editor_core import PLAYER_TABLE_OFFSET, PLAYER_STRIDE, TEAM_TABLE_OFFSET, TEAM_STRIDE, ROSTER_TABLE_OFFSET, ROSTER_STRIDE


def player_entry():
    return {"konami_id":111001,"pes_id":111001,"name":"Player One","full_name":"Player One","fake_name":"FAKE ONE","shirt_names":["ONE"],"fake_shirt_names":[],"birthdate":"1990-01-01","game_versions":["PES 2018"],"nationalities":["Brazil"],"height":180}


def tm_data():
    return {
        "snapshot_date":"2026-07-06",
        "players":[{"player_id":"99","name":"Player One","first_name":"Player","last_name":"One","date_of_birth":"1990-01-01","country_of_citizenship":"Brazil","height_in_cm":180,"current_club_id":"c1","current_national_team_id":"n1"}],
        "clubs":[{"club_id":"c1","name":"Chelsea","country":"England"}],
        "national_teams":[{"national_team_id":"n1","name":"Brazil","country_id":"br","country_name":"Brazil"}],
        "transfers":[]
    }


def make_rosters():
    rosters=[]
    for tid in range(508):
        off=ROSTER_TABLE_OFFSET+tid*ROSTER_STRIDE
        ids=[0]*32; nums=[0]*32
        if tid==55:
            ids[0]=111001; nums[0]=8
            ids[1]=999999 # custom/unknown patch ID; must remain untouched and occupy slot
        rosters.append({"team":tid,"off":off,"ids":ids,"numbers":nums})
    return rosters


def make_teams():
    names={42:"Brasil",55:"Manchester United",57:"Chelsea FC"}
    return [{"id":i,"name":names.get(i,f"Team {i}")} for i in range(508)]


class TestTransferData(unittest.TestCase):
    def test_playersdb_transfermarkt_match_requires_exact_identity(self):
        matched, stats=match_playersdb_to_transfermarkt([player_entry()],tm_data()["players"])
        self.assertEqual(matched[111001]["player_id"],"99")
        bad=tm_data()["players"]+[dict(tm_data()["players"][0],player_id="100",name="Different")]
        matched,stats=match_playersdb_to_transfermarkt([player_entry()],bad)
        self.assertEqual(matched[111001]["player_id"],"99")

    def test_analysis_creates_transfer_and_callup(self):
        report=analyze_roster_updates([{"konami_id":111001,"name":"Player One"}],make_rosters(),make_teams(),[player_entry()],tm_data())
        self.assertEqual(report["stats"]["playersdb_tm_matched"],1)
        self.assertEqual(report["stats"]["planned_transfers"],1)
        self.assertEqual(report["stats"]["planned_callups"],1)
        self.assertEqual([x["operation"] for x in report["plans"]], ["transfer","callup"])

    def test_apply_preserves_unknown_and_selection_when_transfer(self):
        rosters=make_rosters()
        # Set data fixture same as roster records.
        data=bytearray(5_203_344)
        for r in rosters:
            for j,ref in enumerate(r["ids"]): struct.pack_into(">I",data,r["off"]+4+j*4,ref)
        report=analyze_roster_updates([{"konami_id":111001,"name":"Player One"}],rosters,make_teams(),[player_entry()],tm_data())
        out=apply_roster_plan(data,rosters,report["plans"])
        source=rosters[55]; destination=rosters[57]; nation=rosters[42]
        self.assertEqual(struct.unpack_from(">I",out,source["off"]+4)[0],0)
        self.assertEqual(struct.unpack_from(">I",out,source["off"]+8)[0],999999)
        self.assertEqual(struct.unpack_from(">I",out,destination["off"]+4)[0],111001)
        self.assertEqual(struct.unpack_from(">I",out,nation["off"]+4)[0],111001)

    def test_full_destination_rejects_without_partial_result(self):
        rosters=make_rosters(); rosters[57]["ids"]=[x+700000 if x==0 else x for x in range(32)]
        plan=[{"operation":"transfer","konami_id":111001,"from_team_id":55,"to_team_id":57}]
        data=bytearray(5_203_344); before=bytes(data)
        with self.assertRaises(ValueError): apply_roster_plan(data,rosters,plan)
        self.assertEqual(bytes(data),before)

    def test_transfermarkt_csv_gz_import(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            rows={
                "players.csv.gz":[{"player_id":"1","name":"P One","date_of_birth":"1990-01-01","current_club_id":"10","current_national_team_id":"20"}],
                "clubs.csv.gz":[{"club_id":"10","name":"Chelsea"}],
                "national_teams.csv.gz":[{"national_team_id":"20","name":"Brazil","country_name":"Brazil"}],
            }
            files=[]
            for name,data in rows.items():
                path=td/name
                with gzip.open(path,"wt",encoding="utf-8",newline="") as f:
                    w=csv.DictWriter(f,fieldnames=list(data[0])); w.writeheader(); w.writerows(data)
                files.append(path)
            bundle=td/"football-data.zip"
            with zipfile.ZipFile(bundle,"w") as z:
                for p in files: z.write(p,p.name)
            loaded=load_transfermarkt_files([bundle])
            self.assertEqual(len(loaded["players"]),1)
            self.assertEqual(loaded["players"][0]["current_national_team_id"],"20")
            self.assertEqual(len(loaded["clubs"]),1)
            self.assertEqual(len(loaded["national_teams"]),1)


    def test_transfer_allocation_uses_slots_freed_by_accepted_moves(self):
        rosters=make_rosters()
        # Make teams 55 and 57 full. Team 56 has one free slot.
        for tid in (55,57):
            ids=[700000+tid*100+i for i in range(32)]
            rosters[tid]["ids"]=ids
            rosters[tid]["numbers"]=[0]*32
        rosters[55]["ids"][0]=111001
        rosters[57]["ids"][0]=222002
        teams=make_teams(); teams[56]["name"]="Some FC"
        pdb=[player_entry(),dict(player_entry(),konami_id=222002,pes_id=222002,name="Player Two",full_name="Player Two",fake_name="FAKE TWO",birthdate="1991-02-02",height=181)]
        tm=tm_data()
        tm["players"]=[
            dict(tm["players"][0],player_id="99",current_club_id="c1"),
            {"player_id":"100","name":"Player Two","first_name":"Player","last_name":"Two","date_of_birth":"1991-02-02","country_of_citizenship":"Brazil","height_in_cm":181,"current_club_id":"c2","current_national_team_id":""},
        ]
        tm["clubs"]=[{"club_id":"c1","name":"Chelsea"},{"club_id":"c2","name":"Some FC"}]
        # First move waits because Chelsea is full; the next accepted move frees a slot there.
        report=analyze_roster_updates(
            [{"konami_id":111001,"name":"Player One"},{"konami_id":222002,"name":"Player Two"}],
            rosters,teams,pdb,tm,
        )
        moves=[x for x in report["plans"] if x["operation"]=="transfer"]
        self.assertEqual(len(moves),2)
        self.assertEqual({x["konami_id"] for x in moves},{111001,222002})

    def test_apply_accepts_transfer_and_separate_callup_for_same_player(self):
        rosters=make_rosters()
        data=bytearray(5_203_344)
        for r in rosters:
            for j,ref in enumerate(r["ids"]): struct.pack_into(">I",data,r["off"]+4+j*4,ref)
        plan=[
            {"operation":"transfer","konami_id":111001,"from_team_id":55,"to_team_id":57},
            {"operation":"callup","konami_id":111001,"to_team_id":42},
        ]
        out=apply_roster_plan(data,rosters,plan)
        self.assertEqual(struct.unpack_from(">I",out,rosters[55]["off"]+4)[0],0)
        self.assertEqual(struct.unpack_from(">I",out,rosters[57]["off"]+4)[0],111001)
        self.assertEqual(struct.unpack_from(">I",out,rosters[42]["off"]+4)[0],111001)
        # The caller's roster model remains unchanged unless it reloads the data.
        self.assertEqual(rosters[55]["ids"][0],111001)


    def test_historical_name_match_requires_dob_nationality_and_height(self):
        historical=dict(player_entry(),konami_id=222002,pes_id=222002,name="Nome antigo no PES",full_name="Nome antigo no PES",fake_name="NOME FICTICIO",birthdate="1991-02-02",nationalities=["Brazil"],height=181)
        tm=[
            dict(tm_data()["players"][0],player_id="99"),
            {"player_id":"100","name":"Nome moderno do jogador","first_name":"Nome moderno","last_name":"do jogador","date_of_birth":"1991-02-02","country_of_citizenship":"Brazil","height_in_cm":181,"current_club_id":"c1"},
        ]
        matched,stats=match_playersdb_to_transfermarkt([player_entry(),historical],tm)
        self.assertIn(222002,matched)
        self.assertEqual(matched[222002]["_identity_method"],"data_nascimento_nacionalidade_altura")

    def test_configured_historical_alias_is_exact_not_fuzzy(self):
        entry=dict(player_entry(),name="Nome do PES",birthdate="")
        tm=[dict(tm_data()["players"][0],name="Alias PES aprovado",date_of_birth="")]
        matched,stats=match_playersdb_to_transfermarkt([entry],tm,{111001:["Alias PES aprovado"]})
        self.assertIn(111001,matched)
        self.assertEqual(matched[111001]["_identity_method"],"nome_altura")
        matched2,_=match_playersdb_to_transfermarkt([entry],[dict(tm[0],name="Alias PES quase")],{111001:["Alias PES aprovado"]})
        self.assertNotIn(111001,matched2)

    def test_club_and_national_team_maps_use_separate_categories(self):
        teams=make_teams()
        tm={"clubs":[{"club_id":"1","name":"Chelsea"}],
            "national_teams":[{"national_team_id":"42","name":"Brazil","country_name":"Brazil"}]}
        clubs,_=map_transfermarkt_clubs_to_pes(tm,teams,{"57":["Chelsea"]})
        nations=map_national_teams_to_pes(tm,teams,{"42":["Brasil"]})
        self.assertEqual(clubs.get("1"),57)
        self.assertEqual(nations.get("42"),42)

    def test_duplicate_player_ids_block_analysis(self):
        with self.assertRaisesRegex(ValueError,"IDs Konami duplicados"):
            analyze_roster_updates(
                [{"konami_id":111001,"name":"Player One"},{"konami_id":111001,"name":"Player One"}],
                make_rosters(),make_teams(),[player_entry()],tm_data(),
            )

    def test_real_layout_detection(self):
        real=Path('/mnt/data/extracted_EDIT/data.bin')
        if real.exists():
            layout=detect_layout(real.read_bytes())
            self.assertEqual(layout["teams"],508)
            self.assertEqual(layout["rosters"],508)

if __name__=='__main__': unittest.main(verbosity=2)
