from aiogram.fsm.state import State, StatesGroup


class SchedulePostStates(StatesGroup):
    entering_datetime = State()
