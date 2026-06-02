from aiogram.fsm.state import State, StatesGroup


class DepositUPI(StatesGroup):
    waiting_amount = State()
    waiting_utr = State()


class DepositCrypto(StatesGroup):
    waiting_amount = State()
    waiting_txhash = State()


class BuyAccount(StatesGroup):
    select_country = State()
    confirm = State()
    waiting_otp = State()


class BulkBuyState(StatesGroup):
    waiting_qty = State()


class LoadSessionState(StatesGroup):
    waiting_file = State()


class AdminStates(StatesGroup):
    upload_zip = State()
    waiting_zip_password = State()
    set_price = State()
    set_price_value = State()
    broadcast = State()
    broadcast_confirm = State()
    add_balance_user = State()
    add_balance_amount = State()
    set_upi = State()
    set_usdt = State()
    set_support = State()
    set_referral_bonus = State()
    set_referral_percent = State()
    add_country = State()
    add_admin = State()
    remove_admin = State()
    ban_user = State()
    search_user = State()


class SupportState(StatesGroup):
    waiting_message = State()
