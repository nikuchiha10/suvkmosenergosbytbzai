import os

# Токены API
TELEGRAM_BOT_TOKEN = "8368664214:AAHDLlSrAcxS4MkZYcrScpt0-o72mcQCRt4"
HUGGINGFACE_API_KEY = "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"

# Пути к файлам
KNOWLEDGE_FILE = "database/knowledge.txt"
TEMP_KNOWLEDGE_FILE = "database/temp_knowledge.txt"
BACKUP_KNOWLEDGE_FILE = "database/knowledge_backup.txt"
USER_DB_FILE = "database/users.db"

# ID администраторов (замените на реальные ID)
ADMIN_IDS = [6910167987]

# Настройки парсера
LOGIN_URL = "https://mes1-kms.interrao.ru"
BASE_URL = "https://mes1-kms.interrao.ru/content/space/7"

# Настройки нейросети
HUGGINGFACE_API_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-cnn"
MAX_RESPONSE_LENGTH = 1000
