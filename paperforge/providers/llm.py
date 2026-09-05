import os
import json
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
import requests

class LLMProvider(ABC):
    @abstractmethod
    def complete(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        pass

    @abstractmethod
    def complete_with_vision(self, prompt: str, image_path: str, system_prompt: Optional[str] = None) -> str:
        pass

    @abstractmethod
    def check_health(self) -> Dict[str, Any]:
        """Returns {'status': bool, 'message': str}"""
        pass


class OllamaProvider(LLMProvider):
    def __init__(self, host: str = "http://localhost:11434", model: str = "llama3.2"):
        self.host = host.rstrip("/")
        self.model = model

    def check_health(self) -> Dict[str, Any]:
        try:
            res = requests.get(f"{self.host}/api/tags", timeout=3)
            if res.status_code == 200:
                models = [m.get("name") for m in res.json().get("models", [])]
                return {"status": True, "message": f"Reachable. Models available: {models}"}
            return {"status": False, "message": f"HTTP {res.status_code}: {res.text}"}
        except Exception as e:
            return {"status": False, "message": f"Unreachable at {self.host}: {str(e)}"}

    def complete(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False
        }
        if system_prompt:
            payload["system"] = system_prompt
        res = requests.post(f"{self.host}/api/generate", json=payload, timeout=120)
        res.raise_for_status()
        return res.json().get("response", "")

    def complete_with_vision(self, prompt: str, image_path: str, system_prompt: Optional[str] = None) -> str:
        import base64
        with open(image_path, "rb") as f:
            b64_img = base64.b64encode(f.read()).decode("utf-8")
        payload = {
            "model": self.model,
            "prompt": prompt,
            "images": [b64_img],
            "stream": False
        }
        if system_prompt:
            payload["system"] = system_prompt
        res = requests.post(f"{self.host}/api/generate", json=payload, timeout=120)
        res.raise_for_status()
        return res.json().get("response", "")


class CloudAPIProvider(LLMProvider):
    def __init__(self, provider_name: str, api_key_env: str, default_model: str):
        self.provider_name = provider_name
        self.api_key_env = api_key_env
        self.api_key = os.getenv(api_key_env, "")
        self.default_model = default_model

    def check_health(self) -> Dict[str, Any]:
        if not self.api_key:
            return {"status": False, "message": f"Missing environment key: {self.api_key_env}"}
        return {"status": True, "message": f"API key configured for {self.provider_name} ({self.default_model})"}

    def complete(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if not self.api_key:
            raise ValueError(f"Missing API key environment variable {self.api_key_env}")
        
        # Simplified fallback for cloud API completion
        if self.provider_name == "openai" or self.provider_name == "groq" or self.provider_name == "openrouter":
            base_url = "https://api.openai.com/v1"
            if self.provider_name == "groq":
                base_url = "https://api.groq.com/openai/v1"
            elif self.provider_name == "openrouter":
                base_url = "https://openrouter.ai/api/v1"

            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            res = requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json={"model": self.default_model, "messages": messages},
                timeout=60
            )
            res.raise_for_status()
            return res.json()["choices"][0]["message"]["content"]
        else:
            return f"[{self.provider_name} completion placeholder for prompt: {prompt[:50]}...]"

    def complete_with_vision(self, prompt: str, image_path: str, system_prompt: Optional[str] = None) -> str:
        return self.complete(f"[Vision query for {image_path}]: {prompt}", system_prompt=system_prompt)


def get_llm_provider(config: Dict[str, Any]) -> LLMProvider:
    llm_cfg = config.get("llm", {})
    provider = llm_cfg.get("provider", "ollama").lower()
    
    if provider == "ollama":
        return OllamaProvider(
            host=llm_cfg.get("host", "http://localhost:11434"),
            model=llm_cfg.get("model", "llama3.2")
        )
    elif provider == "gemini":
        return CloudAPIProvider("gemini", "GEMINI_API_KEY", llm_cfg.get("model", "gemini-1.5-flash"))
    elif provider == "groq":
        return CloudAPIProvider("groq", "GROQ_API_KEY", llm_cfg.get("model", "llama-3.1-70b-versatile"))
    elif provider == "openrouter":
        return CloudAPIProvider("openrouter", "OPENROUTER_API_KEY", llm_cfg.get("model", "meta-llama/llama-3.1-8b-instruct:free"))
    elif provider == "anthropic":
        return CloudAPIProvider("anthropic", "ANTHROPIC_API_KEY", llm_cfg.get("model", "claude-3-5-sonnet-20240620"))
    elif provider == "openai":
        return CloudAPIProvider("openai", "OPENAI_API_KEY", llm_cfg.get("model", "gpt-4o-mini"))
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")
