import datetime
import re

from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from commands.utils.Synchronize_utils import sync_cat_from_db_to_table
from database import CategoriesTypes, StatusTypes
from datafiles import DAYSUNTILNEXTMONTH
from init import States


class CreateTable(Command):
    def __init__(self, command_manager, postgres_wrapper):
        super().__init__(command_manager, postgres_wrapper)
        self.temp_data = {}

    async def execute(
        self, message: Message, state: FSMContext, command: CommandObject
    ):
        # resp = await check_spreadsheet_exist(message)
        # if resp == 'error':
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
                self.temp_data[message.from_user.id]["gmail"] = message.text
                await state.set_state(States.CHOICE_TABLE_NAME)
                await message.answer("Напишите название будущей таблицы:")

        elif cur_state == States.CHOICE_TABLE_NAME:
            self.temp_data[message.from_user.id]["title"] = message.text
            await state.set_state(States.COMFIRM_CHANGE_DATE_RESET)
            await message.answer(
                "Напишите день, в который будет происходить переход таблицы на новый месяц(этот день должен быть в каждом месяце, т.е. меньший 29)"
            )

        elif cur_state == States.COMFIRM_CHANGE_DATE_RESET:
            try:
                # tz = datetime.timezone(datetime.timedelta(hours=2, minutes=50))
                # today = datetime.datetime.now(tz=tz).date()
                today = datetime.date.today()
                new_day = int(message.text.split()[0])
                if new_day > 0 and new_day < 29:
                    if new_day > today.day:
                        start_date = (
                            today
                            - datetime.timedelta(
                                days=DAYSUNTILNEXTMONTH[str(today.month - 1)]
                            )
                            + datetime.timedelta(days=new_day - today.day)
                        )
                    else:
                        start_date = today - datetime.timedelta(
                            days=today.day - new_day
                        )

                    await message.answer("Подождите, идет создание таблицы")
                    title = self.temp_data[message.from_user.id]["title"]
                    gmail = self.temp_data[message.from_user.id]["gmail"]

                    spreadsheetID = self.spreadsheetWrapper.createTable(title, gmail)
                    response = self.spreadsheetWrapper.addNewOperationsSheet(
                        spreadsheetID, start_date
                    )
                    response = self.spreadsheetWrapper.addNewStatisticsSheet(
                        spreadsheetID, start_date, DAYSUNTILNEXTMONTH[str(start_date.month)]
                    )

                    print(f"https://docs.google.com/spreadsheets/d/{spreadsheetID}/")
                    id = self.postgres_wrapper.spreadsheets_wrapper.create(
                        gmail=[gmail],
                        spreadsheet_id=spreadsheetID,
                        start_date=start_date,
                    )
                    self.postgres_wrapper.users_wrapper.create_user(
                        telegram_id=message.from_user.id, spreadsheet_id=id
                    )

                    self.postgres_wrapper.categories_wrapper.add_category(
                        spreadsheet_id=str(id),
                        status=StatusTypes.ACTIVE,
                        type=CategoriesTypes.INCOME,
                        title="НеопределенныйДоход",
                        associations=["неопределенныйдоход"],
                        product_types=[],
                    )

                    self.postgres_wrapper.categories_wrapper.add_category(
                        spreadsheet_id=str(id),
                        status=StatusTypes.ACTIVE,
                        type=CategoriesTypes.COST,
                        title="НеопределенныеТраты",
                        associations=["неопределенныетраты"],
                        product_types=[],
                    )

                    spreadsheet = self.postgres_wrapper.spreadsheets_wrapper.get_spreadsheet_by_id(
                        id
                    )
                    result_sync = sync_cat_from_db_to_table(
                        spreadsheet, self.postgres_wrapper
                    )
                    values = [result_sync]
                    self.spreadsheetWrapper.setValues(
                        spreadsheet.spreadsheet_id, values
                    )

                    del self.temp_data[message.from_user.id]

                    await state.clear()

                    await self.commandManager.getCommands()["table"].execute(
                        message, state, command
                    )
                    await self.commandManager.getCommands()['help'].execute(message, state, command)
                else:
                    await message.answer("Число должно быть > 0 и < 29")
            except Exception as e:
                await message.answer("Странное число")
