# -*- coding: utf-8 -*-
"""Correspondências conservadoras para a base PES 2018 original (temporada 2017/18).
Só aplica quando ID e nome fictício atual coincidem. Nomes sem equivalente seguro ficam intactos.
"""
import unicodedata, re

def norm(s):
    s=unicodedata.normalize('NFKD',str(s or '')).encode('ascii','ignore').decode().casefold()
    return re.sub(r'[^a-z0-9]+','',s)

# team_id: (nome fictício esperado no arquivo base, nome oficial)
TEAM_NAMES = {
 55:('MAN RED','Manchester United'),57:('LONDON FC','Chelsea FC'),59:('YORKSHIRE WHITES','Leeds United'),
 64:('MD WHITE','Real Madrid'),
 60:('EAST LONDON','West Ham United'),61:('TYNESIDE','Newcastle United'),62:('WEST MIDLANDS VILLAGE','Aston Villa'),
 66:('GA BLUE WHITE','Deportivo de La Coruña'),75:('PM BLACK WHITE','Juventus'),78:('ER YELLOW BLUE','Parma'),
 92:('MAN BLUE','Manchester City'),94:('MERSEYSIDE BLUE','Everton'),96:('NORTH EAST LONDON','Tottenham Hotspur'),
 102:('BRUTIE','Brescia'),108:('AN GREEN WHITE','Real Betis'),109:('GA CYAN','Celta de Vigo'),
 110:('PV BLUE WHITE','Real Sociedad'),115:('WEST MIDLANDS CITY','Birmingham City'),116:('NW WHITE BLACK','Bolton Wanderers'),
 117:('EAST MIDLANDS','Leicester City'),118:('TEESSIDE','Middlesbrough'),119:('HAMPSHIRE RED','Southampton'),
 120:('WM GOLD','Wolverhampton Wanderers'),132:('TO BLUE','Empoli'),133:('SI PINK BLACK','Palermo'),
 146:('PV WHITE RED','Athletic Club'),147:('CT BLUE WHITE','Espanyol'),148:('AN CYAN WHITE','Málaga'),
 149:('NC RED','Osasuna'),150:('AN WHITE RED','Sevilla'),151:('CL PURPLE','Real Valladolid'),
 152:('ED YELLOW','Villarreal'),153:('AR WHITE BLUE','Real Zaragoza'),158:('MA ZEBRA','Ascoli'),
 159:('BAGNARONI','Bari'),163:('AB WHITE LIGHT BLUE','Pescara'),164:('TECCARINA','Ternana'),
 171:('AN SCARLET WHITE','Almería'),172:('AN VIRIDIAN WHITE','Córdoba'),173:('MD COBALT BLUE','Getafe'),
 174:('AS RED WHITE','Sporting Gijón'),175:('CN YELLOW BLUE','Las Palmas'),176:('ED BLUE BURGUNDY','Levante'),
 177:('CL RED','Numancia'),178:('MD SCARLET WHITE','Rayo Vallecano'),179:('EAST SUSSEX','Brighton & Hove Albion'),
 180:('LANCASHIRE CLARET','Burnley'),181:('SOUTH WALES','Cardiff City'),182:('SOUTH NORWOOD','Crystal Palace'),
 183:('DERBYSHIRE','Derby County'),184:('EAST ANGLIA TOWN','Ipswich Town'),185:('GL BLUE WHITE','Millwall'),
 186:('NORFOLK CITY','Norwich City'),187:('NOTTS REDS','Nottingham Forest'),188:('BERKSHIRE BLUES','Reading'),
 189:('SOUTH YORKSHIRE BLUES','Sheffield Wednesday'),190:('ST RED','Stoke City'),191:('WEARSIDE','Sunderland'),
 192:('HERTFORDSHIRE','Watford'),193:('WEST MIDLANDS STRIPES','West Bromwich Albion'),
 257:('NORTH WEST LONDON','Queens Park Rangers'),261:('ER BLACK WHITE','Cesena'),263:('PLEASURE HORN','Al Ahly'),
 266:('SY RED','Barnsley'),267:('YORKSHIRE ORANGE','Hull City'),268:('SPREMONESE','Spezia'),
 272:('SW RED','Bristol City'),273:('AN RED WHITE','Granada'),274:('VISICUTAO','Vitoria SC'),
 275:('WEST GLAMORGAN CITY','Swansea City'),278:('DL CRIMSON','Cittadella'),292:('BLEMOTAO','Belenenses'),
 293:('BRESIGNE','Braga'),294:('MASEADEIRA','Marítimo'),295:('PODEFTEZA','Paços de Ferreira'),
 296:('ROVANECHE','Rio Ave'),297:('VERFOLCAO','Vitória de Setúbal'),298:('CT CARMINE WHITE','Girona'),
 299:('AR BURGUNDY BLUE','Huesca'),328:('AL BLACK WHITE','Portimonense'),329:('PM BLUE WHITE','Novara'),
 330:('BJ RED','Desportivo das Aves'),331:('ESTRALPAO','Estoril Praia'),332:('DL AZURE BLUE','Feirense'),
 333:('MERASZILHO','Moreirense'),334:('MD CANARY YELLOW','Alcorcón'),382:('PAILAMUDOVELI','Pro Vercelli'),
 383:('BA YELLOW GREEN','Tondela'),384:('GA RED WHITE','Lugo'),380:('WEST YORKSHIRE TOWN','Huddersfield Town'),
 429:('EAST DORSETSHIRE','AFC Bournemouth'),430:('ER WHITE RED','Carpi'),431:('TM BLUE RED','Chaves'),
 432:('CT BLUE RED B','Barcelona B'),435:('ALVEGIARO','Avellino'),436:('PV SKY BLUE WHITE','Deportivo Alavés'),
 437:('PV BLUE RED','Eibar'),438:('CN WHITE BLUE','Tenerife'),439:('HOUNSLOW','Brentford'),
 440:('LN WHITE','Preston North End'),441:('YH RED BLACK','Sheffield United'),446:('LB RED GREY','Cremonese'),
 447:('DL GREEN BLACK ORANGE','Venezia'),448:('LR WHITE BLUE','Virtus Entella'),450:('TI YELLOW BLUE','Frosinone'),
 451:('PRASTOGNA','Perugia'),452:('CM BURGUNDY','Salernitana'),453:('CL BLACK WHITE','Cultural Leonesa'),
 454:('AS BLUE','Real Oviedo'),455:('MD BLUE WHITE','Leganés'),456:('CT RED','Gimnàstic de Tarragona'),
 457:('CT RED BLACK','Reus Deportiu'),458:('CM WHITE BLACK','Albacete'),459:('AN YELLOW BLUE','Cádiz'),
 460:('MC BLUE WHITE','Lorca'),461:('AN WHITE RED B','Sevilla Atlético'),463:('BORFECAO','Boavista'),
 466:('PL RED BLACK','Foggia'),470:('ST YELLOW','Burton Albion'),
}

# Competições claramente identificáveis no PES 2018. As ligas PEU/PLA/PAS e KONAMI
# são placeholders genéricos: não são renomeadas automaticamente para não inventar o patch.
COMPETITION_NAMES = {
 1:('Copa internacional de clubes','FIFA Club World Cup'),
 5:('Torneio Sul-Americano','CONMEBOL Libertadores'),
 9:('Liga inglesa','Premier League'),10:('Liga italiana','Serie A'),11:('Liga Espanhola','LaLiga'),
 14:('Liga portuguesa','Liga Portugal (Liga NOS 2017/18)'),
 15:('Copa inglesa','FA Cup'),16:('Copa italiana','Coppa Italia'),17:('Copa espanhola','Copa del Rey'),
 18:('Copa francesa','Coupe de France'),19:('Copa holandesa','KNVB Cup'),20:('Copa portuguesa','Taça de Portugal'),
 22:('Liga Argentina','Superliga Argentina 2017/18'),23:('Liga Chilena','Primera División de Chile'),
 24:('Copa brasileira','Copa do Brasil'),27:('Copa internacional','FIFA World Cup'),
 33:('Copa europeia','UEFA Champions League'),34:('Copa da América','Copa América'),
 35:('Copa Ásia/Oceania','AFC Asian Cup'),36:('Copa africana','Africa Cup of Nations'),
 49:('Copa da Argentina','Copa Argentina'),56:('Copa do Chile','Copa Chile'),
 66:('2ª divisão da Inglaterra','EFL Championship'),67:('2ª Divisão Espanhola','LaLiga 2'),
 69:('2ª divisão da Itália','Serie B'),73:('Supercopa da Inglaterra','FA Community Shield'),
 74:('Supercopa da Espanha','Supercopa de España'),75:('Supercopa da França','Trophée des Champions'),
 76:('Supercopa da Itália','Supercoppa Italiana'),77:('Supercopa da Holanda','Johan Cruyff Shield'),
 78:('Supercopa de Portugal','Supertaça Cândido de Oliveira'),79:('Supercopa da Argentina','Supercopa Argentina'),
}

# IDs de seleções nacionais identificados na tabela de 508 equipes deste save. 395/396 são clássicos.
NATIONAL_TEAM_IDS = set(range(0,55)) | set(range(204,229)) | {265,474}
CLASSIC_TEAM_IDS = {395,396}

def team_category(team_id):
    if team_id in NATIONAL_TEAM_IDS: return 'Seleção'
    if team_id in CLASSIC_TEAM_IDS: return 'Clássicos'
    return 'Clube'
