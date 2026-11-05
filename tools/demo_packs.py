"""Offline synthetic fixture catalog for tests and operator preparation only."""
import json
from pathlib import Path

ASSETS=Path(__file__).resolve().parents[1]/'tests'/'fixtures'/'demo_packs'


def catalog():
    result=[]
    for path in sorted(ASSETS.glob('*/manifest.json')):
        data=json.loads(path.read_text())
        if data['pack']!=path.parent.name:
            raise ValueError('Invalid sample pack manifest')
        result.append(data)
    return result


def pack_data(pack):
    found=next((item for item in catalog() if item['pack']==pack),None)
    if found is None:
        raise ValueError('Sample pack not found')
    return found
