import os
import re
import sys
import time
import subprocess
from openai import OpenAI
import telebot
from dotenv import load_dotenv
import requests
from io import BytesIO

# Загружаем переменные окружения из файла .env
load_dotenv()

# Получаем токены из переменных окружения
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '8508825717:AAEaj_JR9Av2ZR3UWGy23byni7mfSW0ofXM')
HUGGINGFACE_TOKEN = os.getenv('HUGGINGFACE_TOKEN', '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')
# ID администратора (укажите свой Telegram ID)
ADMIN_ID = os.getenv('ADMIN_ID', '8219171639') 

# Инициализируем бота
bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)

def is_admin(user_id):
    """Проверяет, является ли пользователь администратором"""
    return str(user_id) == ADMIN_ID

def format_ai_response(text):
    """
    Форматирует текст от нейросети, добавляя HTML-разметку
    для улучшения читаемости в Telegram
    """
    try:
        # Убираем лишние пробелы и переносы
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
        
        # Форматируем заголовки
        text = re.sub(r'^(#+)\s*(.+)$', lambda m: f"<b>{m.group(2)}</b>\n", text, flags=re.MULTILINE)
        
        # Форматируем подзаголовки
        text = re.sub(r'^(\d+\.\s+[^:\n]+:|[А-Я][^:\n]+:)\s*$', lambda m: f"<b>{m.group(1)}</b>", text, flags=re.MULTILINE)
        
        # Форматируем списки
        lines = text.split('\n')
        formatted_lines = []
        
        for i, line in enumerate(lines):
            if not line.strip():
                formatted_lines.append('')
                continue
            
            list_match = re.match(r'^(\s*[-•*]\s+)(.+)', line)
            if list_match:
                prefix, content = list_match.groups()
                formatted_lines.append(f"• {content}")
                continue
            
            num_match = re.match(r'^(\s*\d+\.\s+)(.+)', line)
            if num_match:
                prefix, content = num_match.groups()
                formatted_lines.append(f"{content}")
                continue
            
            term_match = re.match(r'^([^-\n]+)\s+-\s+(.+)$', line)
            if term_match:
                term, definition = term_match.groups()
                formatted_lines.append(f"<b>{term.strip()}</b> - {definition}")
                continue
            
            if '«' in line or '"' in line or "'" in line:
                def format_quote(match):
                    return f"<i>{match.group(0)}</i>"
                
                line = re.sub(r'«[^»]+»', format_quote, line)
                line = re.sub(r'"[^"]+"', format_quote, line)
                line = re.sub(r"'[^']+'", format_quote, line)
                formatted_lines.append(line)
                continue
            
            if len(line) > 100 and not any(tag in line for tag in ['<b>', '<i>', '<code>']):
                formatted_lines.append(line)
            else:
                formatted_lines.append(line)
        
        text = '\n'.join(formatted_lines)
        
        # Добавляем форматирование для ключевых терминов
        key_terms = re.findall(r'\b([А-ЯЁA-Z][а-яёa-z]+(?:\s+[А-ЯЁA-Z][а-яёa-z]+)*)\b', text)
        for term in set(key_terms):
            if len(term.split()) <= 3:
                text = re.sub(rf'\b{re.escape(term)}\b', f"<b>{term}</b>", text)
        
        # Форматируем имена персонажей
        text = re.sub(r'\b(Онегин|Татьяна|Раскольников|Соня|Мастер|Маргарита|Пьер|Наташа|Андрей)\b', 
                     lambda m: f"<i>{m.group(1)}</i>", text, flags=re.IGNORECASE)
        
        # Добавляем форматирование для литературных терминов
        literary_terms = ['композиция', 'сюжет', 'фабула', 'конфликт', 'образ', 'персонаж', 
                         'характер', 'пейзаж', 'интерьер', 'диалог', 'монолог', 'символ', 
                         'метафора', 'эпитет', 'гипербола', 'аллегория', 'антитеза', 
                         'гротеск', 'ирония', 'сатира', 'лирика', 'эпос', 'драма']
        
        for term in literary_terms:
            text = re.sub(rf'\b({term})\b', rf"<b>\1</b>", text, flags=re.IGNORECASE)
        
        # Форматируем годы
        text = re.sub(r'\b(\d{4})(?:\s*года?)?\b', r'<code>\1</code>', text)
        
        # Форматируем названия произведений
        text = re.sub(r'«([^»]+)»', r'<i>«\1»</i>', text)
        text = re.sub(r'"([^"]+)"', r'<i>"\1"</i>', text)
        
        return text
        
    except Exception as e:
        print(f"[ERROR] Ошибка при форматировании текста: {e}")
        return text

def send_welcome_with_image(chat_id, max_retries=3):
    """Отправляет приветственное сообщение с изображением с повторными попытками"""
    
    start_text = """<b>Привет, я Pushkin AI!</b>

Я специализируюсь на анализе литературных произведений.

<b>Как использовать:</b>
1. Отправьте мне название произведения и автора
2. Я сделаю подробный литературный анализ

<i>Примеры запросов:</i>
• "Преступление и наказание, Федор Достоевский"
• "Евгений Онегин, Александр Пушкин"
• "Мастер и Маргарита, Михаил Булгаков"

<code>Важно:</code> Я занимаюсь только разбором литературных произведений"""
    
    # Сначала отправляем текстовое сообщение
    try:
        bot.send_message(chat_id, start_text, parse_mode='HTML')
        print(f"[LOG] Текстовое приветствие отправлено в чат {chat_id}")
    except Exception as e:
        print(f"[ERROR] Ошибка при отправке текста: {e}")
    
    # Затем пытаемся отправить изображение с повторными попытками
    image_path = "main.png"
    
    if not os.path.exists(image_path):
        print(f"[WARNING] Файл {image_path} не найден.")
        return
    
    for attempt in range(max_retries):
        try:
            print(f"[LOG] Попытка {attempt + 1} отправки изображения...")
            
            with open(image_path, 'rb') as photo:
                bot.send_photo(chat_id, photo, timeout=30)
                print(f"[LOG] Изображение успешно отправлено в чат {chat_id}")
                break
                
        except Exception as e:
            print(f"[ERROR] Ошибка при отправке изображения (попытка {attempt + 1}): {type(e).__name__}: {e}")
            if attempt < max_retries - 1:
                wait_time = 2 * (attempt + 1)
                print(f"[LOG] Ожидание {wait_time} секунд перед повторной попыткой...")
                time.sleep(wait_time)
            else:
                print(f"[ERROR] Не удалось отправить изображение после {max_retries} попыток")
                break

@bot.message_handler(commands=["start", "help"])
def start_handler(message):
    """Обработчик команд /start и /help"""
    print(f"[LOG] Получена команда /start от пользователя {message.from_user.id}")
    send_welcome_with_image(message.chat.id)

@bot.message_handler(commands=["reset"])
def reset_handler(message):
    """Команда для сброса и перезапуска бота (только для администратора)"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        print(f"[SECURITY] Неавторизованная попытка сброса от пользователя {user_id}")
        bot.send_message(message.chat.id, "⛔ У вас нет прав для выполнения этой команды.")
        return
    
    print(f"[ADMIN] Запрошен сброс системы пользователем {user_id}")
    
    # Отправляем подтверждение
    confirm_msg = bot.send_message(
        message.chat.id,
        "<b>🔄 Запущен процесс сброса системы...</b>\n\n"
        "<i>Статус:</i> Очистка кэша и перезапуск...",
        parse_mode='HTML'
    )
    
    try:
        # Шаг 1: Логируем событие
        log_message = f"""
        ⚠️ АДМИНИСТРАТИВНОЕ ДЕЙСТВИЕ ⚠️
        
        Инициатор: {message.from_user.id} ({message.from_user.username})
        Время: {time.strftime('%Y-%m-%d %H:%M:%S')}
        Действие: СБРОС И ПЕРЕЗАПУСК СИСТЕМЫ
        """
        print(log_message)
        
        # Шаг 2: Обновляем статус
        bot.edit_message_text(
            "<b>🔄 Запущен процесс сброса системы...</b>\n\n"
            "<i>Статус:</i> Останавливаю бота...",
            message.chat.id,
            confirm_msg.message_id,
            parse_mode='HTML'
        )
        
        # Шаг 3: Останавливаем polling (это остановит текущий процесс)
        bot.stop_polling()
        time.sleep(2)
        
        # Шаг 4: Обновляем статус
        bot.edit_message_text(
            "<b>🔄 Запущен процесс сброса системы...</b>\n\n"
            "<i>Статус:</i> Бот остановлен. Перезапускаюсь...",
            message.chat.id,
            confirm_msg.message_id,
            parse_mode='HTML'
        )
        
        # Шаг 5: Очищаем любые временные файлы или кэш
        temp_files = ['temp_optimized.png', 'temp_response.txt']
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                    print(f"[ADMIN] Удален временный файл: {temp_file}")
                except:
                    pass
        
        # Шаг 6: Записываем логи о перезапуске
        with open('restart.log', 'a') as log_file:
            log_file.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Перезапуск инициирован пользователем {user_id}\n")
        
        # Шаг 7: Отправляем финальное сообщение
        final_message = f"""
<b>✅ Сброс системы выполнен успешно!</b>

<i>Выполненные действия:</i>
• Бот остановлен
• Временные файлы очищены
• Система перезапускается

<i>Время выполнения:</i> {time.strftime('%H:%M:%S')}
<i>Статус:</i> Переход в режим ожидания...
        """
        
        bot.edit_message_text(
            final_message,
            message.chat.id,
            confirm_msg.message_id,
            parse_mode='HTML'
        )
        
        print("[ADMIN] Сброс завершен. Перезапускаю бота через 3 секунды...")
        
        # Шаг 8: Перезапускаем бота
        time.sleep(3)
        
        # Способ 1: Перезапуск через subprocess (рекомендуется)
        python_executable = sys.executable
        script_path = os.path.abspath(__file__)
        
        # Запускаем новый процесс
        subprocess.Popen([python_executable, script_path])
        
        # Шаг 9: Завершаем текущий процесс
        sys.exit(0)
        
    except Exception as e:
        error_message = f"""
<b>❌ Ошибка при сбросе системы!</b>

<i>Ошибка:</i> <code>{str(e)}</code>

Пожалуйста, перезапустите бота вручную.
        """
        
        try:
            bot.edit_message_text(
                error_message,
                message.chat.id,
                confirm_msg.message_id,
                parse_mode='HTML'
            )
        except:
            bot.send_message(message.chat.id, error_message, parse_mode='HTML')
        
        print(f"[ERROR] Ошибка при выполнении сброса: {e}")

@bot.message_handler(commands=["image"])
def image_handler(message):
    """Отправляет только изображение по команде /image"""
    try:
        image_path = "main.png"
        if os.path.exists(image_path):
            print(f"[LOG] Отправка изображения по команде /image в чат {message.chat.id}")
            
            with open(image_path, 'rb') as photo:
                bot.send_photo(message.chat.id, photo, timeout=30)
            print(f"[LOG] Изображение отправлено по команде /image")
                
        else:
            bot.send_message(message.chat.id, "Изображение не найдено на сервере.")
    except Exception as e:
        print(f"[ERROR] Ошибка при отправке изображения: {e}")
        bot.send_message(message.chat.id, "Ошибка при отправке изображения.")

@bot.message_handler(commands=["about"])
def about_handler(message):
    """Обработчик команды /about"""
    about_text = """<b>Pushkin AI</b>
    
<i>Версия:</i> 1.0
<i>Назначение:</i> Анализ литературных произведений
<i>Используемая модель:</i> DeepSeek-V3.2-Exp
<i>Разработчик:</i> [Ваше имя/организация]
    
<code>По вопросам сотрудничества:</code> ваш_email@example.com"""
    
    bot.send_message(message.chat.id, about_text, parse_mode='HTML')

@bot.message_handler(commands=["admin"])
def admin_handler(message):
    """Показывает информацию об административных командах"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "⛔ У вас нет прав для доступа к панели администратора.")
        return
    
    admin_text = f"""<b>👨‍💼 Панель администратора</b>

<i>Ваш ID:</i> <code>{user_id}</code>
<i>Время сервера:</i> {time.strftime('%Y-%m-%d %H:%M:%S')}

<b>Доступные команды:</b>
• /reset - Сбросить и перезапустить бота
• /status - Показать статус системы
• /logs - Показать последние логи

<b>Информация о системе:</b>
• Python: {sys.version.split()[0]}
• Бот: Pushkin AI v1.0
"""
    
    bot.send_message(message.chat.id, admin_text, parse_mode='HTML')

@bot.message_handler(commands=["status"])
def status_handler(message):
    """Показывает статус системы"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "⛔ У вас нет прав для просмотра статуса.")
        return
    
    # Собираем информацию о системе
    import psutil
    
    try:
        # Использование памяти
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        status_text = f"""<b>📊 Статус системы</b>

<i>Время сервера:</i> {time.strftime('%Y-%m-%d %H:%M:%S')}

<b>Использование ресурсов:</b>
• CPU: {psutil.cpu_percent()}%
• RAM: {memory.percent}% ({memory.used / 1024 / 1024:.1f} MB / {memory.total / 1024 / 1024:.1f} MB)
• Disk: {disk.percent}% ({disk.used / 1024 / 1024 / 1024:.1f} GB / {disk.total / 1024 / 1024 / 1024:.1f} GB)

<b>Файлы системы:</b>
• main.png: {'✅ найден' if os.path.exists('main.png') else '❌ не найден'}
• .env: {'✅ найден' if os.path.exists('.env') else '❌ не найден'}

<b>Процессы:</b>
• Бот: ✅ запущен
• Подключение к API: ✅ активно
"""
        
        bot.send_message(message.chat.id, status_text, parse_mode='HTML')
        
    except ImportError:
        bot.send_message(
            message.chat.id,
            "<b>📊 Статус системы</b>\n\n"
            "<i>Время сервера:</i> {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "<code>Информация:</code> Установите библиотеку psutil для подробной статистики\n"
            "<code>Команда:</code> pip install psutil",
            parse_mode='HTML'
        )
    except Exception as e:
        bot.send_message(
            message.chat.id,
            f"<b>❌ Ошибка при получении статуса:</b>\n\n<code>{str(e)}</code>",
            parse_mode='HTML'
        )

@bot.message_handler(func=lambda message: True)
def text_handler(message):
    """Обработчик всех текстовых сообщений"""
    try:
        user_id = message.from_user.id
        chat_id = message.chat.id
        prompt = str(message.text)
        
        print(f"[LOG] Получен запрос от пользователя {user_id}: {prompt[:50]}...")
        
        if len(prompt) < 5:
            bot.send_message(
                chat_id, 
                "Пожалуйста, укажите полное название произведения и автора для анализа.\n\n" +
                "<i>Пример:</i> 'Война и мир, Лев Толстой'",
                parse_mode='HTML'
            )
            return
        
        # Отправляем сообщение о начале обработки
        status_msg = bot.send_message(chat_id, "🔄 <i>Анализирую произведение...</i>", parse_mode='HTML')
        status_message_id = status_msg.message_id
        
        # Показываем индикатор печати каждые 5 секунд
        def show_typing_indicator():
            while not hasattr(show_typing_indicator, 'stop'):
                try:
                    bot.send_chat_action(chat_id, 'typing')
                    time.sleep(5)
                except:
                    break
        
        # Запускаем индикатор печати в отдельном потоке
        import threading
        typing_thread = threading.Thread(target=show_typing_indicator)
        typing_thread.daemon = True
        typing_thread.start()
        
        try:
            # Получаем ответ от нейросети
            response = get_answer(prompt)
            
            # Останавливаем индикатор печати
            show_typing_indicator.stop = True
            typing_thread.join(timeout=1)
            
            # Форматируем ответ
            formatted_response = format_ai_response(response)
            
            # Проверяем длину ответа
            if len(formatted_response) > 4000:
                # Разбиваем на части
                parts = []
                current_part = ""
                
                for paragraph in formatted_response.split('\n\n'):
                    if len(current_part) + len(paragraph) + 2 < 4000:
                        current_part += paragraph + '\n\n'
                    else:
                        parts.append(current_part)
                        current_part = paragraph + '\n\n'
                
                if current_part:
                    parts.append(current_part)
                
                # Удаляем статусное сообщение
                try:
                    bot.delete_message(chat_id, status_message_id)
                except:
                    pass
                
                # Отправляем первую часть
                first_part = parts[0]
                if len(first_part) > 4000:
                    first_part = first_part[:4000]
                
                sent_msg = bot.send_message(chat_id, first_part, parse_mode='HTML')
                last_message_id = sent_msg.message_id
                
                # Отправляем остальные части как отдельные сообщения
                for i, part in enumerate(parts[1:], 1):
                    if len(part) > 4000:
                        part = part[:4000]
                    
                    # Добавляем номер части
                    part_with_number = f"<b>Часть {i+1}</b>\n\n{part}"
                    sent_msg = bot.send_message(chat_id, part_with_number, parse_mode='HTML')
                    last_message_id = sent_msg.message_id
                    
            else:
                # Удаляем статусное сообщение
                try:
                    bot.delete_message(chat_id, status_message_id)
                except:
                    pass
                
                # Отправляем форматированный ответ
                bot.send_message(chat_id, formatted_response, parse_mode='HTML')
            
            print(f'[LOG] Ответ успешно отправлен пользователю {user_id}, длина: {len(response)} символов')
            
        except Exception as e:
            # Останавливаем индикатор печати
            show_typing_indicator.stop = True
            
            # Удаляем статусное сообщение
            try:
                bot.delete_message(chat_id, status_message_id)
            except:
                pass
            
            error_msg = f"Произошла ошибка при анализе произведения:\n\n<code>{str(e)[:200]}</code>"
            bot.send_message(chat_id, error_msg, parse_mode='HTML')
            print(f"[ERROR] Ошибка при обработке запроса: {e}")
            
    except Exception as e:
        print(f"[ERROR] Критическая ошибка в обработчике: {e}")
        try:
            bot.send_message(
                chat_id,
                "Произошла критическая ошибка при обработке вашего запроса. Пожалуйста, попробуйте еще раз."
            )
        except:
            pass

def get_answer(content):
    """Функция для получения ответа от модели"""
    client = OpenAI(
        base_url="https://router.huggingface.co/v1",
        api_key=HUGGINGFACE_TOKEN
    )

    completion = client.chat.completions.create(
        model="deepseek-ai/DeepSeek-V3.2-Exp:novita",
        messages=[
            {
                "role": "user",
                "content": f'{content} (ТЕХНИЧЕСКОЕ ЗАДАНИЕ: Обязательно проверь, что до тех. задания я написал название литературного произведения и автора этого произведения. Если все соответствует - то сделай очень подробный анализ этого произведения. Если до тех. задания я вставил никак не относящийся к литературе запрос, то напиши текст о том, что ты занимаешься именно разбором литературных произведений и ничего более)'
            }
        ],
        max_tokens=3500,
        temperature=0.7,
    )

    return completion.choices[0].message.content

if __name__ == "__main__":
    print("=" * 50)
    print("Pushkin AI Bot запущен!")
    print(f"Администратор: ID {ADMIN_ID}")
    print(f"Подключен к Telegram")
    print(f"Используется модель: DeepSeek-V3.2-Exp")
    
    if os.path.exists("main.png"):
        file_size = os.path.getsize("main.png")
        print(f"Изображение main.png найдено, размер: {file_size/1024/1024:.2f}MB")
    else:
        print(f"Изображение main.png не найдено в текущей директории")
        print(f"Текущая директория: {os.getcwd()}")
    
    print("=" * 50)
    print("Ожидаю запросы...")
    print("Административные команды:")
    print(f"  • /admin - панель администратора")
    print(f"  • /reset - сброс и перезапуск")
    print(f"  • /status - статус системы")
    
    try:
        bot.polling(none_stop=True, interval=1, timeout=30)
    except Exception as e:
        print(f"[CRITICAL ERROR] Бот остановлен: {e}")
        print(f"[INFO] Перезапуск через 5 секунд...")
        time.sleep(5)
        # Автоматический перезапуск
        python_executable = sys.executable
        script_path = os.path.abspath(__file__)
        subprocess.Popen([python_executable, script_path])
        sys.exit(0)