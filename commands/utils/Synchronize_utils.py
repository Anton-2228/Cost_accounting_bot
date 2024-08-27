import datetime

from database import RecordsOrm, SpreadSheetsOrm, CategoriesOrm, CategoriesTypes, StatusTypes
from database import PostgresWrapper
from init import daysUntilNextMonth, alf


async def sync_cat_from_table_to_db(spreadsheet, spreadsheetWrapper, postgres_wrapper: PostgresWrapper):
    resultSyncCat = postgres_wrapper.categories_wrapper.synchronizeCategories(spreadsheet, "Categories!A2:G100000", spreadsheetWrapper)
    if resultSyncCat is not None:
        if resultSyncCat['result'] == 'error':
            return resultSyncCat['message']
        categories = resultSyncCat['categories']
        return ["Categories", "ROWS", f'A2:G{len(categories) + 2}', categories]
    return 'Добавьте хотя бы одну категорию'


async def sync_sour_from_table_to_db(spreadsheet, spreadsheetWrapper, postgres_wrapper: PostgresWrapper):
    resultSyncSour = postgres_wrapper.sources_wrapper.synchronizeSources(spreadsheet, "Bills!A2:F100000", spreadsheetWrapper)
    if resultSyncSour is not None:
        if resultSyncSour['result'] == 'error':
            return resultSyncSour['message']
        sources = resultSyncSour['sources']
        return ["Bills", "ROWS", f'A2:F{len(sources) + 2}', sources]
    return 'Добавьте хотя бы один источник'

async def sync_records_from_db_to_table(spreadsheet, postgres_wrapper: PostgresWrapper):
    records: list[RecordsOrm] = postgres_wrapper.records_wrapper.get_records_by_current_month(spreadsheet.id, spreadsheet.start_date)
    value = []
    for i in records:
        category = postgres_wrapper.categories_wrapper.get_category(i.category)
        source = postgres_wrapper.sources_wrapper.get_source(i.source)
        value.append([i.id, str(i.added_at), i.amount, i.product_name, category.title, i.type, i.notes, source.title, i.check_json])

    return [str(spreadsheet.start_date), 'ROWS', f'A2:I{len(value) + 1}', value]

async def sync_cat_from_db_to_table(spreadsheet: SpreadSheetsOrm, postgres_wrapper: PostgresWrapper):
    categories: list[CategoriesOrm] = postgres_wrapper.categories_wrapper.get_active_ans_inactive_categories_by_spreadsheet(spreadsheet.id)
    values = []
    for category in categories:
        value = []
        value.append(category.id)

        if category.status == StatusTypes.ACTIVE:
            value.append('1')
        elif category.status == StatusTypes.INACTIVE:
            value.append('0')

        if category.type == CategoriesTypes.INCOME:
            value.append('1')
            value.append('0')
        elif category.type == CategoriesTypes.COST:
            value.append('0')
            value.append('1')

        value.append(category.title)
        value.append(' '.join(category.associations))
        value.append(', '.join(category.product_types))

        values.append(value)

    values.sort(key=lambda x: (x[3], x[0]))
    return ['Categories', 'ROWS', f'A2:H{len(values) + 1}', values]


async def sync_total_from_db_to_table(spreadsheet: SpreadSheetsOrm, postgres_wrapper: PostgresWrapper):
    dates = []
    date = spreadsheet.start_date
    for i in range(daysUntilNextMonth[spreadsheet.start_date.month]):
        dates.append(date)
        date += datetime.timedelta(days=1)

    categories: list[CategoriesOrm] = postgres_wrapper.categories_wrapper.get_active_categories_by_spreadsheet(spreadsheet.id)
    income_categories = {i: [] for i in categories if i.type == CategoriesTypes.INCOME}
    cost_categories = {i: [] for i in categories if i.type == CategoriesTypes.COST}

    total_income = [0 for _ in range(daysUntilNextMonth[spreadsheet.start_date.month]+1)]
    for i in income_categories:
        records: list[RecordsOrm] = postgres_wrapper.records_wrapper.get_records_by_current_month_by_category(spreadsheet.id, spreadsheet.start_date, i.id)
        records = sorted(records, key=lambda x: x.added_at)
        income_categories[i].append(0)
        for x, z in enumerate(dates):
            su = int(sum([x.amount for x in records if x.added_at == z]))
            income_categories[i].append(su)
            income_categories[i][0] += su
            total_income[x+1] += su
        income_categories[i][0] = int(income_categories[i][0])
        total_income[0] += income_categories[i][0]
        # income_categories[i][0] = int(income_categories[i][0])
    # total_income[0] = int(total_income[0])

    total_cost = [0 for _ in range(daysUntilNextMonth[spreadsheet.start_date.month] + 1)]
    for i in cost_categories:
        records: list[RecordsOrm] = postgres_wrapper.records_wrapper.get_records_by_current_month_by_category(spreadsheet.id, spreadsheet.start_date, i.id)
        records = sorted(records, key=lambda x: x.added_at)
        cost_categories[i].append(0)
        for x, z in enumerate(dates):
            su = int(sum([x.amount for x in records if x.added_at == z]))
            cost_categories[i].append(su)
            cost_categories[i][0] += su
            total_cost[x+1] += su
        total_cost[0] += cost_categories[i][0]
        # cost_categories[i][0] = int(cost_categories[i][0])
    # total_cost[0] = int(total_cost[0])

    values = []

    income_value = []
    row = ['Общие доходы'] + total_income
    income_value.append(row)
    for i in income_categories:
        row = [str(i.title)] + income_categories[i]
        income_value.append(row)
    values.append(["Stat. " + str(spreadsheet.start_date), 'ROWS',
                    f'A2:{alf[daysUntilNextMonth[spreadsheet.start_date.month]]}{len(income_value)+2}', income_value])

    cost_value = []
    row = ['Общие расходы'] + total_cost
    cost_value.append(row)
    for i in cost_categories:
        row = [str(i.title)] + cost_categories[i]
        cost_value.append(row)
    values.append(["Stat. " + str(spreadsheet.start_date), 'ROWS',
                   f'A{len(income_value) + 2 + 1}:{alf[daysUntilNextMonth[spreadsheet.start_date.month]]}{len(income_value) + len(cost_value) + 2 + 1}', cost_value])

    # self.spreadsheet.cleanValues(spreadsheet.spreadsheet_id,
    #                              f'{"Stat. " + str(spreadsheet.start_date)}!'
    #                              f'A2:{alf[daysUntilNextMonth[spreadsheet.start_date.month]]}100000')
    #
    # self.spreadsheet.setValues(spreadsheet.spreadsheet_id, values)

    return values
