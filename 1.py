import asyncio
import logging
from typing import Dict, Tuple, Optional, List
from collections import defaultdict
from datetime import datetime

from telegram import (
    Update, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    User
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    filters, 
    ContextTypes,
    ConversationHandler
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
SEARCHING, IN_CHAT, RATING = range(3)

# Хранение данных
waiting_users: List[int] = []  # пользователи в поиске
active_chats: Dict[int, int] = {}  # user_id: partner_id
user_ratings: Dict[int, Dict[str, float]] = {}  # user_id: {total_rating, rating_count}
user_messages: Dict[int, List[Dict]] = {}  # Хранение сообщений для пересылки
user_info: Dict[int, Dict] = {}  # Хранение информации о пользователях (username, first_name)

# ID администраторов (укажите здесь ID администраторов бота)
ADMIN_IDS = [123456789, 987654321]  # Замените на реальные ID администраторов

# Клавиатура для чата
chat_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("🚪 Выйти из диалога")],
    [KeyboardButton("🔍 Выйти и найти нового")]
], resize_keyboard=True)

# Клавиатура для главного меню
main_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("🔍 Найти собеседника")]
], resize_keyboard=True)

def calculate_rating(user_id: int) -> float:
    """Рассчитать средний рейтинг пользователя"""
    if user_id not in user_ratings:
        return 0.0
    
    rating_data = user_ratings[user_id]
    if rating_data['rating_count'] == 0:
        return 0.0
    
    return rating_data['total_rating'] / rating_data['rating_count']

def save_user_info(user: User):
    """Сохраняем информацию о пользователе"""
    user_info[user.id] = {
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'full_name': user.full_name
    }

def is_admin(user_id: int) -> bool:
    """Проверяем, является ли пользователь администратором"""
    return user_id in ADMIN_IDS

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /start"""
    user = update.effective_user
    user_id = user.id
    
    # Сохраняем информацию о пользователе
    save_user_info(user)
    
    # Инициализация рейтинга пользователя если нужно
    if user_id not in user_ratings:
        user_ratings[user_id] = {'total_rating': 0.0, 'rating_count': 0}
    
    # Если пользователь в активном чате, выводим его
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        await exit_chat(user_id, context, notify_partner=True)
    
    # Приветственное сообщение для админов
    if is_admin(user_id):
        await update.message.reply_text(
            "👑 Вы вошли как администратор бота.\n"
            "При начале диалога вы будете видеть username собеседника.\n\n"
            "Нажмите кнопку ниже, чтобы найти собеседника.",
            reply_markup=main_keyboard
        )
    else:
        await update.message.reply_text(
            "👋 Добро пожаловать в анонимный чат!\n\n"
            "Нажмите кнопку ниже, чтобы найти собеседника.",
            reply_markup=main_keyboard
        )
    return SEARCHING

async def search_partner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Поиск собеседника"""
    user = update.effective_user
    user_id = user.id
    
    # Сохраняем информацию о пользователе
    save_user_info(user)
    
    # Проверяем, не в чате ли уже пользователь
    if user_id in active_chats:
        await update.message.reply_text(
            "Вы уже в диалоге! Используйте кнопки ниже для управления.",
            reply_markup=chat_keyboard
        )
        return IN_CHAT
    
    # Проверяем, не ищет ли уже пользователь
    if user_id in waiting_users:
        await update.message.reply_text(
            "⏳ Вы уже в поиске собеседника...",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отменить поиск")]], resize_keyboard=True)
        )
        return SEARCHING
    
    # Добавляем пользователя в очередь
    waiting_users.append(user_id)
    await update.message.reply_text(
        "🔎 Ищем собеседника...",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отменить поиск")]], resize_keyboard=True)
    )
    
    # Ищем пару
    if len(waiting_users) >= 2 and waiting_users[0] != user_id:
        user1_id = waiting_users.pop(0)
        user2_id = waiting_users.pop(0)
        
        # Создаем чат
        active_chats[user1_id] = user2_id
        active_chats[user2_id] = user1_id
        
        # Получаем рейтинги
        rating1 = calculate_rating(user1_id)
        rating2 = calculate_rating(user2_id)
        
        # Получаем информацию о пользователях
        user1_info = user_info.get(user1_id, {})
        user2_info = user_info.get(user2_id, {})
        
        # Формируем сообщения для пользователей
        user1_message = f"✅ Найден собеседник!\n"
        user2_message = f"✅ Найден собеседник!\n"
        
        # Для админа показываем username собеседника
        if is_admin(user1_id):
            partner_username = user2_info.get('username', 'нет username')
            partner_name = user2_info.get('first_name', 'Пользователь')
            if partner_username:
                user1_message += f"👤 Собеседник: @{partner_username} ({partner_name})\n"
            else:
                user1_message += f"👤 Собеседник: {partner_name} (без username)\n"
        
        if is_admin(user2_id):
            partner_username = user1_info.get('username', 'нет username')
            partner_name = user1_info.get('first_name', 'Пользователь')
            if partner_username:
                user2_message += f"👤 Собеседник: @{partner_username} ({partner_name})\n"
            else:
                user2_message += f"👤 Собеседник: {partner_name} (без username)\n"
        
        # Добавляем рейтинг и инструкции
        user1_message += f"⭐ Рейтинг собеседника: {rating2:.1f}/5\n\n"
        user1_message += "Теперь вы можете общаться анонимно.\n"
        user1_message += "Все сообщения и файлы будут пересылаться."
        
        user2_message += f"⭐ Рейтинг собеседника: {rating1:.1f}/5\n\n"
        user2_message += "Теперь вы можете общаться анонимно.\n"
        user2_message += "Все сообщения и файлы будут пересылаться."
        
        # Отправляем уведомления
        try:
            await context.bot.send_message(
                user1_id,
                user1_message,
                reply_markup=chat_keyboard
            )
            
            await context.bot.send_message(
                user2_id,
                user2_message,
                reply_markup=chat_keyboard
            )
            
            # Отправляем сохраненные сообщения если есть
            if user1_id in user_messages:
                for msg_data in user_messages[user1_id]:
                    await forward_message_to_partner(user1_id, msg_data, context)
                user_messages.pop(user1_id, None)
            
            if user2_id in user_messages:
                for msg_data in user_messages[user2_id]:
                    await forward_message_to_partner(user2_id, msg_data, context)
                user_messages.pop(user2_id, None)
                
        except Exception as e:
            logger.error(f"Error starting chat: {e}")
            # Если ошибка, очищаем чат
            active_chats.pop(user1_id, None)
            active_chats.pop(user2_id, None)
            
            await context.bot.send_message(user1_id, "❌ Ошибка при подключении. Попробуйте снова.", reply_markup=main_keyboard)
            await context.bot.send_message(user2_id, "❌ Ошибка при подключении. Попробуйте снова.", reply_markup=main_keyboard)
            return SEARCHING
        
        return IN_CHAT
    
    return SEARCHING

async def cancel_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена поиска"""
    user = update.effective_user
    user_id = user.id
    
    if user_id in waiting_users:
        waiting_users.remove(user_id)
    
    await update.message.reply_text(
        "❌ Поиск отменен.",
        reply_markup=main_keyboard
    )
    return SEARCHING

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка сообщений в чате"""
    user = update.effective_user
    user_id = user.id
    
    # Сохраняем информацию о пользователе
    save_user_info(user)
    
    # Если пользователь в чате
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        
        try:
            # Пересылаем текстовое сообщение
            await context.bot.send_message(
                partner_id,
                update.message.text
            )
            
            # Сохраняем сообщение в случае если партнер переподключится
            if user_id not in user_messages:
                user_messages[user_id] = []
            
            user_messages[user_id].append({
                'type': 'text',
                'content': update.message.text,
                'message_id': update.message.message_id
            })
            
        except Exception as e:
            logger.error(f"Error forwarding message: {e}")
            await update.message.reply_text("❌ Не удалось отправить сообщение. Попробуйте еще раз.")
        
        return IN_CHAT
    
    # Если пользователь в поиске
    elif user_id in waiting_users:
        await update.message.reply_text("⏳ Вы все еще в поиске собеседника...")
        return SEARCHING
    
    # Если пользователь не в системе
    else:
        await update.message.reply_text(
            "Нажмите кнопку ниже, чтобы начать поиск собеседника.",
            reply_markup=main_keyboard
        )
        return SEARCHING

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка медиафайлов"""
    user = update.effective_user
    user_id = user.id
    
    # Сохраняем информацию о пользователе
    save_user_info(user)
    
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        
        try:
            # Определяем тип медиа
            if update.message.photo:
                file_id = update.message.photo[-1].file_id
                caption = update.message.caption
                await context.bot.send_photo(
                    partner_id,
                    photo=file_id,
                    caption=caption if caption else None
                )
                
            elif update.message.video:
                file_id = update.message.video.file_id
                caption = update.message.caption
                await context.bot.send_video(
                    partner_id,
                    video=file_id,
                    caption=caption if caption else None
                )
                
            elif update.message.document:
                file_id = update.message.document.file_id
                caption = update.message.caption
                await context.bot.send_document(
                    partner_id,
                    document=file_id,
                    caption=caption if caption else None
                )
                
            elif update.message.audio:
                file_id = update.message.audio.file_id
                caption = update.message.caption
                await context.bot.send_audio(
                    partner_id,
                    audio=file_id,
                    caption=caption if caption else None
                )
                
            elif update.message.voice:
                file_id = update.message.voice.file_id
                await context.bot.send_voice(partner_id, voice=file_id)
                
            elif update.message.sticker:
                file_id = update.message.sticker.file_id
                await context.bot.send_sticker(partner_id, sticker=file_id)
            
            # Сохраняем информацию о сообщении
            if user_id not in user_messages:
                user_messages[user_id] = []
            
            user_messages[user_id].append({
                'type': 'media',
                'message_id': update.message.message_id,
                'media_type': 'photo' if update.message.photo else 
                             'video' if update.message.video else 
                             'document' if update.message.document else 
                             'audio' if update.message.audio else 
                             'voice' if update.message.voice else 
                             'sticker'
            })
            
        except Exception as e:
            logger.error(f"Error forwarding media: {e}")
            await update.message.reply_text("❌ Не удалось отправить файл. Попробуйте еще раз.")
        
        return IN_CHAT
    
    return await handle_message(update, context)

async def forward_message_to_partner(user_id: int, msg_data: Dict, context: ContextTypes.DEFAULT_TYPE):
    """Пересылка сообщения собеседнику"""
    if user_id not in active_chats:
        return
    
    partner_id = active_chats[user_id]
    
    try:
        if msg_data['type'] == 'text':
            await context.bot.send_message(partner_id, msg_data['content'])
        # Для медиа сообщений уже выполнена пересылка в handle_media
    except Exception as e:
        logger.error(f"Error sending to partner: {e}")

async def exit_chat(user_id: int, context: ContextTypes.DEFAULT_TYPE, notify_partner: bool = True) -> Optional[int]:
    """Выход из чата"""
    if user_id not in active_chats:
        return None
    
    partner_id = active_chats[user_id]
    
    # Удаляем чат
    active_chats.pop(user_id, None)
    if partner_id in active_chats:
        active_chats.pop(partner_id, None)
    
    # Очищаем сообщения
    user_messages.pop(user_id, None)
    user_messages.pop(partner_id, None)
    
    # Уведомляем партнера если нужно
    if notify_partner and partner_id:
        try:
            await context.bot.send_message(
                partner_id,
                "⚠️ Собеседник покинул диалог.\n\n"
                "Пожалуйста, оцените собеседника:",
                reply_markup=create_rating_keyboard(user_id)
            )
        except Exception as e:
            logger.error(f"Error notifying partner: {e}")
    
    return partner_id

async def handle_chat_actions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка действий в чате (выход)"""
    user = update.effective_user
    user_id = user.id
    text = update.message.text
    
    # Сохраняем информацию о пользователе
    save_user_info(user)
    
    if text == "🚪 Выйти из диалога":
        partner_id = await exit_chat(user_id, context, notify_partner=True)
        
        if partner_id:
            await update.message.reply_text(
                "Вы вышли из диалога. Пожалуйста, оцените собеседника:",
                reply_markup=create_rating_keyboard(partner_id)
            )
        else:
            await update.message.reply_text(
                "Вы вышли из диалога.",
                reply_markup=main_keyboard
            )
        
        return RATING if partner_id else SEARCHING
    
    elif text == "🔍 Выйти и найти нового":
        partner_id = await exit_chat(user_id, context, notify_partner=True)
        
        if partner_id:
            await update.message.reply_text(
                "Вы вышли из диалога. Пожалуйста, оцените собеседника:",
                reply_markup=create_rating_keyboard(partner_id)
            )
            return RATING
        
        # Начинаем поиск нового
        waiting_users.append(user_id)
        await update.message.reply_text(
            "🔎 Ищем нового собеседника...",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отменить поиск")]], resize_keyboard=True)
        )
        return SEARCHING
    
    return IN_CHAT

def create_rating_keyboard(partner_id: int) -> InlineKeyboardMarkup:
    """Создание клавиатуры для оценки"""
    keyboard = [
        [
            InlineKeyboardButton("⭐ 1", callback_data=f"rate_{partner_id}_1"),
            InlineKeyboardButton("⭐ 2", callback_data=f"rate_{partner_id}_2"),
            InlineKeyboardButton("⭐ 3", callback_data=f"rate_{partner_id}_3"),
            InlineKeyboardButton("⭐ 4", callback_data=f"rate_{partner_id}_4"),
            InlineKeyboardButton("⭐ 5", callback_data=f"rate_{partner_id}_5"),
        ],
        [InlineKeyboardButton("🚫 Пропустить", callback_data=f"rate_{partner_id}_0")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def handle_rating(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка оценки собеседника"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    user_id = user.id
    data = query.data.split('_')
    
    if len(data) == 3:
        partner_id = int(data[1])
        rating = int(data[2])
        
        # Сохраняем оценку
        if partner_id not in user_ratings:
            user_ratings[partner_id] = {'total_rating': 0.0, 'rating_count': 0}
        
        if rating > 0:
            user_ratings[partner_id]['total_rating'] += rating
            user_ratings[partner_id]['rating_count'] += 1
            
            await query.edit_message_text(
                f"✅ Спасибо за оценку! Вы поставили {rating} ⭐"
            )
        else:
            await query.edit_message_text(
                "Оценка пропущена."
            )
    
    # Добавляем информацию о том, что пользователь админ
    admin_message = ""
    if is_admin(user_id):
        admin_message = "\n👑 Вы вошли как администратор."
    
    await context.bot.send_message(
        user_id,
        f"Нажмите кнопку ниже, чтобы найти нового собеседника.{admin_message}",
        reply_markup=main_keyboard
    )
    return SEARCHING

async def skip_rating(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пропуск оценки"""
    user = update.effective_user
    user_id = user.id
    
    # Сохраняем информацию о пользователе
    save_user_info(user)
    
    # Добавляем информацию о том, что пользователь админ
    admin_message = ""
    if is_admin(user_id):
        admin_message = "\n👑 Вы вошли как администратор."
    
    await update.message.reply_text(
        f"Нажмите кнопку ниже, чтобы найти нового собеседника.{admin_message}",
        reply_markup=main_keyboard
    )
    return SEARCHING

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для администраторов"""
    user_id = update.effective_user.id
    
    if is_admin(user_id):
        # Показываем статистику
        active_chats_count = len(active_chats) // 2
        waiting_users_count = len(waiting_users)
        
        await update.message.reply_text(
            f"👑 Админ-панель:\n\n"
            f"• Активных диалогов: {active_chats_count}\n"
            f"• Пользователей в поиске: {waiting_users_count}\n"
            f"• Всего пользователей в системе: {len(user_info)}\n\n"
            f"Список администраторов: {', '.join(map(str, ADMIN_IDS))}"
        )
    else:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Update {update} caused error {context.error}")

def main():
    """Запуск бота"""
    # Вставьте ваш токен бота здесь
    TOKEN = "8387319893:AAHx9C8zNlSachceXkfqERdXcmAyo-d79Gc"
    
    # Ваши ID администраторов (замените на реальные)
    global ADMIN_IDS
    ADMIN_IDS = [8584812799, 523688738]  # Укажите здесь ID администраторов
    
    # Создаем Application
    application = Application.builder().token(TOKEN).build()
    
    # Добавляем команду для администраторов
    application.add_handler(CommandHandler('admin', admin_command))
    
    # Создаем ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SEARCHING: [
                MessageHandler(filters.Regex("^🔍 Найти собеседника$"), search_partner),
                MessageHandler(filters.Regex("^❌ Отменить поиск$"), cancel_search),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
            ],
            IN_CHAT: [
                MessageHandler(filters.Regex("^(🚪 Выйти из диалога|🔍 Выйти и найти нового)$"), handle_chat_actions),
                MessageHandler(filters.PHOTO, handle_media),
                MessageHandler(filters.VIDEO, handle_media),
                MessageHandler(filters.Document.ALL, handle_media),
                MessageHandler(filters.AUDIO, handle_media),
                MessageHandler(filters.VOICE, handle_media),
                MessageHandler(filters.Sticker.ALL, handle_media),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
            ],
            RATING: [
                CallbackQueryHandler(handle_rating, pattern="^rate_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, skip_rating),
            ]
        },
        fallbacks=[CommandHandler('start', start)],
    )
    
    # Добавляем обработчики
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)
    
    # Запускаем бота
    print("Бот запущен...")
    print(f"Администраторы: {ADMIN_IDS}")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
