import asyncio
import logging
import sqlite3
import aiohttp
import json
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import *

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация бота с правильными настройками
bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# Статистика точности
accuracy_stats = {"total": 0, "correct": 0}

class KnowledgeBase:
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
        
        relevant_articles.sort(key=lambda x: x[1], reverse=True)
        return [article[0] for article in relevant_articles]
    
    @staticmethod
    def calculate_relevance(article, query):
        """Вычисляет релевантность статьи запросу"""
        query_words = set(query.lower().split())
        article_lower = article.lower()
        
        score = 0
        for word in query_words:
            if len(word) > 3:
                score += article_lower.count(word) * len(word)
        
        if query.lower() in article_lower:
            score += 100
        
        return score
    
    @staticmethod
    def extract_script(article):
        """Извлекает скрипт для оператора из статьи"""
        lines = article.split('\n')
        script_lines = []
        
        # Ищем блоки с инструкциями для оператора
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if any(keyword in line_lower for keyword in ['💬', 'что сказать', 'скрипт', 'речь оператора', 'действия оператора']):
                # Берем следующие 3-5 строк как скрипт
                for j in range(i+1, min(i+6, len(lines))):
                    if lines[j].strip() and not lines[j].startswith('---') and '===' not in lines[j]:
                        script_lines.append(lines[j].strip())
                break
        
        return '\n'.join(script_lines) if script_lines else None

class ResponseGenerator:
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
            
            return content, script, title
        
        # Если в базе нет ответа, используем нейросеть
        ai_response = await ResponseGenerator.ask_huggingface(question)
        if ai_response:
            return ai_response, None, "Нейросеть"
        else:
            return "К сожалению, я не нашел информации по вашему вопросу в базе знаний. Пожалуйста, обратитесь к старшему оператору.", None, "Не найдено"
    
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
                if len(line.strip()) > 10:  # Только значимые строки
                    content_lines.append(line.strip())
        
        if content_lines:
            return '\n'.join(content_lines[:10])  # Ограничиваем длину
        
        # Если не нашли структурированного содержания, возвращаем первые значимые строки
        meaningful_lines = []
        for line in lines:
            if line.strip() and len(line.strip()) > 20 and not line.startswith(('===', '---', 'МО', 'Поиск')):
                meaningful_lines.append(line.strip())
            if len(meaningful_lines) >= 5:
                break
        
        return '\n'.join(meaningful_lines) if meaningful_lines else article[:300] + "..."
    
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
    async def ask_huggingface(prompt):
        """Запрос к HuggingFace API"""
        try:
            headers = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"}
            payload = {
                "inputs": prompt,
                "parameters": {
                    "max_length": MAX_RESPONSE_LENGTH,
                    "min_length": 50,
                    "do_sample": False,
                    "temperature": 0.7
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    HUGGINGFACE_API_URL, 
                    headers=headers, 
                    json=payload,
                    timeout=REQUEST_TIMEOUT
                ) as response:
                    
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"HuggingFace response: {result}")
                        
                        if isinstance(result, list) and len(result) > 0:
                            if 'generated_text' in result[0]:
                                return result[0]['generated_text']
                            else:
                                return str(result[0])
                        else:
                            return str(result)
                    else:
                        error_text = await response.text()
                        logger.error(f"HuggingFace API error {response.status}: {error_text}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.error("Timeout from HuggingFace API")
            return None
        except Exception as e:
            logger.error(f"HuggingFace request error: {e}")
            return None

class DatabaseManager:
    @staticmethod
    def init_db():
        """Инициализация базы данных"""
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
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def save_user(user_id, username, first_name):
        """Сохраняет пользователя в БД"""
        conn = sqlite3.connect(USER_DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name, is_admin)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, first_name, user_id in ADMIN_IDS))
        
        conn.commit()
        conn.close()

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
    
    # Сохраняем пользователя
    DatabaseManager.save_user(user_id, message.from_user.username, user_name)
    
    # Создаем базу знаний если её нет
    if not os.path.exists(KNOWLEDGE_FILE):
        with open(KNOWLEDGE_FILE, 'w', encoding='utf-8') as f:
            f.write("=== БАЗА ЗНАНИЙ ===\nВремя создания: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    articles_count = len(KnowledgeBase.load_articles())
    
    await message.answer(
        f"🤖 <b>Добро пожаловать, {user_name}!</b>\n\n"
        f"Я - бот-помощник для операторов МосОблЕИРЦ\n\n"
        f"📚 Статей в базе: <b>{articles_count}</b>\n"
        f"🎯 Точность ответов: <b>{get_accuracy()}</b>",
        reply_markup=main_menu_keyboard()
    )

@dp.callback_query(lambda c: c.data == "ask_question")
async def ask_question(callback: types.CallbackQuery):
    await callback.message.answer(
        "💬 <b>Задайте ваш вопрос:</b>\n\n"
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
🎯 <b>Советы по разговору с клиентом:</b>

1. <b>Приветствие</b>: «Добрый день! Меня зовут [Имя], компания МосОблЕИРЦ. Чем могу помочь?»

2. <b>Активное слушание</b>:
   • «Понял ваш вопрос...»
   • «Уточните, пожалуйста...»
   • «Правильно ли я понимаю, что...»

3. <b>Четкие ответы</b>:
   • «Да, это возможно...»
   • «К сожалению, нет...»
   • «Для этого вам нужно...»

4. <b>Решение проблем</b>:
   • «Я понимаю вашу ситуацию...»
   • «Предлагаю следующий вариант...»
   • «Можем оформить заявку...»

5. <b>Завершение разговора</b>:
   • «Все ли было понятно?»
   • «Есть ли еще вопросы?»
   • «Хорошего дня!»
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
📊 <b>Статистика бота:</b>

• Всего ответов: <b>{accuracy_stats['total']}</b>
• Правильных ответов: <b>{accuracy_stats['correct']}</b>
• Точность: <b>{get_accuracy()}</b>
• Статей в базе: <b>{articles_count}</b>
• Последнее обновление: <b>{last_update}</b>

📈 <b>Эффективность:</b>
• База знаний: {'✅ Актуальна' if articles_count > 0 else '❌ Требует обновления'}
• Нейросеть: {'✅ Работает' if HUGGINGFACE_API_KEY else '❌ Отключена'}
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
        "⚙️ <b>Панель администратора</b>\n\n"
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
        "🔄 <b>Запуск обновления базы знаний...</b>\n\n"
        "Для демонстрации создается тестовая база знаний.\n"
        "В реальной версии здесь будет запущен парсер."
    )
    
    # Создаем тестовую базу знаний для демонстрации
    test_knowledge = """=== БАЗА ЗНАНИЙ - ТЕСТОВАЯ ВЕРСИЯ ===
Время сбора: 2024-01-01 12:00:00
Обработано: 3 статей
==================================================

СТАТЬЯ 1: Передача показаний ПУ
URL: https://mes1-kms.interrao.ru/content/space/7/article/8352
Заголовок: Способы передачи показаний
Время обработки: 12:00:00
---
СОДЕРЖАНИЕ:
Передать показания ПУ коммунальных ресурсов можно одним из способов:
• В ЛКК на сайте мособлеирц.рф
• В мобильном приложении «МосОблЕИРЦ Онлайн»
• По телефону КЦ 8(499)444-01-00 (голосовой помощник)
• С помощью чат-бота на сайте
• В клиентских офисах МосОблЕИРЦ

💬 Что сказать клиенту:
«Вы можете передать показания через личный кабинет, мобильное приложение или по телефону контактного центра.»

---
==================================================

СТАТЬЯ 2: Оплата счетов
URL: https://mes1-kms.interrao.ru/content/space/7/article/8185
Заголовок: Способы оплаты
Время обработки: 12:00:00
---
СОДЕРЖАНИЕ:
Оплатить ЕПД можно любым удобным способом:
Без комиссии:
• В мобильном приложении «МосОблЕИРЦ Онлайн»
• Через кнопку моментальной оплаты на сайте
• В клиентских офисах через POS-терминалы
• Через онлайн-сервисы банков

💬 Что сказать клиенту:
«Оплатить счет можно без комиссии через наше мобильное приложение или на сайте.»

---
==================================================

СТАТЬЯ 3: Личный кабинет
URL: https://mes1-kms.interrao.ru/content/space/7/article/8536
Заголовок: Регистрация в ЛКК
Время обработки: 12:00:00
---
СОДЕРЖАНИЕ:
ЛКК – удобный сервис для решения вопросов ЖКХ в онлайн-режиме.
Преимущества:
• Оплата счетов
• Передача показаний ПУ
• Просмотр истории платежей
• Получение справок и выписок

💬 Что сказать клиенту:
«Зарегистрируйтесь в личном кабинете для удобного управления вашими счетами онлайн.»

---
==================================================
"""
    
    with open(KNOWLEDGE_FILE, 'w', encoding='utf-8') as f:
        f.write(test_knowledge)
    
    await callback.message.answer("✅ <b>Тестовая база знаний создана!</b>\n\nТеперь бот готов к работе с демонстрационными данными.")
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
        "⚠️ <b>Очистка базы знаний</b>\n\n"
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
        if os.path.exists(KNOWLEDGE_FILE):
            with open(KNOWLEDGE_FILE, 'rb') as file:
                await callback.message.answer_document(
                    types.BufferedInputFile(
                        file.read(),
                        filename=f"knowledge_export_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
                    ),
                    caption="📤 <b>Экспорт базы знаний</b>"
                )
        else:
            await callback.message.answer("❌ Файл базы знаний не найден")
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка экспорта: {str(e)}")
    
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    articles_count = len(KnowledgeBase.load_articles())
    
    await callback.message.answer(
        f"🤖 <b>Главное меню</b>\n\n"
        f"📚 Статей в базе: <b>{articles_count}</b>\n"
        f"🎯 Точность ответов: <b>{get_accuracy()}</b>",
        reply_markup=main_menu_keyboard()
    )
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
    thinking_msg = await message.answer("🔍 <i>Ищу ответ в базе знаний...</i>")
    
    try:
        # Генерируем ответ
        response, script, source = await ResponseGenerator.generate_response(question)
        
        if not response:
            await thinking_msg.edit_text("❌ Не удалось найти ответ на ваш вопрос")
            return
        
        # Форматируем ответ
        response_text = f"🤖 <b>Ответ:</b>\n{response}"
        if source and source != "Нейросеть":
            response_text += f"\n\n📚 <b>Источник:</b> {source}"
        
        await thinking_msg.edit_text(response_text)
        
        # Если есть скрипт для оператора
        if script:
            await message.answer(f"💬 <b>Что сказать клиенту:</b>\n{script}")
        
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
            f"⚠️ <b>Неверный ответ бота</b>\n\n"
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
                if 'Время сбора:' in line:
                    return line.split('Время сбора: ')[1].strip()
    except:
        pass
    return "Неизвестно"

async def main():
    """Основная функция запуска бота"""
    # Создаем необходимые директории
    os.makedirs('database', exist_ok=True)
    os.makedirs('logs', exist_ok=True)
    
    # Инициализируем БД
    DatabaseManager.init_db()
    
    logger.info("Запуск бота МосОблЕИРЦ...")
    logger.info(f"Telegram Bot Token: {TELEGRAM_BOT_TOKEN[:10]}...")
    logger.info(f"HuggingFace API Key: {HUGGINGFACE_API_KEY[:10]}...")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
