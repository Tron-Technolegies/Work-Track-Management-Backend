from django.urls import path
from . import views

urlpatterns = [
    # Authentication & User Management
    path('signup/', views.Signup, name="SignUp"),
    path("create-user/", views.Create_Employee, name="create-user"),
    path('login/', views.Login, name="Login"),
    path("reset-employee-password/<int:user_id>/",views.reset_employee_password,name="reset_employee_password"),
    # path('user_login/', views.user_login, name='user_login'),
    path('logout/', views.logout, name="logout"),
    path('current_user/', views.current_user, name='current_user'),
    path('users/', views.Get_Users, name='Get_Users'),
    path("update_employee/<int:user_id>/",views.update_employee,name="update_employee"),
    path('users/list/', views.Get_User_List, name='Get_User_List'),
    path('users/<int:id>/delete/', views.delete_user, name="delete_user"),
    path('members/active/',views.active_members_count,name="active_members"),
    path('users/<int:id>/',views.Get_Single_User,name='Get_Single_User'),
    path('user-dropdown/',views.user_dropdown,name='user-dropdown'),
    path( "team-leads/",views.team_lead_list),

    # Project Management
    path('projects/add/', views.Add_Projects, name='Add_projects'),
    path('projects/', views.View_Projects, name='View_Projects'),
    path('projects/<int:project_id>/view/', views.View_Single_Project, name="view_single_project"),
    path('projects/<int:id>/update/', views.update_projects, name='Updated_projects'),
    path('projects/<int:id>/delete/', views.Delete_Projects, name='Delete_projects'),
    path('projects/total/', views.total_projects, name="Total_Projects"),
    path('projects/total-by-user/', views.total_projects_by_user, name="total_projects_by_user"),
    path("projects/summary/",views.project_summary_table,name="project_summary_table"),
    path("projects/dropdown/",views.project_dropdown),

    # Task Management
    path('tasks/add/', views.Add_Tasks, name='Add_tasks'),
    path('tasks/', views.View_Tasks, name='View_Tasks'),
    path('tasks/user/', views.View_User_Tasks, name='View_User_Tasks'),
    path('tasks/<int:task_id>/view/', views.View_Single_Task, name='View_Single_Task'),
    path('tasks/<int:id>/update/', views.Update_Tasks, name='Update_Task'),
    path('tasks/<int:id>/delete/', views.Delete_Task, name='Delete_Tasks'),
    path('tasks/total/', views.total_tasks, name="Total_Tasks"),
    path('tasks/summary/', views.total_tasks_summary, name='total_tasks_summary'),
    path('tasks/admin-summary/', views.admin_tasks_summary, name='admin_tasks_summary'),
    path('tasks/update-status/', views.update_task_status, name='update_task_status'),
    path('completed_task/',views.completed_task_count,name='completed_task'),

    # Dashboard Metrics
    path('dashboard/efficiency/',views.efficiency_view,name='efficiency_view'),
    path('dashboard/activity/',views.activity_view,name='activity_view'),
    path('tasks/status-count/',views.task_status_count,name='task_status_count'),
    path('kanban/assigned-users/',views.assigned_users,name='assigned_users'),
    path('kanban/statuses/',views.task_statuses,name='task_statuses'),
    path('employees/efficiency/',views.user_efficiency,name='user_efficiency'),
    path('employees/idle-time/',views.user_idle_time,name='user_idle_time'),

    path('dashboard/summary/', views.admin_dashboard_summary, name="admin_dashboard_summary"),
    path('dashboard/employee-status/', views.employee_status_summary, name="employee_status_summary"),
    path('dashboard/work-task-chart/', views.work_task_chart, name="work_task_chart"),
    path('dashboard/project-details/', views.dashboard_project_details, name="dashboard_project_details"),
    path('reports/weekly-work/', views.weekly_work_report, name="weekly_work_report"),
    path('reports/all/', views.all_reports, name="all_reports"),
    path('employees/productivity/', views.View_Employees_Productivity, name="employees_productivity"),
    path('employees/<int:user_id>/productivity/', views.View_Single_Employee_Productivity, name="single_employee_productivity"),

    # Kanban
    path('kanban/tasks/', views.kanban_tasks, name="kanban_tasks"),
    path('kanban/tasks/<int:task_id>/status/', views.update_task_status, name="update_kanban_status"),

    # Time Tracking
    path('tasks/<int:task_id>/start/', views.start_task, name='Start_Task'),
    path('tasks/<int:task_id>/stop/', views.stop_task, name='stop_task'),
    path('tasks/<int:task_id>/running/', views.get_running_task_session, name='get_running_session'),
    path('tasks/running/', views.get_active_task, name="get_active_task"),

    # Notifications
    path('notifications/', views.user_notifications, name='user_notifications'),
    path("notifications/read-all/", views.mark_all_notifications_read, name="mark_all_notifications_read"),
    path("notifications/unread-count/", views.unread_notification_count, name="unread_notification_count"),
    path("notifications/<int:id>/read/", views.mark_notification_read, name="mark_notification_read"),
    path("notifications/<int:id>/", views.delete_notification, name="delete_notification"),

    # Screenshots (Standardized name)
    path('screenshots/', views.all_screenshots, name='all_screenshots'),
    path("attendance/",views.attendance_list,name="attendance_list"),
    path("attendance/calendar/", views.attendance_calendar, name="attendance_calendar"),
    path("attendance/corrections/", views.attendance_corrections, name="attendance_corrections"),
    path("attendance/corrections/<int:pk>/action/", views.attendance_correction_action, name="attendance_correction_action"),
    path("idle-report/",views.idle_report,name="idle_report"),
    path("application-report/",views.application_report,name="application_report"),
    path("website-report/",views.website_report,name="website_report"),


    path("leave-types/", views.list_leave_types),
    path("leave-types/create/", views.create_leave_type),
    path("leave-types/update/<int:pk>/", views.update_leave_type),
    path("leave-types/delete/<int:pk>/", views.delete_leave_type),

    path("leave-requests/", views.leave_requests),
    path("approve-leave/<int:pk>/", views.approve_leave),
    path("reject-leave/<int:pk>/", views.reject_leave),

    path("export/employees/excel/",views.export_employees_excel,name="export_employees_excel"),
    path("export/employees/pdf/",views.export_employees_pdf,name="export_employees_pdf"),
    path("export/reports/excel/",views.export_reports_excel,name="export_reports_excel"),
    path("export/reports/pdf/",views.export_reports_pdf,name="export_reports_pdf"),
    path("export/reports/monthly/excel/",views.export_monthly_excel,name="export_monthly_excel"),
    path("export/reports/monthly/pdf/",views.export_monthly_pdf,name="export_monthly_pdf"),
    path("export/reports/yearly/excel/",views.export_yearly_excel,name="export_yearly_excel"),
    path("export/reports/yearly/pdf/",views.export_yearly_pdf,name="export_yearly_pdf"),
    path("test-email/",views.test_email,name="test_email"),
    path("company/smtp-settings/",views.company_smtp_settings,name="company_smtp_settings"),


    path("create-leave-policy/", views.create_leave_policy),
    path("view-leave-policies/", views.view_leave_policies),
    path("view-leave-policy/<int:policy_id>/", views.view_leave_policy),
    path("update-leave-policy/<int:policy_id>/", views.update_leave_policy),
    path("delete-leave-policy/<int:policy_id>/", views.delete_leave_policy),


    path("create-team/", views.create_team),
    path("view-teams/", views.view_teams),
    path("view-team/<int:team_id>/", views.view_team),
    path("update-team/<int:team_id>/", views.update_team),
    path("delete-team/<int:team_id>/", views.delete_team),

    # Settings endpoints
    path("company/info/", views.company_info_settings, name="company_info_settings"),
    path("security-settings/", views.security_settings, name="security_settings"),
    path("admin-monitoring-settings/", views.admin_monitoring_settings, name="admin_monitoring_settings"),
    path("account-settings/", views.account_settings, name="account_settings"),
    path("global-search/", views.global_search, name="global_search"),

    
]   
