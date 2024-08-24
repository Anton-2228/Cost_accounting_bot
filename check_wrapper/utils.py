import asyncio
import json
from os import getenv

import requests

from ai_wrapper.ai_wrapper import AiWrapper


async def get_check_data(ai_wrapper: AiWrapper, check_text: str) -> dict:
    check_credentials = await ai_wrapper.get_credentials_check(check_text)
    date, time = check_credentials['t'].split()
    date, month, year = date.split(".")
    time = time.replace(":", "")
    check_credentials['t'] = f'{year}{month}{date}T{time}'
    check_data = get_check_json(check_credentials)
    return check_data

def get_check_json(check_credentials: dict) -> dict:
    with open('/home/anton/Desktop/Cost_accounting_bot/check.json', 'r') as file:
        check = file.read()
    return json.loads(check)
    # resp = requests.post(url=getenv("PROVERKACHEKA_BASE_URL"),
    #                      json={"token": getenv("PROVERKACHEKA_API_TOKEN"),
    #                            "fn": check_credentials['fn'],
    #                            "fd": check_credentials["fd"],
    #                            "fp": check_credentials["fp"],
    #                            "t": check_credentials["t"],
    #                            "s": check_credentials["s"]})
    # return json.loads(resp.content.decode())

def get_important_check_data(check_data: dict) -> dict:
    important_data = {}
    for id, product in enumerate(check_data['data']['json']['items']):
        important_data[str(id+1)] = {}
        important_data[str(id+1)]["name"] = product["name"]
        important_data[str(id+1)]["sum"] = product["sum"]/100
    return important_data

