class CommandManager:
    def __init__(self):
        self.commands = {}

    def getCommands(self):
        return self.commands

    def addCommand(self, title, command):
        self.commands[title] = command

    def addCommands(self, commands):
        for i in commands:
            self.addCommand(i, commands[i])

    async def launchCommand(self, title, message, state, command):
        response = await self.commands[title].execute(message, state, command)
