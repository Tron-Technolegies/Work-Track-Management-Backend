from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.utils import timezone
from .models import (
    MonitoringSettings,
    Screenshot,
    Task,
    Project,
    Notification,
    TaskTime,
    Company,
    LeavePolicy,
    WorkSession,
    IdleSession,
    ApplicationUsage,
    Team,
    AttendanceCorrection,
    SecuritySettings,
)

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
        
    company_name = serializers.CharField(
        source="company.company_name",
        read_only=True
    )

    team_name = serializers.CharField(
        source="team.team_name",
        read_only=True
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "role",
            "mobile",
            "password",
            "first_name",
            "last_name",
            "profile_picture",
            "company_name",
            "team",
            "team_name",
        ]

        extra_kwargs = {
            "password": {"write_only": True, "required": False},
            "username": {"required": False},
            "team": {"required": False, "allow_null": True},
            "mobile": {"required": False, "allow_blank": True, "allow_null": True},
            "profile_picture": {"required": False, "allow_null": True},
            "first_name": {"required": False, "allow_blank": True},
            "last_name": {"required": False, "allow_blank": True},
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)

        if instance.profile_picture:
            data["profile_picture"] = instance.profile_picture.url

        return data
class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        exclude = ["company"]

    def to_representation(self, instance):
        from django.utils import timezone

        representation = super().to_representation(instance)

        # Assigned By
        if instance.assigned_by:
            representation["assigned_by"] = (
                instance.assigned_by.first_name
                or instance.assigned_by.username
            )
        else:
            representation["assigned_by"] = None

        # Assigned Users
        representation["assigned_to"] = UserSerializer(
            instance.assigned_to.all(),
            many=True
        ).data

        # Team
        representation["team"] = (
            TeamSerializer(instance.team).data
            if instance.team
            else None
        )

        # Project Name
        representation["project_name"] = (
            instance.project.project_name
            if instance.project
            else None
        )

        # Actual Task Time using related sessions
        task_times = list(instance.sessions.all()) if hasattr(instance, "sessions") else list(TaskTime.objects.filter(task=instance))

        total_seconds = 0
        now = timezone.now()

        for tt in task_times:
            if tt.duration:
                total_seconds += tt.duration.total_seconds()
            elif tt.start_time and tt.end_time:
                total_seconds += (tt.end_time - tt.start_time).total_seconds()
            elif tt.start_time and not tt.end_time:
                total_seconds += (now - tt.start_time).total_seconds()

        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)

        representation["time_spent"] = f"{hours:02d}h {minutes:02d}m"
        representation["total_seconds_spent"] = int(total_seconds)

        return representation

class ProjectSerializer(serializers.ModelSerializer):
    progress = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    attachment_url = serializers.SerializerMethodField()

    class Meta:
        model = Project
        exclude = ["company"]

    def _get_task_stats(self, instance):
        if hasattr(instance, "_cached_task_stats"):
            return instance._cached_task_stats

        tasks = list(instance.tasks.all())
        total_tasks = len(tasks)

        if total_tasks == 0:
            stats = {"progress": 0, "status": "Pending"}
        else:
            completed_tasks = sum(
                1 for t in tasks if str(getattr(t, "status", "")).strip().lower() == "completed"
            )
            in_progress_tasks = sum(
                1 for t in tasks if str(getattr(t, "status", "")).strip().lower() == "in progress"
            )
            progress = round((completed_tasks / total_tasks) * 100)
            if completed_tasks == total_tasks:
                calc_status = "Completed"
            elif in_progress_tasks > 0:
                calc_status = "In Progress"
            else:
                calc_status = "Pending"
            stats = {"progress": progress, "status": calc_status}

        instance._cached_task_stats = stats
        return stats

    def get_progress(self, instance):
        return self._get_task_stats(instance)["progress"]

    def get_status(self, instance):
        return self._get_task_stats(instance)["status"]

    def get_attachment_url(self, instance):
        if not instance.attachments:
            return None

        request = self.context.get("request")
        if request:
            try:
                return request.build_absolute_uri(instance.attachments.url)
            except Exception:
                pass

        return getattr(instance.attachments, "url", str(instance.attachments))

    def to_representation(self, instance):
        representation = super().to_representation(instance)

        representation["assigned_to"] = UserSerializer(
            instance.assigned_to.all(),
            many=True
        ).data

        representation["tasks"] = TaskSerializer(
            instance.tasks.all(),
            many=True
        ).data

        representation["team"] = (
            TeamSerializer(instance.team).data
            if instance.team
            else None
        )

        return representation

class TaskTimeSerializer(serializers.ModelSerializer):
    user_details = UserSerializer(source='user', read_only=True)
    task_name = serializers.ReadOnlyField(source="task.task_name")
    team_name = serializers.ReadOnlyField(source='task.team.team_name')

    class Meta:
        model = TaskTime
        exclude = ["company"]


class WorkSessionSerializer(serializers.ModelSerializer):
    break_seconds = serializers.SerializerMethodField()
    break_time = serializers.SerializerMethodField()
    net_work_seconds = serializers.SerializerMethodField()
    net_work_time = serializers.SerializerMethodField()
    is_on_break = serializers.SerializerMethodField()

    class Meta:
        model = WorkSession
        exclude = ["company"]
        read_only_fields = (
            "clock_in",
            "clock_out",
            "total_work_time",
            "status",
            "work_date",
            "created_at",
        )

    def _get_session_metrics(self, obj):
        if hasattr(obj, "_cached_session_metrics"):
            return obj._cached_session_metrics

        now = timezone.now()
        idles = list(obj.idle_sessions.all())
        break_sec = 0
        is_on_break = False

        for idle in idles:
            if idle.duration:
                break_sec += int(idle.duration.total_seconds())
            elif idle.idle_end_time:
                break_sec += max(0, int((idle.idle_end_time - idle.idle_start_time).total_seconds()))
            elif not idle.idle_end_time:
                if not obj.clock_out:
                    break_sec += max(0, int((now - idle.idle_start_time).total_seconds()))
                    is_on_break = True

        if obj.clock_out:
            is_on_break = False
            total_sec = int(obj.total_work_time.total_seconds()) if obj.total_work_time else int((obj.clock_out - obj.clock_in).total_seconds())
        else:
            total_sec = max(0, int((now - obj.clock_in).total_seconds()))

        net_sec = max(0, total_sec - break_sec)
        h_break, m_break = break_sec // 3600, (break_sec % 3600) // 60
        h_net, m_net = net_sec // 3600, (net_sec % 3600) // 60

        metrics = {
            "break_seconds": break_sec,
            "break_time": f"{h_break:02d}h {m_break:02d}m",
            "net_work_seconds": net_sec,
            "net_work_time": f"{h_net:02d}h {m_net:02d}m",
            "is_on_break": is_on_break,
        }
        obj._cached_session_metrics = metrics
        return metrics

    def get_break_seconds(self, obj):
        return self._get_session_metrics(obj)["break_seconds"]

    def get_break_time(self, obj):
        return self._get_session_metrics(obj)["break_time"]

    def get_net_work_seconds(self, obj):
        return self._get_session_metrics(obj)["net_work_seconds"]

    def get_net_work_time(self, obj):
        return self._get_session_metrics(obj)["net_work_time"]

    def get_is_on_break(self, obj):
        return self._get_session_metrics(obj)["is_on_break"]


class ScreenshotSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    employee_name = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()

    class Meta:
        model = Screenshot
        exclude = ["company"]

    def get_employee_name(self, obj):
        if not obj.user:
            return ""
        return obj.user.get_full_name() or obj.user.first_name or obj.user.username or obj.user.email

    def get_email(self, obj):
        return obj.user.email if obj.user else ""

    def get_image(self, obj):
        if not obj.image:
            return None
        raw = str(obj.image)
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        try:
            import cloudinary.utils
            url, _ = cloudinary.utils.cloudinary_url(
                raw.lstrip("/"),
                resource_type="image",
                secure=True
            )
            return url
        except Exception:
            return getattr(obj.image, "url", raw)


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        exclude = ["company"]
        read_only_fields = [
            "id",
            "created_at",
        ]


class MonitoringSettingsSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = MonitoringSettings
        exclude = ["company"]
        extra_kwargs = {
            "blocked_applications": {"required": False},
            "screenshot_on_blocked_app": {"required": False},
        }


class IdleSessionSerializer(serializers.ModelSerializer):

    employee_name = serializers.CharField(
        source="user.get_full_name",
        read_only=True
    )

    email = serializers.EmailField(
        source="user.email",
        read_only=True
    )

    duration_seconds = serializers.SerializerMethodField()
    formatted_duration = serializers.SerializerMethodField()

    class Meta:
        model = IdleSession
        fields = [
            "id",
            "user",
            "employee_name",
            "email",
            "work_session",
            "idle_start_time",
            "idle_end_time",
            "duration",
            "duration_seconds",
            "formatted_duration",
            "created_at",
        ]

    def get_duration_seconds(self, obj):
        if obj.duration:
            return int(obj.duration.total_seconds())
        if obj.idle_end_time:
            return max(0, int((obj.idle_end_time - obj.idle_start_time).total_seconds()))
        return max(0, int((timezone.now() - obj.idle_start_time).total_seconds()))

    def get_formatted_duration(self, obj):
        sec = self.get_duration_seconds(obj)
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        if h > 0:
            return f"{h:02d}h {m:02d}m"
        return f"{m:02d}m {s:02d}s"


class ApplicationUsageSerializer(serializers.ModelSerializer):

    employee_name = serializers.CharField(
        source="user.get_full_name",
        read_only=True
    )

    email = serializers.EmailField(
        source="user.email",
        read_only=True
    )

    work_date = serializers.DateField(
        source="work_session.work_date",
        read_only=True
    )


    class Meta:
        model = ApplicationUsage
        fields = [
            "id",
            "user",
            "employee_name",
            "email",
            "work_session",
            "work_date",
            "application_name",
            "window_title",
            "start_time",
            "end_time",
            "duration",
            "is_productive",
            "created_at",
        ]


from rest_framework import serializers
from .models import WebsiteUsage


class WebsiteUsageSerializer(serializers.ModelSerializer):

    class Meta:
        model = WebsiteUsage
        exclude = ["company"]


from rest_framework import serializers
from .models import LeaveType


class LeaveTypeSerializer(serializers.ModelSerializer):

    class Meta:
        model = LeaveType
        fields = [
            "id",
            "name",
            "description",
            "days_per_year",
            "is_paid",
            "is_active",
            "allow_half_day",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

from rest_framework import serializers
from .models import LeaveRequest


class LeaveRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveRequest
        fields = [
            "id",
            "leave_type",
            "start_date",
            "end_date",
            "reason",
            "status",
            "total_days",
            "approved_by",
            "approved_at",
            "rejection_reason",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",   
            "status",
            "total_days",
            "approved_by",
            "approved_at",
            "rejection_reason",
            "created_at",
            "updated_at",
        ]

class CompanySMTPSerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = [
            "smtp_host",
            "smtp_port",
            "smtp_email",
            "smtp_password",
            "smtp_use_tls",
            "smtp_use_ssl"
        ]
        extra_kwargs = {
            "smtp_password" : {
                "write_only": True
            }
        }

    def validate(self, attrs): #attrs is datas from frontend
        smtp_use_tls = attrs.get(
            "smtp_use_tls",
            self.instance.smtp_use_tls if self.instance else False
        )
        smtp_use_ssl = attrs.get(
            "smtp_use_ssl",
            self.instance.smtp_use_ssl if self.instance else False
        )

        if smtp_use_tls and smtp_use_ssl:
            raise serializers.ValidationError(
                {
                    "smtp_use_tls" : "TLS and SSL cannot both be enabled",
                    "smtp_use_ssl" : "TLS and SSL cannot both be enabled"
                }
            )
        return attrs

class LeavePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = LeavePolicy
        fields = "__all__"
        read_only_fields = ["company", "created_at"]

class TeamSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.company_name",read_only=True)
    team_lead_name = serializers.CharField(source="team_lead.first_name",read_only=True)
    class Meta:
        model = Team
        fields = [
            "id",
            "team_name",
            "description",
            "team_lead",
            "team_lead_name",
            "status",
            "company",
            "company_name", 
            "created_at",
        ]
        read_only_fields = ["company", "created_at"]


class AttendanceCorrectionSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    employee_email = serializers.ReadOnlyField(source="user.email")
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceCorrection
        fields = [
            "id",
            "user",
            "employee_name",
            "employee_email",
            "work_date",
            "check_in",
            "check_out",
            "reason",
            "status",
            "rejection_reason",
            "approved_by",
            "approved_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["user", "company", "status", "approved_by", "created_at", "updated_at"]

    def get_employee_name(self, obj):
        name = f"{obj.user.first_name} {obj.user.last_name}".strip()
        return name if name else obj.user.username or obj.user.email

    def get_approved_by_name(self, obj):
        if not obj.approved_by:
            return None
        name = f"{obj.approved_by.first_name} {obj.approved_by.last_name}".strip()
        return name if name else obj.approved_by.username or obj.approved_by.email


class CompanySerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            "id",
            "company_name",
            "company_code",
            "email",
            "phone",
            "address",
            "logo",
            "logo_url",
            "created_at",
        ]
        read_only_fields = ["id", "company_code", "created_at"]
        extra_kwargs = {
            "logo": {"write_only": True, "required": False},
        }

    def get_logo_url(self, obj):
        if obj.logo:
            try:
                return obj.logo.url
            except Exception:
                return None
        return None


class SecuritySettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecuritySettings
        exclude = ["company", "created_at", "updated_at"]
