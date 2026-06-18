from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import ErrorReport
from bot.states import ReportError

router = Router()


@router.callback_query(F.data.startswith("err:"))
async def on_error_button(call: CallbackQuery, state: FSMContext):
    group_code = call.data.split(":", 1)[1]
    await state.set_state(ReportError.waiting_message)
    await state.update_data(group_code=group_code)
    await call.message.answer(
        f"⚠️ Опиши что именно не так в расписании группы <b>{group_code}</b>.\n\n"
        "Например: «Неверный преподаватель на 3-й паре в понедельник»",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(ReportError.waiting_message)
async def on_error_message(message: Message, state: FSMContext, db: AsyncSession):
    data = await state.get_data()
    group_code = data.get("group_code", "unknown")

    db.add(ErrorReport(
        user_id=message.from_user.id,
        group_code=group_code,
        message=message.text or "",
    ))
    await db.commit()
    await state.clear()

    await message.answer(
        "✅ Спасибо! Сообщение об ошибке получено.\n"
        "Мы проверим и исправим данные."
    )
