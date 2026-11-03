# API integration for PES 2018 Editor. Uses only Python standard library.
import json, urllib.parse, urllib.request, urllib.error, unicodedata, re

API_INFO = {
 'API-Football': 'https://www.api-football.com/documentation-v3',
 'Sportmonks': 'https://docs.sportmonks.com/v3/endpoints-and-entities/endpoints/team-squads/get-team-squad-by-team-id',
 'Highlightly': 'https://highlightly.net/football-api/documentation/',
}

def norm(s):
 s=unicodedata.normalize('NFKD', str(s or '')).encode('ascii','ignore').decode().lower()
 return re.sub(r'[^a-z0-9]+','',s)

def http_json(url, headers=None, timeout=12):
 req=urllib.request.Request(url, headers=headers or {'User-Agent':'PES2018Editor/0.6'})
 with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read().decode('utf-8'))

def api_football_squad(team_name, key):
 if not key: raise RuntimeError('Chave API-Football não configurada')
 h={'x-apisports-key':key}
 q=urllib.parse.urlencode({'search':team_name})
 data=http_json('https://v3.football.api-sports.io/teams?'+q,h)
 rows=data.get('response',[])
 if not rows: raise RuntimeError('Clube não encontrado na API-Football')
 wanted=norm(team_name)
 rows.sort(key=lambda x: (norm(x.get('team',{}).get('name'))!=wanted,))
 team=rows[0].get('team',{})
 squad=http_json('https://v3.football.api-sports.io/players/squads?team='+str(team['id']),h)
 res=squad.get('response',[])
 if not res or not res[0].get('players'): raise RuntimeError('API-Football não retornou elenco')
 out=[]
 for p in res[0]['players']:
  out.append({'name':p.get('name') or '', 'age':p.get('age'), 'number':p.get('number'), 'position':p.get('position'), 'source':'API-Football'})
 return out

def sportmonks_squad(team_name, key):
 if not key: raise RuntimeError('Token Sportmonks não configurado')
 q=urllib.parse.quote(team_name)
 data=http_json('https://api.sportmonks.com/v3/football/teams/search/'+q+'?api_token='+urllib.parse.quote(key))
 rows=data.get('data',[])
 if not rows: raise RuntimeError('Clube não encontrado no Sportmonks')
 wanted=norm(team_name)
 rows.sort(key=lambda x: norm(x.get('name'))!=wanted)
 team=rows[0]
 sid=str(team['id'])
 squad=http_json('https://api.sportmonks.com/v3/football/squads/teams/'+sid+'?api_token='+urllib.parse.quote(key)+'&include=player')
 out=[]
 for x in squad.get('data',[]):
  p=x.get('player') or {}
  name=p.get('display_name') or p.get('name') or p.get('common_name') or ''
  if name: out.append({'name':name,'age':p.get('age'),'number':x.get('jersey_number'),'position':(x.get('position') or {}).get('name'),'source':'Sportmonks'})
 if not out: raise RuntimeError('Sportmonks não retornou elenco; verifique plano/cobertura')
 return out

def highlightly_player_lookup(player_name, key):
 """Supplementary player identity check. Highlightly's documented player list is not a team-squad endpoint."""
 if not key: raise RuntimeError('Chave Highlightly não configurada')
 q=urllib.parse.urlencode({'name':player_name,'limit':10,'offset':0})
 d=http_json('https://soccer.highlightly.net/players?'+q,{'x-rapidapi-key':key})
 return d.get('data',[])

def fetch_squad(team_name, keys):
 errors=[]
 for name,fn,k in [('API-Football',api_football_squad,keys.get('api_football','')),('Sportmonks',sportmonks_squad,keys.get('sportmonks',''))]:
  try: return fn(team_name,k), name, errors
  except Exception as e: errors.append(name+': '+str(e))
 # Highlightly is intentionally not treated as a squad provider: docs expose team/player search,
 # but no current-team-squad endpoint. It can enrich individual player identity only.
 if keys.get('highlightly'):
  errors.append('Highlightly: disponível para consulta complementar de jogador, não fornece endpoint documentado de elenco por clube.')
 return [], None, errors

def football_data_squad(team_name, key):
 if not key: raise RuntimeError('Token football-data.org não configurado')
 h={'X-Auth-Token':key}
 q=urllib.parse.urlencode({'name':team_name})
 data=http_json('https://api.football-data.org/v4/teams?'+q,h)
 rows=data.get('teams',[])
 if not rows: raise RuntimeError('Clube não encontrado/sem cobertura no football-data.org')
 wanted=norm(team_name); rows.sort(key=lambda x:norm(x.get('name'))!=wanted)
 team=rows[0]
 detail=http_json('https://api.football-data.org/v4/teams/'+str(team['id']),h)
 squad=detail.get('squad',[])
 out=[]
 for p in squad:
  if p.get('name') and p.get('role','PLAYER')=='PLAYER':
   out.append({'name':p.get('name'),'age':None,'number':None,'position':p.get('position'),'source':'football-data.org'})
 if not out: raise RuntimeError('Elenco indisponível no plano/cobertura do football-data.org')
 return out

# Replace the provider chain with three providers that expose team squad data.
def fetch_squad(team_name, keys):
 errors=[]
 providers=[('API-Football',api_football_squad,keys.get('api_football','')),
            ('Sportmonks',sportmonks_squad,keys.get('sportmonks','')),
            ('football-data.org',football_data_squad,keys.get('football_data',''))]
 for name,fn,key in providers:
  try: return fn(team_name,key),name,errors
  except Exception as e: errors.append(name+': '+str(e))
 return [],None,errors
