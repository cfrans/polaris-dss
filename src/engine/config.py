from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Polaris DSS Configuration Settings.
    Loads configurations from environment variables.
    """
    
    # Zabbix Integration
    zabbix_url: str
    zabbix_user: str
    zabbix_password: str
    
    # Database Configuration
    database_url: str
    
    # Heuristics Engine
    rules_path: str = "knowledge_base/rules.json"
    log_level: str = "INFO"
    remediation_timeout: int = 30

settings = Settings()
