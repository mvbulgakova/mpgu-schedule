from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.db.models import User, Schedule
from bot.keyboards.schedule import build_schedule_kb
from bot.services.schedule_fmt import format_today, format_tomorrow, format_week

router = Router()
MAX_MESSAGE_LEN = 4096


async def _get_group_data(db: AsyncSession, user_id: int) -> dict | None:
    user = await db.get(User, user_id)
    if not user or not user.group_code:
        return None
    schedule = await db.get(Schedule, user.group_code)
    return schedule.data if schedule else None


async def send_today(message: Message, db: AsyncSession, group_code: str | None = None):
    if group_code is None:
        user = await db.get(User, message.from_user.id)
        group_code = user.group_code if user else None
    if not group_code:
        await message.answer("Сначала выбери группу. Напиши /start")
        return
    await send_today_by_code(message, db, group_code)


async def send_today_by_code(message: Message, db: AsyncSession, group_code: str):
    schedule = await db.get(Schedule, group_code)
    if not schedule:
        await message.answer("Расписание не найдено. Попробуй позже.")
        return
    text = format_today(schedule.data)
    kb = build_schedule_kb(group_code)
    await message.answer(text[:MAX_MESSAGE_LEN], parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "sch:today")
async def on_today(call: CallbackQuery, db: AsyncSession):
    group_data = await _get_group_data(db, call.from_user.id)
    if not group_data:
        await call.answer("Группа не выбрана", show_alert=True)
        return
    text = format_today(group_data)
    kb = build_schedule_kb(group_data["name"])
    await call.message.edit_text(text[:MAX_MESSAGE_LEN], parse_mode="HTML", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "sch:tomorrow")
async def on_tomorrow(call: CallbackQuery, db: AsyncSession):
    group_data = await _get_group_data(db, call.from_user.id)
    if not group_data:
        await call.answer("Группа не выбрана", show_alert=True)
        return
    text = format_tomorrow(group_data)
    kb = build_schedule_kb(group_data["name"])
    await call.message.edit_text(text[:MAX_MESSAGE_LEN], parse_mode="HTML", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "sch:week")
async def on_week(call: CallbackQuery, db: AsyncSession):
    group_data = await _get_group_data(db, call.from_user.id)
    if not group_data:
        await call.answer("Группа не выбрана", show_alert=True)
        return
    text = format_week(group_data)
    kb = build_schedule_kb(group_data["name"])
    if len(text) > MAX_MESSAGE_LEN:
        text = text[:MAX_MESSAGE_LEN - 50] + "\n\n<i>...список обрезан</i>"
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await call.answer()
