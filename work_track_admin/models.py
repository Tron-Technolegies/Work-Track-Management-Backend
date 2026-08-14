from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.db import models
from django.db.models import DateField
from django.views.decorators.csrf import csrf_exempt
from cloudinary.models import CloudinaryField
from datetime import timedelta
from django.conf import settings

# Create your models here.

class Company(models.Model):
    company_name = models.CharField(max_length=200,unique=True)
    company_code = models.CharField(max_length=50,unique=True)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    smtp_host = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="SMTP server (e.g.smtp.gmail.com)"
    )
    smtp_port = models.PositiveIntegerField(
        default=587
    )
    smtp_email = models.EmailField(
        blank=True,
        null=True,
        help_text="Sender email address"
    )

    smtp_password = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="SMTP password or App Password"
    )
    smtp_use_tls = models.BooleanField(
        default=True
    )
    smtp_use_ssl = models.BooleanField(
        default=False
    )
    logo = CloudinaryField("company_logo", blank=True, null=True)
    def __str__(self):
        return self.company_name


class User(AbstractUser):
    username = models.CharField(max_length=255, unique=True)
    email = models.EmailField()
    ROLE_CHOICES = (
        ("admin", "Admin"),
        ("project_lead", "Project Lead"),
        ("user", "User"),
    )

    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name="users",null=True,blank=True)
    leave_policy = models.ForeignKey("LeavePolicy",on_delete=models.SET_NULL,null=True,blank=True,related_name="employees")
    team = models.ForeignKey("Team",on_delete=models.SET_NULL,null=True,blank=True,related_name="members")
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default="user"
    )

    mobile = models.CharField(max_length=15, blank=True, null=True)

    profile_picture = CloudinaryField("profile_picture",blank=True,null=True)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['company', 'email'], name='unique_company_email')
        ]




    def __str__(self):
        return self.email




class Project(models.Model):
    PRIORITY_CHOICES = [('High', 'High'), ('Medium', 'Medium'), ('Low', 'Low')]
    STATUS_CHOICES = [
        ('In Progress', 'In Progress'),
        ('Pending', 'Pending'),
        ('To Do', 'To Do'),
        ('Task Done', 'Task Done'),
        ('Completed', 'Completed')
    ]
    ACTIVE_CHOICES = [('View', 'View'), ('Edit', 'Edit'), ('Delete', 'Delete')]
    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name="projects",null=True,blank=True)

    project_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    assigned_to = models.ManyToManyField(User, blank=True, related_name='projects')
    team = models.ForeignKey("Team",on_delete=models.SET_NULL,null=True,blank=True,related_name="projects")
    due_date = models.DateField(null=True, blank=True)
    est_hour = models.IntegerField(default=0)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES)
    links = models.URLField(blank=True)
    attachments = models.FileField(upload_to="project_files/", blank=True, null=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='Pending')
    active = models.CharField(max_length=15, choices=ACTIVE_CHOICES, default='View')

    def __str__(self):
        return self.project_name
class Task(models.Model):
    PRIORITY_CHOICES = [('High', 'High'), ('Medium', 'Medium'), ('Low', 'Low')]
    STATUS_CHOICES = [
        ('In Progress', 'In Progress'),
        ('Pending', 'Pending'),
        ('To Do', 'To Do'),
        ('Completed', 'Completed')
    ]
    
    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name="tasks",null=True,blank=True)
    project = models.ForeignKey(Project,on_delete=models.CASCADE,related_name="tasks",null=True,blank=True)
    task_name = models.CharField(max_length=255)
    team = models.ForeignKey("Team",on_delete=models.SET_NULL,null=True,blank=True,related_name="tasks")
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES)
    due_date = models.DateField()
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='Pending')
    assigned_to = models.ManyToManyField(User, blank=True, related_name='tasks')
    assigned_by = models.ForeignKey(
    User,
    on_delete=models.SET_NULL,
    null=True,
    related_name="created_tasks"
)
    working_hours = models.IntegerField(default=0)
    description = models.TextField(blank=True)
    discussion = models.TextField(blank=True)
    links = models.URLField(blank=True)
    attachments = models.URLField(blank=True,null=True)
    total_time = models.DurationField(default=timedelta())

    def __str__(self):
        return self.task_name





class TaskTime(models.Model):
    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name="task_times",null=True,blank=True)
    task = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True, related_name="sessions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_sessions")
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["task", "user"],
                condition=models.Q(end_time__isnull=True),
                name="one_running_session_per_user_per_task"
            )
        ]
        
    def stop(self):
        if not self.end_time:
            self.end_time = timezone.now()
            self.duration = self.end_time - self.start_time
            self.save(update_fields=["end_time", "duration"])
            self.task.total_time += self.duration
            self.task.save(update_fields=["total_time"])

    def __str__(self):
        return f"{self.task.task_name} - {self.user.email}"


class WorkSession(models.Model):
    
    STATUS_CHOICES = (
        ("working", "Working"),
        ("completed", "Completed"),
    )

    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name="work_sessions",null=True,blank=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="work_sessions"
    )

    clock_in = models.DateTimeField(default=timezone.now)

    clock_out = models.DateTimeField(
        null=True,
        blank=True
    )

    total_work_time = models.DurationField(
        default=timedelta
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="working"
    )

    work_date = models.DateField(
        default=timezone.localdate
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ["-clock_in"]

        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(clock_out__isnull=True),
                name="one_active_work_session_per_user"
            )
        ]


    def stop(self):
        """
        Close the session and calculate duration.
        """
        if not self.clock_out:
            self.clock_out = timezone.now()
            self.total_work_time = (
                self.clock_out - self.clock_in
            )
            self.status = "completed"
            self.save(
                update_fields=[
                    "clock_out",
                    "total_work_time",
                    "status"
                ]
            )

    def __str__(self):
        return f"{self.user.email} ({self.work_date})"



class Screenshot(models.Model):
    
    REASON_CHOICES = (
        ("periodic", "Periodic"),
        ("idle", "Idle"),
        ("manual", "Manual"),
    )
    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name="screenshots",null=True,blank=True)


    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="screenshots"
    )
    work_session = models.ForeignKey(
        WorkSession,
        on_delete=models.CASCADE,
        related_name="screenshots"
    )

    image = CloudinaryField(
        "screenshot",
        folder="worktrack/screenshots"
    )

    reason = models.CharField(
        max_length=20,
        choices=REASON_CHOICES,
        default="periodic"
    )

    captured_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ["-captured_at"]

    def __str__(self):
        return f"{self.user.email} - {self.captured_at}"
    

class MonitoringSettings(models.Model):

    company = models.OneToOneField(Company,on_delete=models.CASCADE,related_name="monitoring_settings",null=True,blank=True)
    
    screenshot_interval = models.PositiveIntegerField(
        default=300,
        help_text="Screenshot interval in seconds"
    )

    screenshot_retention_days = models.PositiveIntegerField(
        default=30,
        help_text="Delete screenshots after these many days"
    )

    idle_timeout = models.PositiveIntegerField(
        default=300,
        help_text="Idle timeout in seconds"
    )

    screenshot_enabled = models.BooleanField(
        default=True
    )

    app_tracking_enabled = models.BooleanField(
        default=True
    )

    website_tracking_enabled = models.BooleanField(
        default=True
    )

    idle_tracking_enabled = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )
    capture_quality = models.PositiveIntegerField(
        default=70,
        help_text="Screenshot JPEG quality (1-100)"
    )

    def __str__(self):
        return "Monitoring Settings"


class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ("task", "Task"),
        ("project", "Project"),
        ("attendance", "Attendance"),
        ("idle", "Idle"),
        ("application", "Application"),
        ("website", "Website"),
        ("screenshot", "Screenshot"),
        ("system", "System"),
        ("leave_request", "Leave Request"),
        ("leave_approved", "Leave Approved"),
        ("leave_rejected", "Leave Rejected"),
        ("leave_cancelled", "Leave Cancelled")
    ]

    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name="notifications",null=True,blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,blank=True, related_name='notifications')
    title = models.CharField(max_length=150, default="Notification")
    message = models.CharField(max_length=255)
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES,default="system")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        # order by created last ie .. Newset to oldest.

    def __str__(self):
        return f"{self.user.email} - {self.title}"
    #eg..print notification -- user@gmail.com - Task Assigned
    



class IdleSession(models.Model):


    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name="idle_sessions",null=True,blank=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="idle_sessions"
    )


    work_session = models.ForeignKey(
        WorkSession,
        on_delete=models.CASCADE,
        related_name="idle_sessions"
    )

    idle_start_time = models.DateTimeField(
        default=timezone.now
    )

    idle_end_time = models.DateTimeField(
        null=True,
        blank=True
    )

    duration = models.DurationField(
        default=timedelta
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ["-idle_start_time"]

        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(idle_end_time__isnull=True),
                name="one_active_idle_session_per_user"
            )
        ]

    def stop(self):
        if not self.idle_end_time:
            self.idle_end_time = timezone.now()
            self.duration = self.idle_end_time - self.idle_start_time
            self.save(update_fields=["idle_end_time", "duration"])

    def __str__(self):
        return f"{self.user.email} - {self.idle_start_time}"
    


class ApplicationUsage(models.Model):


    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name="application_usage",null=True,blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="application_usage"
    )

    work_session = models.ForeignKey(
        WorkSession,
        on_delete=models.CASCADE,
        related_name="application_usage"
    )

    application_name = models.CharField(
        max_length=255
    )

    window_title = models.CharField(
        max_length=500,
        blank=True
    )

    start_time = models.DateTimeField(
        default=timezone.now
    )

    end_time = models.DateTimeField(
        null=True,
        blank=True
    )

    duration = models.DurationField(
        default=timedelta
    )

    is_productive = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:

        ordering = ["-start_time"]

        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(end_time__isnull=True),
                name="one_running_application_per_user"
            )
        ]

    def stop(self):

        if not self.end_time:

            self.end_time = timezone.now()

            self.duration = (
                self.end_time -
                self.start_time
            )

            self.save(
                update_fields=[
                    "end_time",
                    "duration"
                ]
            )

    def __str__(self):

        return (
            f"{self.user.email} - "
            f"{self.application_name}"
        )

from datetime import timedelta
from django.conf import settings
from django.db import models
from django.utils import timezone


class WebsiteUsage(models.Model):

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="website_usage"
    )
    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name="website_usage",null=True,blank=True)

    work_session = models.ForeignKey(
        WorkSession,
        on_delete=models.CASCADE,
        related_name="website_usage"
    )

    application_usage = models.ForeignKey(
        ApplicationUsage,
        on_delete=models.CASCADE,
        related_name="website_usage",
        null=True,
        blank=True
    )

    browser_name = models.CharField(
        max_length=100
    )

    website = models.CharField(
        max_length=255
    )

    page_title = models.CharField(
        max_length=500,
        blank=True
    )

    start_time = models.DateTimeField(
        default=timezone.now
    )

    end_time = models.DateTimeField(
        null=True,
        blank=True
    )

    duration = models.DurationField(
        default=timedelta
    )

    is_productive = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:

        ordering = ["-start_time"]

        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(end_time__isnull=True),
                name="one_running_website_per_user"
            )
        ]

    def stop(self):

        if not self.end_time:

            self.end_time = timezone.now()

            self.duration = (
                self.end_time -
                self.start_time
            )

            self.save(
                update_fields=[
                    "end_time",
                    "duration"
                ]
            )

    def __str__(self):

        return (
            f"{self.user.email} - "
            f"{self.website}"
        )


from django.db import models

class LeaveType(models.Model):

    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]
    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name="leave_types")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    days_per_year = models.PositiveIntegerField(default=0)
    is_paid = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    allow_half_day = models.BooleanField(default=False)
    status = models.CharField(max_length=10,choices=STATUS_CHOICES,default="active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"],
                name="unique_leave_type_per_company"
            )
        ]

    def __str__(self):
        return f"{self.name} - {self.company.company_name}"




class LeaveRequest(models.Model):

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("cancelled", "Cancelled"),
    ]

    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name="leave_requests")
    employee = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="leave_requests")
    leave_type = models.ForeignKey(LeaveType,on_delete=models.CASCADE,related_name="leave_requests")
    start_date = models.DateField()
    end_date = models.DateField()
    total_days = models.PositiveIntegerField()
    reason = models.TextField()
    status = models.CharField(max_length=20,choices=STATUS_CHOICES,default="pending")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name="approved_leave_requests")
    approved_at = models.DateTimeField(null=True,blank=True)
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "start_date", "end_date"],
                name="unique_leave_request_per_employee"
            )
        ]   
    def __str__(self):
        return f"{self.employee.full_name} - {self.leave_type.get_name_display()} ({self.status})"


class LeavePolicy(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="leave_policies"
    )

    policy_name = models.CharField(max_length=100)

    description = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=[
            ("active", "Active"),
            ("inactive", "Inactive")
        ],
        default="active"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "policy_name"],
                name="unique_leave_policy_per_company"
            )
        ]

    def __str__(self):
        return self.policy_name


class LeavePolicyDetail(models.Model):
    
    policy = models.ForeignKey(
        LeavePolicy,
        on_delete=models.CASCADE,
        related_name="leave_details"
    )

    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.CASCADE,
        related_name="policy_details"
    )

    days_allowed = models.PositiveIntegerField()

    carry_forward = models.BooleanField(default=False)

    allow_half_day = models.BooleanField(default=False)

    is_paid = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["policy", "leave_type"],
                name="unique_leave_type_per_policy"
            )
        ]

    def __str__(self):
        return f"{self.policy.policy_name} - {self.leave_type.get_name_display()}"

class Team(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="teams"
    )

    team_name = models.CharField(max_length=100)

    description = models.TextField(blank=True)

    team_lead = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leading_teams"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="active"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "team_name"],
                name="unique_team_per_company"
            )
        ]

    def __str__(self):
        return self.team_name


class SecuritySettings(models.Model):
    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name="security_settings",
        null=True,
        blank=True
    )
    min_password_length = models.PositiveIntegerField(default=8)
    require_uppercase = models.BooleanField(default=True)
    require_number = models.BooleanField(default=True)
    require_special_character = models.BooleanField(default=True)
    force_password_change_days = models.PositiveIntegerField(default=90)
    session_timeout = models.PositiveIntegerField(default=30, help_text="Session timeout in minutes")
    max_login_attempts = models.PositiveIntegerField(default=5)
    account_lock_minutes = models.PositiveIntegerField(default=15)
    enable_2fa = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Security Settings - {self.company}"


class AttendanceCorrection(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    )

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="attendance_corrections"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attendance_corrections"
    )
    work_date = models.DateField()
    check_in = models.TimeField(null=True, blank=True)
    check_out = models.TimeField(null=True, blank=True)
    reason = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )
    rejection_reason = models.TextField(blank=True, null=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_attendance_corrections"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} - {self.work_date} ({self.status})"
