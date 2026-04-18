from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="local-voice-ai-pipeline", validation_alias="APP_NAME")
    app_env: str = Field(default="development", validation_alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", validation_alias="APP_HOST")
    app_port: int = Field(default=8000, validation_alias="APP_PORT")
    app_log_level: str = Field(default="INFO", validation_alias="APP_LOG_LEVEL")
    app_api_v1_prefix: str = Field(default="/api/v1", validation_alias="APP_API_V1_PREFIX")
    stt_provider: str = Field(default="whisper_cpp", validation_alias="STT_PROVIDER")
    whisper_cpp_binary_path: str | None = Field(
        default=None,
        validation_alias="WHISPER_CPP_BINARY_PATH",
    )
    whisper_cpp_model_path: str | None = Field(
        default=None,
        validation_alias="WHISPER_CPP_MODEL_PATH",
    )
    whisper_cpp_threads: int = Field(default=4, validation_alias="WHISPER_CPP_THREADS")
    whisper_cpp_language: str | None = Field(
        default=None,
        validation_alias="WHISPER_CPP_LANGUAGE",
    )
    upload_max_bytes: int = Field(default=10_485_760, validation_alias="UPLOAD_MAX_BYTES")
    llm_provider: str = Field(default="ollama", validation_alias="LLM_PROVIDER")
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="OLLAMA_BASE_URL",
    )
    ollama_model: str = Field(default="llama3.2:3b", validation_alias="OLLAMA_MODEL")
    llm_request_timeout_seconds: int = Field(
        default=30,
        ge=1,
        validation_alias="LLM_REQUEST_TIMEOUT_SECONDS",
    )
    session_history_limit: int = Field(default=10, ge=1, validation_alias="SESSION_HISTORY_LIMIT")
    tts_provider: str = Field(default="piper", validation_alias="TTS_PROVIDER")
    piper_binary_path: str | None = Field(default=None, validation_alias="PIPER_BINARY_PATH")
    piper_model_path: str | None = Field(default=None, validation_alias="PIPER_MODEL_PATH")
    audio_storage_dir: str = Field(default=".data/audio", validation_alias="AUDIO_STORAGE_DIR")
    audio_public_base_path: str = Field(
        default="/api/v1/audio",
        validation_alias="AUDIO_PUBLIC_BASE_PATH",
    )
    audio_file_ttl_seconds: int = Field(
        default=3600,
        ge=1,
        validation_alias="AUDIO_FILE_TTL_SECONDS",
    )
    trace_history_limit: int = Field(default=100, ge=1, validation_alias="TRACE_HISTORY_LIMIT")
    metrics_retention_limit: int = Field(
        default=500,
        ge=1,
        validation_alias="METRICS_RETENTION_LIMIT",
    )
    demo_runner_timeout_seconds: int = Field(
        default=60,
        ge=1,
        validation_alias="DEMO_RUNNER_TIMEOUT_SECONDS",
    )
    demo_mode: bool = Field(default=True, validation_alias="DEMO_MODE")
    demo_auto_cleanup_audio: bool = Field(
        default=True,
        validation_alias="DEMO_AUTO_CLEANUP_AUDIO",
    )
    demo_startup_validate_providers: bool = Field(
        default=True,
        validation_alias="DEMO_STARTUP_VALIDATE_PROVIDERS",
    )
    demo_samples_dir: str = Field(
        default=".data/demo_assets",
        validation_alias="DEMO_SAMPLES_DIR",
    )
    demo_samples_public_path: str = Field(
        default="/api/v1/demo/samples",
        validation_alias="DEMO_SAMPLES_PUBLIC_PATH",
    )
    demo_cleanup_interval_seconds: int = Field(
        default=300,
        ge=10,
        validation_alias="DEMO_CLEANUP_INTERVAL_SECONDS",
    )
    live_audio_enabled: bool = Field(default=True, validation_alias="LIVE_AUDIO_ENABLED")
    live_audio_max_seconds_per_utterance: float = Field(
        default=10.0,
        gt=0,
        validation_alias="LIVE_AUDIO_MAX_SECONDS_PER_UTTERANCE",
    )
    live_audio_min_seconds_per_utterance: float = Field(
        default=0.5,
        ge=0,
        validation_alias="LIVE_AUDIO_MIN_SECONDS_PER_UTTERANCE",
    )
    live_audio_max_queue_per_session: int = Field(
        default=5,
        ge=1,
        validation_alias="LIVE_AUDIO_MAX_QUEUE_PER_SESSION",
    )
    live_audio_autoplay_default: bool = Field(
        default=True,
        validation_alias="LIVE_AUDIO_AUTOPLAY_DEFAULT",
    )
    live_audio_silence_window_ms: int = Field(
        default=1200,
        ge=0,
        validation_alias="LIVE_AUDIO_SILENCE_WINDOW_MS",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
