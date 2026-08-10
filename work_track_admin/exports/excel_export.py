from openpyxl import Workbook
from openpyxl.styles import Font
from django.http import HttpResponse

def export_to_excel(filename, headers, rows):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = filename

    # Header Row
    for column, header in enumerate(headers, start=1):
        cell = worksheet.cell(row=1, column=column)
        cell.value = header
        cell.font = Font(bold=True)

    # Data Rows
    for row_index, row in enumerate(rows, start=2):
        for column_index, value in enumerate(row, start=1):
            worksheet.cell(
                row=row_index,
                column=column_index,
                value=value
            )

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    response["Content-Disposition"] = (
        f'attachment; filename="{filename}.xlsx"'
    )

    workbook.save(response)

    return response