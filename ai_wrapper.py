import json
from os import getenv

from langchain.agents import AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from init import getFirstPrompt, getSecondPrompt


class AiWrapper:
    def __init__(self, pr=None):
        first = getFirstPrompt()
        second = getSecondPrompt()
        first_base_agent = ChatPromptTemplate.from_messages(
            [("system", first)]
        )
        second_base_agent = ChatPromptTemplate.from_messages(
            [("system", second)]
        )

        api_key = getenv("OPENAI_API_KEY")
        assert api_key is not None, "Set enviroment variable 'OPENAI_API_KEY'"
        base_url = getenv("OPENAI_BASE_URL")
        assert base_url is not None, "Set enviroment variable 'OPENAI_BASE_URL'"
        model = getenv("OPENAI_MODEL")
        assert model is not None, "Set enviroment variable 'OPENAI_MODEL'"

        model = ChatOpenAI(model=model, openai_api_key=api_key, base_url=base_url, temperature=0.2)
        self.first_agent = first_base_agent | model
        self.second_agent = second_base_agent | model

    def first_invoke_check(self, input: dict):
        resp: AIMessage = self.first_agent.invoke(input)
        print(resp.content)
        try:
            answer = json.loads(resp.content)
        except:
            answer = json.loads(resp.content[7:][:-3])
        return answer

    def second_invoke_check(self, input: dict):
        resp: AIMessage = self.second_agent.invoke(input)
        print(resp.content)
        try:
            answer = json.loads(resp.content)
        except:
            answer = json.loads(resp.content[7:][:-3])
        return answer
