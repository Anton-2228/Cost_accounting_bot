import json
from os import getenv
from typing import Iterable

from langchain.agents import AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from openai import OpenAI, AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from ai_wrapper.utils import parsing_model_json_response, get_input_for_types_user_prompt, \
    get_input_for_categories_user_prompt
from datafiles import GET_CREDENTIALS_CHECK_PROMPT, GET_TYPES_FOR_CHECK_USER_PROMPT, GET_TYPES_FOR_CHECK_SYSTEM_PROMPT, \
    GET_CATEGORIES_FOR_CHECK_SYSTEM_PROMPT
from init import getFirstPrompt, getSecondPrompt, getCredentialsCheckPrompt


class AiWrapper:
    def __init__(self, pr=None):
        # first = getFirstPrompt()
        # second = getSecondPrompt()
        # first_base_agent = ChatPromptTemplate.from_messages(
        #     [("system", first)]
        # )
        # second_base_agent = ChatPromptTemplate.from_messages(
        #     [("system", second)]
        # )

        self.api_key = getenv("OPENAI_API_KEY")
        assert self.api_key is not None, "Set enviroment variable 'OPENAI_API_KEY'"
        self.base_url = getenv("OPENAI_BASE_URL")
        assert self.api_key is not None, "Set enviroment variable 'OPENAI_BASE_URL'"
        self.model = getenv("OPENAI_MODEL")
        assert self.api_key is not None, "Set enviroment variable 'OPENAI_MODEL'"
        self.temperature = 0.2

        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        # self.first_agent = first_base_agent | model
        # self.second_agent = second_base_agent | model

    async def create(self, messages: Iterable[ChatCompletionMessageParam]):
        response = await self.client.chat.completions.create(
            messages=messages,
            model=self.model,
            temperature=self.temperature,
            n=1,
            response_format={"type": "json_object"},
            max_tokens=4096,
        )
        content = response.choices[0].message.content
        assert content is not None
        return parsing_model_json_response(content)

    async def invoke(self, system_prompt: str, user_prompt: str):
        system_content = [{"type": "text", "text": system_prompt}]
        user_content = [{"type": "text", "text": user_prompt}]

        messages = [{"role": "system", "content": system_content},
                    {"role": "user", "content": user_content}]

        return await self.create(messages)

    async def get_credentials_check(self, input: str):
        system_prompt = GET_CREDENTIALS_CHECK_PROMPT
        user_prompt = input

        return await self.invoke(system_prompt=system_prompt,
                                 user_prompt=user_prompt)

    async def first_invoke_check(self, input: dict):
        system_prompt = GET_TYPES_FOR_CHECK_SYSTEM_PROMPT
        user_prompt = get_input_for_types_user_prompt(input)

        return await self.invoke(system_prompt=system_prompt,
                                 user_prompt=user_prompt)

    async def second_invoke_check(self, input: dict):
        system_prompt = GET_CATEGORIES_FOR_CHECK_SYSTEM_PROMPT
        user_prompt = get_input_for_categories_user_prompt(input)

        return await self.invoke(system_prompt=system_prompt,
                                 user_prompt=user_prompt)
