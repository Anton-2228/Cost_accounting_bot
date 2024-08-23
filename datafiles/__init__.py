from pathlib import Path

GET_CREDENTIALS_CHECK_PROMPT = (Path(__file__).parent / "prompts/get_credentials_check_prompt.txt").read_text()
GET_TYPES_FOR_CHECK_SYSTEM_PROMPT = (Path(__file__).parent / "prompts/get_TYPES_for_check_SYSTEM_prompt.txt").read_text()
GET_TYPES_FOR_CHECK_USER_PROMPT = (Path(__file__).parent / "prompts/get_TYPES_for_check_USER_prompt.txt").read_text()
GET_CATEGORIES_FOR_CHECK_SYSTEM_PROMPT = (Path(__file__).parent / "prompts/get_CATEGORIES_for_check_SYSTEM_prompt.txt").read_text()
GET_CATEGORIES_FOR_CHECK_USER_PROMPT = (Path(__file__).parent / "prompts/get_CATEGORIES_for_check_USER_prompt.txt").read_text()

FIRST_STAGE_ADD_CHECK_MESSAGE = (Path(__file__).parent / "messages/first_stage_add_check_message.txt").read_text()
SECOND_STAGE_ADD_CHECK_MESSAGE = (Path(__file__).parent / "messages/second_stage_add_check_message.txt").read_text()
FINISH_STAGE_ADD_CHECK_MESSAGE = (Path(__file__).parent / "messages/finish_stage_add_check_message.txt").read_text()
HELP_MESSAGE = (Path(__file__).parent / "messages/help_message.txt").read_text()
ADD_RECORD_MESSAGE = (Path(__file__).parent / "messages/add_record_message.txt").read_text()
