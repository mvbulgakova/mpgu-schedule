from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def build_institutes_kb(institutes: list[dict]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=inst["name"], callback_data=f"inst:{inst['id']}")]
        for inst in institutes
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
