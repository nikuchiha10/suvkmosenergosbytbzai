import os
import time
import logging
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from config import LOGIN_URL, BASE_URL, KNOWLEDGE_FILE, TEMP_KNOWLEDGE_FILE

logger = logging.getLogger(__name__)

class EnhancedParser:
    """Расширенный парсер для сбора базы знаний"""
    
    def __init__(self):
        self.driver = None
        self.articles_collected = 0
        
    def setup_driver(self, headless=True):
        """Настраивает веб-драйвер"""
        try:
            options = Options()
            if headless:
                options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            
            self.driver = webdriver.Chrome(options=options)
            self.driver.implicitly_wait(10)
            logger.info("Веб-драйвер успешно запущен")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка запуска веб-драйвера: {e}")
            return False
    
    def wait_for_login(self, timeout=300):
        """Ожидает ручного входа пользователя"""
        logger.info("Ожидание ручного входа пользователя...")
        
        try:
            # Ждем, пока пользователь перейдет на нужную страницу после логина
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CLASS_NAME, "content-space"))
            )
            logger.info("Успешный вход обнаружен")
            return True
            
        except TimeoutException:
            logger.error("Таймаут ожидания входа")
            return False
    
    def collect_articles_from_space(self, space_url):
        """Собирает статьи из пространства"""
        try:
            self.driver.get(space_url)
            time.sleep(3)
            
            articles_data = []
            
            # Поиск ссылок на статьи
            article_links = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/article/']")
            logger.info(f"Найдено ссылок на статьи: {len(article_links)}")
            
            for i, link in enumerate(article_links[:50]):  # Ограничиваем для демо
                try:
                    article_url = link.get_attribute('href')
                    article_title = link.text.strip()
                    
                    if article_url and article_title:
                        article_content = self.extract_article_content(article_url)
                        if article_content:
                            articles_data.append({
                                'url': article_url,
                                'title': article_title,
                                'content': article_content,
                                'collected_at': datetime.now().isoformat()
                            })
                            self.articles_collected += 1
                            logger.info(f"Собрана статья {self.articles_collected}: {article_title}")
                    
                    # Небольшая пауза между запросами
                    time.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Ошибка при сборе статьи {i}: {e}")
                    continue
            
            return articles_data
            
        except Exception as e:
            logger.error(f"Ошибка сбора статей: {e}")
            return []
    
    def extract_article_content(self, article_url):
        """Извлекает содержание статьи"""
        try:
            self.driver.get(article_url)
            time.sleep(2)
            
            content_parts = []
            
            # Заголовок
            try:
                title = self.driver.find_element(By.TAG_NAME, 'h1').text
                content_parts.append(f"ЗАГОЛОВОК: {title}")
            except NoSuchElementException:
                content_parts.append("ЗАГОЛОВОК: Не указан")
            
            # Основное содержание
            try:
                # Пытаемся найти различные элементы с контентом
                content_selectors = [
                    '.article-content',
                    '.content',
                    '.main-content',
                    'article',
                    '[role="main"]'
                ]
                
                for selector in content_selectors:
                    try:
                        content_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        for element in content_elements:
                            text = element.text.strip()
                            if text and len(text) > 50:
                                content_parts.append(f"СОДЕРЖАНИЕ:\n{text}")
                                break
                        if len(content_parts) > 1:  # Если нашли контент
                            break
                    except:
                        continue
                
                # Если не нашли структурированный контент, берем весь текст body
                if len(content_parts) <= 1:
                    body_text = self.driver.find_element(By.TAG_NAME, 'body').text
                    # Фильтруем полезный контент
                    lines = body_text.split('\n')
                    useful_lines = [line.strip() for line in lines if len(line.strip()) > 20]
                    if useful_lines:
                        content_parts.append(f"СОДЕРЖАНИЕ:\n{' '.join(useful_lines[:20])}")
                
            except Exception as e:
                logger.warning(f"Не удалось извлечь содержание: {e}")
                content_parts.append("СОДЕРЖАНИЕ: Не удалось загрузить")
            
            return '\n'.join(content_parts)
            
        except Exception as e:
            logger.error(f"Ошибка извлечения контента: {e}")
            return None
    
    def format_articles_to_knowledge(self, articles_data):
        """Форматирует собранные статьи в формат базы знаний"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        knowledge_content = f"""=== БАЗА ЗНАНИЙ - АВТОМАТИЧЕСКИЙ СБОР ===
Время сбора: {timestamp}
Обработано статей: {len(articles_data)}
Источник: {BASE_URL}
==================================================

"""
        
        for i, article in enumerate(articles_data, 1):
            knowledge_content += f"""СТАТЬЯ {i}: {article['title']}
URL: {article['url']}
Заголовок: {article['title']}
Время обработки: {datetime.now().strftime('%H:%M:%S')}
---
{article['content']}
---
==================================================

"""
        
        return knowledge_content
    
    def run_full_parsing(self):
        """Запускает полный процесс парсинга"""
        try:
            logger.info("Запуск расширенного парсинга...")
            
            # Настройка драйвера
            if not self.setup_driver(headless=False):  # Не headless для ручного входа
                return False
            
            # Переход на страницу логина
            self.driver.get(LOGIN_URL)
            logger.info("Открыта страница логина")
            
            # Ожидание ручного входа
            if not self.wait_for_login():
                self.driver.quit()
                return False
            
            # Сбор статей
            articles_data = self.collect_articles_from_space(BASE_URL)
            
            if not articles_data:
                logger.warning("Не удалось собрать статьи")
                self.driver.quit()
                return False
            
            # Форматирование в базу знаний
            knowledge_content = self.format_articles_to_knowledge(articles_data)
            
            # Сохранение во временный файл
            with open(TEMP_KNOWLEDGE_FILE, 'w', encoding='utf-8') as f:
                f.write(knowledge_content)
            
            logger.info(f"Успешно собрано {self.articles_collected} статей")
            
            # Закрытие драйвера
            self.driver.quit()
            
            return True
            
        except Exception as e:
            logger.error(f"Критическая ошибка парсинга: {e}")
            if self.driver:
                self.driver.quit()
            return False

class SmartParser:
    """Умный парсер с обработкой различных структур сайта"""
    
    @staticmethod
    def parse_existing_knowledge():
        """Парсит существующий файл знаний для анализа"""
        try:
            with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
            
            articles = content.split('==================================================')
            parsed_data = []
            
            for article in articles:
                if not article.strip():
                    continue
                
                article_data = {
                    'title': SmartParser.extract_field(article, 'СТАТЬЯ', 'Заголовок'),
                    'url': SmartParser.extract_field(article, 'URL'),
                    'content': SmartParser.extract_content(article),
                    'has_script': SmartParser.has_operator_script(article),
                    'word_count': len(article.split()),
                    'top_keywords': SmartParser.extract_keywords(article)
                }
                
                parsed_data.append(article_data)
            
            return parsed_data
            
        except Exception as e:
            logger.error(f"Ошибка анализа базы знаний: {e}")
            return []
    
    @staticmethod
    def extract_field(article, field_name, alternative_field=None):
        """Извлекает поле из статьи"""
        lines = article.split('\n')
        for line in lines:
            if field_name in line and ':' in line:
                return line.split(':', 1)[1].strip()
        
        if alternative_field:
            for line in lines:
                if alternative_field in line and ':' in line:
                    return line.split(':', 1)[1].strip()
        
        return "Не указано"
    
    @staticmethod
    def extract_content(article):
        """Извлекает основное содержание"""
        lines = article.split('\n')
        content_lines = []
        in_content = False
        
        for line in lines:
            if 'СОДЕРЖАНИЕ:' in line or '---' in line:
                in_content = True
                continue
            if in_content and line.strip():
                if '===' in line or '---' in line:
                    break
                content_lines.append(line.strip())
        
        return ' '.join(content_lines)
    
    @staticmethod
    def has_operator_script(article):
        """Проверяет наличие скрипта для оператора"""
        keywords = ['сказать', 'рекомендовать', 'советовать', 'информировать', 'объяснить']
        article_lower = article.lower()
        return any(keyword in article_lower for keyword in keywords)
    
    @staticmethod
    def extract_keywords(article, top_n=10):
        """Извлекает ключевые слова из статьи"""
        from collections import Counter
        import re
        
        # Убираем стоп-слова
        stop_words = {'и', 'в', 'во', 'не', 'что', 'он', 'на', 'я', 'с', 'со', 'как', 'а', 'то', 'все', 'она', 'так', 'его', 'но', 'да', 'ты', 'к', 'у', 'же', 'вы', 'за', 'бы', 'по', 'только', 'ее', 'мне', 'было', 'вот', 'от', 'меня', 'еще', 'нет', 'о', 'из', 'ему', 'теперь', 'когда', 'даже', 'ну', 'ли', 'если', 'уже', 'или', 'ни', 'быть', 'был', 'него', 'до', 'вас', 'нибудь', 'опять', 'уж', 'вам', 'ведь', 'там', 'потом', 'себя', 'ничего', 'ей', 'может', 'они', 'тут', 'где', 'есть', 'надо', 'ней', 'для', 'мы', 'тебя', 'их', 'чем', 'была', 'сам', 'чтоб', 'без', 'будто', 'чего', 'раз', 'тоже', 'себе', 'под', 'будет', 'ж', 'тогда', 'кто', 'этот', 'того', 'потому', 'этого', 'какой', 'совсем', 'ним', 'здесь', 'этом', 'один', 'почти', 'мой', 'тем', 'чтобы', 'неё', 'сейчас', 'были', 'куда', 'зачем', 'всех', 'никогда', 'можно', 'при', 'наконец', 'два', 'об', 'другой', 'хоть', 'после', 'над', 'больше', 'тот', 'через', 'эти', 'нас', 'про', 'всего', 'них', 'какая', 'много', 'разве', 'три', 'эту', 'моя', 'впрочем', 'хорошо', 'свою', 'этой', 'перед', 'иногда', 'лучше', 'чуть', 'том', 'нельзя', 'такой', 'им', 'более', 'всегда', 'конечно', 'всю', 'между'}
        
        words = re.findall(r'\b[а-яё]{4,}\b', article.lower())
        filtered_words = [word for word in words if word not in stop_words]
        
        word_freq = Counter(filtered_words)
        return word_freq.most_common(top_n)
