from aiogram.fsm.state import State, StatesGroup


class AddPropertyStates(StatesGroup):
    # Step 1: property type
    choosing_type = State()
    # Step 2: district
    choosing_district = State()
    entering_district = State()       # custom district text input
    # Step 3: address (optional)
    entering_address = State()
    # Step 4: rooms
    choosing_rooms = State()
    # Step 5: floor (apartments only)
    entering_floor = State()
    entering_total_floors = State()
    # Step 6: area (optional)
    choosing_area = State()
    entering_area = State()           # custom area text input
    # Step 7: price
    choosing_price = State()
    entering_price = State()          # custom price text input
    # Step 8: features (multi-select, stays here while toggling)
    choosing_features = State()
    # Step 9: keywords (optional)
    entering_keywords = State()
    # Step 10: upload media
    uploading_media = State()
    # Step 11: processing/preview preparation
    entering_description = State()
    # Step 12: preview
    reviewing_preview = State()
    editing_description = State()     # inline edit of property text
    waiting_custom_text = State()
    # Step 13: publish options
    choosing_publish_date = State()
    choosing_publish_time = State()
    entering_schedule_datetime = State()  # manual text fallback
