from commands.AddCheck import AddCheck
from commands.AddEmail import AddEmail
from commands.AddRecord import AddRecord
from commands.CreateTable import CreateTable
from commands.DeleteRecord import DeleteRecord
from commands.DeleteTable import DeleteTable
from commands.GetHelp import GetHelp
from commands.GetTable import GetTable
from commands.Synchronize import Synchronize
from commands.Transfer import Transfer

def get_commands(command_manager, postgres_wrapper):
    commands = {"start": CreateTable(command_manager, postgres_wrapper),
                "table": GetTable(command_manager, postgres_wrapper),
                "addEmail": AddEmail(command_manager, postgres_wrapper),
                "help": GetHelp(command_manager, postgres_wrapper),
                "deleteTable": DeleteTable(command_manager, postgres_wrapper),
                "sync": Synchronize(command_manager, postgres_wrapper),
                "del": DeleteRecord(command_manager, postgres_wrapper),
                "transfer": Transfer(command_manager, postgres_wrapper),
                "addRecord": AddRecord(command_manager, postgres_wrapper),
                "addCheck": AddCheck(command_manager, postgres_wrapper)}
    return commands