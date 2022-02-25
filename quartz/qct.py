from datetime import datetime
import json
import logging
import os
import re
from threading import Thread
import time
from typing import List, Union

from dumpster import fdict
from googleapiclient import discovery
from oauth2client.service_account import ServiceAccountCredentials

from quartz import cue

# Constants
CREDS = json.loads(os.environ['CREDS'])
SCOPE = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/drive.file',
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/spreadsheets'
]
IMG = 'https://cdn-virttrade-assets-eucalyptus.cloud.virttrade.com/filekey'
ID = '1JL8Vfyj4uRVx6atS5njJxL03dpKFkgBu74u-h0kTNSo' 
CARDS = 'Card List!A:N'
COLS = 'Collection!B:E'
FUSE = 'Fusion'
DEF_SUBS = {
    ':power:': '⚡',
    ':power/turn:': '⚡/turn',
    ':energy:': '🔋',
    ':energy/turn:': '🔋/turn',
    ':lock:': '🔒 ',
    ':burn:': '🔥 ',
    ':return:': '↩️ ',
    ':play:': '▶️ ',
    ':draw:': '⬆️ '
}


# Variables
fd = fdict(epoch=0, subs=DEF_SUBS)


# Authentication
creds = ServiceAccountCredentials.from_json_keyfile_dict(CREDS, SCOPE)
service = discovery.build('sheets', 'v4', credentials=creds)
sheet = service.spreadsheets()


# Functions
def get(ranges: List[str]) -> List[List[str]]:
    ranges = sheet.values().batchGet(
        spreadsheetId=ID, ranges=ranges).execute()['valueRanges']
    return [r['values'] for r in ranges]


def append(range: str, body: List[List[str]]) -> None:
    return sheet.values().append(
        spreadsheetId=ID, range=range, 
        body={'values': body}, 
        valueInputOption='USER_ENTERED').execute()


def update(range: str, body: List[List[str]]) -> None:
    return sheet.values().update(
        spreadsheetId=ID, range=range, 
        body={'values': body}, 
        valueInputOption='USER_ENTERED').execute()


def to_datetime(ms: Union[str, int]) -> str:
    if isinstance(ms, str):
        ms = int(ms)
    dt = datetime.utcfromtimestamp(ms/1000.0)
    return dt.strftime("%d/%m/%Y %H:%M:%S")


def extract_card(pl: dict) -> List[str]:
    code = pl['code']
    name = pl['name']

    album = pl['albumCode']
    collection = pl['collection']

    type_ = ''
    rarity = pl['type']
    if len(k := rarity.split()) > 1:
        type_, rarity = k

    e = str(pl['energy'])
    energy = e if e.isnumeric() else '0'
    p = str(pl['power'])
    power = p if p.isnumeric() else '0'
    ppe = '∞'
    if energy != '0': 
        ppe = str(eval(power + "//" + energy))

    title = ability = ''
    if pl['abilityTitle'] is not None: 
        title = pl['abilityTitle']
        ability = pl['abilityPlaintextV2']
        for p in fd['subs']:
            ability = re.sub(p, fd['subs'][p], ability)

    pull = to_datetime(pl['firstPull'])
    modified = to_datetime(pl['modifiedDate'])

    _img = pl['img'] 
    img = f'{IMG}/{_img[0:2]}/{_img[2:4]}/{_img[4:]}'

    return [code, name,
            album, collection,
            type_, rarity,
            energy, power, ppe,
            title, ability,
            pull, modified,
            img]


def update_cards(cards: List[dict], *, silent: bool = False) -> None:
    Q_CARDS, Q_COLS = get([CARDS, COLS]) 
    q_cards, q_cols = Q_CARDS.copy(), Q_COLS.copy()
    changelogs, dyks, legacies, fusions = ([] for _ in range(4))

    for c in cards:
        epoch = int(c['modifiedDate']) 
        if epoch > fd['epoch']:
            fd['epoch'] = epoch

        card = extract_card(c)
        logging.info(f'{card[0]}:{card[1]}')
        for i in range(len(q_cards)): # Update card
            if q_cards[i][0] == card[0]:
                if not silent:
                    legacies.append(['Updated'] + q_cards[i] + card)
                q_cards[i] = card
                break
        else: # New card
            q_cards.append(card)
            dyks.append([c['name'], c['dyk']])
            # Fusion
            if card[3] == FUSE: 
                fusions.append([card[1]])
            # Collection
            if not any(card[3] == j[0] for j in q_cols): 
                _img = c['collectionImage']
                img = f'{IMG}/{_img[0:2]}/{_img[2:4]}/{_img[4:]}'
                q_cols.append([c['collectionCode'], card[3], card[11], img])
        changelogs.append([c['name'], c['firstPull']])

    if Q_CARDS != q_cards: update(CARDS, q_cards) 
    if Q_COLS != q_cols: update(COLS, q_cols) 
    if dyks: append('Do You Know', dyks)
    if changelogs: append('Changelog', changelogs)
    if legacies: append('Legacy Cards', legacies)
    if fusions: append(FUSE, fusions)
    
    fd.write()


def mass_update(*, silent: bool = False) -> None:
    update_cards(cue.get_card_updates(1574969089362), silent=silent)


def scheduled_update(interval: int = 60*60*24, silent: bool = True) -> None:
    def schedule():
        while True:
            cards = cue.get_card_updates(fd['epoch'])
            update_cards(cards, silent=silent)
            time.sleep(interval)
    Thread(target=schedule).start()