import re

from database.models import CategoriesOrm, SourcesOrm


def validate_category_row(spreadsheets_categories):
    names = []
    associations = []
    for z, row in enumerate(spreadsheets_categories["values"]):
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
        cur_associations = [x.lower() for x in row[5].split()]
        associations += list(set(cur_associations + [row[4].lower()]))

    if len(set(names)) != len(names):
        return f"В категориях один name используется несколько раз"
    if len(set(associations)) != len(associations):
        return f"В категориях один association используется несколько раз"

def validate_sources_row(spreadsheets_sources):
    names = []
    associations = []
    for z, row in enumerate(spreadsheets_sources["values"]):
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
        cur_associations = [x.lower() for x in row[3].split()]
        associations += list(set(cur_associations + [row[2].lower()]))

    if len(set(names)) != len(names):
        return f"В источниках один name используется несколько раз"
    if len(set(associations)) != len(associations):
        return f"В источниках один association используется несколько раз"

def validate_records_row(row, categories:list[CategoriesOrm], sources:list[SourcesOrm] = None):
    args = row.split()
    if len(args) < 3:
        return "Какой-то странный ввод"

    amount = args[0]
    category = args[1].lower()
    source = args[2].lower()
    notes = ' '.join(args[3:])

    if re.fullmatch(r'\d+', amount) == None:
        return "Сумма должна быть натуральным числом"

    categories_associations = [association.lower() for category in categories for association in category.associations]
    if category not in categories_associations:
        return "Такой категории нет, либо она выключена"

    sources_associations = [association.lower() for source in sources for association in source.associations]
    if source not in sources_associations:
        return "Такого источника нет, либо он выключен"

def validate_delete_command_args(args):
    try:
        delete_id = int(args)
    except:
        return 'Было передано не число'

def validate_transfer_command_args(args, sources):
    if args == None:
        return 'Передайте аргументы'
    args = args.split()
    if len(args) != 3:
        return f'Было передано {len(args)} аргументов, а должно быть 3'
    amount = args[0]
    from_source = args[1].lower()
    to_source = args[2].lower()
    if re.fullmatch(r'\d+', amount) == None:
        return "Сумма должна быть натуральным числом"
    sources_associations = [association.lower() for source in sources for association in source.associations]
    if from_source not in sources_associations:
        return "Источника отправителя нет, либо он выключен"
    if to_source not in sources_associations:
        return "Источника получателя нет, либо он выключен"