# -*- coding: utf-8 -*-
"""Leitura local do PlayersDB CSV/JSONL. Sem conectores ou APIs de futebol."""
from __future__ import annotations
import csv, gzip, io, json, re, unicodedata, urllib.request
from html.parser import HTMLParser
from pathlib import Path
SITE = "https://playersdb.app/"

def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", "", value)

def _json_list(value):
    if isinstance(value, list): return value
    if not value: return []
    try:
        parsed=json.loads(value)
        return parsed if isinstance(parsed,list) else [parsed]
    except Exception:
        return [x.strip() for x in re.split(r"[;,|]", str(value)) if x.strip()]

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
    req=urllib.request.Request(SITE,headers={"User-Agent":"PES2018-X360-Editor/1.0"})
    with urllib.request.urlopen(req,timeout=timeout) as resp: html=resp.read().decode("utf-8","replace")
    parser=DownloadLinks(); parser.feed(html); out={}
    for kind,href in parser.links:
        if href.startswith("//"): href="https:"+href
        elif href.startswith("/"): href=SITE.rstrip("/")+href
        elif not href.startswith("http"): href=SITE+href
        out.setdefault(kind,href)
    if not out: raise RuntimeError("O site abriu, mas os links CSV/JSONL não foram encontrados automaticamente.")
    return out

def download_latest(folder: Path):
    folder.mkdir(parents=True,exist_ok=True); links=discover_downloads()
    url=links.get("csv") or links.get("jsonl"); ext=".csv" if links.get("csv") else ".jsonl"
    target=folder/("playersdb_latest"+ext); tmp=target.with_suffix(target.suffix+".part")
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"PES2018-X360-Editor/1.0"})
        with urllib.request.urlopen(req,timeout=90) as resp,tmp.open("wb") as f:
            while True:
                chunk=resp.read(1024*1024)
                if not chunk: break
                f.write(chunk)
        if tmp.stat().st_size<1024: raise RuntimeError("Download muito pequeno; pode ser uma página de erro.")
        tmp.replace(target)
    finally: tmp.unlink(missing_ok=True)
    return target

def _int(value):
    m=re.search(r"-?\d+",str(value or "")); return int(m.group()) if m else None

def parse_entry(row):
    # Campos efetivamente presentes no CSV PlayersDB 2026.10.29.
    kid=_int(row.get("konamiID") or row.get("konami_id") or row.get("PES ID") or row.get("Player ID"))
    name=str(row.get("playerName") or row.get("Player") or row.get("name") or "").strip()
    fake=str(row.get("fakeName") or row.get("fake_name") or "").strip()
    fake_shirts=_json_list(row.get("fakeShirtName") or row.get("fake_shirt_name"))
    versions=[str(x).strip() for x in _json_list(row.get("game_versions"))]
    shirts=_json_list(row.get("shirtName") or row.get("shirt_name"))
    return {
        "konami_id":kid,"pes_id":kid,"name":name,"full_name":str(row.get("fullName") or row.get("full_name") or "").strip(),
        "fake_name":fake,"shirt_names":[str(x).strip() for x in shirts if str(x).strip()],
        "fake_shirt_names":[str(x).strip() for x in fake_shirts if str(x).strip()],
        "birthdate":str(row.get("birthdate") or row.get("birth_date") or "").strip(),
        "game_versions":versions,"youth_club":_int(row.get("youthClub")),
        "nationalities":_json_list(row.get("nationalities")),
        "age":_int(row.get("age")),"height":_int(row.get("height")),"weight":_int(row.get("weight")),
        "strong_foot":_int(row.get("strongFoot")),"registered_position":_int(row.get("registeredPosition")),
        # O PlayersDB usado aqui é um índice de identidades/IDs; youthClub NÃO é clube atual.
        "teams":[],
    }

def load_dataset(path: str | Path):
    path=Path(path); entries=[]
    low=path.name.casefold()
    if low.endswith(".jsonl.gz") or low.endswith(".ndjson.gz"):
        opener=lambda: gzip.open(path,"rt",encoding="utf-8-sig")
        with opener() as f:
            for line_no,line in enumerate(f,1):
                if not line.strip(): continue
                try: row=json.loads(line)
                except json.JSONDecodeError as exc: raise ValueError(f"JSONL inválido na linha {line_no}: {exc}")
                if isinstance(row,dict):
                    entry=parse_entry(row)
                    if entry["konami_id"] is not None: entries.append(entry)
    elif low.endswith(".jsonl"):
        with path.open("r",encoding="utf-8-sig") as f:
            for line_no,line in enumerate(f,1):
                if not line.strip(): continue
                try: row=json.loads(line)
                except json.JSONDecodeError as exc: raise ValueError(f"JSONL inválido na linha {line_no}: {exc}")
                if isinstance(row,dict):
                    entry=parse_entry(row)
                    if entry["konami_id"] is not None: entries.append(entry)
    elif low.endswith(".csv.gz"):
        with gzip.open(path,"rt",encoding="utf-8-sig",newline="") as f:
            sample=f.read(8192); f.seek(0)
            try: dialect=csv.Sniffer().sniff(sample,delimiters=",;\t")
            except csv.Error: dialect=csv.excel
            reader=csv.DictReader(f,dialect=dialect)
            if not reader.fieldnames: raise ValueError("CSV sem cabeçalho.")
            for row in reader:
                entry=parse_entry(row)
                if entry["konami_id"] is not None: entries.append(entry)
    elif path.suffix.casefold()==".csv":
        with path.open("r",encoding="utf-8-sig",newline="") as f:
            sample=f.read(8192); f.seek(0)
            try: dialect=csv.Sniffer().sniff(sample,delimiters=",;\t")
            except csv.Error: dialect=csv.excel
            reader=csv.DictReader(f,dialect=dialect)
            if not reader.fieldnames: raise ValueError("CSV sem cabeçalho.")
            for row in reader:
                entry=parse_entry(row)
                if entry["konami_id"] is not None: entries.append(entry)
    else: raise ValueError("Escolha um arquivo .csv, .csv.gz, .jsonl ou .jsonl.gz.")
    if not entries: raise ValueError("Nenhum registro com konamiID foi encontrado. Confira o arquivo PlayersDB.")
    return entries
