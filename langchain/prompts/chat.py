"""Chat prompt template."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, List, Sequence, Tuple, Type, Union

from pydantic import BaseModel, Field

from langchain.memory.buffer import get_buffer_string
from langchain.prompts.base import BasePromptTemplate, StringPromptTemplate
from langchain.prompts.prompt import PromptTemplate
from langchain.schema import (
    AIMessage,
    BaseMessage,
    ChatMessage,
    HumanMessage,
    PromptValue,
    SystemMessage,
)


class BaseMessagePromptTemplate(BaseModel, ABC):
    @abstractmethod
    def format_messages(self, **kwargs: Any) -> List[BaseMessage]:
        """To messages."""

    @property
    @abstractmethod
    def input_variables(self) -> List[str]:
        """Input variables for this prompt template."""


class MessagesPlaceholder(BaseMessagePromptTemplate):
    """Prompt template that assumes variable is already list of messages."""

    variable_name: str

    def format_messages(self, **kwargs: Any) -> List[BaseMessage]:
        """To a BaseMessage."""
        value = kwargs[self.variable_name]
        if not isinstance(value, list):
            raise ValueError(
                f"variable {self.variable_name} should be a list of base messages, "
                f"got {value}"
            )
        for v in value:
            if not isinstance(v, BaseMessage):
                raise ValueError(
                    f"variable {self.variable_name} should be a list of base messages,"
                    f" got {value}"
                )
        return value

    @property
    def input_variables(self) -> List[str]:
        """Input variables for this prompt template."""
        return [self.variable_name]


class BaseStringMessagePromptTemplate(BaseMessagePromptTemplate, ABC):
    prompt: StringPromptTemplate
    additional_kwargs: dict = Field(default_factory=dict)

    @classmethod
    def from_template(cls, template: str, **kwargs: Any) -> BaseMessagePromptTemplate:
        prompt = PromptTemplate.from_template(template)
        return cls(prompt=prompt, **kwargs)

    @abstractmethod
    def format(self, **kwargs: Any) -> BaseMessage:
        """To a BaseMessage."""

    def format_messages(self, **kwargs: Any) -> List[BaseMessage]:
        return [self.format(**kwargs)]

    @property
    def input_variables(self) -> List[str]:
        return self.prompt.input_variables


class ChatMessagePromptTemplate(BaseStringMessagePromptTemplate):
    role: str

    def format(self, **kwargs: Any) -> BaseMessage:
        text = self.prompt.format(**kwargs)
        return ChatMessage(
            content=text, role=self.role, additional_kwargs=self.additional_kwargs
        )


class HumanMessagePromptTemplate(BaseStringMessagePromptTemplate):
    def format(self, **kwargs: Any) -> BaseMessage:
        text = self.prompt.format(**kwargs)
        return HumanMessage(content=text, additional_kwargs=self.additional_kwargs)


class AIMessagePromptTemplate(BaseStringMessagePromptTemplate):
    def format(self, **kwargs: Any) -> BaseMessage:
        text = self.prompt.format(**kwargs)
        return AIMessage(content=text, additional_kwargs=self.additional_kwargs)


class SystemMessagePromptTemplate(BaseStringMessagePromptTemplate):
    def format(self, **kwargs: Any) -> BaseMessage:
        text = self.prompt.format(**kwargs)
        return SystemMessage(content=text, additional_kwargs=self.additional_kwargs)


class ChatPromptValue(PromptValue):
    messages: List[BaseMessage]

    def to_string(self) -> str:
        """Return prompt as string."""
        return get_buffer_string(self.messages)

    def to_messages(self) -> List[BaseMessage]:
        """Return prompt as messages."""
        return self.messages


class BaseChatPromptTemplate(BasePromptTemplate, ABC):
    def format(self, **kwargs: Any) -> str:
        return self.format_prompt(**kwargs).to_string()

    def format_prompt(self, **kwargs: Any) -> PromptValue:
        messages = self.format_messages(**kwargs)
        return ChatPromptValue(messages=messages)

    @abstractmethod
    def format_messages(self, **kwargs: Any) -> List[BaseMessage]:
        """Format kwargs into a list of messages."""


class ChatPromptTemplate(BaseChatPromptTemplate, ABC):
    input_variables: List[str]
    messages: List[Union[BaseMessagePromptTemplate, BaseMessage, AIMessagePromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate]]

    @classmethod
    def from_role_strings(
        cls, string_messages: List[Tuple[str, str]]
    ) -> ChatPromptTemplate:
        messages = [
            ChatMessagePromptTemplate(
                content=PromptTemplate.from_template(template), role=role
            )
            for role, template in string_messages
        ]
        return cls.from_messages(messages)

    @classmethod
    def from_strings(
        cls, string_messages: List[Tuple[Type[BaseMessagePromptTemplate], str]]
    ) -> ChatPromptTemplate:
        messages = [
            role(content=PromptTemplate.from_template(template))
            for role, template in string_messages
        ]
        return cls.from_messages(messages)

    @classmethod
    def from_messages(
        cls, messages: Sequence[Union[BaseMessagePromptTemplate, BaseMessage]]
    ) -> ChatPromptTemplate:
        input_vars = set()
        for message in messages:
            if isinstance(message, BaseMessagePromptTemplate):
                input_vars.update(message.input_variables)
        return cls(input_variables=list(input_vars), messages=messages)

    def format(self, **kwargs: Any) -> str:
        return self.format_prompt(**kwargs).to_string()

    def format_messages(self, **kwargs: Any) -> List[BaseMessage]:
        kwargs = self._merge_partial_and_user_variables(**kwargs)
        result = []
        for message_template in self.messages:
            if isinstance(message_template, BaseMessage):
                result.extend([message_template])
            elif isinstance(message_template, BaseMessagePromptTemplate):
                rel_params = {
                    k: v
                    for k, v in kwargs.items()
                    if k in message_template.input_variables
                }
                message = message_template.format_messages(**rel_params)
                result.extend(message)
            else:
                raise ValueError(f"Unexpected input: {message_template}")
        return result

    def partial(self, **kwargs: Union[str, Callable[[], str]]) -> BasePromptTemplate:
        raise NotImplementedError

    @property
    def _prompt_type(self) -> str:
        """Return the prompt type key."""
        return "chatPrompt"

    def dict(self, **kwargs: Any) -> Dict:
        prompt_dict = json.loads(self.json())

        prompt_dict["_type"] = self._prompt_type
        for i, message in enumerate(self.messages):
            if isinstance(message, SystemMessagePromptTemplate):
                prompt_dict['messages'][i]['prompt']['role'] = 'system'
            elif isinstance(message, HumanMessagePromptTemplate):
                prompt_dict['messages'][i]['prompt']['role'] = 'human'
            elif isinstance(message, AIMessagePromptTemplate):
                prompt_dict['messages'][i]['prompt']['role'] = 'ai'

        return prompt_dict

    def save(self, file_path: Union[Path, str]) -> None:
        if isinstance(file_path, str):
            save_path = Path(file_path)
        else:
            save_path = file_path

        directory_path = save_path.parent
        directory_path.mkdir(parents=True, exist_ok=True)

        # Fetch dictionary to save
        prompt_dict = self.dict()

        if save_path.suffix == ".json":
            with open(file_path, "w") as f:
                json.dump(prompt_dict, f, indent=4)
        elif save_path.suffix == ".yaml":
            with open(file_path, "w") as f:
                yaml.dump(prompt_dict, f, default_flow_style=False)
        else:
            raise ValueError(f"{save_path} must be json or yaml")
