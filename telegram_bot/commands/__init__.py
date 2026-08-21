"""Команды бота и их сборка."""

from __future__ import annotations

from telegram_bot.access import AccessGuard
from telegram_bot.ai import AiClient
from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.commands.cancel import CancelCommand
from telegram_bot.commands.check import CheckCommand
from telegram_bot.commands.check_delete import CheckDeleteCommand
from telegram_bot.commands.check_skip import CheckSkipCommand
from telegram_bot.commands.help import HelpCommand
from telegram_bot.commands.manager import Manager
from telegram_bot.commands.record_add import RecordAddCommand
from telegram_bot.commands.record_delete import RecordDeleteCommand
from telegram_bot.commands.settings import SettingsCommand
from telegram_bot.commands.settings_llm import SettingsLlmCostsCommand
from telegram_bot.commands.start import StartCommand
from telegram_bot.commands.table import TableCommand
from telegram_bot.commands.table_email import TableEmailCommand
from telegram_bot.commands.table_sync import TableSyncCommand
from telegram_bot.commands.table_unlink import TableUnlinkCommand
from telegram_bot.commands.transfer_add import TransferAddCommand
from telegram_bot.commands.transfer_delete import TransferDeleteCommand
from telegram_bot.enums import CommandName
from telegram_bot.notifications import NotificationCatchUp


def get_commands(
    manager: Manager,
    api: ApiGateway,
    aiogram_wrapper: AiogramWrapper,
    catch_up: NotificationCatchUp,
    ai: AiClient,
    access: AccessGuard,
) -> dict[str, BaseCommand]:
    """Собирает реестр команд.

    Ключ совпадает с командой Telegram без слеша, поэтому второй таблицы
    соответствий не существует и рассинхронизироваться нечему.

    `/check_skip` и `/check_del` получают саму команду разбора, а не копию её
    логики: очередь и черновик живут в одном месте, и показать следующий чек
    умеет только оно. Тем же способом собран `/settings`: админская ветка
    получает сам экран настроек, потому что возвращается к нему после отчёта.

    `AccessGuard` нужен ровно одной команде — экрану настроек, который выбирает
    по роли текст. Право на админскую ветку здесь не проверяется: оно объявлено
    у самой ветки и проверяется `Manager`.
    """
    arguments = (manager, api, aiogram_wrapper, catch_up)
    check = CheckCommand(*arguments, ai)
    settings = SettingsCommand(*arguments, access)
    return {
        CommandName.START: StartCommand(*arguments),
        CommandName.HELP: HelpCommand(*arguments),
        CommandName.CANCEL: CancelCommand(*arguments),
        CommandName.ADD: RecordAddCommand(*arguments),
        CommandName.DEL: RecordDeleteCommand(*arguments),
        CommandName.ADD_TRANS: TransferAddCommand(*arguments),
        CommandName.DEL_TRANS: TransferDeleteCommand(*arguments),
        CommandName.TABLE: TableCommand(*arguments),
        CommandName.TABLE_SYNC: TableSyncCommand(*arguments),
        CommandName.TABLE_EMAIL: TableEmailCommand(*arguments),
        CommandName.TABLE_UNLINK: TableUnlinkCommand(*arguments),
        CommandName.CHECK: check,
        CommandName.CHECK_SKIP: CheckSkipCommand(*arguments, check),
        CommandName.CHECK_DEL: CheckDeleteCommand(*arguments, check),
        CommandName.SETTINGS: settings,
        CommandName.SETTINGS_LLM: SettingsLlmCostsCommand(*arguments, settings),
    }


__all__ = ["BaseCommand", "Manager", "get_commands"]
