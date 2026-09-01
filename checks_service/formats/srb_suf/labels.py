"""Названия полей сербского чека — зафиксированные, а не снятые на лету.

Подписи взяты со страницы `suf.purs.gov.rs` один раз и с тех пор живут здесь.
Это осознанный обмен: ключи `raw_payload` читаются человеком на том же языке,
что и бумажка в руках, но **не зависят** от того, переименует ли сайт свою
подпись. Снимай мы их на лету, переименование «Укупан износ» молча сменило бы
ключ в JSON и так же молча сломало бы разбор через месяц после того, как чеки
уже накопились.

Со страницы снимаются только **значения**, и адресуются они по `id` элементов:
якорей мало, они машинные и меняются куда реже подписей.

Пара подписей назначена нами, потому что на странице их нет:

* «Врста трансакције» / «Transaction Type» — на странице оба поля стоят под
  одной подписью «Врста». Слить их в один ключ значило бы потерять различие
  «Промет / Рефундација», а именно его разбор и проверяет;
* «Статус рачуна» / «Invoice Status» — у статуса подписи нет вовсе, значение
  стоит само по себе. Взято название панели;
* «ГТИН» / «GTIN» — колонки в видимой таблице нет, а поле в ответе есть.

Если сюда добавляется поле, его надо добавить и в зеркало
`telegram_bot.checks.srb_labels` — иначе разбор не найдёт того, что приём
записал.
"""

from __future__ import annotations

from dataclasses import dataclass

from checks_service import constants


@dataclass(frozen=True)
class Label:
    """Название поля на обоих языках."""

    sr: str
    en: str

    def of(self, locale: str) -> str:
        """Название для языка страницы."""
        return self.sr if locale == constants.SRB_SUF_LOCALE_SR else self.en


# ---- Поля, снимаемые по `id` элемента ----
#: Пары «якорь на странице → название в JSON». Порядок задаёт порядок ключей в
#: `raw_payload`: он повторяет порядок на самой странице, и чек в JSON читается
#: сверху вниз так же, как на экране.
SPAN_FIELDS: tuple[tuple[str, Label], ...] = (
    ("tinLabel", Label("ПИБ", "TIN")),
    ("shopFullNameLabel", Label("Име продајног места", "Location Name")),
    ("addressLabel", Label("Адреса", "Address")),
    ("cityLabel", Label("Град", "City")),
    ("administrativeUnitLabel", Label("Општина", "Administrative Unit")),
    ("buyerIdLabel", Label("ИД купца", "Buyer's TIN")),
    ("requestedByLabel", Label("Затражио", "Requested By")),
    ("invoiceTypeId", Label("Врста", "Type")),
    ("transactionTypeId", Label("Врста трансакције", "Transaction Type")),
    ("totalAmountLabel", Label("Укупан износ", "Total Amount")),
    (
        "transactionTypeCounterLabel",
        Label("Бројач по врсти трансакције", "Transaction Type Counter"),
    ),
    ("totalCounterLabel", Label("Бројач укупног броја", "Total Counter")),
    (
        "invoiceCounterExtensionLabel",
        Label("Екстензија бројача рачуна", "Invoice Counter Extension"),
    ),
    (
        "invoiceNumberLabel",
        Label("Затражио - Потписао - Бројач", "Requested By - Signed By - Counter"),
    ),
    ("signedByLabel", Label("Потписао", "Signed By")),
    (
        "sdcDateTimeLabel",
        Label("ПФР време (временска зона сервера)", "SDC Time (server time zone)"),
    ),
    ("invoiceStatusLabel", Label("Статус рачуна", "Invoice Status")),
)

#: Поля из списка выше, чьё значение — деньги. Сербская страница печатает их с
#: запятой («610,38»), английская с точкой, и в JSON они приводятся к точке.
#:
#: Список явный, а не «всё, что похоже на число»: под догадку попали бы и ЕСИР
#: номер «253/49.0», и ПИБ, и счётчики, и хоть один из них однажды оказался бы
#: испорчен молча. Запятая же в JSON — ловушка для любого, кто станет его
#: читать: `Decimal("610,38")` не разбирается вовсе.
MONEY_SPAN_IDS = frozenset({"totalAmountLabel"})

# ---- Поля из блока для печати ----
#: Только те, которых нет выше. Название юрлица встречается **лишь** здесь и в
#: журнале, и потерять его значило бы не знать, чей это чек: «1002342-195 - Maxi»
#: говорит о продавце меньше, чем «DELHAIZE SERBIA DOO BEOGRAD».
#:
#: В блоке печати подпись стоит внутри `<strong>` и оканчивается двоеточием,
#: поэтому искать её надо как `f"{label}:"` — двоеточие в имя ключа не идёт.
PRINT_FIELDS: tuple[Label, ...] = (
    Label("Предузеће", "Company"),
    Label("Место продаје", "Store"),
    Label("Касир", "Cashier TIN"),
    Label("Опционо поље купца", "Buyer's Cost Center"),
    Label("ЕСИР број", "POS Number"),
)

# ---- Позиции чека ----
#: Ключ ответа `/specifications` → название колонки. `Стопа`/`Rate` собирается
#: из двух полей ответа сразу (`label` и `labelRate`): отдельной колонки под
#: ставку на странице нет, а терять её незачем.
ITEM_FIELDS: tuple[tuple[str, Label], ...] = (
    ("name", Label("Назив", "Name")),
    ("gtin", Label("ГТИН", "GTIN")),
    ("quantity", Label("Количина", "Quantity")),
    ("unitPrice", Label("Јед. цена са ПДВ", "Gross Unit Price")),
    ("total", Label("Укупна цена", "Total Price")),
    ("taxBaseAmount", Label("Основица", "Net Price")),
    ("vatAmount", Label("ПДВ", "Tax Amount")),
)

#: Поля позиции, приходящие числами. Их значения приводятся к строке через
#: `Decimal`, а не через `str(float)`: последний однажды выдаст
#: «0.5840000000000001» вместо «0.584».
ITEM_NUMERIC_KEYS = frozenset({"quantity", "unitPrice", "total", "taxBaseAmount", "vatAmount"})

#: Ставка налога: буква из `label` и процент из `labelRate` одной строкой.
ITEM_RATE = Label("Стопа", "Rate")

# ---- Разделы ----
SPECIFICATION = Label("Спецификација рачуна", "Invoice specification")
JOURNAL = Label("Журнал", "Journal")

# ---- Поля верхнего уровня ----
#: Не подписи со страницы, а наши собственные служебные ключи, поэтому они
#: машинные и одинаковые для обеих версий.
URL_FIELD = "url"
INVOICE_NUMBER_FIELD = "invoice_number"
SR_FIELD = "sr"
EN_FIELD = "en"
