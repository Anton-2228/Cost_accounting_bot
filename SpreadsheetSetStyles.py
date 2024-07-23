class SpreadSheetSetStyler():
    def __init__(self, sheetService, driveService, templateTitle, templateOperation, templateStatistics):
        self.sheetService = sheetService
        self.driveService = driveService
        self.templateTitle = templateTitle
        self.templateOperation = templateOperation
        self.templateStatistics = templateStatistics
    def setStyleBaseLists(self, spreadsheetID):
        sheetService = self.sheetService
        startSheets = self.templateTitle

        reqData = []
        for z, i in enumerate([len(startSheets["Categories"][0]), len(startSheets["Bills"][0])]):
            reqData.append({
                "repeatCell": {
                    "range": {
                        "sheetId": z,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": i
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 0.9,
                                "green": 0.9,
                                "blue": 0.9
                            },
                            "horizontalAlignment": "CENTER",
                            "textFormat": {
                                "fontSize": 10,
                                "bold": True
                            }
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor, textFormat, horizontalAlignment)"
                }
            })
            reqData.append({
                "repeatCell": {
                    "range": {
                        "sheetId": z,
                        "startRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": i
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "horizontalAlignment": "CENTER"
                        }
                    },
                    "fields": "userEnteredFormat(horizontalAlignment)"
                }
            })
            reqData.append({
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": z,
                        "gridProperties": {
                            "frozenRowCount": 1
                        }
                    },
                    "fields": "gridProperties(frozenRowCount)"
                }
            })

        response = self.sheetService.spreadsheets().batchUpdate(spreadsheetId=spreadsheetID, body={
            'requests': reqData
        }).execute()

    def setSecurityBaseLists(self, spreadsheetID):
        sheetService = self.sheetService
        startSheets = self.templateTitle

        reqData = []
        for z, i in enumerate([len(startSheets["Categories"][0]), len(startSheets["Bills"][0])]):
            reqData.append({
                "addProtectedRange": {
                    "protectedRange": {
                        "range": {
                            "sheetId": z,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": i
                        },
                        "warningOnly": False,
                        "editors": {
                            "users": []
                        }
                    }
                }
            })
            reqData.append({
                "addProtectedRange": {
                    "protectedRange": {
                        "range": {
                            "sheetId": z,
                            "startRowIndex": 0,
                            "startColumnIndex": 0,
                            "endColumnIndex": 1
                        },
                        "warningOnly": False,
                        "editors": {
                            "users": []
                        }
                    }
                }
            })
            if z == 1:
                reqData.append({
                    "addProtectedRange": {
                        "protectedRange": {
                            "range": {
                                "sheetId": z,
                                "startRowIndex": 0,
                                "startColumnIndex": 5,
                                "endColumnIndex": 6
                            },
                            "warningOnly": False,
                            "editors": {
                                "users": []
                            }
                        }
                    }
                })

        response = self.sheetService.spreadsheets().batchUpdate(spreadsheetId=spreadsheetID, body={
            'requests': reqData
        }).execute()


    def setStyleOperationLists(self, spreadsheetID, sheetId):
        sheetService = self.sheetService
        template = self.templateOperation

        reqData = []

        reqData.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheetId,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": len(template["template"][0])
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {
                            "red": 0.9,
                            "green": 0.9,
                            "blue": 0.9
                        },
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                        "textFormat": {
                            "fontSize": 10,
                            "bold": True
                        }
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
            }
        })

        reqData.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheetId,
                    "startRowIndex": 0,
                    "startColumnIndex": 0,
                    "endColumnIndex": len(template["template"][0])
                },
                "cell": {
                    "userEnteredFormat": {
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE"
                    }
                },
                "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment)"
            }
        })

        reqData.append({
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheetId,
                    "gridProperties": {
                        "frozenRowCount": 1
                    }
                },
                "fields": "gridProperties(frozenRowCount)"
            }
        })

        response = self.sheetService.spreadsheets().batchUpdate(spreadsheetId=spreadsheetID, body={
            'requests': reqData
        }).execute()

    def setSecurityOperationLists(self, spreadsheetID, sheetId):
        sheetService = self.sheetService
        template = self.templateOperation

        reqData = []
        reqData.append({
            "addProtectedRange": {
                "protectedRange": {
                    "range": {
                        "sheetId": sheetId,
                        "startRowIndex": 0,
                        "startColumnIndex": 0,
                        "endColumnIndex": len(template["template"][0])
                    },
                    "warningOnly": False,
                    "editors": {
                        "users": []
                    }
                }
            }
        })

        response = self.sheetService.spreadsheets().batchUpdate(spreadsheetId=spreadsheetID, body={
            'requests': reqData
        }).execute()

    def setStyleStatisticsLists(self, spreadsheetID, sheetId, days):
        sheetService = self.sheetService
        template = self.templateStatistics

        reqData = []
        reqData.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheetId,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 2,
                    "endColumnIndex": len(days)+2
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {
                            "red": 0.9,
                            "green": 0.9,
                            "blue": 0.9
                        },
                        "textFormat": {
                            "fontSize": 10,
                            "bold": True
                        },
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                        "textRotation": {
                            "angle": -90
                        }
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,textRotation,verticalAlignment)"
            }
        })

        reqData.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheetId,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 2
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {
                            "red": 0.9,
                            "green": 0.9,
                            "blue": 0.9
                        },
                        "textFormat": {
                            "fontSize": 10,
                            "bold": True
                        },
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE"
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
            }
        })

        reqData.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheetId,
                    "startRowIndex": 0,
                    "startColumnIndex": 0,
                    "endColumnIndex": len(days)+2
                },
                "cell": {
                    "userEnteredFormat": {
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE"
                    }
                },
                "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment)"
            }
        })

        reqData.append({
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheetId,
                    "gridProperties": {
                        "frozenRowCount": 1
                    }
                },
                "fields": "gridProperties(frozenRowCount)"
            }
        })

        response = self.sheetService.spreadsheets().batchUpdate(spreadsheetId=spreadsheetID, body={
            'requests': reqData
        }).execute()

    def setSecurityStatisticsLists(self, spreadsheetID, sheetId, days):
        sheetService = self.sheetService
        template = self.templateStatistics

        reqData = []
        reqData.append({
            "addProtectedRange": {
                "protectedRange": {
                    "range": {
                        "sheetId": sheetId,
                        "startRowIndex": 0,
                        "startColumnIndex": 0,
                        "endColumnIndex": len(days)+2
                    },
                    "warningOnly": False,
                    "editors": {
                        "users": []
                    }
                }
            }
        })

        response = self.sheetService.spreadsheets().batchUpdate(spreadsheetId=spreadsheetID, body={
            'requests': reqData
        }).execute()