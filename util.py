from typing import Optional, Dict, List

from openai import OpenAI
class OpenAiClient:
    def __init__(self, api: Optional[str] = None,
                 baseUrl: Optional[str] = None,
                 model: str = ""):
        self.api = api
        self.baseUrl = baseUrl
        self.model = model

        self.client = OpenAI(api_key=api, base_url=baseUrl)

    def chat(self, messages: List[Dict],
             tools: Optional[List[Dict]] = None,
             temperature: float = 0.7,
             stream: bool = False,
             max_tokens: Optional[int] = None
             ):
        response = self.client.chat.completions.create(model=self.model,
                                            messages=messages,
                                            temperature=temperature,
                                            stream=stream,
                                            max_tokens=max_tokens,
                                                       tools=tools)

        # return response.choices[0].message.content

        return response

