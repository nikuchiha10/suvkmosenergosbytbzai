import sqlite3
import json
import os
import shutil
from datetime import datetime
from config import USER_DB_FILE, KNOWLEDGE_FILE, TEMP_KNOWLEDGE_FILE, BACKUP_KNOWLEDGE_FILE

class DatabaseManager:
    """Класс для управления базой данных и файлами"""
    
    @staticmethod
    def init_database():
        """Инициализация базы данных пользователей"""
        conn = sqlite3.connect(USER_DB_FILE)
        cursor = conn.cursor()
        
        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                is_admin BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица статистики
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE DEFAULT CURRENT_DATE,
                total_questions INTEGER DEFAULT 0,
                correct_answers INTEGER DEFAULT 0,
                accuracy_rate REAL DEFAULT 0
            )
        ''')
        
        # Таблица обратной связи
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                question TEXT,
                bot_response TEXT,
                is_correct BOOLEAN,
                correct_answer TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def update_user_activity(user_id, username, first_name, is_admin=False):
        """Обновляет активность пользователя"""
        conn = sqlite3.connect(USER_DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO users 
            (user_id, username, first_name, is_admin, last_activity) 
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, username, first_name, is_admin))
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_user_stats(user_id):
        """Получает статистику пользователя"""
        conn = sqlite3.connect(USER_DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM feedback 
            WHERE user_id = ?
        ''', (user_id,))
        total_questions = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT COUNT(*) FROM feedback 
            WHERE user_id = ? AND is_correct = 1
        ''', (user_id,))
        correct_answers = cursor.fetchone()[0]
        
        conn.close()
        
        accuracy = (correct_answers / total_questions * 100) if total_questions > 0 else 0
        
        return {
            'total_questions': total_questions,
            'correct_answers': correct_answers,
            'accuracy': accuracy
        }
    
    @staticmethod
    def save_feedback(user_id, question, bot_response, is_correct, correct_answer=None):
        """Сохраняет обратную связь по ответу"""
        conn = sqlite3.connect(USER_DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO feedback 
            (user_id, question, bot_response, is_correct, correct_answer)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, question, bot_response, is_correct, correct_answer))
        
        # Обновляем дневную статистику
        today = datetime.now().date().isoformat()
        cursor.execute('''
            INSERT OR REPLACE INTO statistics 
            (date, total_questions, correct_answers, accuracy_rate)
            SELECT 
                ?, 
                COUNT(*),
                SUM(CASE WHEN is_correct THEN 1 ELSE 0 END),
                CAST(SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS REAL) / COUNT(*) * 100
            FROM feedback 
            WHERE DATE(created_at) = ?
        ''', (today, today))
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_daily_stats(days=7):
        """Получает статистику за последние N дней"""
        conn = sqlite3.connect(USER_DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT date, total_questions, correct_answers, accuracy_rate
            FROM statistics 
            WHERE date >= date('now', ?) 
            ORDER BY date DESC
        ''', (f'-{days} days',))
        
        stats = cursor.fetchall()
        conn.close()
        
        return [
            {
                'date': row[0],
                'total_questions': row[1],
                'correct_answers': row[2],
                'accuracy_rate': row[3]
            }
            for row in stats
        ]
    
    @staticmethod
    def get_knowledge_stats():
        """Получает статистику базы знаний"""
        try:
            with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
            
            articles = content.split('==================================================')
            article_count = len([a for a in articles if a.strip()])
            
            # Подсчет примерного количества символов
            total_chars = len(content)
            total_words = len(content.split())
            
            # Поиск времени последнего обновления
            last_update = "Неизвестно"
            for line in content.split('\n'):
                if 'ОБНОВЛЕНО' in line:
                    last_update = line.split('ОБНОВЛЕНО ')[1].strip()
                    break
            
            return {
                'article_count': article_count,
                'total_chars': total_chars,
                'total_words': total_words,
                'last_update': last_update
            }
        except FileNotFoundError:
            return {
                'article_count': 0,
                'total_chars': 0,
                'total_words': 0,
                'last_update': "Файл не найден"
            }

class FileManager:
    """Класс для управления файлами базы знаний"""
    
    @staticmethod
    def create_backup():
        """Создает резервную копию базы знаний"""
        try:
            if os.path.exists(KNOWLEDGE_FILE):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_name = f"database/knowledge_backup_{timestamp}.txt"
                shutil.copy2(KNOWLEDGE_FILE, backup_name)
                return True, f"Резервная копия создана: {backup_name}"
            return False, "Файл базы знаний не найден"
        except Exception as e:
            return False, f"Ошибка создания резервной копии: {str(e)}"
    
    @staticmethod
    def restore_backup(backup_file=None):
        """Восстанавливает базу знаний из резервной копии"""
        try:
            if backup_file is None:
                backup_file = BACKUP_KNOWLEDGE_FILE
            
            if os.path.exists(backup_file):
                shutil.copy2(backup_file, KNOWLEDGE_FILE)
                return True, f"База восстановлена из: {backup_file}"
            return False, "Файл резервной копии не найден"
        except Exception as e:
            return False, f"Ошибка восстановления: {str(e)}"
    
    @staticmethod
    def export_knowledge(format_type='txt'):
        """Экспортирует базу знаний в указанном формате"""
        try:
            with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            if format_type == 'json':
                # Преобразуем в JSON структуру
                articles = content.split('==================================================')
                json_data = {
                    'export_time': datetime.now().isoformat(),
                    'article_count': len([a for a in articles if a.strip()]),
                    'articles': []
                }
                
                for i, article in enumerate(articles):
                    if article.strip():
                        lines = article.split('\n')
                        title = "Статья без заголовка"
                        for line in lines:
                            if 'СТАТЬЯ' in line and ':' in line:
                                title = line.split(':', 1)[1].strip()
                                break
                        
                        json_data['articles'].append({
                            'id': i + 1,
                            'title': title,
                            'content': article.strip()
                        })
                
                filename = f"knowledge_export_{timestamp}.json"
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(json_data, f, ensure_ascii=False, indent=2)
                
            else:  # txt format
                filename = f"knowledge_export_{timestamp}.txt"
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(content)
            
            return True, filename
            
        except Exception as e:
            return False, f"Ошибка экспорта: {str(e)}"
    
    @staticmethod
    def import_knowledge(file_path):
        """Импортирует базу знаний из файла"""
        try:
            if file_path.endswith('.json'):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                content = "=== БАЗА ЗНАНИЙ - ИМПОРТИРОВАНО ===\n"
                content += f"Время импорта: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                content += f"Источник: {file_path}\n"
                content += "==================================================\n"
                
                for article in data.get('articles', []):
                    content += f"СТАТЬЯ {article['id']}: {article['title']}\n"
                    content += article['content'] + "\n"
                    content += "==================================================\n"
            
            else:  # txt format
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            
            # Создаем резервную копию перед импортом
            FileManager.create_backup()
            
            # Записываем новую базу
            with open(KNOWLEDGE_FILE, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return True, "База знаний успешно импортирована"
            
        except Exception as e:
            return False, f"Ошибка импорта: {str(e)}"
    
    @staticmethod
    def cleanup_old_backups(max_backups=5):
        """Очищает старые резервные копии, оставляя только последние max_backups"""
        try:
            backup_files = []
            for filename in os.listdir('database'):
                if filename.startswith('knowledge_backup_') and filename.endswith('.txt'):
                    filepath = os.path.join('database', filename)
                    backup_files.append((filepath, os.path.getctime(filepath)))
            
            # Сортируем по дате создания (новые сначала)
            backup_files.sort(key=lambda x: x[1], reverse=True)
            
            # Удаляем старые файлы
            for filepath, _ in backup_files[max_backups:]:
                os.remove(filepath)
                print(f"Удален старый backup: {filepath}")
            
            return True, f"Оставлено {min(len(backup_files), max_backups)} резервных копий"
            
        except Exception as e:
            return False, f"Ошибка очистки backup: {str(e)}"

class KnowledgeAnalyzer:
    """Класс для анализа базы знаний"""
    
    @staticmethod
    def analyze_coverage():
        """Анализирует покрытие тем в базе знаний"""
        try:
            with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Ключевые темы для анализа
            topics = {
                'Показания ПУ': ['показания', 'счетчик', 'ИПУ', 'передать показания'],
                'Оплата': ['оплата', 'платеж', 'квитанция', 'ЕПД'],
                'Задолженность': ['задолженность', 'долг', 'работа с должниками'],
                'Техподдержка': ['техническая поддержка', 'ЛКК', 'сбой', 'ошибка'],
                'Договоры': ['договор', 'лицевой счет', 'переоформление'],
                'Тарифы': ['тариф', 'стоимость', 'цена', 'начисление'],
                'Качество услуг': ['качество', 'жалоба', 'перерасчет', 'ненадлежащее качество']
            }
            
            coverage = {}
            content_lower = content.lower()
            
            for topic, keywords in topics.items():
                keyword_count = 0
                for keyword in keywords:
                    keyword_count += content_lower.count(keyword.lower())
                
                coverage[topic] = {
                    'keyword_count': keyword_count,
                    'coverage_level': 'высокое' if keyword_count > 10 else 'среднее' if keyword_count > 3 else 'низкое'
                }
            
            return coverage
            
        except Exception as e:
            return {"error": str(e)}
    
    @staticmethod
    def find_gaps(user_questions):
        """Находит пробелы в базе знаний на основе вопросов пользователей"""
        try:
            with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
                content = f.read().lower()
            
            gaps = []
            for question in user_questions:
                question_lower = question.lower()
                
                # Проверяем, есть ли ответ в базе
                found = False
                for keyword in question_lower.split():
                    if len(keyword) > 4 and keyword in content:
                        found = True
                        break
                
                if not found:
                    gaps.append(question)
            
            return gaps
            
        except Exception as e:
            return {"error": str(e)}
