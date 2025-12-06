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
    KeyboardButton
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /start"""
    user_id = update.effective_user.id

    # Инициализация рейтинга пользователя если нужно
    if user_id not in user_ratings:
        user_ratings[user_id] = {'total_rating': 0.0, 'rating_count': 0}

    # Если пользователь в активном чате, выводим его
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        await exit_chat(user_id, context, notify_partner=True)

    await update.message.reply_text(
        "👋 Добро пожаловать в анонимный чат!\n\n"
        "Нажмите кнопку ниже, чтобы найти собеседника.",
        reply_markup=main_keyboard
    )
    return SEARCHING


async def search_partner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Поиск собеседника"""
    user_id = update.effective_user.id

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
        user1 = waiting_users.pop(0)
        user2 = waiting_users.pop(0)

        # Создаем чат
        active_chats[user1] = user2
        active_chats[user2] = user1

        # Получаем рейтинги
        rating1 = calculate_rating(user1)
        rating2 = calculate_rating(user2)

        # Отправляем уведомления
        try:
            await context.bot.send_message(
                user1,
                f"✅ Найден собеседник!\n"
                f"Рейтинг собеседника: ⭐ {rating2:.1f}/5\n\n"
                f"Теперь вы можете общаться анонимно.\n"
                f"Все сообщения и файлы будут пересылаться.",
                reply_markup=chat_keyboard
            )

            await context.bot.send_message(
                user2,
                f"✅ Найден собеседник!\n"
                f"Рейтинг собеседника: ⭐ {rating1:.1f}/5\n\n"
                f"Теперь вы можете общаться анонимно.\n"
                f"Все сообщения и файлы будут пересылаться.",
                reply_markup=chat_keyboard
            )

            # Отправляем сохраненные сообщения если есть
            if user1 in user_messages:
                for msg_data in user_messages[user1]:
                    await forward_message_to_partner(user1, msg_data, context)
                user_messages.pop(user1, None)

            if user2 in user_messages:
                for msg_data in user_messages[user2]:
                    await forward_message_to_partner(user2, msg_data, context)
                user_messages.pop(user2, None)

        except Exception as e:
            logger.error(f"Error starting chat: {e}")
            # Если ошибка, очищаем чат
            active_chats.pop(user1, None)
            active_chats.pop(user2, None)

            await context.bot.send_message(user1, "❌ Ошибка при подключении. Попробуйте снова.",
                                           reply_markup=main_keyboard)
            await context.bot.send_message(user2, "❌ Ошибка при подключении. Попробуйте снова.",
                                           reply_markup=main_keyboard)
            return SEARCHING

        return IN_CHAT

    return SEARCHING


async def cancel_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена поиска"""
    user_id = update.effective_user.id

    if user_id in waiting_users:
        waiting_users.remove(user_id)

    await update.message.reply_text(
        "❌ Поиск отменен.",
        reply_markup=main_keyboard
    )
    return SEARCHING


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка сообщений в чате"""
    user_id = update.effective_user.id

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
    user_id = update.effective_user.id

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
    user_id = update.effective_user.id
    text = update.message.text

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

    user_id = update.effective_user.id
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

    await context.bot.send_message(
        user_id,
        "Нажмите кнопку ниже, чтобы найти нового собеседника.",
        reply_markup=main_keyboard
    )
    return SEARCHING


async def skip_rating(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пропуск оценки"""
    await update.message.reply_text(
        "Нажмите кнопку ниже, чтобы найти нового собеседника.",
        reply_markup=main_keyboard
    )
    return SEARCHING


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Update {update} caused error {context.error}")


def main():
    """Запуск бота"""
    # Вставьте ваш токен бота здесь
    TOKEN = "8387319893:AAHx9C8zNlSachceXkfqERdXcmAyo-d79Gc"

    # Создаем Application
    application = Application.builder().token(TOKEN).build()

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
                MessageHandler(filters.Document.ALL, handle_media),  # Исправленный фильтр для документов
                MessageHandler(filters.AUDIO, handle_media),
                MessageHandler(filters.VOICE, handle_media),
                MessageHandler(filters.Sticker.ALL, handle_media),  # Исправленный фильтр для стикеров
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
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()