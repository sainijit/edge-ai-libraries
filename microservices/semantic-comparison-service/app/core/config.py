"""Application configuration management."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Service configuration
    service_name: str = Field(default="semantic-search-agent", alias="SERVICE_NAME")
    service_version: str = Field(default="1.0.0", alias="SERVICE_VERSION")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_port: int = Field(default=8080, alias="API_PORT")
    metrics_port: int = Field(default=9090, alias="METRICS_PORT")
    
    # VLM backend configuration
    vlm_backend: Literal["ovms", "openvino_local", "openai"] = Field(
        default="ovms", alias="VLM_BACKEND"
    )
    
    # OVMS configuration
    ovms_endpoint: str = Field(default="http://ovms-vlm:8000", alias="OVMS_ENDPOINT")
    ovms_model_name: str = Field(default="Qwen2-VL-2B-Instruct", alias="OVMS_MODEL_NAME")
    ovms_timeout: int = Field(default=30, alias="OVMS_TIMEOUT")
    
    # OpenVINO local configuration
    openvino_model_path: str = Field(
        default="/models/Qwen2-VL-2B-Instruct", alias="OPENVINO_MODEL_PATH"
    )
    openvino_device: str = Field(default="GPU", alias="OPENVINO_DEVICE")
    openvino_max_new_tokens: int = Field(default=512, alias="OPENVINO_MAX_NEW_TOKENS")
    openvino_temperature: float = Field(default=0.0, alias="OPENVINO_TEMPERATURE")
    
    # OpenAI configuration
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    openai_max_tokens: int = Field(default=100, alias="OPENAI_MAX_TOKENS")
    
    # Cache configuration
    cache_enabled: bool = Field(default=True, alias="CACHE_ENABLED")
    cache_backend: Literal["memory", "redis"] = Field(default="memory", alias="CACHE_BACKEND")
    redis_host: str = Field(default="redis", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")
    cache_ttl: int = Field(default=3600, alias="CACHE_TTL")
    
    # Matching configuration
    default_matching_strategy: Literal["exact", "semantic", "hybrid"] = Field(
        default="hybrid", alias="DEFAULT_MATCHING_STRATEGY"
    )
    confidence_threshold: float = Field(default=0.85, alias="CONFIDENCE_THRESHOLD")
    max_retries: int = Field(default=2, alias="MAX_RETRIES")
    
    # Metrics
    prometheus_enabled: bool = Field(default=True, alias="PROMETHEUS_ENABLED")
    
    # Paths
    config_dir: Path = Field(default=Path(__file__).parent.parent.parent / "config")
    orders_file: Path | None = Field(default=None)
    inventory_file: Path | None = Field(default=None)
    
    def __init__(self, **data):
        """Initialize settings with paths."""
        super().__init__(**data)
        # Set default paths if not provided
        if self.orders_file is None:
            self.orders_file = self.config_dir / "orders.json"
        if self.inventory_file is None:
            self.inventory_file = self.config_dir / "inventory.json"
    
    @classmethod
    def from_yaml(cls, config_path: Path) -> "Settings":
        """Load settings from YAML file."""
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f)
        
        # Flatten nested config for Pydantic
        flat_config = {}
        if "service" in config_data:
            flat_config.update(config_data["service"])
        if "vlm" in config_data:
            vlm_config = config_data["vlm"]
            flat_config["vlm_backend"] = vlm_config.get("backend", "ovms")
            
            if "ovms" in vlm_config:
                flat_config.update({f"ovms_{k}": v for k, v in vlm_config["ovms"].items()})
            if "openvino_local" in vlm_config:
                flat_config.update({f"openvino_{k}": v for k, v in vlm_config["openvino_local"].items()})
            if "openai" in vlm_config:
                flat_config.update({f"openai_{k}": v for k, v in vlm_config["openai"].items()})
        
        if "matching" in config_data:
            match_config = config_data["matching"]
            flat_config["default_matching_strategy"] = match_config.get("default_strategy", "hybrid")
            if "semantic_match" in match_config:
                flat_config.update({
                    "confidence_threshold": match_config["semantic_match"].get("confidence_threshold", 0.85),
                    "max_retries": match_config["semantic_match"].get("max_retries", 2),
                    "cache_ttl": match_config["semantic_match"].get("cache_ttl", 3600),
                })
        
        if "cache" in config_data:
            cache_config = config_data["cache"]
            flat_config["cache_enabled"] = cache_config.get("enabled", True)
            flat_config["cache_backend"] = cache_config.get("backend", "memory")
            flat_config["cache_ttl"] = cache_config.get("ttl", 3600)
            if "redis" in cache_config:
                flat_config.update({f"redis_{k}": v for k, v in cache_config["redis"].items()})
        
        if "metrics" in config_data:
            flat_config["prometheus_enabled"] = config_data["metrics"].get("enabled", True)
        
        return cls(**flat_config)


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    config_yaml = Path(__file__).parent.parent.parent / "config" / "service_config.yaml"
    
    if config_yaml.exists():
        return Settings.from_yaml(config_yaml)
    
    return Settings()


settings = get_settings()
