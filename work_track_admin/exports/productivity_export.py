from datetime import timedelta

from django.http import HttpResponse
from django.utils import timezone

from .excel_export import export_to_excel
from .pdf_export import export_to_pdf



from ..models import (
    Task,
    TaskTime,
    WorkSession,
    IdleSession,
    ApplicationUsage,
    WebsiteUsage,
    Screenshot,
)


# =========================================================
# HELPERS
# =========================================================



def duration_seconds(duration):
    if not duration:
        return 0

    return max(
        0,
        int(duration.total_seconds())
    )
def get_report_date_range(period, selected_date):
    
    if period == "daily":

        return (
            selected_date,
            selected_date
        )

    elif period == "weekly":

        # Monday → Sunday
        start_date = (
            selected_date
            - timedelta(
                days=selected_date.weekday()
            )
        )

        end_date = (
            start_date
            + timedelta(days=6)
        )

        return (
            start_date,
            end_date
        )

    elif period == "monthly":

        start_date = selected_date.replace(
            day=1
        )

        if selected_date.month == 12:

            next_month = selected_date.replace(
                year=selected_date.year + 1,
                month=1,
                day=1
            )

        else:

            next_month = selected_date.replace(
                month=selected_date.month + 1,
                day=1
            )

        end_date = (
            next_month
            - timedelta(days=1)
        )

        return (
            start_date,
            end_date
        )

    raise ValueError(
        "Invalid period. "
        "Use daily, weekly or monthly."
    )

def format_duration(seconds):
    seconds = max(0, int(seconds))

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    return f"{hours:02d}h {minutes:02d}m {secs:02d}s"


def format_time(value):
    if not value:
        return "-"

    return value.strftime(
        "%d-%m-%Y %I:%M %p"
    )


def get_screenshot_url(screenshot):

    if not screenshot.image:
        return ""

    try:
        return screenshot.image.url
    except Exception:
        return str(screenshot.image)


# =========================================================
# ACTIVE / COMPLETED WORK SESSION
# =========================================================

def get_session_work_seconds(
    session,
    idle_sessions
):

    # Completed session
    if session.clock_out:

        return duration_seconds(
            session.total_work_time
        )

    # Active session
    if not session.clock_in:
        return 0

    now = timezone.now()

    raw_seconds = max(
        0,
        int(
            (
                now - session.clock_in
            ).total_seconds()
        )
    )

    idle_seconds = 0

    for idle in idle_sessions:

        if idle.work_session_id != session.id:
            continue

        if idle.duration:

            idle_seconds += duration_seconds(
                idle.duration
            )

        elif idle.idle_end_time:

            idle_seconds += max(
                0,
                int(
                    (
                        idle.idle_end_time
                        - idle.idle_start_time
                    ).total_seconds()
                )
            )

        elif idle.idle_start_time:

            idle_seconds += max(
                0,
                int(
                    (
                        now
                        - idle.idle_start_time
                    ).total_seconds()
                )
            )

    return max(
        0,
        raw_seconds - idle_seconds
    )


# =========================================================
# BUILD PRODUCTIVITY DATA
# =========================================================

def build_productivity_data(
    employee,
    company,
    start_date,
    end_date
):

    # -----------------------------------------------------
    # WORK SESSIONS
    # -----------------------------------------------------

    work_sessions = WorkSession.objects.filter(
        company=company,
        user=employee,
        work_date__range=(
            start_date,
            end_date
        )
    ).order_by(
        "clock_in"
    )

    # -----------------------------------------------------
    # IDLE SESSIONS
    # -----------------------------------------------------

    idle_sessions = IdleSession.objects.filter(
        company=company,
        user=employee,
        work_session__work_date__range=(
            start_date,
            end_date
        )
    ).order_by(
        "idle_start_time"
    )

    # -----------------------------------------------------
    # APPLICATIONS
    # -----------------------------------------------------

    applications = ApplicationUsage.objects.filter(
        company=company,
        user=employee,
        work_session__work_date__range=(
            start_date,
            end_date
        )
    ).order_by(
        "start_time"
    )

    # -----------------------------------------------------
    # WEBSITES
    # -----------------------------------------------------

    websites = WebsiteUsage.objects.filter(
        company=company,
        user=employee,
        work_session__work_date__range=(
            start_date,
            end_date
        )
    ).order_by(
        "start_time"
    )

    # -----------------------------------------------------
    # SCREENSHOTS
    # -----------------------------------------------------

    screenshots = Screenshot.objects.filter(
        company=company,
        user=employee,
        work_session__work_date__range=(
            start_date,
            end_date
        )
    ).order_by(
        "captured_at"
    )

    # -----------------------------------------------------
    # TASK TIME
    # -----------------------------------------------------

    task_times = TaskTime.objects.filter(
        company=company,
        user=employee,
        start_time__date__range=(
            start_date,
            end_date
        )
    ).select_related(
        "task"
    ).order_by(
        "start_time"
    )

    # -----------------------------------------------------
    # TASKS WORKED ON DURING PERIOD
    # -----------------------------------------------------

    task_ids = (
        task_times
        .exclude(
            task__isnull=True
        )
        .values_list(
            "task_id",
            flat=True
        )
        .distinct()
    )

    tasks = Task.objects.filter(
        company=company,
        id__in=task_ids
    ).distinct()

    # =====================================================
    # TOTAL WORK TIME
    # =====================================================

    total_work_seconds = 0

    for session in work_sessions:

        total_work_seconds += (
            get_session_work_seconds(
                session,
                idle_sessions
            )
        )

    # =====================================================
    # TOTAL IDLE TIME
    # =====================================================

    total_idle_seconds = 0

    for idle in idle_sessions:

        if idle.duration:

            total_idle_seconds += (
                duration_seconds(
                    idle.duration
                )
            )

        elif idle.idle_end_time:

            total_idle_seconds += max(
                0,
                int(
                    (
                        idle.idle_end_time
                        - idle.idle_start_time
                    ).total_seconds()
                )
            )

        elif idle.idle_start_time:

            total_idle_seconds += max(
                0,
                int(
                    (
                        timezone.now()
                        - idle.idle_start_time
                    ).total_seconds()
                )
            )

    # =====================================================
    # TOTAL TASK TIME
    # =====================================================

    total_task_seconds = 0

    for task_time in task_times:

        if task_time.duration:

            total_task_seconds += (
                duration_seconds(
                    task_time.duration
                )
            )

        elif (
            task_time.start_time
            and task_time.end_time
        ):

            total_task_seconds += max(
                0,
                int(
                    (
                        task_time.end_time
                        - task_time.start_time
                    ).total_seconds()
                )
            )

        elif task_time.start_time:

            total_task_seconds += max(
                0,
                int(
                    (
                        timezone.now()
                        - task_time.start_time
                    ).total_seconds()
                )
            )

    # =====================================================
    # TASK COUNTS
    # =====================================================

    total_tasks = tasks.count()

    completed_tasks = tasks.filter(
        status__iexact="Completed"
    ).count()

    pending_tasks = tasks.exclude(
        status__iexact="Completed"
    ).count()

    # =====================================================
    # PRODUCTIVITY
    # =====================================================

    base_seconds = max(
        total_work_seconds,
        total_task_seconds
    )

    if base_seconds > 0:

        productive = round(
            min(
                100,
                (
                    total_task_seconds
                    / base_seconds
                ) * 100
            ),
            2
        )

        unproductive = round(
            min(
                100 - productive,
                (
                    total_idle_seconds
                    / base_seconds
                ) * 100
            ),
            2
        )

        neutral = round(
            max(
                0,
                100
                - productive
                - unproductive
            ),
            2
        )

    else:

        productive = 0
        neutral = 0
        unproductive = 0

    return {
        "employee": employee,

        "start_date": start_date,
        "end_date": end_date,

        "work_sessions": work_sessions,
        "idle_sessions": idle_sessions,
        "applications": applications,
        "websites": websites,
        "screenshots": screenshots,
        "task_times": task_times,
        "tasks": tasks,

        "total_work_seconds":
            total_work_seconds,

        "total_idle_seconds":
            total_idle_seconds,

        "total_task_seconds":
            total_task_seconds,

        "total_tasks":
            total_tasks,

        "completed_tasks":
            completed_tasks,

        "pending_tasks":
            pending_tasks,

        "productive":
            productive,

        "neutral":
            neutral,

        "unproductive":
            unproductive,
    }


# =========================================================
# EXCEL DATA
# =========================================================

def generate_productivity_excel(
    data,
    filename
):

    employee = data["employee"]

    # =====================================================
    # SUMMARY
    # =====================================================

    summary_headers = [
        "Metric",
        "Value"
    ]

    employee_name = (
        employee.get_full_name()
        or employee.username
        or employee.email
    )

    summary_rows = [
        [
            "Employee",
            employee_name
        ],
        [
            "Email",
            employee.email
        ],
        [
            "Report Start",
            str(data["start_date"])
        ],
        [
            "Report End",
            str(data["end_date"])
        ],
        [
            "Total Working Time",
            format_duration(
                data["total_work_seconds"]
            )
        ],
        [
            "Total Task Time",
            format_duration(
                data["total_task_seconds"]
            )
        ],
        [
            "Total Idle / Break Time",
            format_duration(
                data["total_idle_seconds"]
            )
        ],
        [
            "Total Tasks",
            data["total_tasks"]
        ],
        [
            "Completed Tasks",
            data["completed_tasks"]
        ],
        [
            "Pending Tasks",
            data["pending_tasks"]
        ],
        [
            "Productive",
            f'{data["productive"]}%'
        ],
        [
            "Neutral",
            f'{data["neutral"]}%'
        ],
        [
            "Unproductive",
            f'{data["unproductive"]}%'
        ],
    ]

    # =====================================================
    # CLOCK SESSIONS
    # =====================================================

    clock_headers = [
        "Date",
        "Clock In",
        "Clock Out",
        "Worked Time",
        "Status"
    ]

    clock_rows = []

    for session in data["work_sessions"]:

        worked_seconds = (
            get_session_work_seconds(
                session,
                data["idle_sessions"]
            )
        )

        clock_rows.append([
            str(session.work_date),
            format_time(
                session.clock_in
            ),
            format_time(
                session.clock_out
            ),
            format_duration(
                worked_seconds
            ),
            session.status
        ])

    # =====================================================
    # APPLICATIONS
    # =====================================================

    application_headers = [
        "Application",
        "Window Title",
        "Start",
        "End",
        "Duration",
        "Productive"
    ]

    application_rows = []

    for app in data["applications"]:

        if app.duration:

            duration = duration_seconds(
                app.duration
            )

        elif app.end_time:

            duration = max(
                0,
                int(
                    (
                        app.end_time
                        - app.start_time
                    ).total_seconds()
                )
            )

        else:

            duration = max(
                0,
                int(
                    (
                        timezone.now()
                        - app.start_time
                    ).total_seconds()
                )
            )

        application_rows.append([
            app.application_name,
            app.window_title,
            format_time(
                app.start_time
            ),
            format_time(
                app.end_time
            ),
            format_duration(
                duration
            ),
            "Yes"
            if app.is_productive
            else "No"
        ])

    # =====================================================
    # WEBSITES
    # =====================================================

    website_headers = [
        "Browser",
        "Website",
        "Page Title",
        "Start",
        "End",
        "Duration",
        "Productive"
    ]

    website_rows = []

    for website in data["websites"]:

        if website.duration:

            duration = duration_seconds(
                website.duration
            )

        elif website.end_time:

            duration = max(
                0,
                int(
                    (
                        website.end_time
                        - website.start_time
                    ).total_seconds()
                )
            )

        else:

            duration = max(
                0,
                int(
                    (
                        timezone.now()
                        - website.start_time
                    ).total_seconds()
                )
            )

        website_rows.append([
            website.browser_name,
            website.website,
            website.page_title,
            format_time(
                website.start_time
            ),
            format_time(
                website.end_time
            ),
            format_duration(
                duration
            ),
            "Yes"
            if website.is_productive
            else "No"
        ])

    # =====================================================
    # IDLE / BREAKS
    # =====================================================

    idle_headers = [
        "Idle Started",
        "Idle Ended",
        "Duration"
    ]

    idle_rows = []

    for idle in data["idle_sessions"]:

        if idle.duration:

            duration = duration_seconds(
                idle.duration
            )

        elif idle.idle_end_time:

            duration = max(
                0,
                int(
                    (
                        idle.idle_end_time
                        - idle.idle_start_time
                    ).total_seconds()
                )
            )

        else:

            duration = max(
                0,
                int(
                    (
                        timezone.now()
                        - idle.idle_start_time
                    ).total_seconds()
                )
            )

        idle_rows.append([
            format_time(
                idle.idle_start_time
            ),
            format_time(
                idle.idle_end_time
            ),
            format_duration(
                duration
            )
        ])

    # =====================================================
    # TASK TIME
    # =====================================================

    task_time_headers = [
        "Task",
        "Start",
        "End",
        "Duration"
    ]

    task_time_rows = []

    for task_time in data["task_times"]:

        if task_time.duration:

            duration = duration_seconds(
                task_time.duration
            )

        elif (
            task_time.start_time
            and task_time.end_time
        ):

            duration = max(
                0,
                int(
                    (
                        task_time.end_time
                        - task_time.start_time
                    ).total_seconds()
                )
            )

        else:

            duration = max(
                0,
                int(
                    (
                        timezone.now()
                        - task_time.start_time
                    ).total_seconds()
                )
            )

        task_name = (
            task_time.task.task_name
            if task_time.task
            else "Deleted Task"
        )

        task_time_rows.append([
            task_name,
            format_time(
                task_time.start_time
            ),
            format_time(
                task_time.end_time
            ),
            format_duration(
                duration
            )
        ])

    # =====================================================
    # TASKS
    # =====================================================

    task_headers = [
        "Task",
        "Status",
        "Priority",
        "Due Date"
    ]

    task_rows = []

    for task in data["tasks"]:

        task_rows.append([
            task.task_name,
            task.status,
            getattr(
                task,
                "priority",
                ""
            ),
            getattr(
                task,
                "due_date",
                ""
            ),
        ])

    # =====================================================
    # SCREENSHOTS
    # =====================================================

    screenshot_headers = [
        "Captured At",
        "Reason",
        "Screenshot URL"
    ]

    screenshot_rows = []

    for screenshot in data["screenshots"]:

        screenshot_rows.append([
            format_time(
                screenshot.captured_at
            ),
            screenshot.reason,
            get_screenshot_url(
                screenshot
            )
        ])

    # =====================================================
    # EXPORT
    # =====================================================

    sheets = {

        "Summary": {
            "headers": summary_headers,
            "rows": summary_rows
        },

        "Clock Sessions": {
            "headers": clock_headers,
            "rows": clock_rows
        },

        "Applications": {
            "headers": application_headers,
            "rows": application_rows
        },

        "Websites": {
            "headers": website_headers,
            "rows": website_rows
        },

        "Idle & Breaks": {
            "headers": idle_headers,
            "rows": idle_rows
        },

        "Task Time": {
            "headers": task_time_headers,
            "rows": task_time_rows
        },

        "Tasks": {
            "headers": task_headers,
            "rows": task_rows
        },

        "Screenshots": {
            "headers": screenshot_headers,
            "rows": screenshot_rows
        },
    }

    return export_to_excel(
        filename,
        sheets=sheets
    )


# =========================================================
# PDF
# =========================================================

def generate_productivity_pdf(data, filename):
    
    import io
    import os
    import requests
    from concurrent.futures import ThreadPoolExecutor
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate,
        Table,
        TableStyle,
        Paragraph,
        Spacer,
        PageBreak,
        Image,
    )

    employee = data["employee"]

    employee_name = (
        employee.get_full_name()
        or employee.username
        or employee.email
    )

    title = (
        f"Employee Productivity Report - "
        f"{employee_name}"
    )

    # =====================================================
    # DOCUMENT
    # =====================================================

    response = HttpResponse(
        content_type="application/pdf"
    )

    response["Content-Disposition"] = (
        f'attachment; filename="{filename}.pdf"'
    )

    document = SimpleDocTemplate(
        response,
        pagesize=landscape(A4),
        rightMargin=25,
        leftMargin=25,
        topMargin=25,
        bottomMargin=25,
    )

    styles = getSampleStyleSheet()

    title_style = styles["Heading1"]

    section_style = ParagraphStyle(
        "SectionStyle",
        parent=styles["Heading2"],
        fontSize=14,
        spaceBefore=10,
        spaceAfter=8,
    )

    normal_style = ParagraphStyle(
        "NormalStyle",
        parent=styles["Normal"],
        fontSize=8,
    )

    elements = []

    # =====================================================
    # TITLE
    # =====================================================

    elements.append(
        Paragraph(
            title,
            title_style
        )
    )

    elements.append(
        Spacer(1, 10)
    )

    # =====================================================
    # SUMMARY
    # =====================================================

    elements.append(
        Paragraph(
            "Summary",
            section_style
        )
    )

    summary_rows = [
        ["Employee", employee_name],
        ["Email", employee.email],
        [
            "Report Period",
            f'{data["start_date"]} to {data["end_date"]}'
        ],
        [
            "Total Working Time",
            format_duration(
                data["total_work_seconds"]
            )
        ],
        [
            "Total Task Time",
            format_duration(
                data["total_task_seconds"]
            )
        ],
        [
            "Total Idle / Break Time",
            format_duration(
                data["total_idle_seconds"]
            )
        ],
        [
            "Total Tasks",
            data["total_tasks"]
        ],
        [
            "Completed Tasks",
            data["completed_tasks"]
        ],
        [
            "Pending Tasks",
            data["pending_tasks"]
        ],
        [
            "Productive",
            f'{data["productive"]}%'
        ],
        [
            "Neutral",
            f'{data["neutral"]}%'
        ],
        [
            "Unproductive",
            f'{data["unproductive"]}%'
        ],
    ]

    summary_table = Table(
        summary_rows,
        colWidths=[180, 300]
    )

    summary_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])
    )

    elements.append(summary_table)

    elements.append(PageBreak())

    # =====================================================
    # HELPER FOR SECTION TABLES
    # =====================================================

    def add_section(title, headers, rows, col_widths=None):

        elements.append(
            Paragraph(
                title,
                section_style
            )
        )

        if not rows:

            elements.append(
                Paragraph(
                    "No data available for this period.",
                    normal_style
                )
            )

            elements.append(
                Spacer(1, 12)
            )

            return

        table_data = [headers]

        for row in rows:
            row_data = []
            for value in row:
                if isinstance(value, (Paragraph, Table, Image, list)):
                    row_data.append(value)
                elif value is not None:
                    row_data.append(
                        Paragraph(
                            str(value),
                            normal_style
                        )
                    )
                else:
                    row_data.append(
                        Paragraph(
                            "-",
                            normal_style
                        )
                    )
            table_data.append(row_data)

        table = Table(
            table_data,
            repeatRows=1,
            colWidths=col_widths
        )

        table.setStyle(
            TableStyle([
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.darkblue
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold"
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, 0),
                    8
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.grey
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP"
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    4
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    4
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    4
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    4
                ),
            ])
        )

        elements.append(table)

        elements.append(
            Spacer(1, 15)
        )

    # =====================================================
    # CLOCK SESSIONS
    # =====================================================

    clock_rows = []

    for session in data["work_sessions"]:

        worked_seconds = (
            get_session_work_seconds(
                session,
                data["idle_sessions"]
            )
        )

        clock_rows.append([
            str(session.work_date),
            format_time(session.clock_in),
            format_time(session.clock_out),
            format_duration(worked_seconds),
            session.status,
        ])

    add_section(
        "Clock Sessions",
        [
            "Date",
            "Clock In",
            "Clock Out",
            "Worked Time",
            "Status",
        ],
        clock_rows
    )

    # =====================================================
    # APPLICATIONS
    # =====================================================

    application_rows = []

    for app in data["applications"]:

        if app.duration:

            duration = duration_seconds(
                app.duration
            )

        elif app.end_time:

            duration = max(
                0,
                int(
                    (
                        app.end_time -
                        app.start_time
                    ).total_seconds()
                )
            )

        else:

            duration = max(
                0,
                int(
                    (
                        timezone.now() -
                        app.start_time
                    ).total_seconds()
                )
            )

        application_rows.append([
            app.application_name,
            app.window_title,
            format_time(app.start_time),
            format_time(app.end_time),
            format_duration(duration),
            "Yes" if app.is_productive else "No",
        ])

    add_section(
        "Application Usage",
        [
            "Application",
            "Window Title",
            "Start",
            "End",
            "Duration",
            "Productive",
        ],
        application_rows
    )

    # =====================================================
    # WEBSITES
    # =====================================================

    website_rows = []

    for website in data["websites"]:

        if website.duration:

            duration = duration_seconds(
                website.duration
            )

        elif website.end_time:

            duration = max(
                0,
                int(
                    (
                        website.end_time -
                        website.start_time
                    ).total_seconds()
                )
            )

        else:

            duration = max(
                0,
                int(
                    (
                        timezone.now() -
                        website.start_time
                    ).total_seconds()
                )
            )

        website_rows.append([
            website.browser_name,
            website.website,
            website.page_title,
            format_time(website.start_time),
            format_time(website.end_time),
            format_duration(duration),
            "Yes" if website.is_productive else "No",
        ])

    add_section(
        "Website Usage",
        [
            "Browser",
            "Website",
            "Page Title",
            "Start",
            "End",
            "Duration",
            "Productive",
        ],
        website_rows
    )

    # =====================================================
    # IDLE / BREAKS
    # =====================================================

    idle_rows = []

    for idle in data["idle_sessions"]:

        if idle.duration:

            duration = duration_seconds(
                idle.duration
            )

        elif idle.idle_end_time:

            duration = max(
                0,
                int(
                    (
                        idle.idle_end_time -
                        idle.idle_start_time
                    ).total_seconds()
                )
            )

        else:

            duration = max(
                0,
                int(
                    (
                        timezone.now() -
                        idle.idle_start_time
                    ).total_seconds()
                )
            )

        idle_rows.append([
            format_time(
                idle.idle_start_time
            ),
            format_time(
                idle.idle_end_time
            ),
            format_duration(duration),
        ])

    add_section(
        "Idle / Break Sessions",
        [
            "Started",
            "Ended",
            "Duration",
        ],
        idle_rows
    )

    # =====================================================
    # TASK TIME
    # =====================================================

    task_time_rows = []

    for task_time in data["task_times"]:

        if task_time.duration:

            duration = duration_seconds(
                task_time.duration
            )

        elif (
            task_time.start_time
            and task_time.end_time
        ):

            duration = max(
                0,
                int(
                    (
                        task_time.end_time -
                        task_time.start_time
                    ).total_seconds()
                )
            )

        else:

            duration = max(
                0,
                int(
                    (
                        timezone.now() -
                        task_time.start_time
                    ).total_seconds()
                )
            )

        task_name = (
            task_time.task.task_name
            if task_time.task
            else "Deleted Task"
        )

        task_time_rows.append([
            task_name,
            format_time(
                task_time.start_time
            ),
            format_time(
                task_time.end_time
            ),
            format_duration(duration),
        ])

    add_section(
        "Task Time",
        [
            "Task",
            "Start",
            "End",
            "Duration",
        ],
        task_time_rows
    )

    # =====================================================
    # TASKS
    # =====================================================

    task_rows = []

    for task in data["tasks"]:

        task_rows.append([
            task.task_name,
            task.status,
            getattr(
                task,
                "priority",
                ""
            ),
            getattr(
                task,
                "due_date",
                ""
            ),
        ])

    add_section(
        "Tasks",
        [
            "Task",
            "Status",
            "Priority",
            "Due Date",
        ],
        task_rows
    )

    # =====================================================
    # SCREENSHOTS
    # =====================================================

    screenshot_rows = []

    def fetch_screenshot_flowable(screenshot):
        url = get_screenshot_url(screenshot)
        img_flowable = None

        if url:
            try:
                if not url.startswith("http://") and not url.startswith("https://") and os.path.exists(url):
                    img_flowable = Image(url, width=220, height=124)
                else:
                    resp = requests.get(url, timeout=6)
                    if resp.status_code == 200 and resp.content:
                        img_buf = io.BytesIO(resp.content)
                        img_flowable = Image(img_buf, width=220, height=124)
            except Exception as ex:
                print(f"Error fetching screenshot {url}: {ex}")
                img_flowable = None

        cell_contents = []
        if img_flowable:
            cell_contents.append(img_flowable)
        if url:
            cell_contents.append(
                Paragraph(
                    f'<font size="7" color="#2563eb"><a href="{url}"><u>View Full Image</u></a></font>',
                    normal_style
                )
            )
        elif not img_flowable:
            cell_contents.append(
                Paragraph(
                    '<font color="#94a3b8"><i>Image unavailable</i></font>',
                    normal_style
                )
            )

        return cell_contents

    if data["screenshots"]:
        with ThreadPoolExecutor(max_workers=8) as executor:
            screenshot_images = list(
                executor.map(
                    fetch_screenshot_flowable,
                    data["screenshots"]
                )
            )

        for screenshot, img_cell in zip(data["screenshots"], screenshot_images):
            reason_display = (
                screenshot.reason.capitalize()
                if screenshot.reason
                else "Periodic"
            )
            screenshot_rows.append([
                format_time(screenshot.captured_at),
                reason_display,
                img_cell,
            ])

    add_section(
        "Screenshots",
        [
            "Captured At",
            "Reason",
            "Screenshot",
        ],
        screenshot_rows,
        col_widths=[140, 110, 540]
    )

    # =====================================================
    # BUILD PDF
    # =====================================================

    document.build(elements)

    return response