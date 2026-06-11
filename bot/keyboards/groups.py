from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

PAGE_SIZE = 10


def build_groups_kb(groups: list[dict], page: int = 0) -> InlineKeyboardMarkup:
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_groups = groups[start:end]

    buttons = [
        [InlineKeyboardButton(text=g["name"], callback_data=f"grp:{g['name']}")]
        for g in page_groups
    ]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="← Назад", callback_data=f"grp_page:{page - 1}"))
    if end < len(groups):
        nav.append(InlineKeyboardButton(text="Далее →", callback_data=f"grp_page:{page + 1}"))
    if nav:
        buttons.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=buttons)
