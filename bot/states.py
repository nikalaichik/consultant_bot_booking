from aiogram.fsm.state import State, StatesGroup

class UserStates(StatesGroup):
    # Состояния для консультации
    waiting_for_skin_type = State()
    waiting_for_age = State()
    waiting_for_problem_description = State()

    # Состояния для записи
    booking_procedure = State()
    booking_procedure_confirmation = State()  # Новое состояние для подтверждения процедуры
    booking_time_selection = State()          # Выбор времени из календаря
    booking_contact_info = State()            # Ввод контактных данных
    booking_final_confirmation = State()      # Финальное подтверждение записи