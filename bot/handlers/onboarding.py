from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.db.models import User, Schedule
from bot.keyboards.groups import build_groups_kb

router = Router()


@router.callback_query(F.data.startswith("inst:"))
async def on_institute_selected(call: CallbackQuery, db: AsyncSession):
    institute_id = call.data.split(":", 1)[1]

    result = await db.execute(
        select(Schedule.group_code)
        .where(Schedule.institute_id == institute_id)
        .order_by(Schedule.group_code)
    )
    group_codes = [r[0] for r in result.fetchall()]

    if not group_codes:
        await call.answer("Группы не найдены. Попробуйте позже.", show_alert=True)
        return

    groups = [{"name": code} for code in group_codes]
    kb = build_groups_kb(groups, page=0, institute_id=institute_id)

    await call.message.edit_text(
        f"Найдено групп: {len(groups)}\nВыбери свою группу:",
        reply_markup=kb,
    )
    await call.answer()


@router.callback_query(F.data.startswith("grp_page:"))
async def on_group_page(call: CallbackQuery, db: AsyncSession):
    parts = call.data.split(":")  # grp_page:institute_id:page_num
    institute_id = parts[1]
    page = int(parts[2])

    result = await db.execute(
        select(Schedule.group_code)
        .where(Schedule.institute_id == institute_id)
        .order_by(Schedule.group_code)
    )
    group_codes = [r[0] for r in result.fetchall()]
    groups = [{"name": code} for code in group_codes]
    kb = build_groups_kb(groups, page=page, institute_id=institute_id)

    await call.message.edit_reply_markup(reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("grp:"))
async def on_group_selected(call: CallbackQuery, db: AsyncSession):
    group_code = call.data.split(":", 1)[1]

    result = await db.execute(
        select(Schedule.institute_id).where(Schedule.group_code == group_code)
    )
    row = result.first()
    institute_id = row[0] if row else None

    user = await db.get(User, call.from_user.id)
    if user:
        user.group_code = group_code
        user.institute_id = institute_id
    else:
        db.add(User(
            user_id=call.from_user.id,
            group_code=group_code,
            institute_id=institute_id,
        ))
    await db.commit()

    await call.message.edit_text(
        f"✅ Группа <b>{group_code}</b> сохранена!",
        parse_mode="HTML",
    )

    from bot.handlers.schedule import send_today_by_code
    await send_today_by_code(call.message, db, group_code)
    await call.answer()
