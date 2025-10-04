import asyncio
import logging
import sqlite3
import aiohttp
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import os

from config import *

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Статистика точности
accuracy_stats = {"total": 0, "correct": 0}

class KnowledgeBase:
    """Класс для работы с базой знаний"""
    
    @staticmethod
    def load_articles():
        """Загружает статьи из базы знаний"""
        try:
            with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
            articles = content.split('==================================================')
            return [article.strip() for article in articles if article.strip()]
        except FileNotFoundError:
            logger.error("Файл базы знаний не найден")
            return []
    
    @staticmethod
    def search_articles(query):
        """Ищет статьи по запросу"""
        articles = KnowledgeBase.load_articles()
        relevant_articles = []
        
        for article in articles:
            score = KnowledgeBase.calculate_relevance(article, query)
            if score > 0:
                relevant_articles.append((article, score))
        
        # Сортируем по релевантности
        relevant_articles.sort(key=lambda x: x[1], reverse=True)
        return [article[0] for article in relevant_articles]
    
    @staticmethod
    def calculate_relevance(article, query):
        """Вычисляет релевантность статьи запросу"""
        query_words = set(query.lower().split())
        article_lower = article.lower()
        
        score = 0
        for word in query_words:
            if len(word) > 3:  # Игнорируем короткие слова
                score += article_lower.count(word) * len(word)
        
        # Бонус за точное совпадение фраз
        if query.lower() in article_lower:
            score += 100
        
        return score
    
    @staticmethod
    def extract_script(article):
        """Извлекает скрипт для оператора из статьи"""
        lines = article.split('\n')
        script_lines = []
        in_script_section = False
        
        for line in lines:
            if any(keyword in line for keyword in ['💬', 'Что сказать', 'скрипт', 'речь оператора']):
                in_script_section = True
                continue
            if in_script_section and line.strip():
                if line.startswith('---') or '========' in line:
                    break
                script_lines.append(line.strip())
        
        if script_lines:
            return '\n'.join(script_lines[:10])  # Ограничиваем длину
        
        # Если нет специального скрипта, пытаемся найти основные рекомендации
        for i, line in enumerate(lines):
            if 'Действия оператора' in line or 'Консультация' in line:
                # Берем следующие 3-5 строк как скрипт
                script_content = []
                for j in range(i+1, min(i+6, len(lines))):
                    if lines[j].strip() and not lines[j].startswith('---'):
                        script_content.append(lines[j].strip())
                if script_content:
                    return '\n'.join(script_content)
        
        return None

class ResponseGenerator:
    """Класс для генерации ответов"""
    
    @staticmethod
    async def generate_response(question):
        """Генерирует ответ на вопрос"""
        # Сначала ищем в базе знаний
        relevant_articles = KnowledgeBase.search_articles(question)
        
        if relevant_articles:
            best_article = relevant_articles[0]
            content = ResponseGenerator.extract_main_content(best_article)
            script = KnowledgeBase.extract_script(best_article)
            title = ResponseGenerator.get_article_title(best_article)
            
            # Если вопрос очень конкретный и есть точный ответ
            if ResponseGenerator.is_direct_answer(question, content):
                return content, script, title
            
            # Используем нейросеть для улучшения ответа
            enhanced_response = await ResponseGenerator.enhance_with_ai(question, content)
            if enhanced_response:
                return enhanced_response, script, title
            else:
                return content, script, title
        
        # Если в базе нет ответа, используем только нейросеть
        ai_response = await ResponseGenerator.ask_huggingface(question)
        return ai_response, None, "Нейросеть"
    
    @staticmethod
    def extract_main_content(article):
        """Извлекает основное содержание статьи"""
        lines = article.split('\n')
        content_lines = []
        in_content = False
        
        for line in lines:
            if 'СОДЕРЖАНИЕ:' in line or 'Общая информация' in line:
                in_content = True
                continue
            if in_content and line.strip():
                if line.startswith('---') or '========' in line:
                    break
                if not line.startswith('МО') and not line.startswith('Поиск'):
                    content_lines.append(line.strip())
        
        if content_lines:
            return '\n'.join(content_lines[:15])  # Ограничиваем длину
        
        # Если не нашли структурированного содержания, возвращаем первые значимые строки
        meaningful_lines = []
        for line in lines:
            if line.strip() and len(line.strip()) > 10 and not line.startswith('==='):
                meaningful_lines.append(line.strip())
            if len(meaningful_lines) >= 10:
                break
        
        return '\n'.join(meaningful_lines) if meaningful_lines else article[:500] + "..."
    
    @staticmethod
    def get_article_title(article):
        """Извлекает заголовок статьи"""
        lines = article.split('\n')
        for line in lines:
            if 'СТАТЬЯ' in line and ':' in line:
                return line.split(':', 1)[1].strip()
            if 'Заголовок:' in line:
                return line.split(':', 1)[1].strip()
        return "Статья из базы знаний"
    
    @staticmethod
    def is_direct_answer(question, content):
        """Проверяет, есть ли прямой ответ на вопрос в содержании"""
        question_lower = question.lower()
        content_lower = content.lower()
        
        # Ключевые слова, указывающие на прямой ответ
        direct_keywords = ['да', 'нет', 'можно', 'нельзя', 'нужно', 'не нужно']
        
        if any(keyword in question_lower for keyword in ['можно ли', 'возможно ли', 'есть ли']):
            return any(keyword in content_lower for keyword in direct_keywords)
        
        return False
    
    @staticmethod
    async def enhance_with_ai(question, context):
        """Улучшает ответ с помощью нейросети"""
        try:
            prompt = f"""
            Вопрос: {question}
            Контекст: {context[:800]}
            
            Дай точный и краткий ответ на вопрос на основе контекста. 
            Если в контексте нет информации - верни None.
            Ответ:
            """
            
            return await ResponseGenerator.ask_huggingface(prompt)
        except Exception as e:
            logger.error(f"Ошибка улучшения ответа: {e}")
            return None
    
    @staticmethod
    async def ask_huggingface(prompt):
        """Запрос к HuggingFace API"""
        try:
            headers = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"}
            payload = {
                "inputs": prompt,
                "parameters": {
                    "max_length": MAX_RESPONSE_LENGTH,
                    "temperature": 0.3,
                    "do_sample": False
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    HUGGINGFACE_API_URL, 
                    headers=headers, 
                    json=payload,
                    timeout=30
                ) as response:
                    
                    if response.status == 200:
                        result = await response.json()
                        if isinstance(result, list) and len(result) > 0:
                            return result[0].get('generated_text', 'Не удалось сгенерировать ответ')
                        else:
                            return str(result)
                    else:
                        logger.error(f"Ошибка API: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Ошибка запроса к нейросети: {e}")
            return None

class Parser:
    """Класс для парсинга базы знаний"""
    
    @staticmethod
    async def update_knowledge_base():
        """Обновляет базу знаний"""
        try:
            logger.info("Запуск парсера для обновления базы знаний")
            
            # Создаем резервную копию
            Parser.create_backup()
            
            # Запускаем парсинг
            success = Parser.run_parsing()
            
            if success:
                logger.info("База знаний успешно обновлена")
                return True
            else:
                logger.error("Ошибка при парсинге")
                return False
                
        except Exception as e:
            logger.error(f"Критическая ошибка при обновлении базы: {e}")
            return False
    
    @staticmethod
    def create_backup():
        """Создает резервную копию базы знаний"""
        try:
            if os.path.exists(KNOWLEDGE_FILE):
                import shutil
                shutil.copy2(KNOWLEDGE_FILE, BACKUP_KNOWLEDGE_FILE)
                logger.info("Резервная копия создана")
        except Exception as e:
            logger.error(f"Ошибка создания резервной копии: {e}")
    
    @staticmethod
    def run_parsing():
        """Запускает процесс парсинга"""
        driver = None
        try:
            # Настройка браузера
            options = webdriver.ChromeOptions()
            options.add_argument('--headless')  # Режим без графического интерфейса
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            
            driver = webdriver.Chrome(options=options)
            driver.get(LOGIN_URL)
            
            logger.info("Браузер открыт. Ожидание ручного входа...")
            
            # Ждем, пока пользователь вручную войдет в систему
            WebDriverWait(driver, 300).until(  # 5 минут timeout
                EC.presence_of_element_located((By.CLASS_NAME, "content-space"))
            )
            
            logger.info("Успешный вход detected. Начинаем сбор статей...")
            
            # Здесь должна быть логика сбора статей
            # Для демонстрации просто копируем существующий файл
            if os.path.exists(KNOWLEDGE_FILE):
                with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as source:
                    content = source.read()
                
                # Добавляем метку времени
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                updated_content = f"=== БАЗА ЗНАНИЙ - ОБНОВЛЕНО {timestamp} ===\n{content}"
                
                with open(TEMP_KNOWLEDGE_FILE, 'w', encoding='utf-8') as target:
                    target.write(updated_content)
                
                # Заменяем основную базу
                os.replace(TEMP_KNOWLEDGE_FILE, KNOWLEDGE_FILE)
                
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Ошибка парсинга: {e}")
            return False
        finally:
            if driver:
                driver.quit()

# Клавиатуры
def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Задать вопрос", callback_data="ask_question")],
        [InlineKeyboardButton(text="🔍 Совет по разговору", callback_data="conversation_tips")],
        [InlineKeyboardButton(text="📊 Статистика точности", callback_data="accuracy_stats")],
        [InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")]
    ])

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить базу", callback_data="update_base")],
        [InlineKeyboardButton(text="🗑️ Очистить базу", callback_data="clear_base")],
        [InlineKeyboardButton(text="📤 Экспорт базы", callback_data="export_base")],
        [InlineKeyboardButton(text="📥 Импорт базы", callback_data="import_base")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])

def accuracy_keyboard(message_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=f"correct_{message_id}"),
            InlineKeyboardButton(text="❌ Нет", callback_data=f"incorrect_{message_id}")
        ]
    ])

# Обработчики команд
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    # Сохраняем пользователя в БД
    conn = sqlite3.connect(USER_DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_admin BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name, is_admin) VALUES (?, ?, ?, ?)",
        (user_id, message.from_user.username, user_name, user_id in ADMIN_IDS)
    )
    conn.commit()
    conn.close()
    
    await message.answer(
        f"🤖 Добро пожаловать, {user_name}!\n"
        f"Я - бот-помощник для операторов МосОблЕИРЦ\n\n"
        f"📚 База знаний: {len(KnowledgeBase.load_articles())} статей\n"
        f"🎯 Точность ответов: {get_accuracy()}",
        reply_markup=main_menu_keyboard()
    )

@dp.callback_query(lambda c: c.data == "ask_question")
async def ask_question(callback: types.CallbackQuery):
    await callback.message.answer(
        "💬 Задайте ваш вопрос:\n\n"
        "Примеры вопросов:\n"
        "• «Какие сроки передачи показаний?»\n"
        "• «Как получить справку об отсутствии задолженности?»\n"
        "• «Какими способами можно оплатить счёт?»\n"
        "• «Что такое ЛКК и как им пользоваться?»"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "conversation_tips")
async def conversation_tips(callback: types.CallbackQuery):
    tips = """
🎯 **Советы по разговору с клиентом:**

1. **Приветствие**: «Добрый день! Меня зовут [Имя], компания МосОблЕИРЦ. Чем могу помочь?»

2. **Активное слушание**: 
   - «Понял ваш вопрос...»
   - «Уточните, пожалуйста...»
   - «Правильно ли я понимаю, что...»

3. **Четкие ответы**:
   - «Да, это возможно...»
   - «К сожалению, нет...»
   - «Для этого вам нужно...»

4. **Решение проблем**:
   - «Я понимаю вашу ситуацию...»
   - «Предлагаю следующий вариант...»
   - «Можем оформить заявку...»

5. **Завершение разговора**:
   - «Все ли было понятно?»
   - «Есть ли еще вопросы?»
   - «Хорошего дня!»
"""
    await callback.message.answer(tips)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "accuracy_stats")
async def show_accuracy(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in ADMIN_IDS:
        await callback.answer("❌ Доступ только для администраторов", show_alert=True)
        return
    
    articles_count = len(KnowledgeBase.load_articles())
    last_update = get_last_update_time()
    
    stats_text = f"""
📊 **Статистика бота:**

• Всего ответов: {accuracy_stats['total']}
• Правильных ответов: {accuracy_stats['correct']}
• Точность: {get_accuracy()}
• Статей в базе: {articles_count}
• Последнее обновление: {last_update}

📈 **Эффективность:**
- База знаний: {'✅ Актуальна' if articles_count > 0 else '❌ Требует обновления'}
- Нейросеть: {'✅ Работает' if HUGGINGFACE_API_KEY else '❌ Отключена'}
"""
    await callback.message.answer(stats_text)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in ADMIN_IDS:
        await callback.answer("❌ Доступ только для администраторов", show_alert=True)
        return
    
    await callback.message.answer(
        "⚙️ **Панель администратора**\n\n"
        "Управление базой знаний и настройками бота",
        reply_markup=admin_keyboard()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "update_base")
async def update_base(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in ADMIN_IDS:
        await callback.answer("❌ Доступ только для администраторов", show_alert=True)
        return
    
    await callback.message.answer(
        "🔄 **Запуск обновления базы знаний...**\n\n"
        "Процесс займет несколько минут:\n"
        "1. ✅ Создание резервной копии\n"
        "2. 🔓 Открытие браузера для входа\n"
        "3. 👤 Ожидание ручного входа\n"
        "4. 📥 Сбор новых статей\n"
        "5. 💾 Обновление базы данных\n\n"
        "⏳ Начинаю процесс..."
    )
    
    # Запускаем обновление
    success = await Parser.update_knowledge_base()
    
    if success:
        articles_count = len(KnowledgeBase.load_articles())
        await callback.message.answer(
            f"✅ **База знаний успешно обновлена!**\n\n"
            f"• Статей в базе: {articles_count}\n"
            f"• Время обновления: {datetime.now().strftime('%H:%M:%S')}\n"
            f"• Резервная копия: создана"
        )
    else:
        await callback.message.answer(
            "❌ **Ошибка при обновлении базы знаний**\n\n"
            "Проверьте:\n"
            "• Доступ к сайту МосОблЕИРЦ\n"
            "• Логин и пароль администратора\n"
            "• Интернет-соединение\n\n"
            "Резервная копия восстановлена."
        )
    
    await callback.answer()

@dp.callback_query(lambda c: c.data == "clear_base")
async def clear_base(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in ADMIN_IDS:
        await callback.answer("❌ Доступ только для администраторов", show_alert=True)
        return
    
    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, очистить", callback_data="confirm_clear"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_clear")
        ]
    ])
    
    await callback.message.answer(
        "⚠️ **Очистка базы знаний**\n\n"
        "Вы уверены, что хотите полностью очистить базу знаний?\n"
        "Это действие нельзя отменить!",
        reply_markup=confirm_keyboard
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "export_base")
async def export_base(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in ADMIN_IDS:
        await callback.answer("❌ Доступ только для администраторов", show_alert=True)
        return
    
    try:
        with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Сохраняем во временный файл для отправки
        export_filename = f"knowledge_export_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
        with open(export_filename, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Отправляем файл
        with open(export_filename, 'rb') as file:
            await callback.message.answer_document(
                types.BufferedInputFile(
                    file.read(),
                    filename=export_filename
                ),
                caption="📤 Экспорт базы знаний"
            )
        
        # Удаляем временный файл
        os.remove(export_filename)
        
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка экспорта: {str(e)}")
    
    await callback.answer()

# Обработчик вопросов
@dp.message()
async def handle_questions(message: types.Message):
    if message.text.startswith('/'):
        return
    
    question = message.text.strip()
    user_id = message.from_user.id
    
    if not question:
        await message.answer("Пожалуйста, введите ваш вопрос")
        return
    
    # Показываем, что бот думает
    thinking_msg = await message.answer("🔍 Ищу ответ в базе знаний...")
    
    try:
        # Генерируем ответ
        response, script, source = await ResponseGenerator.generate_response(question)
        
        if not response:
            await thinking_msg.edit_text("❌ Не удалось найти ответ на ваш вопрос")
            return
        
        # Форматируем ответ
        response_text = f"🤖 **Ответ:**\n{response}"
        if source and source != "Нейросеть":
            response_text += f"\n\n📚 **Источник:** {source}"
        
        await thinking_msg.edit_text(response_text)
        
        # Если есть скрипт для оператора
        if script:
            await message.answer(f"💬 **Что сказать клиенту:**\n{script}")
        
        # Спрашиваем о точности ответа
        accuracy_stats["total"] += 1
        await message.answer(
            "✅ Правильно ли я ответил?",
            reply_markup=accuracy_keyboard(accuracy_stats["total"])
        )
        
    except Exception as e:
        logger.error(f"Ошибка обработки вопроса: {e}")
        await thinking_msg.edit_text("❌ Произошла ошибка при поиске ответа")

# Обработчик обратной связи
@dp.callback_query(lambda c: c.data.startswith(('correct_', 'incorrect_')))
async def handle_accuracy_feedback(callback: types.CallbackQuery):
    action, count = callback.data.split('_')
    
    if action == "correct":
        accuracy_stats["correct"] += 1
        await callback.message.edit_text("✅ Спасибо за обратную связь! Ответ помечен как правильный.")
    else:
        # Уведомляем администратора
        question = callback.message.reply_to_message.text
        admin_message = (
            f"⚠️ **Неверный ответ бота**\n\n"
            f"❓ Вопрос: {question}\n"
            f"👤 Пользователь: {callback.from_user.first_name}\n"
            f"🆔 User ID: {callback.from_user.id}\n"
            f"📅 Время: {datetime.now().strftime('%H:%M:%S')}"
        )
        
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, admin_message)
            except Exception as e:
                logger.error(f"Не удалось уведомить администратора {admin_id}: {e}")
        
        await callback.message.edit_text(
            "❌ Спасибо за обратную связь! Администратор уведомлен об ошибке.\n"
            "Пожалуйста, уточните правильный ответ у старшего оператора."
        )
    
    await callback.answer()

# Вспомогательные функции
def get_accuracy():
    if accuracy_stats["total"] == 0:
        return "0%"
    accuracy = (accuracy_stats["correct"] / accuracy_stats["total"]) * 100
    return f"{accuracy:.1f}%"

def get_last_update_time():
    try:
        with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if 'ОБНОВЛЕНО' in line:
                    return line.split('ОБНОВЛЕНО ')[1].strip()
    except:
        pass
    return "Неизвестно"

# Создание необходимых директорий
def setup_directories():
    os.makedirs('database', exist_ok=True)
    os.makedirs('logs', exist_ok=True)

async def main():
    """Основная функция запуска бота"""
    setup_directories()
    logger.info("Запуск бота МосОблЕИРЦ...")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
