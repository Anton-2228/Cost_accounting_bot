import json
import re

from datafiles import (GET_CATEGORIES_FOR_CHECK_USER_PROMPT,
                       GET_TYPES_FOR_CHECK_USER_PROMPT)


def parsing_model_json_response(resp) -> str:
    try:
        answer = json.loads(resp)
    except:
        pattern = r"```json([\w\W]+)```"
        matches = re.findall(pattern, resp)
        answer = json.loads(matches[0])
    return answer


def get_input_for_types_user_prompt(data: dict) -> str:
    return GET_TYPES_FOR_CHECK_USER_PROMPT.format(
        check=data["check"], types=data["types"]
    )


def get_input_for_categories_user_prompt(data: dict) -> str:
    return GET_CATEGORIES_FOR_CHECK_USER_PROMPT.format(
        check=data["check"], categories=data["categories"]
    )
