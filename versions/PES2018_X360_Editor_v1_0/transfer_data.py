# -*- coding: utf-8 -*-
"""Dados estáticos de futebol e associação conservadora para PES 2018 X360.
Sem APIs. O snapshot Transfermarkt publicado neste pacote é de 2026-07-06.
"""
from __future__ import annotations
import csv, gzip, io, json, re, unicodedata, urllib.request, zipfile
from pathlib import Path
from datetime import date
from difflib import SequenceMatcher

SNAPSHOT_DATE = "2026-07-06"
DATASET_HOME = "https://github.com/dcaribou/transfermarkt-datasets"
STATIC_ROOT = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/"
FILES = {
    "players": "players.csv.gz",
    "clubs": "clubs.csv.gz",
    "national_teams": "national_teams.csv.gz",
    "transfers": "transfers.csv.gz",
}


def norm(value):
    s = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().casefold()
    s = re.sub(r"\b(football club|football|club|futbol club|futebol clube|fc|cf|afc|sc|ac|calcio|cfc|ssc|sv|fk|sk|as|rc|ud|cd|sd|real)\b", " ", s)
    s = re.sub(r"\b(de|da|do|del|la|el|the|of|and|y)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def _text(value):
    return str(value or "").strip()


def _int(value):
    m = re.search(r"-?\d+", _text(value))
    return int(m.group()) if m else None


def _date(value):
    v = _text(value)
    if not v:
        return ""
    # Transfermarkt export uses YYYY-MM-DD; PlayersDB also has ISO dates.
    if "T" in v:
        v = v.split("T", 1)[0]
    if len(v) >= 10 and v[4:5] == "-":
        return v[:10]
    for fmt in ("%d/%m/%Y", "%Y/%m/%d"):
        try:
            from datetime import datetime
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def _read_csv(path):
    p = Path(path)
    raw = p.open("rb")
    try:
        if p.suffix.lower() == ".gz" or p.name.lower().endswith(".csv.gz"):
            stream = gzip.GzipFile(fileobj=raw, mode="rb")
        else:
            stream = raw
        text = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")
        sample = text.read(8192); text.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(text, dialect=dialect)
        if not reader.fieldnames:
            raise ValueError(f"CSV sem cabeçalho: {p.name}")
        return reader
    except Exception:
        raw.close()
        raise


def load_transfermarkt_files(paths):
    """Load local .csv/.csv.gz or a ZIP containing players/clubs/national_teams CSVs."""
    paths = [Path(p) for p in paths]
    found = {}
    for p in paths:
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as zf:
                for name in zf.namelist():
                    low = Path(name).name.lower()
                    for key in FILES:
                        if low == FILES[key] or low == FILES[key].removesuffix(".gz"):
                            found[key] = (p, name)
        else:
            low = p.name.lower()
            for key in FILES:
                if low == FILES[key] or low == FILES[key].removesuffix(".gz"):
                    found[key] = p
    missing = [x for x in ("players", "clubs") if x not in found]
    if missing:
        raise ValueError("Faltam os arquivos obrigatórios: " + ", ".join(missing) + ". Selecione players.csv(.gz) e clubs.csv(.gz).")

    def rows(source):
        if isinstance(source, tuple):
            zpath, member = source
            with zipfile.ZipFile(zpath) as zf:
                data = zf.read(member)
            if member.lower().endswith(".gz"):
                data = gzip.decompress(data)
            text = io.StringIO(data.decode("utf-8-sig"))
            sample = text.read(8192); text.seek(0)
            try: dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error: dialect = csv.excel
            reader = csv.DictReader(text, dialect=dialect)
            return list(reader)
        return list(_read_csv(source))

    data = {k: rows(v) for k, v in found.items()}
    player_headers = {str(x).strip() for x in (data["players"][0].keys() if data["players"] else [])}
    club_headers = {str(x).strip() for x in (data["clubs"][0].keys() if data["clubs"] else [])}
    if not {"player_id", "name", "current_club_id"}.issubset(player_headers):
        raise ValueError("players.csv não tem o esquema esperado: requer player_id, name e current_club_id. Não use um CSV de outra tabela como base de elenco.")
    if not {"club_id", "name"}.issubset(club_headers):
        raise ValueError("clubs.csv não tem o esquema esperado: requer club_id e name.")
    players = []
    for r in data["players"]:
        pid = _text(r.get("player_id") or r.get("id"))
        name = _text(r.get("name") or r.get("player_name"))
        if not pid or not name:
            continue
        players.append({
            "player_id": pid,
            "name": name,
            "first_name": _text(r.get("first_name")),
            "last_name": _text(r.get("last_name")),
            "date_of_birth": _date(r.get("date_of_birth")),
            "country_of_citizenship": _text(r.get("country_of_citizenship")),
            "height_in_cm": _int(r.get("height_in_cm")),
            "position": _text(r.get("position")),
            "foot": _text(r.get("foot")),
            "current_club_id": _text(r.get("current_club_id")),
            "current_national_team_id": _text(r.get("current_national_team_id")),
            "current_club_name": _text(r.get("current_club_name")),
        })
    clubs = []
    for r in data["clubs"]:
        cid = _text(r.get("club_id") or r.get("id"))
        name = _text(r.get("name") or r.get("club_name"))
        if cid and name:
            clubs.append({"club_id": cid, "name": name, "country": _text(r.get("domestic_competition_name") or r.get("country_name"))})
    nations = []
    for r in data.get("national_teams", []):
        nid = _text(r.get("national_team_id") or r.get("id"))
        name = _text(r.get("name") or r.get("national_team_name") or r.get("country_name"))
        if nid and name:
            nations.append({"national_team_id": nid, "name": name, "country_id": _text(r.get("country_id")), "country_name": _text(r.get("country_name"))})
    transfers = []
    for r in data.get("transfers", []):
        pid = _text(r.get("player_id"))
        if pid:
            transfers.append({"player_id": pid, "date": _date(r.get("transfer_date") or r.get("date") or r.get("date_unformatted")), "from": _text(r.get("from_club_name")), "to": _text(r.get("to_club_name"))})
    return {
        "players": players, "clubs": clubs, "national_teams": nations, "transfers": transfers,
        "snapshot_date": SNAPSHOT_DATE, "loaded_files": [Path(p).name for p in paths],
        "has_national_assignment": any(p.get("current_national_team_id") for p in players),
    }


def download_transfermarkt(folder, progress=None, timeout=90):
    """Download static CSV.GZ files; players and clubs are required, others optional."""
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    targets = []
    required = {"players", "clubs"}
    errors = []
    for key in ("players", "clubs", "national_teams", "transfers"):
        name = FILES[key]
        target = folder / name
        if target.exists() and target.stat().st_size > 1024:
            targets.append(target)
            continue
        url = STATIC_ROOT + name
        tmp = target.with_suffix(target.suffix + ".part")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PES2018-X360-Editor/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open("wb") as out:
                total = int(resp.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk: break
                    out.write(chunk); got += len(chunk)
                    if progress: progress(key, got, total)
            if tmp.stat().st_size < 128:
                raise RuntimeError(f"Download de {name} retornou arquivo pequeno demais.")
            with gzip.open(tmp, "rb") as gz:
                gz.read(64)
            tmp.replace(target); targets.append(target)
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            if key in required:
                raise RuntimeError("Não foi possível baixar a base obrigatória: " + "; ".join(errors)) from exc
        finally:
            tmp.unlink(missing_ok=True)
    # Optional national-team / transfer files may be absent; the editor still
    # loads club assignments from players.csv.gz + clubs.csv.gz.
    return targets

def _birth_from_pdb(entry):
    return _date(entry.get("birthdate"))


def _entry_aliases(entry):
    vals = [entry.get("name"), entry.get("full_name"), entry.get("fake_name")]
    vals += entry.get("shirt_names", []) or []
    vals += entry.get("fake_shirt_names", []) or []
    aliases = {norm(v) for v in vals if norm(v)}
    # Algumas bases PES escrevem sobrenome antes do nome (ex.: Endo Yasuhito).
    for value in vals:
        words = _text(value).split()
        if len(words) == 2 and all(len(w) > 1 for w in words):
            aliases.add(norm(" ".join(reversed(words))))
    return aliases


def match_playersdb_to_transfermarkt(playersdb_entries, tm_players, player_aliases=None):
    """Map Konami IDs to Transfermarkt rows using strong identity evidence.

    Pass 1: exact canonical/full/fake name + DOB, or exact name + height when DOB
    is missing. Pass 2: for changed/abbreviated historical display names, exact DOB
    + PDB nationality code mapped from unambiguous pass-1 identities + height.
    No global fuzzy-name matching is used.
    """
    player_aliases = player_aliases or {}
    by_dob = {}
    by_name = {}
    for tm in tm_players:
        primary = tm.get("name") or (tm.get("first_name", "") + " " + tm.get("last_name", "")).strip()
        alias = norm(primary)
        if alias:
            by_name.setdefault(alias, []).append(tm)
        if tm.get("date_of_birth"):
            by_dob.setdefault(tm["date_of_birth"], []).append(tm)

    pdb_by_id, duplicate_pdb = {}, set()
    for e in playersdb_entries:
        kid = e.get("konami_id")
        if not kid or "PES 2018" not in (e.get("game_versions") or []):
            continue
        kid = int(kid)
        if kid in pdb_by_id:
            old = pdb_by_id[kid]
            same = (_birth_from_pdb(old) == _birth_from_pdb(e) and norm(old.get("name")) == norm(e.get("name")))
            if not same:
                duplicate_pdb.add(kid)
        else:
            pdb_by_id[kid] = e

    matched, match_methods = {}, {}
    ambiguous_ids, unmatched_ids, pending = set(), set(), []
    # First pass: exact names/aliases.
    for kid, e in pdb_by_id.items():
        if kid in duplicate_pdb:
            ambiguous_ids.add(kid)
            continue
        aliases = _entry_aliases(e)
        aliases.update(norm(x) for x in player_aliases.get(kid, player_aliases.get(str(kid), [])) if norm(x))
        birth = _birth_from_pdb(e)
        candidates = list(by_dob.get(birth, [])) if birth else []
        if not birth:
            for alias in aliases:
                candidates.extend(by_name.get(alias, []))
        candidates = [c for c in candidates if norm(c.get("name") or (c.get("first_name", "") + " " + c.get("last_name", "")).strip()) in aliases]
        if birth:
            candidates = [c for c in candidates if c.get("date_of_birth") == birth]
        if len(candidates) > 1 and e.get("height"):
            candidates = [c for c in candidates if c.get("height_in_cm") and abs(int(c["height_in_cm"]) - int(e["height"])) <= 3]
        if not birth:
            # Without DOB, exact name must also be corroborated by height.
            candidates = [c for c in candidates if e.get("height") and c.get("height_in_cm") and abs(int(c["height_in_cm"]) - int(e["height"])) <= 2]
        if len(candidates) == 1:
            matched[kid] = candidates[0]
            match_methods[kid] = "nome_data_nascimento" if birth else "nome_altura"
        elif len(candidates) > 1:
            ambiguous_ids.add(kid)
        elif birth:
            pending.append((kid, e, aliases, birth))
        else:
            unmatched_ids.add(kid)

    # Infer PDB nationality-code -> Transfermarkt citizenship only from unique
    # exact-name+birthdate matches where PlayersDB shows a single nationality.
    nation_code_map = {}
    for kid, tm in matched.items():
        entry = pdb_by_id[kid]
        codes = entry.get("nationalities") or []
        if len(codes) == 1 and tm.get("country_of_citizenship"):
            nation_code_map.setdefault(str(codes[0]), set()).add(norm(tm["country_of_citizenship"]))

    # Second pass: recover cases where PES 2018 uses an old/abbreviated display
    # name that no longer appears in Transfermarkt, without fuzzy matching.
    for kid, e, aliases, birth in pending:
        candidates = list(by_dob.get(birth, []))
        codes = [str(x) for x in (e.get("nationalities") or [])]
        countries = set().union(*(nation_code_map.get(code, set()) for code in codes)) if codes else set()
        if countries:
            candidates = [c for c in candidates if norm(c.get("country_of_citizenship")) in countries]
        if e.get("height"):
            candidates = [c for c in candidates if c.get("height_in_cm") and abs(int(c["height_in_cm"]) - int(e["height"])) <= 2]
        else:
            candidates = []
        if len(candidates) == 1 and countries:
            matched[kid] = candidates[0]
            match_methods[kid] = "data_nascimento_nacionalidade_altura"
        elif len(candidates) > 1:
            ambiguous_ids.add(kid)
        else:
            unmatched_ids.add(kid)

    # Annotate results without changing source values.
    for kid, method in match_methods.items():
        matched[kid] = dict(matched[kid], _identity_method=method)
    stats = {
        "matched": len(matched), "ambiguous": len(ambiguous_ids), "unmatched": len(unmatched_ids),
        "duplicate_konami_ids": len(duplicate_pdb), "pdb_pes2018_rows": len(pdb_by_id),
        "matched_exact_name_dob": sum(1 for m in match_methods.values() if m == "nome_data_nascimento"),
        "matched_exact_name_height": sum(1 for m in match_methods.values() if m == "nome_altura"),
        "matched_historical_identity": sum(1 for m in match_methods.values() if m == "data_nascimento_nacionalidade_altura"),
    }
    return matched, stats

def build_club_index(tm_data):
    by_id = {str(c["club_id"]): c for c in tm_data.get("clubs", [])}
    return by_id


def map_transfermarkt_clubs_to_pes(tm_data, pes_teams, extra_aliases=None):
    """Map only exact normalized team names / configured aliases."""
    extra_aliases = extra_aliases or {}
    pes_by_name = {}
    for t in pes_teams:
        if not _is_club_id(int(t["id"])):
            continue
        for nm in [t.get("name"), *extra_aliases.get(str(t.get("id")), [])]:
            n = norm(nm)
            if n:
                pes_by_name.setdefault(n, []).append(int(t["id"]))
    result, ambiguous = {}, 0
    for c in tm_data.get("clubs", []):
        n = norm(c.get("name"))
        ids = list(dict.fromkeys(pes_by_name.get(n, [])))
        if len(ids) == 1:
            result[str(c["club_id"])] = ids[0]
        elif len(ids) > 1:
            ambiguous += 1
    return result, ambiguous


def _nation_variants(name):
    n = norm(name)
    aliases = {
        "brazil": ["Brasil"], "brasil": ["Brazil"], "england": ["Inglaterra"],
        "scotland": ["Escócia"], "wales": ["País de Gales", "Gales"],
        "northernireland": ["Irlanda do Norte"], "ireland": ["República da Irlanda", "Eire"],
        "southkorea": ["Coreia do Sul", "Korea Republic"], "korearepublic": ["Coreia do Sul", "South Korea"],
        "iran": ["Irã"], "unitedstates": ["Estados Unidos", "USA"],
        "usa": ["Estados Unidos", "United States"], "ivorycoast": ["Costa do Marfim", "Cote d'Ivoire"],
        "czechia": ["República Tcheca", "Czech Republic"], "turkiye": ["Turquia", "Turkey"],
        "netherlands": ["Holanda", "Países Baixos"], "japan": ["Japão"],
        "saudiarabia": ["Arábia Saudita"], "southafrica": ["África do Sul"],
        "newzealand": ["Nova Zelândia"], "russia": ["Rússia"], "germany": ["Alemanha"],
        "spain": ["Espanha"], "portugal": ["Portugal"], "france": ["França"],
        "italy": ["Itália"], "argentina": ["Argentina"], "mexico": ["México"],
        "uruguay": ["Uruguai"], "colombia": ["Colômbia"], "chile": ["Chile"],
        "peru": ["Peru"], "paraguay": ["Paraguai"], "ecuador": ["Equador"],
        "australia": ["Austrália"], "china": ["China"], "morocco": ["Marrocos"],
        "egypt": ["Egito"], "nigeria": ["Nigéria"], "cameroon": ["Camarões"],
        "senegal": ["Senegal"], "tunisia": ["Tunísia"], "ghana": ["Gana"],
        "croatia": ["Croácia"], "serbia": ["Sérvia"], "switzerland": ["Suíça"],
        "belgium": ["Bélgica"], "denmark": ["Dinamarca"], "sweden": ["Suécia"],
        "norway": ["Noruega"], "poland": ["Polônia"], "ukraine": ["Ucrânia"],
        "austria": ["Áustria"], "greece": ["Grécia"], "turkey": ["Turquia"],
        "republicofireland": ["Irlanda"], "ireland": ["Irlanda", "República da Irlanda", "Republic of Ireland", "Eire"],
        "northernireland": ["Irlanda do Norte"], "irlandadonorte": ["Northern Ireland"],
        "iraq": ["Iraque"], "jordan": ["Jordânia"], "northkorea": ["Coreia do Norte"],
        "koreadpr": ["Coreia do Norte"], "unitedarabemirates": ["Emirados Árabes Unidos"],
        "burkinafaso": ["Burkina-Fasso"], "cotedivoire": ["Costa do Marfim"],
        "bosniaandherzegovina": ["Bósnia-Herzegóvina"], "bosniaherzegovina": ["Bósnia-Herzegóvina"],
        "korearepublic": ["Coreia do Sul"], "uae": ["Emirados Árabes Unidos"],
    }
    return {n, *(norm(x) for x in aliases.get(n, []))} - {""}


def map_national_teams_to_pes(tm_data, pes_teams, extra_aliases=None):
    national_rows = tm_data.get("national_teams", [])
    extra_aliases = extra_aliases or {}
    pes_nations = [t for t in pes_teams if _is_national_id(int(t["id"]))]
    idx = {}
    for t in pes_nations:
        for name in [t.get("name"), *t.get("aliases", []), *extra_aliases.get(str(t.get("id")), [])]:
            for n in _nation_variants(name): idx.setdefault(n, []).append(int(t["id"]))
    out = {}
    for nt in national_rows:
        names = [nt.get("name"), nt.get("country_name")]
        candidates = set()
        for name in names:
            for n in _nation_variants(name): candidates.update(idx.get(n, []))
        if len(candidates) == 1:
            out[str(nt["national_team_id"])] = next(iter(candidates))
    return out


def _is_national_id(team_id):
    try:
        from official_names import team_category
        return team_category(int(team_id)) == "Seleção"
    except Exception:
        return False


def _is_club_id(team_id):
    try:
        from official_names import team_category
        return team_category(int(team_id)) == "Clube"
    except Exception:
        return False


def analyze_roster_updates(pes_players, pes_rosters, pes_teams, playersdb_entries, tm_data, extra_team_aliases=None, player_aliases=None):
    """Build a conservative transfer/call-up plan from the loaded static snapshot."""
    refs = [int(p.get("konami_id") or 0) for p in pes_players if int(p.get("konami_id") or 0)]
    if len(refs) != len(set(refs)):
        raise ValueError("A tabela de jogadores contém IDs Konami duplicados. Corrija a ambiguidade antes de analisar transferências.")
    id_to_tm, pstats = match_playersdb_to_transfermarkt(playersdb_entries, tm_data.get("players", []), player_aliases)
    club_map, c_ambiguous = map_transfermarkt_clubs_to_pes(tm_data, pes_teams, extra_team_aliases)
    nation_map = map_national_teams_to_pes(tm_data, pes_teams, extra_team_aliases)
    roster_membership = {}
    roster_by_team = {int(r["team"]): r for r in pes_rosters}
    for r in pes_rosters:
        for ref in r.get("ids", []):
            if ref:
                roster_membership.setdefault(int(ref), []).append(int(r["team"]))
    team_names = {int(t["id"]): t.get("name", str(t["id"])) for t in pes_teams}
    plans = []
    statuses = {"already_correct": 0, "planned_transfers": 0, "planned_callups": 0,
                "no_transfermarkt_match": 0, "no_pes_club": 0, "ambiguous_roster": 0,
                "full": 0, "free_agent": 0, "no_national_data": 0,
                "national_team_unmapped": 0, "already_in_national_team": 0}
    initial_free = {int(r["team"]): sum(1 for x in r.get("ids", []) if not x) for r in pes_rosters}
    transfer_candidates = []
    outgoing_by_team = {}

    # First resolve every player's destination and source before allocating slots.
    for p in pes_players:
        ref = int(p.get("konami_id") or 0)
        if not ref:
            continue
        tm = id_to_tm.get(ref)
        if not tm:
            statuses["no_transfermarkt_match"] += 1
            continue
        club_id = _text(tm.get("current_club_id"))
        if not club_id or club_id.casefold() in ("0", "none", "nan"):
            statuses["free_agent"] += 1
            continue
        dest = club_map.get(club_id)
        if dest is None:
            statuses["no_pes_club"] += 1
            continue
        members = roster_membership.get(ref, [])
        club_members = [x for x in members if x in roster_by_team and _is_club_id(x)]
        if len(club_members) > 1:
            statuses["ambiguous_roster"] += 1
            continue
        if len(club_members) == 1 and club_members[0] == dest:
            statuses["already_correct"] += 1
            continue
        source = club_members[0] if club_members else None
        transfer_candidates.append({"operation": "transfer" if source is not None else "add_to_club",
                                    "konami_id": ref, "player": p.get("name", ""),
                                    "from_team_id": source,
                                    "from_team": team_names.get(source, "Sem clube no elenco") if source is not None else "Sem clube no elenco",
                                    "to_team_id": dest, "to_team": team_names.get(dest, str(dest)),
                                    "tm_player_id": tm.get("player_id"), "confidence": "alta",
                                    "reason": "ID Konami + identidade biográfica corroborada + current_club_id do snapshot Transfermarkt"})
        if source is not None:
            outgoing_by_team[source] = outgoing_by_team.get(source, 0) + 1

    # Allocate moves iteratively. A transfer accepted from team A frees a real
    # slot in A; only then may another player enter A. This avoids relying on
    # slots from transfers that were themselves rejected for lack of capacity.
    available = dict(initial_free)
    pending = list(transfer_candidates)
    while pending:
        next_pending = []
        accepted_this_round = 0
        for item in pending:
            dest = int(item["to_team_id"])
            if available.get(dest, 0) <= 0:
                next_pending.append(item)
                continue
            plans.append(item)
            available[dest] -= 1
            source = item.get("from_team_id")
            if source is not None:
                available[int(source)] = available.get(int(source), 0) + 1
            accepted_this_round += 1
        if not accepted_this_round:
            statuses["full"] += len(next_pending)
            break
        pending = next_pending

    # Current-national-team metadata indicates profile affiliation, not a dated
    # match-day call-up list. We label these as suggestions for review, not official squads.
    has_nt_field = any(p.get("current_national_team_id") for p in tm_data.get("players", []))
    if has_nt_field:
        pes_by_ref = {int(p.get("konami_id") or 0): p for p in pes_players}
        for ref, tm in id_to_tm.items():
            nt_id = _text(tm.get("current_national_team_id"))
            if not nt_id:
                continue
            dest = nation_map.get(nt_id)
            if dest is None:
                statuses["national_team_unmapped"] += 1
                continue
            members = roster_membership.get(ref, [])
            if dest in members:
                statuses["already_in_national_team"] += 1
                continue
            if available.get(dest, 0) <= 0:
                statuses["full"] += 1
                continue
            player = pes_by_ref.get(ref, {})
            plans.append({"operation": "callup", "konami_id": ref, "player": player.get("name", ""),
                          "from_team_id": None, "from_team": "Vínculo de seleção no perfil",
                          "to_team_id": dest, "to_team": team_names.get(dest, str(dest)),
                          "tm_player_id": tm.get("player_id"), "confidence": "revisar",
                          "reason": "current_national_team_id do perfil; sugestão de vínculo, não convocação oficial para uma data específica"})
            available[dest] -= 1
    else:
        statuses["no_national_data"] = len(id_to_tm)
    statuses["planned"] = len(plans)
    statuses["planned_transfers"] = sum(1 for p in plans if p["operation"] in ("transfer", "add_to_club"))
    statuses["planned_callups"] = sum(1 for p in plans if p["operation"] == "callup")
    statuses["club_names_mapped"] = len(club_map)
    statuses["club_names_ambiguous"] = c_ambiguous
    statuses["national_teams_mapped"] = len(nation_map)
    statuses["playersdb_tm_matched"] = pstats["matched"]
    statuses["playersdb_tm_ambiguous"] = pstats["ambiguous"]
    statuses["playersdb_tm_unmatched"] = pstats["unmatched"]
    return {"plans": plans, "stats": statuses, "player_match_stats": pstats,
            "club_map": club_map, "national_map": nation_map,
            "snapshot_date": tm_data.get("snapshot_date", SNAPSHOT_DATE)}

def apply_roster_plan(data, rosters, plan):
    """Apply reviewed transfer/call-up plan atomically; preserve unknown refs."""
    import struct
    out = bytearray(data)
    # Clone roster views so a failed preflight never mutates caller state.
    roster_by_team = {int(r["team"]): {**r, "ids": list(r["ids"]), "numbers": list(r["numbers"])} for r in rosters}
    reserved = {int(r["team"]): sum(1 for x in r["ids"] if not x) for r in roster_by_team.values()}
    outgoing = {}
    seen = set()
    # A player may receive one club operation and one selection call-up in the
    # same batch; duplicate operations of the same membership type are refused.
    # Preflight: unique operation per player/category, valid destination/source.
    for item in plan:
        dest = int(item["to_team_id"]); ref = int(item["konami_id"])
        op = item.get("operation")
        category = "national" if op == "callup" else "club"
        key = (ref, category)
        if key in seen:
            raise ValueError(f"Plano contém operações duplicadas para o jogador {ref}; nada foi gravado.")
        seen.add(key)
        if dest not in roster_by_team:
            raise ValueError(f"Equipe de destino {dest} não possui registro de elenco.")
        if ref in roster_by_team[dest]["ids"]:
            raise ValueError(f"O jogador {ref} já está no destino; nada foi gravado.")
        if op == "transfer":
            src = int(item["from_team_id"])
            if src not in roster_by_team or sum(1 for x in roster_by_team[src]["ids"] if int(x) == ref) != 1:
                raise ValueError(f"Origem não é única para o jogador {ref}; nada foi gravado.")
            outgoing[src] = outgoing.get(src, 0) + 1
        elif op not in ("add_to_club", "callup"):
            raise ValueError(f"Operação desconhecida no plano: {op!r}.")
    # Account for slots that become free due to departures in this same batch.
    for tid, count in outgoing.items():
        reserved[tid] = reserved.get(tid, 0) + count
    for item in plan:
        dest = int(item["to_team_id"])
        if reserved.get(dest, 0) <= 0:
            raise ValueError(f"A equipe {dest} não tem vaga disponível; nada foi gravado.")
        reserved[dest] -= 1

    # Remove all transfers first, allowing a slot freed by one move to receive another.
    shirt_by_ref = {}
    for item in plan:
        if item.get("operation") != "transfer":
            continue
        ref = int(item["konami_id"]); src = int(item["from_team_id"])
        rsrc = roster_by_team[src]
        src_slot = rsrc["ids"].index(ref)
        shirt_by_ref[ref] = rsrc["numbers"][src_slot]
        struct.pack_into(">I", out, rsrc["off"] + 4 + src_slot * 4, 0)
        out[rsrc["off"] + 0x84 + src_slot] = 0
        rsrc["ids"][src_slot] = 0; rsrc["numbers"][src_slot] = 0

    # Add destination links after every outgoing slot has been cleared.
    for item in plan:
        ref = int(item["konami_id"]); dest = int(item["to_team_id"])
        rdest = roster_by_team[dest]
        free_slots = [i for i, value in enumerate(rdest["ids"]) if not value]
        if not free_slots:
            raise ValueError(f"A equipe {dest} ficou sem vaga durante a aplicação; plano cancelado.")
        free = free_slots[0]
        shirt = int(shirt_by_ref.get(ref, 0))
        struct.pack_into(">I", out, rdest["off"] + 4 + free * 4, ref)
        out[rdest["off"] + 0x84 + free] = shirt & 0xFF
        rdest["ids"][free] = ref; rdest["numbers"][free] = shirt
    return out
