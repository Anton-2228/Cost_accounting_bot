import re


def validate_category_row(spreadsheets_categories):
    names = []
    associations = []
    for z, row in enumerate(spreadsheets_categories["values"]):
        print(row)
        if len(row) == 0 or len(row) == 1:
            continue
        if len(row) < 6:
            return f"В категориях в {z + 1} строке не все поля заполнены"
        if row[1] not in ['0', '1']:
            return f"В категориях в {z + 1} строке Active странный"
        if row[2] not in ['0', '1']:
            return f"В категориях в {z + 1} строке Income странный"
        if row[3] not in ['0', '1']:
            return f"В категориях в {z + 1} строке Cost странный"
        if row[2] == row[3]:
            return f"В категориях в {z + 1} строке одинаковое значение у Income и Cost"
        if row[4] == '':
            return f"В категориях в {z + 1} строке Name пустой"
        if len(row[4].split()) > 1:
            return f"В категориях в {z + 1} строке Name записан не одним словом"
        names.append(row[4])
        associations += row[5].split() + [row[4]]

    if len(set(names)) != len(names):
        return f"В категориях один name используется несколько раз"
    if len(set(associations)) != len(associations):
        return f"В категориях один association используется несколько раз"

def validate_sources_row(spreadsheets_categories):
    names = []
    associations = []
    for z, row in enumerate(spreadsheets_categories["values"]):
        print(row)
        if len(row) == 0:
            continue
        if row[1] == '' and row[2] == '' and row[3] == '' and row[4] == '':
            continue
        if len(row) < 5:
            return f"В источниках в {z + 1} строке не все поля заполнены"
        if row[1] not in ['0', '1']:
            return f"В источниках в {z + 1} строке Active странный"
        if row[2] == '':
            return f"В источниках в {z + 1} строке Name пустой"
        if len(row[2].split()) > 1:
            return f"В источниках в {z + 1} строке Name записан не одним словом"
        if re.fullmatch(r'-?\d+', row[4]) == None:
            return f"В источниках в {z + 1} строке Balance должен быть целым числом"
        names.append(row[2])
        associations += row[3].split() + [row[2]]

    if len(set(names)) != len(names):
        return f"В источниках один name используется несколько раз"
    if len(set(associations)) != len(associations):
        return f"В источниках один association используется несколько раз"