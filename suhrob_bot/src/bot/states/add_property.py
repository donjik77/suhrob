from aiogram.fsm.state import State, StatesGroup


class AddPropertyStates(StatesGroup):
    choosing_type = State()
    choosing_district = State()
    entering_district = State()
    entering_address = State()
    entering_rooms = State()
    entering_floor = State()
    entering_total_floors = State()
    entering_area = State()
    entering_price = State()
    entering_description = State()
    uploading_photos = State()
    uploading_videos = State()
    preview = State()
    choosing_publish_time = State()
    entering_schedule_datetime = State()
