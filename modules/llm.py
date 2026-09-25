from __future__ import annotations

# from langchain_openai import ChatOpenAI
# from langchain_ollama import ChatOllama

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from modules.config import get_logger
from modules.config import GROQ_API_KEY
from modules.config import OPENAI_API_KEY

logger = get_logger("llm")


def get_llm_openai() -> ChatOpenAI:
    """Create the OpenAI LLM."""

    return ChatOpenAI(
        model="gpt-5.6-luna",
        temperature=0.0,
    )

# def get_llm() -> ChatOllama:
#     """Create the local Ollama LLM."""
#     return ChatOllama(
#          model="gemma3:12b", 
#          # model="ministral-3:3b" 
#          #  model="qwen2.5:7b" temperature=0.0,
#         )  


def get_llm() -> ChatGroq:
    """Create the Groq LLM used for answer generation."""

    return ChatGroq(
        # model="llama-3.1-8b-instant",
        model ="openai/gpt-oss-120b",
        temperature=0.0,
        api_key=GROQ_API_KEY,
    )      


def test_llm():
    try:
        llm =get_llm_openai() 
        response =llm.invoke("What is AGI , in modern AI context?")
        print("API call successful")
        print("response: " , response.content)

    except Exception as e :
        print("api call failed")
        print(str(e))   


if __name__ =="__main__" :
    test_llm()


