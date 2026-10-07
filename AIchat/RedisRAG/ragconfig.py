import redis
from langchain_ollama import OllamaEmbeddings


def get_redis_url(url):
     return url


def load_embedding(model, base_url):
    embedding_model = OllamaEmbeddings(
        model=model,
        base_url=base_url,
    )
    return embedding_model