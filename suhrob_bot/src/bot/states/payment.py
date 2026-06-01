from aiogram.fsm.state import State, StatesGroup


class PaymentStates(StatesGroup):
    choosing_method = State()
    waiting_proof = State()
    entering_reject_reason = State()
    entering_custom_amount = State()
