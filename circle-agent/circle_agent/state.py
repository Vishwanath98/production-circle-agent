import operator

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class CircleState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    final: dict
