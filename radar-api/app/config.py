from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Auth
    api_key: str = "changeme"

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://radar:radar@postgres:5432/radar"
    database_url_sync: str = "postgresql+psycopg2://radar:radar@postgres:5432/radar"

    # Groq (primary whisper)
    groq_api_key: str = ""
    groq_whisper_model: str = "whisper-large-v3-turbo"

    # Gemini (fallback LLM enrichment)
    gemini_api_key: str = ""

    # Ollama (legacy, unused)
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.1:8b"

    # ChromaDB
    chromadb_url: str = "http://chromadb:8000"

    # CalDAV (Apple iCloud)
    caldav_url: str = ""
    caldav_username: str = ""
    caldav_password: str = ""
    caldav_calendar: str = "WhatsOrga"
    caldav_suggest_calendar: str = "WhatsOrga ?"
    termin_auto_confidence: float = 0.85
    termin_user_name: str = ""
    termin_partner_name: str = ""
    termin_children_names: str = ""  # comma-separated
    termin_family_context: str = ""  # custom family context for LLM prompt

    # EverMemOS (semantic context memory)
    evermemos_url: str = "http://evermemos:8001"
    evermemos_enabled: bool = True

    # Marker registry
    marker_registry_path: str = "data/marker_registry_radar.json"

    model_config = {"env_prefix": "RADAR_"}


settings = Settings()
