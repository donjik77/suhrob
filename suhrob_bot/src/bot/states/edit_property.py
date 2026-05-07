from aiogram.fsm.state import State, StatesGroup


class EditExistingPropertyStates(StatesGroup):
    entering_field_value = State()
