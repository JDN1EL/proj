import json, tempfile
from pathlib import Path
from playersdb_local import load_dataset, parse_entry, norm, DownloadLinks

def main():
    e=parse_entry({"PES ID":"123","Player":"João Silva","Position":"CF","Nationality":"Brazil","Height":"180cm","Weight":"75kg","Team Name(s)":"Arsenal, Brazil"})
    assert e["pes_id"]==123 and e["height"]==180 and e["weight"]==75 and e["teams"]==["Arsenal","Brazil"]
    with tempfile.TemporaryDirectory() as d:
        csvp=Path(d)/"players.csv"
        csvp.write_text('PES ID,Player,Position,Nationality,Height,Weight,Strong Foot,Team Name(s)\n123,João Silva,CF,Brazil,180cm,75kg,Right,"Arsenal, Brazil"\n',encoding="utf-8")
        rows=load_dataset(csvp); assert len(rows)==1 and rows[0]["name"]=="João Silva"
        jp=Path(d)/"players.jsonl"; jp.write_text(json.dumps({"pes_id":123,"name":"João Silva","team_names":"Arsenal"},ensure_ascii=False)+"\n",encoding="utf-8")
        rows=load_dataset(jp); assert len(rows)==1 and rows[0]["teams"]==["Arsenal"]
    assert norm("João Silva")==norm("Joao Silva")
    parser=DownloadLinks(); parser.feed('<a href="/export?format=csv">Download CSV</a><a href="/export.jsonl">Download JSONL</a>')
    assert ("csv", "/export?format=csv") in parser.links and ("jsonl", "/export.jsonl") in parser.links
    print("PASS: parser PlayersDB CSV/JSONL, IDs, nomes, altura/peso, vínculos e descoberta de links.")
if __name__=="__main__": main()
