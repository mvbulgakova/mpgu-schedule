from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.db.models import User, Institute

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, db: AsyncSession):
    await _show_institute_picker(message, db)


@router.callback_query(F.data == "change_group")
async def on_change_group(call: CallbackQuery, db: AsyncSession):
    await _show_institute_picker(call.message, db)
    await call.answer()


async def _show_institute_picker(message: Message, db: AsyncSession):
    result = await db.execute(select(Institute).order_by(Institute.name))
    institutes = result.scalars().all()

    from bot.keyboards.institutes import build_institutes_kb
    kb = build_institutes_kb([{"id": i.id, "name": i.name} for i in institutes])

    await message.answer(
        "👋 Привет! Я помогу найти расписание МПГУ.\n\n"
        "Выбери свой институт:",
        reply_markup=kb,
    )
