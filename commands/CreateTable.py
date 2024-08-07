import datetime
import re

from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from database.queries.spreadsheets_queries import create, get_spreadsheet
from database.queries.users_queries import create_user
from init import States, daysUntilNextMonth


class CreateTable(Command):
    def __init__(self, command_manager):
        super().__init__(command_manager)
        self.temp_data = {}

    async def execute(self, message: Message, state: FSMContext, command: CommandObject):
        # spreadsheet = get_spreadsheet(message.from_user.id)
        # if spreadsheet != None:
        #     await message.answer('Таблица уже создана')
        #     return

        cur_state = await state.get_state()
        if cur_state == None:
            self.temp_data[message.from_user.id] = {}
            await state.set_state(States.SET_EMAIL)
            await message.answer("Пришлите почту на домене @gmail")

        elif cur_state == States.SET_EMAIL:
            if re.fullmatch(r"\w+@gmail.com", message.text) == None:
                await message.answer("Мне почта не нравится, давай другую")
            else:
                self.temp_data[message.from_user.id]['gmail'] = message.text
                await state.set_state(States.CHOICE_TABLE_NAME)
                await message.answer("Напишите название будущей таблицы:")

        elif cur_state == States.CHOICE_TABLE_NAME:
            self.temp_data[message.from_user.id]['title'] = message.text
            await state.set_state(States.COMFIRM_CHANGE_DATE_RESET)
            await message.answer(
                "Напишите день, в который будет происходить переход таблицы на новый месяц(этот день должен быть в каждом месяце, т.е. меньший 29)")

        elif cur_state == States.COMFIRM_CHANGE_DATE_RESET:
            try:
                # tz = datetime.timezone(datetime.timedelta(hours=2, minutes=50))
                # today = datetime.datetime.now(tz=tz).date()
                today = datetime.date.today()
                new_day = int(message.text.split()[0])
                if new_day > 0 and new_day < 29:
                    if new_day > today.day:
                        start_date = today - datetime.timedelta(days=daysUntilNextMonth[today.month-1]) + datetime.timedelta(days=new_day-today.day)
                    else:
                        start_date = today - datetime.timedelta(days=today.day-new_day)

                    await message.answer("Подождите, идет создание таблицы")
                    title = self.temp_data[message.from_user.id]['title']
                    gmail = self.temp_data[message.from_user.id]['gmail']

                    spreadsheetID = self.spreadsheet.createTable(title, gmail)
                    response = self.spreadsheet.addNewOperationsSheet(spreadsheetID,
                                                                      start_date)
                    response = self.spreadsheet.addNewStatisticsSheet(spreadsheetID,
                                                                      start_date,
                                                                      daysUntilNextMonth[start_date.month])

                    print(f"https://docs.google.com/spreadsheets/d/{spreadsheetID}/")
                    id = create(gmail=[gmail], spreadsheet_id=spreadsheetID, start_date=start_date)
                    create_user(telegram_id=message.from_user.id, spreadsheet_id=id)

                    del self.temp_data[message.from_user.id]

                    await state.clear()

                    await self.commandManager.getCommands()['table'].execute(message, state, command)
                    # await self.commandManager.getCommands()['help'].execute(message, state)
                else:
                    await message.answer("Число должно быть > 0 и < 29")
            except Exception as e:
                print(e)
                await message.answer("Странное число")
