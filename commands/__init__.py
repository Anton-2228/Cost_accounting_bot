from commands.AddEmail import AddEmail
from commands.AddRecord import AddRecord
from commands.CreateTable import CreateTable
from commands.DeleteRecord import DeleteRecord
from commands.DeleteTable import DeleteTable
from commands.GetHelp import GetHelp
from commands.GetTable import GetTable
from commands.Synchronize import Synchronize
from commands.Transfer import Transfer

def get_commands(command_manager):
    commands = {"start": CreateTable(command_manager),
                "table": GetTable(command_manager),
                "addEmail": AddEmail(command_manager),
                "help": GetHelp(command_manager),
                "deleteTable": DeleteTable(command_manager),
                "sync": Synchronize(command_manager),
                "del": DeleteRecord(command_manager),
                "transfer": Transfer(command_manager),
                "addRecord": AddRecord(command_manager)}
    return commands