from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    select_group = State()


class ReportError(StatesGroup):
    waiting_message = State()
