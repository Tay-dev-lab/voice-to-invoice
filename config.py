import os
from typing import List
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    # Server Configuration
    PORT = int(os.getenv("PORT", 8080))
    HOST = os.getenv("HOST", "0.0.0.0")
    
    # CORS Configuration
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
    
    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]
    
    # OpenAI Configuration
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    
    # Security Configuration
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", 30))
    RATE_LIMIT_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_HOUR", 100))
    
    # File Upload Settings
    MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", 10))
    MAX_AUDIO_DURATION_SECONDS = int(os.getenv("MAX_AUDIO_DURATION_SECONDS", 300))
    
    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024
    
    # Database Configuration
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./voice_invoice.db")
    
    # Logging Configuration
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "voice_invoice.log")
    
    def validate(self):
        """Validate required configuration"""
        if not self.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required. Set it as an environment variable.")
        
        if self.SECRET_KEY == "change-this-in-production":
            import warnings
            warnings.warn("Using default SECRET_KEY. Please set a secure key in production.")
    
    def validate_api_key_only(self):
        """Validate only the API key for runtime checks"""
        if not self.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required. Please set it in Railway environment variables.")

config = Config()