from aiogram.fsm.state import State, StatesGroup


class AddPropertyStates(StatesGroup):
    waiting_content = State()           # Agent sends photos + text
    editing_field = State()             # Editing one specific field
    confirming = State()                # Showing AI-parsed preview
    choosing_publish_time = State()
    entering_schedule_datetime = State()
