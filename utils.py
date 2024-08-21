import json
import re


def parsing_model_json_response(resp) -> str:
    try:
        answer = json.loads(resp)
    except:
        pattern = r'```json([\w\W]+)```'
        matches = re.findall(pattern, resp)
        answer = json.loads(matches[0])
    return answer