from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.db.models import User, Institute

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, db: AsyncSession):
    user = await db.get(User, message.from_user.id)

    if user and user.group_code:
        from bot.handlers.schedule import send_today_by_code
        await send_today_by_code(message, db, user.group_code)
        return

    result = await db.execute(select(Institute).order_by(Institute.name))
    institutes = result.scalars().all()

    from bot.keyboards.institutes import build_institutes_kb
    kb = build_institutes_kb([{"id": i.id, "name": i.name} for i in institutes])

    await message.answer(
        "👋 Привет! Я помогу найти расписание МПГУ.\n\n"
        "Выбери свой институт:",
        reply_markup=kb,
    )
