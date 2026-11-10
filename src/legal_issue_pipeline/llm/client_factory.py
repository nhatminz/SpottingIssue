from __future__ import annotations
import asyncio
from ..config import PipelineConfig
from .openai_client import OpenAICompatibleClient


class ClientFactory:
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.semaphore = asyncio.Semaphore(config.max_concurrent_requests)
        self.tokenizer = None
        if config.tokenizer_path:
            from transformers import AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(config.tokenizer_path, local_files_only=True, trust_remote_code=False)

    def create(self, role: str) -> OpenAICompatibleClient:
        return OpenAICompatibleClient(getattr(self.config, role), self.config, self.semaphore, role, tokenizer=self.tokenizer)
