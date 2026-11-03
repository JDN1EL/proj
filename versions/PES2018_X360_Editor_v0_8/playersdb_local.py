# -*- coding: utf-8 -*-
"""Importador local de CSV/JSONL do PlayersDB. Não usa APIs de futebol."""
from __future__ import annotations
import csv, json, re, unicodedata, urllib.request
from html.parser import HTMLParser
from pathlib import Path
SITE = "https://playersdb.app/"

def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", "", value)

def keynorm(value): return norm(value).replace("konami", "").replace("pes", "")

class DownloadLinks(HTMLParser):
    def __init__(self): super().__init__(); self.links=[]; self._href=None; self._text=[]
    def handle_starttag(self, tag, attrs):
        if tag.lower()=="a": self._href=dict(attrs).get("href"); self._text=[]
    def handle_data(self, data):
        if self._href is not None: self._text.append(data)
    def handle_endtag(self, tag):
        if tag.lower()=="a" and self._href:
            label=" ".join(self._text).strip().casefold(); href=self._href
            if "csv" in label or href.casefold().endswith(".csv"): self.links.append(("csv",href))
            elif "jsonl" in label or href.casefold().endswith(".jsonl"): self.links.append(("jsonl",href))
            self._href=None

def discover_downloads(timeout=15):
    req=urllib.request.Request(SITE,headers={"User-Agent":"PES2018-X360-Editor/0.8"})
    with urllib.request.urlopen(req,timeout=timeout) as resp: html=resp.read().decode("utf-8","replace")
    parser=DownloadLinks(); parser.feed(html); out={}
    for kind,href in parser.links:
        if href.startswith("//"): href="https:"+href
        elif href.startswith("/"): href=SITE.rstrip("/")+href
        elif not href.startswith("http"): href=SITE+href
        out.setdefault(kind,href)
    if not out: raise RuntimeError("O site abriu, mas os links de CSV/JSONL não foram encontrados automaticamente.")
    return out

def download_latest(folder: Path):
    folder.mkdir(parents=True,exist_ok=True); links=discover_downloads()
    url=links.get("csv") or links.get("jsonl"); ext=".csv" if links.get("csv") else ".jsonl"
    target=folder/("playersdb_latest"+ext); tmp=target.with_suffix(target.suffix+".part")
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"PES2018-X360-Editor/0.8"})
        with urllib.request.urlopen(req,timeout=60) as resp,tmp.open("wb") as f:
            while True:
                chunk=resp.read(1024*1024)
                if not chunk: break
                f.write(chunk)
        if tmp.stat().st_size<1024: raise RuntimeError("Download muito pequeno; pode ser uma página de erro.")
        tmp.replace(target)
    finally: tmp.unlink(missing_ok=True)
    return target

def _pick(row,candidates):
    normalized={keynorm(k):v for k,v in row.items()}
    for candidate in candidates:
        value=normalized.get(keynorm(candidate))
        if value not in (None,"","-"): return str(value).strip()
    return ""

def parse_entry(row):
    pes_id=_pick(row,["PES ID","Konami ID","Player ID","ID","konami_id","pes_id"])
    name=_pick(row,["Player","Player Name","Name","player_name","name"])
    teams=_pick(row,["Team Name(s)","Team Names","Team Name","Teams","team_names","team_name"])
    team_names=[x.strip() for x in re.split(r"\s*[;,|]\s*",teams) if x.strip() and x.strip()!="-"]
    def number(keys):
        m=re.search(r"-?\d+",_pick(row,keys)); return int(m.group()) if m else None
    if isinstance(row.get("Team Name(s)"), (list, tuple)):
        team_names=[str(x).strip() for x in row["Team Name(s)"] if str(x).strip()]
    elif isinstance(row.get("team_names"), (list, tuple)):
        team_names=[str(x).strip() for x in row["team_names"] if str(x).strip()]
    return {"pes_id":int(pes_id) if pes_id.isdigit() else None,"name":name,
            "position":_pick(row,["Position","position"]),"nationality":_pick(row,["Nationality","Country","nationality"]),
            "height":number(["Height","height"]),"weight":number(["Weight","weight"]),"age":number(["Age","age"]),
            "teams":team_names}

def load_dataset(path: str | Path):
    path=Path(path); entries=[]
    if path.suffix.casefold()==".jsonl":
        with path.open("r",encoding="utf-8-sig") as f:
            for line_no,line in enumerate(f,1):
                if not line.strip(): continue
                try: row=json.loads(line)
                except json.JSONDecodeError as exc: raise ValueError(f"JSONL inválido na linha {line_no}: {exc}")
                if isinstance(row,dict):
                    entry=parse_entry(row)
                    if entry["name"]: entries.append(entry)
    elif path.suffix.casefold()==".csv":
        with path.open("r",encoding="utf-8-sig",newline="") as f:
            sample=f.read(8192); f.seek(0)
            try: dialect=csv.Sniffer().sniff(sample,delimiters=",;\t")
            except csv.Error: dialect=csv.excel
            reader=csv.DictReader(f,dialect=dialect)
            if not reader.fieldnames: raise ValueError("CSV sem cabeçalho.")
            for row in reader:
                entry=parse_entry(row)
                if entry["name"]: entries.append(entry)
    else: raise ValueError("Escolha um arquivo .csv ou .jsonl.")
    if not entries: raise ValueError("Nenhum jogador reconhecível foi encontrado. Confira se é o arquivo PlayersDB.")
    return entries
