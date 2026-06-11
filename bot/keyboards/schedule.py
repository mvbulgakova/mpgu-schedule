from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def build_schedule_kb(group_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Завтра", callback_data="sch:tomorrow"),
            InlineKeyboardButton(text="Вся Неделя", callback_data="sch:week"),
        ],
        [
            InlineKeyboardButton(text="Сегодня", callback_data="sch:today"),
            InlineKeyboardButton(text="⚠️ Ошибка в данных", callback_data=f"err:{group_code}"),
        ],
    ])
