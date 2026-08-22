"""Базовый класс команды."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar, cast

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.api_client.errors import ApiNotFoundError
from telegram_bot.api_client.models import NotificationKind, Spreadsheet
from telegram_bot.enums import CommandName, FsmDataKeys
from telegram_bot.errors import NO_TABLE_MESSAGE, TABLE_CREATING_MESSAGE
from telegram_bot.notifications import NotificationCatchUp

if TYPE_CHECKING:
    from telegram_bot.commands.manager import Manager
    from telegram_bot.commands.menu import MenuCommand


class BaseCommand(ABC):
    """Общее для всех команд: доступ к api, обёртке aiogram и менеджеру."""

    #: Требует ли команда роли админа. Проверяет `Manager` — там же, где
    #: проверяется сам доступ, и на обоих входах сразу. Команда о роли не знает
    #: ничего: иначе каждая следующая админская кнопка помнила бы о проверке
    #: вручную, и первая забытая молча открыла бы ветку всем.
    requires_admin: ClassVar[bool] = False

    def __init__(
        self,
        manager: Manager,
        api: ApiGateway,
        aiogram_wrapper: AiogramWrapper,
        catch_up: NotificationCatchUp,
    ) -> None:
        self.manager = manager
        self.api = api
        self.aiogram = aiogram_wrapper
        self.catch_up = catch_up

    @abstractmethod
    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Выполняет команду."""

    async def handle_callback(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """Обрабатывает нажатие кнопки.

        Кнопки есть не у всех команд; там, где их нет, нажатие может прийти
        лишь от кнопки, оставшейся в переписке от другой версии бота, и тихо
        проглатывать такое нельзя — это ошибка сборки, а не ввода.
        """
        raise NotImplementedError(f"{type(self).__name__} не работает с кнопками")

    async def callback_target(self, callback: CallbackQuery) -> tuple[int, int] | None:
        """Гасит «часики» и отдаёт пару «чат, автор нажатия».

        Одно место на все кнопочные ветки, потому что ошибиться здесь можно
        дважды и обе ошибки молчаливые. Первая: не ответить на callback —
        кнопка у пользователя крутится до таймаута Telegram. Вторая: взять
        пользователя из `callback.message` — его автор бот, и команда искала бы
        таблицу по идентификатору самого бота.

        `None` означает, что отвечать некуда: к сообщению старше суток Telegram
        не прикладывает `message`, и продолжать нечем.
        """
        await self.aiogram.answer_callback(callback)
        if callback.message is None:
            return None
        return callback.message.chat.id, callback.from_user.id

    async def ask(
        self,
        *,
        chat_id: int,
        state: FSMContext,
        text: str,
        rows: Sequence[Sequence[tuple[str, str]]] = (),
        parse_mode: str | None = None,
    ) -> None:
        """Отправляет блок диалога, оставляя живой ровно одну клавиатуру.

        Любое сообщение, после которого бот ждёт ответа, идёт через этот метод:
        вопрос шага, повтор вопроса на нетекстовый ввод, отказ разбора. Иначе
        живая кнопка «Отмена» оставалась бы выше по переписке — там, где
        пользователь её уже не ищет.

        Клавиатура предыдущего блока гасится **до** отправки нового: порядок
        виден пользователю, и мигание «две клавиатуры разом» заметнее, чем
        пустой промежуток.
        """
        await self.drop_keyboard(chat_id=chat_id, state=state)
        sent = await self.aiogram.send_message(
            chat_id,
            text,
            keyboard=self.aiogram.inline_keyboard_rows(rows) if rows else None,
            parse_mode=parse_mode,
        )
        if rows:
            await self.aiogram.set_state_data(
                state, FsmDataKeys.KEYBOARD_MESSAGE_ID, sent.message_id
            )

    async def drop_keyboard(self, *, chat_id: int, state: FSMContext) -> None:
        """Гасит клавиатуру последнего блока, если она ещё висит.

        Идентификатор стирается из FSM первым: гашение может не удаться
        (сообщение удалили, оно устарело), и хранить после этого номер значило
        бы пытаться погасить одно и то же на каждом следующем шаге.
        """
        raw = await self.aiogram.get_state_data(state, FsmDataKeys.KEYBOARD_MESSAGE_ID)
        if not isinstance(raw, int):
            return
        await self.aiogram.set_state_data(state, FsmDataKeys.KEYBOARD_MESSAGE_ID, None)
        await self.aiogram.clear_keyboard(chat_id, raw)

    async def finish(self, *, chat_id: int, state: FSMContext) -> None:
        """Закрывает ветку: гасит клавиатуру и снимает состояние.

        Один выход на все случаи — успех, отмена, потерянный черновик, отказ
        модели, пустая очередь. Порядок обязателен: `clear_state` стирает
        FSM-данные вместе с номером сообщения, и гашение после него не нашло бы
        уже ничего, а живая кнопка осталась бы висеть вне всякого диалога.
        """
        await self.drop_keyboard(chat_id=chat_id, state=state)
        await self.aiogram.clear_state(state)

    @staticmethod
    def user_id(message: Message) -> int:
        """Идентификатор автора сообщения.

        Везде именно `from_user`, а не `chat`: в группе это разные числа, и
        старая версия из-за расхождения искала таблицу по id чата в одной
        команде и по id пользователя во всех остальных.
        """
        if message.from_user is None:
            raise ValueError("Сообщение без автора")
        return message.from_user.id

    @staticmethod
    def text_of(message: Message) -> str | None:
        """Текст сообщения или `None`, если это не текст.

        Проверка обязательна на каждом шаге диалога: фотография или стикер в
        ожидании ответа давали в старой версии `TypeError` мимо всех
        обработчиков, и пользователь оставался в состоянии без единого слова в
        ответ.
        """
        return message.text

    async def spreadsheet(self, message: Message) -> Spreadsheet | None:
        """Таблица пользователя либо `None` с уже отправленной подсказкой."""
        return await self.spreadsheet_for(
            user_id=self.user_id(message),
            chat_id=message.chat.id,
        )

    async def spreadsheet_for(self, *, user_id: int, chat_id: int) -> Spreadsheet | None:
        """То же, но по явным идентификаторам.

        Нужно там, где сообщения пользователя нет вовсе: шаг разбора чека может
        прийти нажатием кнопки, и `callback.message` принадлежит боту, а не
        человеку — искать по нему документ значило бы повторить старую ошибку с
        `chat.id` вместо `from_user.id`.

        **Неготовая таблица здесь равносильна отсутствующей.** Пока
        `google_sheets_service` не создал документ, работать не с чем: смотреть
        пользователю некуда, а операция, принятая «вслепую», выглядела бы
        потерянной. Api это проверяет и сам, но не везде — очередь чеков он
        отдаёт и неготовому документу, и без проверки здесь пользователь прошёл
        бы все три стадии разбора и два вызова модели, чтобы получить отказ на
        записи. Одна точка на все команды: новая получает проверку даром.
        """
        spreadsheet = await self.find_spreadsheet(user_id=user_id, chat_id=chat_id)
        if spreadsheet is None:
            await self.aiogram.send_message(chat_id, NO_TABLE_MESSAGE)
            return None
        if not spreadsheet.is_ready:
            await self.aiogram.send_message(chat_id, TABLE_CREATING_MESSAGE)
            return None
        return spreadsheet

    async def find_spreadsheet(
        self,
        *,
        user_id: int,
        chat_id: int,
        menu_on_ready: bool = True,
    ) -> Spreadsheet | None:
        """Таблица пользователя или `None` — молча, без подсказки.

        Отдельно от `spreadsheet_for`, потому что для входа в бота отсутствие
        таблицы — рабочий случай, а не ошибка: `/start` на него показывает
        приветствие с кнопкой, и «Сначала создайте таблицу» перед этим
        приветствием было бы ответом на вопрос, которого никто не задавал.

        Ловится только 404 по ресурсам `spreadsheet` и `user`: старая версия
        отвечала «Сначала создайте таблицу» на любой 404, включая «нет такой
        операции».

        Здесь же — единственная точка дочитки уведомлений: это ровно тот
        момент, когда бот и знает документ, и разговаривает с его владельцем.
        Дочитка идёт и для неготовой таблицы: `TABLE_READY` иначе нечем было бы
        доехать, если push не прошёл.

        `menu_on_ready` выключает дорисовку меню по `TABLE_READY`. Нужно это
        одному `/start`: он и сам показывает экран по готовности, и без флага
        меню пришло бы дважды подряд.
        """
        try:
            spreadsheet = await self.api.spreadsheets.by_telegram_id(user_id)
        except ApiNotFoundError as error:
            if error.resource not in {"spreadsheet", "user"}:
                raise
            return None

        delivered = await self.catch_up.deliver(spreadsheet.id, chat_id)
        if menu_on_ready and NotificationKind.TABLE_READY in delivered:
            # Дочитка — второй путь доставки, и по нему сообщение «таблица
            # готова» приезжает так же, как push-ом. Значит, и меню за ним
            # должно идти так же: иначе пользователь, чьё уведомление приехало
            # дочиткой, остался бы без экрана, ничем не отличаясь от
            # остальных, — и не зная, что его чего-то лишили.
            await self.menu().show(chat_id=chat_id)
        return spreadsheet

    def menu(self) -> MenuCommand:
        """Экран меню из реестра команд.

        Через `Manager`, а не полем: `MenuCommand` — тоже команда, и второй
        ссылки на неё, живущей отдельно от реестра, быть не должно. Он же
        разрывает круг импортов — `menu.py` наследуется отсюда.

        Ключ отсутствует — это ошибка сборки, и `Manager.get` роняет её сам.
        """
        return cast("MenuCommand", self.manager.get(CommandName.MENU))
