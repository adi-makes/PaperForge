import os
import yaml
from typing import Dict, Any

DEFAULT_CONFIG = {
    "llm": {
        "provider": "ollama",
        "host": "http://localhost:11434",
        "model": "llama3.2"
    },
    "embeddings": {
        "provider": "local",
        "model": "BAAI/bge-small-en-v1.5"
    },
    "paths": {
        "sources_dir": "sources",
        "paper_dir": "paper",
        "assets_dir": "assets",
        "db_path": ".paperforge/paperforge.db"
    }
}

def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    if not os.path.exists(config_path):
        return DEFAULT_CONFIG.copy()
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    
    # Merge defaults
    merged = DEFAULT_CONFIG.copy()
    for k, v in data.items():
        if isinstance(v, dict) and k in merged:
            merged[k].update(v)
        else:
            merged[k] = v
    return merged
