from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import MonitoringSettings, Screenshot, Task, Project, Notification, TaskTime ,Company, LeavePolicy,WorkSession,ApplicationUsage,Team, AttendanceCorrection, SecuritySettings

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
            "password": {"write_only": True}
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
        representation = super().to_representation(instance)
        representation["assigned_by"] = (instance.assigned_by.first_name if instance.assigned_by else None)
        representation['assigned_to'] = UserSerializer(instance.assigned_to.all(), many=True).data
        representation["team"] = TeamSerializer(instance.team).data if instance.team else None
        return representation

class ProjectSerializer(serializers.ModelSerializer):
    progress = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    class Meta:
        model = Project
        exclude = ["company"]

    def get_progress(self, instance):
        total_tasks = instance.tasks.count()

        if total_tasks == 0:
            return 0

        completed_tasks = instance.tasks.filter(
            status="Completed"
        ).count()

        return round(
            (completed_tasks / total_tasks) * 100
        )
    
    def get_status(self, instance):
        total_tasks = instance.tasks.count()

        if total_tasks == 0:
            return "Pending"
        
        completed_tasks = instance.tasks.filter(
            status = "Completed"
        ).count()

        in_progress_tasks = instance.tasks.filter(
            status="In Progress"
        ).count()

        if completed_tasks == total_tasks:
            return "Completed"

        if in_progress_tasks > 0:
            return "In Progress"

        return "Pending"

    def to_representation(self, instance):
        representation = super().to_representation(instance)

        representation['assigned_to'] = UserSerializer(
            instance.assigned_to.all(),
            many=True
        ).data

        representation['tasks'] = TaskSerializer(
            instance.tasks.all(),
            many=True
        ).data

        representation["team"] = TeamSerializer(
            instance.team
        ).data if instance.team else None
        return representation
    def get_total_time(self, obj):
            
        if not obj.start_time or not obj.end_time:
            
            return None

        duration = obj.end_time - obj.start_time

        total_seconds = int(duration.total_seconds())

        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60

        return f"{hours}h {minutes}m"

class TaskTimeSerializer(serializers.ModelSerializer):
    user_details = UserSerializer(source='user', read_only=True)
    task_name = serializers.ReadOnlyField(source="task.task_name")
    team_name = serializers.ReadOnlyField(source='task.team.team_name')

    class Meta:
        model = TaskTime
        exclude = ["company"]


class WorkSessionSerializer(serializers.ModelSerializer):
    
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


class ScreenshotSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Screenshot
        exclude = ["company"]


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


from rest_framework import serializers
from .models import IdleSession


class IdleSessionSerializer(serializers.ModelSerializer):

    employee_name = serializers.CharField(
        source="user.get_full_name",
        read_only=True
    )

    email = serializers.EmailField(
        source="user.email",
        read_only=True
    )

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
            "created_at",
        ]


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
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

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