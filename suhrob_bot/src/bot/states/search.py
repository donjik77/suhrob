from aiogram.fsm.state import State, StatesGroup


class SearchStates(StatesGroup):
    choosing_type = State()
    choosing_district = State()
    entering_district = State()
    choosing_rooms = State()
    choosing_price = State()
    entering_custom_price = State()
    showing_results = State()
