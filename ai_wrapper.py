from os import getenv

from langchain.agents import AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from init import getSystemPrompt


class AiWrapper:
    def __init__(self):
        system = getSystemPrompt()
        base_agent = ChatPromptTemplate.from_messages(
            [("system", system)]
        )

        api_key = getenv("OPENAI_API_KEY")
        assert api_key is not None, "Set enviroment variable 'OPENAI_API_KEY'"
        base_url = getenv("OPENAI_BASE_URL")
        assert base_url is not None, "Set enviroment variable 'OPENAI_BASE_URL'"
        model = getenv("OPENAI_MODEL")
        assert model is not None, "Set enviroment variable 'OPENAI_MODEL'"

        model = ChatOpenAI(model=model, openai_api_key=api_key, base_url=base_url)
        self.agent = base_agent | model

AIWRAPPER = AiWrapper()
resp = AIWRAPPER.agent.invoke({"num": 2})
print(resp)