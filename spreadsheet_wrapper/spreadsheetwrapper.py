import datetime

from datafiles import TEMPLATEOPERATIONS, TEMPLATESTATISTICS, TEMPLATETITLE
from init import createDriveService, createSheetService
from spreadsheet_wrapper.spreadsheet_set_styles import SpreadSheetSetStyler


class SpreadsheetWrapper:
    def __init__(self):
        self.sheetService = createSheetService()
        self.driveService = createDriveService()
        self.templateTitle = TEMPLATETITLE
        self.templateOperation = TEMPLATEOPERATIONS
        self.templateStatistics = TEMPLATESTATISTICS
        self.spreadSheetSetStyler = SpreadSheetSetStyler(
            self.sheetService,
            self.driveService,
            self.templateTitle,
            self.templateOperation,
            self.templateStatistics,
        )

    def createTable(self, title, email):
        sheets = []
        for x, i in enumerate(self.templateTitle):
            sheet = {"properties": {"sheetType": "GRID", "sheetId": x, "title": i}}
            sheets.append(sheet)

        spreadsheet = (
            self.sheetService.spreadsheets()
            .create(
                body={
                    "properties": {"title": title, "locale": "ru_RU"},
                    "sheets": sheets,
                }
            )
            .execute()
        )

        spreadsheetID = spreadsheet["spreadsheetId"]

        values = []
        widthsValues = []
        for list in self.templateTitle:
            value = self.templateTitle[list][0]
            values.append([list, "ROWS", f"A{1}:{len(value)}", [value]])
            widths = self.templateTitle[list][1]
            for x, width in enumerate(widths):
                widthsValues.append([list, x, x + 1, width])
        self.setWidthColumn(spreadsheetID, widthsValues)
        self.setValues(spreadsheetID, values)

        self.spreadSheetSetStyler.setStyleBaseLists(spreadsheetID)
        self.spreadSheetSetStyler.setSecurityBaseLists(spreadsheetID)

        self.issueRights(spreadsheetID, "user", "writer", email)

        return spreadsheetID

    def addNewOperationsSheet(self, spreadsheetID, currentMonth):
        sheetService = self.sheetService
        template = self.templateOperation["template"]

        reqData = []
        reqData.append({"addSheet": {"properties": {"title": str(currentMonth)}}})
        response = (
            sheetService.spreadsheets()
            .batchUpdate(spreadsheetId=spreadsheetID, body={"requests": reqData})
            .execute()
        )

        values = []
        values.append(
            [str(currentMonth), "ROWS", f"A1:{len(template[0])}", [template[0]]]
        )

        """
        width = []
        days = []
        for i in range(delta.days):
            days.append(str(currentMonth + datetime.timedelta(days=i)))
            width.append([str(currentMonth), 11 + i, 12 + i, 45])
        values.append([str(currentMonth), 'ROWS', f'L1:{len(days)}', [days]])
        """

        width = []
        for x, z in enumerate(template[1]):
            width.append([str(currentMonth), x, x + 1, z])

        self.setValues(spreadsheetID, values)
        self.setWidthColumn(spreadsheetID, width)

        sheets = self.getSheets(spreadsheetID)
        self.spreadSheetSetStyler.setStyleOperationLists(
            spreadsheetID, sheets[str(currentMonth)]
        )
        self.spreadSheetSetStyler.setSecurityOperationLists(
            spreadsheetID, sheets[str(currentMonth)]
        )

    def addNewStatisticsSheet(self, spreadsheetID, currentMonth, count_days):
        sheetService = self.sheetService
        template = self.templateStatistics["template"]

        reqData = []
        reqData.append(
            {
                "addSheet": {
                    "properties": {
                        "title": "Stat. " + str(currentMonth),
                        "gridProperties": {"columnCount": 50},
                    }
                }
            }
        )
        response = (
            sheetService.spreadsheets()
            .batchUpdate(spreadsheetId=spreadsheetID, body={"requests": reqData})
            .execute()
        )

        values = []
        values.append(["Stat. " + str(currentMonth), "ROWS", f"A1:3", [template[0]]])
        width = []
        for x, i in enumerate(template[1]):
            width.append(["Stat. " + str(currentMonth), x, x + 1, i])
        days = []
        # for i in range(delta.days):
        for i in range(count_days):
            days.append(str(currentMonth + datetime.timedelta(days=i)))
            width.append(["Stat. " + str(currentMonth), i + 2, i + 3, 45])
        values.append(["Stat. " + str(currentMonth), "ROWS", f"C1:{len(days)}", [days]])

        self.setValues(spreadsheetID, values)
        self.setWidthColumn(spreadsheetID, width)

        sheets = self.getSheets(spreadsheetID)
        self.spreadSheetSetStyler.setStyleStatisticsLists(
            spreadsheetID, sheets["Stat. " + str(currentMonth)], days
        )
        self.spreadSheetSetStyler.setSecurityStatisticsLists(
            spreadsheetID, sheets["Stat. " + str(currentMonth)], days
        )

    def issueRights(self, spreadsheetID, type, role, emailAddress):
        shareRes = (
            self.driveService.permissions()
            .create(
                fileId=spreadsheetID,
                body={"type": type, "role": role, "emailAddress": emailAddress},
                fields="id",
            )
            .execute()
        )

    def setWidthColumn(self, spreadsheetID, data):
        sheets = self.getSheets(spreadsheetID)
        reqData = []
        for i in data:
            loc = {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheets[i[0]],
                        "dimension": "COLUMNS",
                        "startIndex": i[1],
                        "endIndex": i[2],
                    },
                    "properties": {"pixelSize": i[3]},
                    "fields": "pixelSize",
                }
            }
            reqData.append(loc)

        results = (
            self.sheetService.spreadsheets()
            .batchUpdate(spreadsheetId=spreadsheetID, body={"requests": reqData})
            .execute()
        )

    def setValues(self, spreadsheetID, data):
        reqData = []
        for i in data:
            loc = {"range": f"{i[0]}!{i[2]}", "majorDimension": i[1], "values": i[3]}
            reqData.append(loc)

        results = (
            self.sheetService.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=spreadsheetID,
                body={"valueInputOption": "USER_ENTERED", "data": reqData},
            )
            .execute()
        )

    def cleanValues(self, spreadsheetID, range):
        sheetService = self.sheetService
        response = (
            sheetService.spreadsheets()
            .values()
            .clear(spreadsheetId=spreadsheetID, range=range)
            .execute()
        )

    def getValues(self, spreadsheetID, range):
        sheetService = self.sheetService
        result = (
            sheetService.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheetID, range=range)
            .execute()
        )
        return result

    def getSheets(self, spreadsheetID):
        response = (
            self.sheetService.spreadsheets().get(spreadsheetId=spreadsheetID).execute()
        )
        sheets = {}
        for i in response["sheets"]:
            sheets[i["properties"]["title"]] = i["properties"]["sheetId"]
        return sheets


# ss = Spreadsheet()
# id = ss.createTable("123", 'stepansokoladov@gmail.com')
# print(f"https://docs.google.com/spreadsheets/d/{id}/")
