import json
import os
import base64
import platform
import re
import traceback
import threading
import subprocess
# from django.tasks import task
import psutil
from datetime import datetime, date, timedelta
import calendar
from work_track_admin.exports.pdf_export import export_to_pdf

from django.contrib.auth import authenticate, get_user_model
from django.db.models import Sum, Q, F, ExpressionWrapper, DurationField
from django.db.models.functions import ExtractWeekDay
from django.utils import timezone
from django.shortcuts import get_object_or_404
from requests import request
from .models import ApplicationUsage, Screenshot,IdleSession,Company,LeaveRequest,Task, Project, Notification, TaskTime, WorkSession,WebsiteUsage,LeaveType,LeavePolicy,Team, AttendanceCorrection, SecuritySettings, MonitoringSettings

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from rest_framework.parsers import MultiPartParser, FormParser,JSONParser
from rest_framework.decorators import parser_classes
from rest_framework import status
from .notification_service import send_notification
from django.db import transaction
from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone
from datetime import datetime, timedelta
from utils.encryption import encrypt_password

from datetime import datetime
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from work_track_admin.exports.excel_export import export_to_excel
from work_track_admin.email_service import send_email_notification
from .permissions import (
    IsAdminRole,
    IsProjectLeadRole,
    IsEmployeeRole,
    IsAdminOrProjectLead,
    IsAdminOrOwner,
)
from .exports.productivity_export import (
    get_report_date_range,
    build_productivity_data,
    generate_productivity_excel,
    generate_productivity_pdf,
)
from .serializers import (
    UserSerializer,
    TaskSerializer,
    ProjectSerializer,
    TaskTimeSerializer,
    NotificationSerializer,
    WebsiteUsageSerializer,
    WorkSessionSerializer,
    LeaveRequestSerializer,
    LeaveTypeSerializer,
    CompanySMTPSerializer,
    LeavePolicySerializer,
    TeamSerializer,
    AttendanceCorrectionSerializer,
    CompanySerializer,
    SecuritySettingsSerializer,
    MonitoringSettingsSerializer,
)

User = get_user_model()

import uuid

def generate_company_code():
    return f"CMP-{uuid.uuid4().hex[:6].upper()}"

@api_view(["POST"])
@permission_classes([AllowAny])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def Signup(request):
    try:
        print("========== SIGNUP START ==========")
        print("Request Data:", request.data)

        data = request.data.copy()

        # Map frontend fields
        data["first_name"] = request.data.get("name", "").strip()
        data["mobile"] = request.data.get("phone", "").strip()

        email = request.data.get("email", "").strip()

        if email:
            data["username"] = email
            data["email"] = email

        password = request.data.get("password", "")
        company_name = request.data.get("company_name", "").strip()

        # -----------------------------
        # Required field validation
        # -----------------------------
        required_fields = {
            "company_name": company_name,
            "name": request.data.get("name"),
            "email": email,
            "phone": request.data.get("phone"),
            "password": password,
        }

        for field, value in required_fields.items():
            if not value:
                return Response(
                    {"error": f"{field} is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # -----------------------------
        # Password Validation
        # -----------------------------
        if len(password) < 8:
            return Response(
                {"error": "Password must be at least 8 characters long"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not re.search(r"[A-Z]", password):
            return Response(
                {"error": "Password must contain at least one uppercase letter"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not re.search(r"[a-z]", password):
            return Response(
                {"error": "Password must contain at least one lowercase letter"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not re.search(r"\d", password):
            return Response(
                {"error": "Password must contain at least one number"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            return Response(
                {"error": "Password must contain at least one special character"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # -----------------------------
        # Duplicate validation
        # -----------------------------
        if Company.objects.filter(company_name=company_name).exists():
            return Response(
                {"error": "Company already exists"},
                status=status.HTTP_400_BAD_REQUEST
            )
        if User.objects.filter(email__iexact=email).exists():
            return Response(
                {"error": "An account with this email address already exists."},
                status=status.HTTP_400_BAD_REQUEST
        )

        # Removed global email existence check since we allow cross-company identical emails.
        # But we must check if a company already exists for this email if we want to restrict one company per email owner.
        # Let's assume an owner CAN create multiple companies with same email if they want.

        print("Creating serializer...")

        serializer = UserSerializer(data=data)

        if not serializer.is_valid():
            print("Serializer Errors:", serializer.errors)
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        print("Serializer Valid")

        with transaction.atomic():
            company_code = generate_company_code()
            company = Company.objects.create(
                company_name=company_name,
                company_code=company_code,
                email=email,
                phone=request.data.get("phone"),
                address=request.data.get("address", ""),
            )

            user = serializer.save(company=company)

            user.set_password(password)
            user.role = "admin"
            user.is_staff = True
            user.save()

        return Response(
            {
                "message": "Company registered successfully",
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )

    except Exception:
        traceback.print_exc()

        return Response(
            {
                "error": "Internal Server Error"
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminOrProjectLead])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def Create_Employee(request):

    first_name = str(request.data.get("first_name", "")).strip()
    last_name = str(request.data.get("last_name", "")).strip()
    email = str(request.data.get("email", "")).strip().lower()
    mobile = str(request.data.get("mobile", "")).strip()
    password = request.data.get("password", "")

    # -----------------------------
    # Required field validation
    # -----------------------------

    if not first_name:
        return Response(
            {"error": "First name is required."},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not last_name:
        return Response(
            {"error": "Last name is required."},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not email:
        return Response(
            {"error": "Email address is required."},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return Response(
            {"error": "Please enter a valid email address."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # -----------------------------
    # Company
    # -----------------------------

    user_company = request.user.company

    if not user_company:
        return Response(
            {"error": "Your account is not associated with a company."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # -----------------------------
    # Duplicate email
    # -----------------------------

    if User.objects.filter(
        email__iexact=email,
        company=user_company
    ).exists():
        return Response(
            {
                "error": f"An employee account with email '{email}' already exists in this company."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # -----------------------------
    # Mobile validation
    # -----------------------------

    if mobile and not re.match(r"^[6-9]\d{9}$", mobile):
        return Response(
            {
                "error": "Mobile number must be a valid 10-digit number starting with 6, 7, 8, or 9."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # -----------------------------
    # Password validation
    # -----------------------------

    if not password:
        return Response(
            {"error": "Password is required."},
            status=status.HTTP_400_BAD_REQUEST
        )

    if len(password) < 8:
        return Response(
            {"error": "Password must be at least 8 characters long."},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not re.search(r"[A-Z]", password):
        return Response(
            {"error": "Password must contain at least one uppercase letter."},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not re.search(r"[a-z]", password):
        return Response(
            {"error": "Password must contain at least one lowercase letter."},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not re.search(r"\d", password):
        return Response(
            {"error": "Password must contain at least one number."},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return Response(
            {
                "error": "Password must contain at least one special character."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # -----------------------------
    # Role
    # -----------------------------

    requested_role = request.data.get("role", "user")

    assigned_role = (
        requested_role
        if requested_role in ["user", "project_lead"]
        else "user"
    )

    # -----------------------------
    # Team
    # -----------------------------

    team = None
    team_id = request.data.get("team")

    if team_id not in ["", "null", None]:
        try:
            team = Team.objects.get(
                id=team_id,
                company=user_company,
                status__iexact="active"
            )

        except (Team.DoesNotExist, ValueError):
            return Response(
                {
                    "error": "Selected Team is invalid or does not exist."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    # -----------------------------
    # Build serializer data
    # -----------------------------

    data = {
        "username": email,
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "mobile": mobile,
        "role": assigned_role,
    }

    if team:
        data["team"] = team.id

    # Profile picture
    profile_picture = request.FILES.get("profile_picture")

    if profile_picture:
        data["profile_picture"] = profile_picture

    # -----------------------------
    # Serializer
    # -----------------------------

    serializer = UserSerializer(data=data)

    if not serializer.is_valid():
        print(
            "CREATE EMPLOYEE SERIALIZER ERRORS:",
            serializer.errors
        )

        err_msgs = []

        for field, errs in serializer.errors.items():
            field_name = field.replace("_", " ").title()

            if isinstance(errs, list):
                err_msgs.append(
                    f"{field_name}: {' '.join(str(e) for e in errs)}"
                )
            else:
                err_msgs.append(
                    f"{field_name}: {errs}"
                )

        return Response(
            {
                "error": (
                    " | ".join(err_msgs)
                    if err_msgs
                    else "Employee validation failed."
                )
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # -----------------------------
    # Create employee
    # -----------------------------

    with transaction.atomic():

        user = serializer.save(
            company=user_company,
            team=team
        )

        user.set_password(password)
        user.role = assigned_role
        user.is_staff = False
        user.save()

    return Response(
        {
            "message": "Employee created successfully",
            "user": UserSerializer(user).data
        },
        status=status.HTTP_201_CREATED
    )



@api_view(["POST"])
@permission_classes([AllowAny])
def Login(request):

    email = str(request.data.get("email", "")).strip().lower()
    password = request.data.get("password", "")

    # Required fields
    if not email or not password:
        return Response(
            {
                "error": "Email and password are required."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # Authenticate using email as username
    user = authenticate(
        username=email,
        password=password
    )

    # Wrong email OR wrong password
    if user is None:
        return Response(
            {
                "error": "Invalid email or password."
            },
            status=status.HTTP_401_UNAUTHORIZED
        )

    # Account disabled
    if not user.is_active:
        return Response(
            {
                "error": "Account disabled."
            },
            status=status.HTTP_403_FORBIDDEN
        )

    # Generate JWT tokens
    refresh = RefreshToken.for_user(user)

    return Response(
        {
            "message": "Login successful.",

            "user": {
                "id": user.id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "role": user.role,

                "company_id": (
                    user.company.id
                    if user.company
                    else None
                ),

                "company_name": (
                    user.company.company_name
                    if user.company
                    else None
                ),

                "company_code": (
                    user.company.company_code
                    if user.company
                    else None
                ),

                "profile_picture": (
                    user.profile_picture.url
                    if user.profile_picture
                    else None
                ),
            },

            "role": user.role,
            "id": user.id,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        },
        status=status.HTTP_200_OK
    )

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    try:
        refresh_token = request.data.get("refresh")
        token = RefreshToken(refresh_token)
        token.blacklist()
        return Response({"message": "Logged out successfully"})
    except Exception:
        return Response({"error": "Invalid token"}, status=400)
    
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def current_user(request):
    serializer = UserSerializer(request.user,context={"request": request})
    return Response(serializer.data, status=status.HTTP_200_OK)



# @api_view(["GET"])
# @permission_classes([IsAuthenticated])
# def Get_Users(request):

#     users = User.objects.filter(role="user",is_active=True,company=request.user.company)

#     response_data = []

#     for user in users:

#         tasks = Task.objects.filter(
#             company=request.user.company,
#             assigned_to=user
#         )

#         date = request.GET.get("date")

#         if date:
#             tasks = tasks.filter(due_date=date)

#         if tasks.exists():

#             for task in tasks:

#                 response_data.append({
#                     "user_id": user.id,
#                     "user_name": user.first_name or user.username,
#                     "avatar": user.profile_picture.url if user.profile_picture else None,

#                     "task_name": task.task_name,
#                     "due_date": task.due_date.strftime("%Y-%m-%d") if task.due_date else "-",
#                     "status": task.status,
#                     "working_hours": f"{task.working_hours}h",
#                     "priority": task.priority,
#                 })

#         else:

#             response_data.append({
#                 "user_id": user.id,
#                 "user_name": user.first_name or user.username,
#                 "avatar": user.profile_picture.url if user.profile_picture else None,

#                 "task_name": "No Task Assigned",
#                 "due_date": "-",
#                 "status": "Pending",
#                 "working_hours": "0h",
#                 "priority": "Low",
#             })

#     return Response(
#         response_data,
#         status=status.HTTP_200_OK
#     )

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def Get_Users(request):
    team_id = request.query_params.get("team_id") or request.query_params.get("team")

    if request.user.role in ("admin", "super_admin"):
        users = User.objects.filter(
            company=request.user.company,
            is_active=True
        ).exclude(role="admin").select_related("company", "team")
        if team_id and str(team_id).lower() != "all":
            users = users.filter(team_id=team_id)
    else:
        if request.user.team:
            users = User.objects.filter(
                company=request.user.company,
                team=request.user.team,
                is_active=True
            ).exclude(role="admin").select_related("company", "team")
        else:
            users = User.objects.filter(
                id=request.user.id,
                company=request.user.company,
                is_active=True
            ).select_related("company", "team")

    serializer = UserSerializer(users, many=True)

    return Response(serializer.data, status=status.HTTP_200_OK)
    

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def Get_User_List(request):
    team_id = request.query_params.get("team_id") or request.query_params.get("team")

    if request.user.role in ("admin", "super_admin"):
        users = User.objects.filter(
            company=request.user.company,
            is_active=True
        ).exclude(
            role="admin"
        ).select_related("company", "team").order_by("first_name")
        if team_id and str(team_id).lower() != "all":
            users = users.filter(team_id=team_id)
    else:
        if request.user.team:
            users = User.objects.filter(
                company=request.user.company,
                team=request.user.team,
                is_active=True
            ).exclude(
                role="admin"
            ).select_related("company", "team").order_by("first_name")
        else:
            users = User.objects.filter(
                id=request.user.id,
                company=request.user.company,
                is_active=True
            ).select_related("company", "team").order_by("first_name")

    serializer = UserSerializer(users, many=True)

    data = [
        {
            "id": u["id"],
            "first_name": u["first_name"],
            "last_name": u["last_name"],
            "email": u["email"],
            "mobile": u["mobile"],
            "profile_picture": u["profile_picture"],
            "role": u["role"],
        }
        for u in serializer.data
    ]

    return Response(
        data,
        status=status.HTTP_200_OK
    )




@api_view(["PUT"])
@permission_classes([IsAuthenticated, IsAdminRole])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def update_employee(request, user_id):
    try:
        user = User.objects.get(
            id=user_id,
            company=request.user.company
        )
    except User.DoesNotExist:
        return Response(
            {"error": "Employee not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = UserSerializer(
        user,
        data=request.data,
        partial=True
    )

    if serializer.is_valid():

        role = request.data.get("role")

        if role and role not in ["user", "project_lead"]:
            return Response(
                {"error": "Invalid role."},
                status=status.HTTP_400_BAD_REQUEST
            )

        employee = serializer.save()

        if role:
            employee.role = role

        if "password" in request.data and request.data["password"]:
            employee.set_password(request.data["password"])

        employee.save()

        return Response(
            {
                "message": "Employee updated successfully.",
                "data": UserSerializer(employee).data
            },
            status=status.HTTP_200_OK
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)




@api_view(["DELETE"])
@permission_classes([IsAuthenticated, IsAdminRole])
def delete_user(request, id):
    try:
        user = get_object_or_404(User, id=id,company=request.user.company)


        user.is_active=False
        user.save(update_fields=["is_active"])

        return Response(
            {"message": "User deleted successfully"},
            status=status.HTTP_200_OK
        )

    except IntegrityError as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def active_members_count(request):
    count = User.objects.filter(is_active=True,company=request.user.company).count()

    return Response({
        "active_members": count
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def Get_Single_User(request, id):
    user = get_object_or_404(User, id=id,is_active=True,company=request.user.company)
    serializer = UserSerializer(user)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsAdminOrProjectLead])
def user_dropdown(request):
    users = User.objects.filter(role="user",is_active=True,company=request.user.company)

    data = [
        {
            "user_id": user.id,
            "user_name": user.first_name
        }
        for user in users
    ]

    return Response(data)



@api_view(["POST"])
@permission_classes([IsAuthenticated,IsAdminRole])
def Add_Projects(request):
    data = request.data.copy()
    mapping = {
        'project_name': 'project_name',
        'description': 'description',
        'assigned_to': 'assigned_to',
        'team' : 'team',
        'due_date': 'due_date',
        'est_hour': 'est_hour',
        'priority': 'priority',
        'links': 'links',
        'status': 'status'
    }
    
    formatted_data = {mapping.get(k, k): v for k, v in data.items()}
    
    # Ensure assigned_to is a list of IDs for the serializer if it's currently a single ID
    if 'assigned_to' in formatted_data:
        val = formatted_data['assigned_to']
        if not isinstance(val, list):
            # If it's a comma-separated string from FormData, split it
            if isinstance(val, str) and ',' in val:
                formatted_data['assigned_to'] = [x.strip() for x in val.split(',')]
            else:
                formatted_data['assigned_to'] = [val]

    # Handle attachments separately if not already in formatted_data
    if 'attachments' in request.FILES:
        # If model only supports one file, take the first one
        attachments = request.FILES.getlist('attachments')
        if attachments:
            formatted_data['attachments'] = attachments[0]


    team_id = formatted_data.get("team")

    if team_id:
        if not Team.objects.filter(
            id=team_id,
            company=request.user.company,
            status__iexact="active"
        ).exists():
            return Response(
                {"error": "Selected team is invalid or inactive."},
                status=status.HTTP_400_BAD_REQUEST
            )
    assigned_users = formatted_data.get("assigned_to", [])

    for user_id in assigned_users:
        if not User.objects.filter(
            id=user_id,
            company=request.user.company
        ).exists():
            return Response(
                {"error": "Invalid user selected."},
                status=status.HTTP_400_BAD_REQUEST
            )


    serializer = ProjectSerializer(data=formatted_data)
    if serializer.is_valid():

        project = serializer.save(
            active="View",
            company=request.user.company
        )

        for user in project.assigned_to.all():

            # In-app notification
            try:
                send_notification(
                    company=request.user.company,
                    user=user,
                    title="Project Assigned",
                    message=f"You have been assigned to project '{project.project_name}'.",
                    notification_type="project",
                )
            except Exception as e:
                print(
                    f"Project notification failed for {user.username}: {e}"
                )
            # Email notification
            try:
                full_name = f"{user.first_name} {user.last_name}".strip()
                send_email_notification(
                    company=request.user.company,
                    subject="New Project Assigned",
                    message=(
                        f"Hello {full_name or user.username},\n\n"
                        f"You have been assigned to a new project.\n\n"
                        f"Team: "
                        f"{project.team.team_name if project.team else 'Not Assigned'}\n"
                        f"Project: {project.project_name}\n"
                        f"Priority: {project.priority}\n"
                        f"Due Date: {project.due_date}\n\n"
                        f"Description:\n{project.description}\n\n"
                        f"Please log in to Work Track Management "
                        f"to view the project details."
                    ),
                    recipient_email=user.email,
                )
            except Exception as e:
                print(
                    f"Email sending failed for {user.email}: {e}"
                )
        return Response(
            {
                "message": "Project added successfully",
                "project": ProjectSerializer(project).data
            },
            status=status.HTTP_201_CREATED
        )

        
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def View_Projects(request):

    team_filter = request.query_params.get("team_id") or request.query_params.get("team")

    if request.user.role in ("admin", "super_admin"):
        projects = Project.objects.filter(company=request.user.company).order_by("-id")
        if team_filter and str(team_filter).lower() != "all":
            projects = projects.filter(team_id=team_filter)
    elif request.user.team:
        projects = Project.objects.filter(
            company=request.user.company
        ).filter(
            Q(team=request.user.team) | Q(assigned_to=request.user)
        ).distinct().order_by("-id")
    else:
        projects = Project.objects.filter(
            company=request.user.company,
            assigned_to=request.user
        ).order_by("-id")

    projects = projects.select_related(
        "company", "team"
    ).prefetch_related(
        "assigned_to",
        "tasks",
        "tasks__assigned_to",
        "tasks__assigned_by",
        "tasks__team",
        "tasks__sessions"
    )

    serializer = ProjectSerializer(projects, many=True)
    data = serializer.data

    status_filter = request.query_params.get("status")

    if status_filter and status_filter != "All":
        data = [
            project
            for project in data
            if project["status"] == status_filter
        ]

    return Response({
        "message": "success",
        "count": len(data),
        "projects": data
    }, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def View_Single_Project(request, project_id):
    if request.user.role in ("admin", "super_admin"):
        project = get_object_or_404(
            Project,
            id=project_id,
            company=request.user.company
        )
    elif request.user.team:
        project = get_object_or_404(
            Project.objects.filter(
                Q(team=request.user.team) | Q(assigned_to=request.user)
            ).distinct(),
            id=project_id,
            company=request.user.company
        )
    else:
        project = get_object_or_404(
            Project,
            id=project_id,
            assigned_to=request.user,
            company=request.user.company
        )
    serializer = ProjectSerializer(project)
    return Response({
        'message': 'success', 
        'project': serializer.data
    }, status=status.HTTP_200_OK)


@api_view(["GET", "POST", "PUT", "PATCH"])
@permission_classes([IsAuthenticated,IsAdminRole])
def update_projects(request, id):
    project = get_object_or_404(Project, id=id,company=request.user.company)

    if request.method == 'GET':
        serializer = ProjectSerializer(project)
        return Response(serializer.data, status=status.HTTP_200_OK)


    data = request.data.copy()
    mapping = {
        'project_name': 'project_name',
        'description': 'description',
        'team' : 'team',
        'due_date': 'due_date',
        'est_hr': 'est_hour',
        'priority': 'priority',
        'links': 'links',
        'status': 'status',
        'assigned_to': 'assigned_to'
    }
    formatted_data = {mapping.get(k, k): v for k, v in data.items()}
    if 'assigned_to' in formatted_data and not isinstance(formatted_data['assigned_to'], list):
        formatted_data['assigned_to'] = [formatted_data['assigned_to']]

    team_id = formatted_data.get("team")

    if team_id:
        if not Team.objects.filter(
            id=team_id,
            company=request.user.company,
            status__iexact="active"
        ).exists():
            return Response(
                {"error": "Selected team is invalid or inactive."},
                status=status.HTTP_400_BAD_REQUEST
            )

    assigned_users = formatted_data.get("assigned_to", [])

    for user_id in assigned_users:
        if not User.objects.filter(
            id=user_id,
            company=request.user.company
        ).exists():
            return Response(
                {"error": "Invalid user selected."},
                status=status.HTTP_400_BAD_REQUEST
            )

    serializer = ProjectSerializer(project, data=formatted_data, partial=(request.method in ['PATCH', 'POST']))
    if serializer.is_valid():
        project = serializer.save()

        if "attachments" in request.FILES:
            project.attachments = request.FILES["attachments"]
            project.save()

        for user in project.assigned_to.all():

            # In-app notification
            try:
                send_notification(
                    company=request.user.company,
                    user=user,
                    title="Project Updated",
                    message=f"The project '{project.project_name}' has been updated.",
                    notification_type="project",
                )
            except Exception as e:
                print(
                    f"Project update notification failed "
                    f"for {user.username}: {e}"
                )

            # Email notification
            try:
                full_name = f"{user.first_name} {user.last_name}".strip()

                send_email_notification(
                    company=request.user.company,
                    subject="Project Updated",
                    message=(
                        f"Hello {full_name or user.username},\n\n"
                        f"A project assigned to you has been updated.\n\n"
                        f"Team: "
                        f"{project.team.team_name if project.team else 'Not Assigned'}\n"
                        f"Project: {project.project_name}\n"
                        f"Priority: {project.priority}\n"
                        f"Status: {project.status}\n"
                        f"Due Date: {project.due_date}\n\n"
                        f"Description:\n{project.description}\n\n"
                        f"Please log in to Work Track Management "
                        f"to view the latest project details."
                    ),
                    recipient_email=user.email,
                )

            except Exception as e:
                print(
                    f"Email sending failed for {user.email}: {e}"
                )

        return Response(
            {
                "message": "Successfully updated",
                "project": ProjectSerializer(project).data
            },
            status=status.HTTP_200_OK
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



@api_view(["DELETE"])
@permission_classes([IsAuthenticated, IsAdminRole])
def Delete_Projects(request, id):

    project = get_object_or_404(
        Project,
        id=id,
        company=request.user.company
    )

    project_name = project.project_name

    # Save assigned users before deletion
    assigned_users = list(project.assigned_to.all())

    # Delete project FIRST
    project.delete()

    # Send notifications AFTER successful deletion
    for user in assigned_users:

        try:
            send_notification(
                company=request.user.company,
                user=user,
                title="Project Deleted",
                message=f"The project '{project_name}' has been deleted.",
                notification_type="project",
            )
        except Exception as e:
            print(
                f"Project deletion notification failed "
                f"for {user.username}: {e}"
            )

    return Response(
        {
            "message": "Successfully deleted"
        },
        status=status.HTTP_200_OK
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def total_projects(request):
    total = Project.objects.filter(company=request.user.company,active="View").count()
    return Response({"total_projects": total}, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def total_projects_by_user(request):
    # Filters projects where the logged-in user is assigned
    count = Project.objects.filter(company=request.user.company,assigned_to=request.user).count()
    return Response({"total_projects": count}, status=status.HTTP_200_OK)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def project_summary_table(request):

    if request.user.role == "admin":
        projects = Project.objects.filter(company=request.user.company).order_by("-id")
    else:
        projects = Project.objects.filter(
            company=request.user.company,
            assigned_to=request.user
        ).order_by("-id")

    # Filters
    project_name = request.GET.get("project")
    status_filter = request.GET.get("status")
    deadline = request.GET.get("date")
    user_id = request.GET.get("user")

    if project_name:
        projects = projects.filter(
            project_name=project_name
        )

    if deadline:
        projects = projects.filter(
            due_date=deadline
        )

    if user_id:
        projects = projects.filter(
            assigned_to__id=user_id
        )

    data = []

    for project in projects:

        total_tasks = project.tasks.count()

        completed_tasks = project.tasks.filter(
            status="Completed"
        ).count()

        in_progress_tasks = project.tasks.filter(
            status="In Progress"
        ).count()

        completion_percent = 0

        if total_tasks > 0:
            completion_percent = round(
                (completed_tasks / total_tasks) * 100
            )

        if total_tasks == 0:
            project_status = "Pending"
        elif completed_tasks == total_tasks:
            project_status = "Task Done"
        elif in_progress_tasks > 0:
            project_status = "In Progress"
        else:
            project_status = "To Do"

        # Status Filter
        if status_filter and project_status != status_filter:
            continue

        data.append({
            "id": project.id,
            "project_name": project.project_name,
            "task_count": total_tasks,
            "deadline": project.due_date,
            "status": project_status,
            "completed": completion_percent
        })

    return Response({
        "count": len(data),
        "projects": data
    })

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def project_dropdown(request):

    if request.user.role == "admin":
        projects = Project.objects.filter(
            company=request.user.company
        )
    else:
        projects = Project.objects.filter(
            company=request.user.company,
            assigned_to=request.user
        )

    projects = projects.values(
        "id",
        "project_name",
        "team_id",
        "team__team_name"
    )

    result = [
        {
            "id": p["id"],
            "project_name": p["project_name"],
            "team": p["team_id"],
            "team_id": p["team_id"],
            "team_name": p["team__team_name"],
        }
        for p in projects
    ]

    return Response(result)




@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminOrProjectLead])
def Add_Tasks(request):

    data = request.data.copy()

    mapping = {
        "task_name": "task_name",
        "priority": "priority",
        "project": "project",
        "team": "team",
        "due_date": "due_date",
        "status": "status",
        "working_hours": "working_hours",
        "description": "description",
        "assigned_to": "assigned_to",
    }

    formatted_data = {
        mapping.get(k, k): v
        for k, v in data.items()
    }

    # -----------------------------------
    # Validate project
    # -----------------------------------

    project = Project.objects.filter(
        id=request.data.get("project"),
        company=request.user.company
    ).first()

    if not project:
        return Response(
            {"error": "Invalid project."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # -----------------------------------
    # Validate team
    # -----------------------------------

    team_id = request.data.get("team")

    if team_id:

        team = Team.objects.filter(
            id=team_id,
            company=request.user.company
        ).first()

        if not team:
            return Response(
                {"error": "Invalid team."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if project.team_id != team.id:
            return Response(
                {
                    "error": "Selected team does not belong to this project."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    # -----------------------------------
    # Validate task data
    # -----------------------------------

    serializer = TaskSerializer(data=formatted_data)

    if not serializer.is_valid():

        error_messages = []

        for field, errors in serializer.errors.items():

            field_name = field.replace("_", " ").title()

            if isinstance(errors, list):
                error_messages.append(
                    f"{field_name}: {' '.join(str(error) for error in errors)}"
                )
            else:
                error_messages.append(
                    f"{field_name}: {str(errors)}"
                )

        return Response(
            {
                "error": (
                    " | ".join(error_messages)
                    if error_messages
                    else "Task validation failed."
                )
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # -----------------------------------
    # Validate assigned users
    # -----------------------------------

    assigned_ids = request.data.get("assigned_to", [])

    if not isinstance(assigned_ids, list):
        assigned_ids = [assigned_ids]

    users = User.objects.filter(
        id__in=assigned_ids,
        company=request.user.company
    )

    if users.count() != len(assigned_ids):
        return Response(
            {"error": "Invalid employee selection."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # ===================================
    # CREATE TASK
    # ===================================

    task = serializer.save(
        company=request.user.company
    )

    # ===================================
    # NOTIFICATION + EMAIL
    # These must NOT break task creation
    # ===================================

    notification_errors = []
    email_errors = []

    for user in task.assigned_to.all():

        # -----------------------------------
        # In-app notification
        # -----------------------------------

        try:

            send_notification(
                company=request.user.company,
                user=user,
                title="Task Assigned",
                message=f"You have been assigned a new task: {task.task_name}",
                notification_type="task"
            )

        except Exception as e:

            # Log technical error in backend
            print(
                f"Notification failed for {user.email}: {e}"
            )

            notification_errors.append(
                f"Notification could not be sent to {user.email}"
            )

        # -----------------------------------
        # Email notification
        # -----------------------------------

        try:

            full_name = (
                f"{user.first_name} {user.last_name}"
            ).strip()

            send_email_notification(
                company=request.user.company,
                subject="New Task Assigned",
                message=(
                    f"Hello {full_name or user.username},\n\n"
                    f"You have been assigned a new task.\n\n"
                    f"Team: "
                    f"{task.team.team_name if task.team else 'Not Assigned'}\n"
                    f"Task: {task.task_name}\n"
                    f"Project: {task.project.project_name}\n"
                    f"Priority: {task.priority}\n"
                    f"Due Date: {task.due_date}\n\n"
                    f"Please log in to Work Track Management "
                    f"to view the task."
                ),
                recipient_email=user.email
            )

        except Exception as e:

            # Log technical error
            print(
                f"Email sending failed for {user.email}: {e}"
            )

            email_errors.append(
                f"Email could not be sent to {user.email}"
            )

    # ===================================
    # TASK CREATED SUCCESSFULLY
    # ===================================

    return Response(
        {
            "message": "Task successfully added",
            "data": serializer.data,

            # Notification status
            "notification_success": len(notification_errors) == 0,
            "notification_errors": notification_errors,

            # Email status
            "email_success": len(email_errors) == 0,
            "email_errors": email_errors,
        },
        status=status.HTTP_201_CREATED
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def View_Tasks(request):

    query = request.GET.get("search", "").strip()
    filter_date = request.GET.get("date", "").strip()
    filter_status = request.GET.get("status", "").strip()
    team_filter = request.GET.get("team_id") or request.GET.get("team")

    # ==========================================
    # BASE TASK QUERY
    # ==========================================

    if request.user.role in ("admin", "super_admin"):
        tasks = Task.objects.filter(
            company=request.user.company
        ).order_by("-id")
        if team_filter and str(team_filter).lower() != "all":
            tasks = tasks.filter(Q(team_id=team_filter) | Q(project__team_id=team_filter)).distinct()
    elif request.user.team:
        tasks = Task.objects.filter(
            company=request.user.company
        ).filter(
            Q(team=request.user.team) |
            Q(project__team=request.user.team) |
            Q(assigned_to=request.user)
        ).distinct().order_by("-id")
    else:
        tasks = Task.objects.filter(
            company=request.user.company,
            assigned_to=request.user
        ).order_by("-id")

    # ==========================================
    # SEARCH
    # ==========================================

    if query:
        tasks = tasks.filter(
            Q(task_name__icontains=query) |
            Q(priority__icontains=query) |
            Q(status__icontains=query) |
            Q(description__icontains=query)
        )

    # ==========================================
    # DATE FILTER
    # ==========================================

    if filter_date:
        tasks = tasks.filter(
            due_date=filter_date
        )

    # ==========================================
    # STATUS FILTER
    # ==========================================

    if filter_status and filter_status.lower() != "all":
        tasks = tasks.filter(
            status__iexact=filter_status
        )

    # ==========================================
    # SERIALIZE
    # ==========================================

    tasks = tasks.select_related(
        "company", "team", "project", "assigned_by"
    ).prefetch_related(
        "assigned_to",
        "sessions",
        "team"
    )

    serializer = TaskSerializer(tasks, many=True)

    return Response({
        "count": len(serializer.data),
        "tasks": serializer.data
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def View_User_Tasks(request):

    query = request.GET.get("search", "").strip()

    tasks = Task.objects.filter(
        company=request.user.company,
        assigned_to=request.user
    )

    # Only unfinished tasks
    tasks = tasks.exclude(
        status__iexact="Completed"
    ).order_by("-id")

    if query:
        tasks = tasks.filter(
            Q(task_name__icontains=query) |
            Q(priority__icontains=query) |
            Q(status__icontains=query) |
            Q(description__icontains=query)
        )

    tasks = tasks.select_related(
        "company", "team", "project", "assigned_by"
    ).prefetch_related(
        "assigned_to",
        "sessions",
        "team"
    )

    serializer = TaskSerializer(tasks, many=True)

    return Response(
        {
            "count": tasks.count(),
            "tasks": serializer.data
        },
        status=status.HTTP_200_OK
    )



from django.http import JsonResponse
from django.db.models import Q
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def View_Single_Task(request, task_id):
    if request.user.role in ("admin", "super_admin"):
        task = get_object_or_404(Task, id=task_id, company=request.user.company)
    elif request.user.team:
        task = get_object_or_404(
            Task.objects.filter(
                Q(team=request.user.team) |
                Q(project__team=request.user.team) |
                Q(assigned_to=request.user)
            ).distinct(),
            id=task_id,
            company=request.user.company
        )
    else:
        task = get_object_or_404(
            Task,
            id=task_id,
            assigned_to=request.user,
            company=request.user.company
        )
    serializer = TaskSerializer(task)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["GET", "POST", "PUT", "PATCH"])
@permission_classes([IsAuthenticated, IsAdminOrProjectLead])
def Update_Tasks(request, id):

    task = get_object_or_404(
        Task,
        id=id,
        company=request.user.company
    )

    if request.method == "GET":
        serializer = TaskSerializer(task)
        return Response(serializer.data, status=status.HTTP_200_OK)

    data = request.data.copy()

    mapping = {
        "project": "project",
        "task-name": "task_name",
        "team" : "team",
        "priority": "priority",
        "due-date": "due_date",
        "status": "status",
        "description": "description",
        "working-hours": "working_hours",
        "discussion": "discussion",
        "links": "links",
        "attachments": "attachments",
        "assigned_to": "assigned_to",
    }

    formatted_data = {
        mapping.get(k, k): v
        for k, v in data.items()
    }

    if "assigned_to" in request.data:
        formatted_data["assigned_to"] = request.data.get("assigned_to")

    project_id = request.data.get("project")

    if project_id:
        project = Project.objects.filter(
            id=project_id,
            company=request.user.company
        ).first()

        if not project:
            return Response(
                {"error": "Invalid project."},
                status=status.HTTP_400_BAD_REQUEST
            )

    serializer = TaskSerializer(
        task,
        data=formatted_data,
        partial=(request.method in ["PATCH", "POST"])
    )

    if serializer.is_valid():

        # Validate assigned users belong to the same company
        assigned_ids = request.data.get("assigned_to", [])

        if not isinstance(assigned_ids, list):
            assigned_ids = [assigned_ids]

        if assigned_ids:

            users = User.objects.filter(
                id__in=assigned_ids,
                company=request.user.company
            )

            if users.count() != len(assigned_ids):
                return Response(
                    {"error": "Invalid employee selection."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        team_id = request.data.get("team")

        if team_id:
            team = Team.objects.filter(
                id=team_id,
                company=request.user.company
            ).first()

            if not team:
                return Response(
                    {"error": "Invalid team."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if project and project.team_id != team.id:
                return Response(
                    {
                        "error" : "Selected team does not belong to this project."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

        task = serializer.save()

        # Notify assigned users
# Notify assigned users
    notification_errors = []
    email_errors = []


    for user in task.assigned_to.all():

        # -----------------------------------
        # In-app notification
        # -----------------------------------

        try:

            send_notification(
                company=request.user.company,
                user=user,
                title="Task Updated",
                message=(
                    f"The task '{task.task_name}' has been updated. "
                    f"Please review the latest changes."
                ),
                notification_type="task",
            )

        except Exception as e:

            print(
                f"Notification failed for {user.email}: {e}"
            )

            notification_errors.append(
                f"Notification could not be sent to {user.email}"
            )

        # -----------------------------------
        # Email notification
        # -----------------------------------

        try:

            full_name = (
                f"{user.first_name} {user.last_name}"
            ).strip()

            send_email_notification(
                company=request.user.company,
                subject="Task Updated",
                message=(
                    f"Hello {full_name or user.username},\n\n"
                    f"A task assigned to you has been updated.\n\n"
                    f"Team: "
                    f"{task.team.team_name if task.team else 'Not Assigned'}\n"
                    f"Task: {task.task_name}\n"
                    f"Project: {task.project.project_name}\n"
                    f"Priority: {task.priority}\n"
                    f"Status: {task.status}\n"
                    f"Due Date: {task.due_date}\n\n"
                    f"Description:\n{task.description}\n\n"
                    f"Please log in to Work Track Management "
                    f"to review the latest task details."
                ),
                recipient_email=user.email
            )

        except Exception as e:

            print(
                f"Email sending failed for {user.email}: {e}"
            )

            email_errors.append(
                f"Email could not be sent to {user.email}"
            )

        return Response(
            {
                "message": "Task updated successfully",
                "data": TaskSerializer(task).data,
            },
            status=status.HTTP_200_OK,
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated,IsAdminOrProjectLead])
def Delete_Task(request, id):
    task = get_object_or_404(Task, id=id,company=request.user.company)
    

    for user in task.assigned_to.all():
    
        send_notification(
            company=request.user.company,
            user=user,
            title="Task Deleted",
            message=f"The task '{task.task_name}' has been deleted.",
            notification_type="task",
        )
    task.delete()


    return Response(
        {
            'message': 'Task deleted successfully.'
        },
        status=status.HTTP_200_OK,
    )

#total task
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def total_tasks(request):
    total = Task.objects.filter(
        company=request.user.company
    ).count()
    return Response({"total_tasks": total}, status=status.HTTP_200_OK)





@api_view(["GET"])
@permission_classes([IsAuthenticated])
def total_tasks_summary(request):
    # Get tasks assigned to the logged-in user
    user_tasks = Task.objects.filter(company=request.user.company,assigned_to=request.user)

    total = user_tasks.count()
    todo = user_tasks.filter(status__iexact="To Do").count()
    inprogress = user_tasks.filter(status__iexact="In Progress").count()
    pending = user_tasks.filter(status__iexact="Pending").count()
    taskdone = user_tasks.filter(status__iexact="Task Done").count()
    completed = user_tasks.filter(status__iexact="Completed").count()
    
    unfinished = total - completed

    return Response({
        "total_tasks": total,
        "todo_tasks": todo,
        "inprogress_tasks": inprogress,
        "pending_tasks": pending,
        "taskdone_tasks": taskdone,
        "completed_tasks": completed,
        "unfinished_tasks": unfinished
    }, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def admin_tasks_summary(request):
    if request.user.role in ("admin", "super_admin"):
        all_tasks = Task.objects.filter(
            company=request.user.company
        )
    elif request.user.team:
        all_tasks = Task.objects.filter(
            company=request.user.company
        ).filter(
            Q(team=request.user.team) |
            Q(project__team=request.user.team) |
            Q(assigned_to=request.user)
        ).distinct()
    else:
        all_tasks = Task.objects.filter(
            company=request.user.company,
            assigned_to=request.user
        )

    total = all_tasks.count()
    todo = all_tasks.filter(status__iexact="To Do").count()
    inprogress = all_tasks.filter(status__iexact="In Progress").count()
    pending = all_tasks.filter(status__iexact="Pending").count()
    # taskdone = all_tasks.filter(status__iexact="Task Done").count()
    completed = all_tasks.filter(status__iexact="Completed").count()
    
    return Response({
        "total_tasks": total,
        "todo_tasks": todo,
        "inprogress_tasks": inprogress,
        "pending_tasks": pending,
        # "taskdone_tasks": taskdone,
        "completed_tasks": completed
    }, status=status.HTTP_200_OK)






@api_view(["GET"])
@permission_classes([IsAuthenticated])
def completed_task_count(request):
    count = Task.objects.filter(status="Completed").count()

    return Response({
        "completed_tasks": count
    }, status=status.HTTP_200_OK)








# def total_tasks_by_users(request, username):
#     total_task = Tasks.objects.filter(
#         Assigned_By__iexact=username
#     ).count()
#
#     return JsonResponse({
#         "employee": username,
#         "total_tasks": total_task
#     })





@api_view(["GET"])
@permission_classes([IsAuthenticated])
def efficiency_view(request):

    total_tasks = Task.objects.filter(
        company=request.user.company
    ).count()

    completed_tasks = Task.objects.filter(
        company=request.user.company,
        status="Completed"
    ).count()

    efficiency = (
        (completed_tasks / total_tasks) * 100
        if total_tasks > 0 else 0
    )

    return Response({
        "efficiency": round(efficiency, 1)
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def activity_view(request):

    total_users = User.objects.filter(
        company=request.user.company
    ).count()

    active_users = User.objects.filter(
        company=request.user.company,
        is_active=True
    ).count()

    activity = (
        (active_users / total_users) * 100
        if total_users > 0 else 0
    )

    return Response({
        "activity": round(activity, 1)
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def task_status_count(request):

    return Response({
        "todo": Task.objects.filter(
            company=request.user.company,
            status="To Do"
        ).count(),

        "in_progress": Task.objects.filter(
            company=request.user.company,
            status="In Progress"
        ).count(),

        "pending": Task.objects.filter(
            company=request.user.company,
            status="Pending"
        ).count(),

        "task_done": Task.objects.filter(
            company=request.user.company,
            status="Completed"
        ).count(),
    })

#assigned to dropdown
@api_view(["GET"])
@permission_classes([IsAuthenticated, IsAdminOrProjectLead])
def assigned_users(request):

    users = User.objects.filter(
        company=request.user.company,
        is_active=True
    ).values(
        "id",
        "username"
    )

    return Response(users)

#STATUS filter api
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def task_statuses(request):
    return Response([
        "To Do",
        "In Progress",
        "Pending",
        "Completed"
    ])


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_efficiency(request):

    selected_date = request.GET.get("date")

    if selected_date:
        selected_date = datetime.strptime(
            selected_date,
            "%Y-%m-%d"
        ).date()
    else:
        selected_date = timezone.now().date()

    users_data = []

    for user in User.objects.filter(company=request.user.company,is_active=True, role="user"):

        total_duration = TaskTime.objects.filter(
            company=request.user.company,
            user=user,
            start_time__date=selected_date,
            duration__isnull=False
        ).aggregate(
            total=Sum("duration")
        )["total"] or timedelta()
        
        total_seconds = int(total_duration.total_seconds())

        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60

        efficiency = min(
            round((total_seconds / (8 * 60 * 60)) * 100, 1),
            100
        )

        users_data.append({
            "user": user.first_name,
            "email": user.email,
            "worked_hours": f"{hours}h {minutes}m",
            "efficiency": efficiency
        })

    return Response(users_data)




@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_idle_time(request):

    users_data = []

    for user in User.objects.filter(company=request.user.company,is_active=True):

        sessions = TaskTime.objects.filter(
            company=request.user.company,
            user=user,
            start_time__date=timezone.now().date(),
            end_time__isnull=False
        )

        total_seconds = 0

        for session in sessions:
            total_seconds += (
                session.end_time - session.start_time
            ).total_seconds()

        target_seconds = 8 * 60 * 60  # 8 hours

        idle_seconds = max(
            target_seconds - total_seconds,
            0
        )

        users_data.append({
            "user": user.username,
            "email": user.email,
            "idle_hours": round(idle_seconds / 3600, 2)
        })

    return Response(users_data)




@api_view(["GET"])
@permission_classes([IsAuthenticated])
def admin_dashboard_summary(request):
    # Optional: enforce admin role
    total_projects = Project.objects.filter(
        company=request.user.company
    ).count()

    total_tasks = Task.objects.filter(
        company=request.user.company
    ).count()

    completed_tasks = Task.objects.filter(
        company=request.user.company,
        status__iexact="Completed"
    ).count()

    active_members = User.objects.filter(
        company=request.user.company,
        is_active=True
    ).count()

    active_tasks = total_tasks - completed_tasks

    return Response({
        "total_projects": total_projects,
        "total_tasks": total_tasks,
        "active_tasks": active_tasks,
        "completed_tasks": completed_tasks,
        "active_members": active_members,
    }, status=status.HTTP_200_OK)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def employee_status_summary(request):
    user = request.user
    today = timezone.now().date()

    active_projects = Project.objects.filter(
        company=request.user.company,
        assigned_to=user,
        status="In Progress"
    ).count()

    task_in_progress = Task.objects.filter(
        company=request.user.company,
        assigned_to=user,
        status="In Progress"
    ).count()

    completed_tasks = Task.objects.filter(
        company=request.user.company,
        assigned_to=user,
        status="Task Done"
    ).count()

    today_sessions = TaskTime.objects.filter(
        company=request.user.company,
        user=user,
        start_time__date=today
    )

    worked_seconds = sum(
        [(s.duration or timedelta()).total_seconds() for s in today_sessions]
    )

    idle_seconds = max(0, 8 * 3600 - worked_seconds)  # assuming 8h workday

    return Response({
        "active_projects": active_projects,
        "task_in_progress": task_in_progress,
        "completed_tasks": completed_tasks,
        "idle_time_minutes": int(idle_seconds // 60),
    }, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def weekly_work_report(request):

    try:
        today = timezone.localdate()

        # Monday of current week
        start_of_week = today - timedelta(days=today.weekday())

        # Sunday of current week
        end_of_week = start_of_week + timedelta(days=6)

        sessions = TaskTime.objects.filter(
            company=request.user.company,
            user=request.user,
            start_time__date__gte=start_of_week,
            start_time__date__lte=end_of_week,
            end_time__isnull=False,
        ).order_by("start_time")

        # Monday -> Sunday
        days_map = {
            0: {"day": "Mon", "hours": 0},
            1: {"day": "Tue", "hours": 0},
            2: {"day": "Wed", "hours": 0},
            3: {"day": "Thu", "hours": 0},
            4: {"day": "Fri", "hours": 0},
            5: {"day": "Sat", "hours": 0},
            6: {"day": "Sun", "hours": 0},
        }

        for session in sessions:

            if not session.start_time or not session.end_time:
                continue

            duration = session.end_time - session.start_time

            hours = duration.total_seconds() / 3600

            weekday = session.start_time.astimezone(
                timezone.get_current_timezone()
            ).weekday()

            days_map[weekday]["hours"] += hours

        report = []

        for day in range(7):
            report.append({
                "day": days_map[day]["day"],
                "hours": round(days_map[day]["hours"], 2),
            })

        return Response(
            report,
            status=status.HTTP_200_OK
        )

    except Exception as e:

        return Response(
            {
                "error": str(e)
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def work_task_chart(request):
    try:
        today = timezone.now().date()
        start_date = today - timedelta(days=5)
        company = request.user.company

        chart_data = []
        total_work_seconds = 0
        total_task_seconds = 0

        for i in range(6):
            curr_date = start_date + timedelta(days=i)
            date_str = curr_date.strftime("%Y-%m-%d")

            work_sessions = WorkSession.objects.filter(
                company=company,
                work_date=curr_date
            )
            if request.user.role != "admin":
                work_sessions = work_sessions.filter(user=request.user)

            day_work_sec = 0
            for ws in work_sessions:
                if ws.total_work_time:
                    day_work_sec += ws.total_work_time.total_seconds()
                elif ws.clock_in and not ws.clock_out:
                    day_work_sec += (timezone.now() - ws.clock_in).total_seconds()

            task_times = TaskTime.objects.filter(
                company=company,
                start_time__date=curr_date
            )
            if request.user.role != "admin":
                task_times = task_times.filter(user=request.user)

            day_task_sec = 0
            for tt in task_times:
                if tt.duration:
                    day_task_sec += tt.duration.total_seconds()
                elif tt.start_time and tt.end_time:
                    day_task_sec += (tt.end_time - tt.start_time).total_seconds()

            total_work_seconds += day_work_sec
            total_task_seconds += day_task_sec

            work_hrs = round(day_work_sec / 3600, 1)
            task_hrs = round(day_task_sec / 3600, 1)
            billable_hrs = round(task_hrs * 0.8, 1)

            chart_data.append({
                "date": date_str,
                "work": work_hrs,
                "task": task_hrs,
                "billable": billable_hrs
            })

        at_work_hrs = round(total_work_seconds / 3600)
        task_spent_hrs = round(total_task_seconds / 3600)
        billable_hrs = round(task_spent_hrs * 0.8)

        return Response({
            "at_work_total": f"{at_work_hrs} hr",
            "task_spent_total": f"{task_spent_hrs} hr",
            "billable_total": f"{billable_hrs} hr",
            "chart_data": chart_data
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


from datetime import datetime
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_project_details(request):

    try:
        company = request.user.company
        user = request.user

        # ==========================================
        # DATE
        # ==========================================

        selected_date_str = request.GET.get("date")
        selected_date = None

        if selected_date_str:
            try:
                selected_date = datetime.strptime(
                    selected_date_str,
                    "%Y-%m-%d"
                ).date()
            except ValueError:
                selected_date = None

        # ==========================================
        # PROJECT RBAC
        # ==========================================

        if user.role == "admin":

            projects_qs = Project.objects.filter(
                company=company
            )

        else:

            # Project Lead / Employee
            # Only projects assigned to logged-in user

            projects_qs = Project.objects.filter(
                company=company,
                assigned_to=user
            )

        # ==========================================
        # TASK RBAC
        # ==========================================

        if user.role == "admin":

            tasks_qs = Task.objects.filter(
                company=company
            )

        elif user.role == "project_lead":

            # Project Lead can see ALL tasks
            # inside their own projects

            tasks_qs = Task.objects.filter(
                company=company,
                project__in=projects_qs
            )

        else:

            # Normal employee:
            # only tasks assigned to logged-in user
            # and belonging to their projects

            tasks_qs = Task.objects.filter(
                company=company,
                project__in=projects_qs,
                assigned_to=user
            )

        tasks_qs = tasks_qs.distinct()

        # ==========================================
        # DATE FILTER
        # ==========================================

        if selected_date:
            tasks_qs = tasks_qs.filter(
                Q(due_date=selected_date) |
                Q(sessions__start_time__date=selected_date)
            ).distinct()

        # ==========================================
        # STATUS DISTRIBUTION
        # ==========================================

        completed_cnt = tasks_qs.filter(
            status="Completed"
        ).count()

        working_cnt = tasks_qs.filter(
            status="In Progress"
        ).count()

        pending_cnt = tasks_qs.filter(
            status="Pending"
        ).count()

        review_cnt = tasks_qs.filter(
            status="To Do"
        ).count()

        # ==========================================
        # PROJECT TIME
        # ==========================================

# ==========================================
# PROJECT TIME
# ==========================================

        project_data = []

        visible_projects = projects_qs.distinct()

        total_seconds = 0

        for project in visible_projects:

            project_tasks = tasks_qs.filter(
                project=project
            )

            # Calculate time from all allowed tasks
            task_times = TaskTime.objects.filter(
                company=company,
                task__in=project_tasks
            )

            project_seconds = 0

            for tt in task_times:

                if tt.duration:
                    project_seconds += tt.duration.total_seconds()

                elif tt.start_time and tt.end_time:
                    project_seconds += (
                        tt.end_time - tt.start_time
                    ).total_seconds()

                elif tt.start_time:
                    project_seconds += (
                        timezone.now() - tt.start_time
                    ).total_seconds()

            total_seconds += project_seconds

            hours = int(project_seconds // 3600)
            minutes = int((project_seconds % 3600) // 60)

            project_data.append({
                "id": project.id,
                "project_name": project.project_name,
                "task_count": project_tasks.count(),
                "spent": f"{hours:02d}h {minutes:02d}m",
                "total_seconds": int(project_seconds),
            })

        # ==========================================
        # INDIVIDUAL TASK TIME
        # ==========================================

        task_data = []

        for task in tasks_qs:

            task_times = TaskTime.objects.filter(
                company=company,
                task=task
            )

            task_seconds = 0

            for tt in task_times:

                if tt.duration:

                    task_seconds += tt.duration.total_seconds()

                elif tt.start_time and tt.end_time:

                    task_seconds += (
                        tt.end_time - tt.start_time
                    ).total_seconds()

                elif tt.start_time and not tt.end_time:

                    task_seconds += (
                        timezone.now() - tt.start_time
                    ).total_seconds()

            hours = int(task_seconds // 3600)
            minutes = int(
                (task_seconds % 3600) // 60
            )

            task_data.append({
                "id": task.id,
                "task_name": task.task_name,
                "project_id": task.project_id,
                "project_name": (
                    task.project.project_name
                    if task.project
                    else None
                ),
                "status": task.status,
                "spent": f"{hours:02d}h {minutes:02d}m",
                "total_seconds": int(task_seconds),
            })

        # ==========================================
        # TOTAL TIME
        # ==========================================

        total_hours = int(total_seconds // 3600)
        total_minutes = int(
            (total_seconds % 3600) // 60
        )

        total_time_str = (
            f"{total_hours:02d}h "
            f"{total_minutes:02d}m"
        )

        # ==========================================
        # RESPONSE
        # ==========================================

        return Response({

            "status_distribution": [
                {
                    "name": "Completed",
                    "value": completed_cnt
                },
                {
                    "name": "Working",
                    "value": working_cnt
                },
                {
                    "name": "Pending",
                    "value": pending_cnt
                },
                {
                    "name": "Review",
                    "value": review_cnt
                }
            ],

            "total_time": total_time_str,

            "projects": project_data,

            "tasks": task_data

        }, status=status.HTTP_200_OK)

    except Exception as e:

        return Response(
            {
                "error": str(e)
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def View_Single_Employee_Productivity(request, user_id):

    logged_user = request.user

    # ==========================================
    # GET TARGET USER
    # ==========================================

    user = get_object_or_404(
        User,
        id=user_id,
        company=logged_user.company
    )

    # ==========================================
    # RBAC
    # ==========================================

    if logged_user.role == "admin":
        # Admin can view any employee in their company
        pass

    elif logged_user.role == "project_lead" or Team.objects.filter(company=logged_user.company, team_lead=logged_user).exists():
        # Project Leads & Team Leads can view themselves and members under their assigned teams or projects
        if user.id != logged_user.id:
            # 1. Teams led by this user
            teams_led = Team.objects.filter(
                company=logged_user.company,
                team_lead=logged_user
            )
            in_led_team = User.objects.filter(
                company=logged_user.company,
                id=user.id,
                team__in=teams_led
            ).exists()

            # 2. Projects led by this user
            lead_projects = Project.objects.filter(
                company=logged_user.company,
                assigned_to=logged_user
            )

            # Assigned to tasks in projects led by this user
            in_lead_project_tasks = Task.objects.filter(
                company=logged_user.company,
                project__in=lead_projects,
                assigned_to=user
            ).exists()

            # Belongs to the team assigned to projects led by this user
            in_lead_project_team = User.objects.filter(
                company=logged_user.company,
                id=user.id,
                team__in=lead_projects.filter(team__isnull=False).values_list("team_id", flat=True)
            ).exists()

            if not (in_led_team or in_lead_project_tasks or in_lead_project_team):
                return Response(
                    {
                        "detail": "You do not have permission to view this employee's productivity."
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

    else:
        # Normal employee can only view their own productivity
        if user.id != logged_user.id:
            return Response(
                {
                    "detail": "You do not have permission to view other employees' productivity."
                },
                status=status.HTTP_403_FORBIDDEN
            )

    # ==========================================
    # USER TASKS
    # ==========================================

    tasks = Task.objects.filter(
        company=logged_user.company,
        assigned_to=user
    ).order_by("-id")

    # ==========================================
    # TASK STATISTICS
    # ==========================================

    total_tasks = tasks.count()

    completed_tasks = tasks.filter(
        status="Completed"
    ).count()

    inprogress_tasks = tasks.filter(
        status="In Progress"
    ).count()

    pending_tasks = tasks.filter(
        status="Pending"
    ).count()

    today_tasks = tasks.filter(
        due_date=date.today()
    ).count()

    # ==========================================
    # ACTUAL TASK TIME SPENT (Total)
    # ==========================================

    task_times = TaskTime.objects.filter(
        company=logged_user.company,
        user=user
    )

    total_task_seconds = 0

    for tt in task_times:
        if tt.duration:
            total_task_seconds += tt.duration.total_seconds()
        elif tt.start_time and tt.end_time:
            total_task_seconds += (tt.end_time - tt.start_time).total_seconds()
        elif tt.start_time:
            total_task_seconds += (timezone.now() - tt.start_time).total_seconds()

    total_hours = int(total_task_seconds // 3600)
    total_minutes = int((total_task_seconds % 3600) // 60)
    actual_worked_hours_str = f"{total_hours:02d}h {total_minutes:02d}m" if total_hours > 0 or total_minutes > 0 else "00h 00m"

    # ==========================================
    # TODAY'S WORK SESSION & DAILY EFFICIENCY
    # ==========================================

    today_date = date.today()

    today_task_times = TaskTime.objects.filter(
        company=logged_user.company,
        user=user,
        start_time__date=today_date
    )

    today_task_seconds = 0
    for tt in today_task_times:
        if tt.duration:
            today_task_seconds += tt.duration.total_seconds()
        elif tt.start_time and tt.end_time:
            today_task_seconds += (tt.end_time - tt.start_time).total_seconds()
        elif tt.start_time:
            today_task_seconds += (timezone.now() - tt.start_time).total_seconds()

    today_sessions = WorkSession.objects.filter(
        company=logged_user.company,
        user=user,
        work_date=today_date
    )

    session_seconds = 0
    for ws in today_sessions:
        if ws.clock_out:
            session_seconds += ws.total_work_time.total_seconds()
        elif ws.clock_in:
            session_seconds += (timezone.now() - ws.clock_in).total_seconds()

    idle_seconds = 0
    idles = IdleSession.objects.filter(work_session__in=today_sessions)
    for idle in idles:
        if idle.duration:
            idle_seconds += idle.duration.total_seconds()
        elif idle.idle_end_time:
            idle_seconds += max(0, (idle.idle_end_time - idle.idle_start_time).total_seconds())
        elif idle.idle_start_time:
            idle_seconds += max(0, (timezone.now() - idle.idle_start_time).total_seconds())

    net_session_seconds = max(0, session_seconds - idle_seconds)
    total_base_seconds = max(session_seconds, today_task_seconds)

    if total_base_seconds > 0:
        productive_percentage = round(min(100.0, (today_task_seconds / total_base_seconds) * 100), 2)
        unproductive_percentage = round(min(100.0 - productive_percentage, (idle_seconds / total_base_seconds) * 100), 2)
        neutral_percentage = max(0.0, round(100.0 - productive_percentage - unproductive_percentage, 2))
    elif total_task_seconds > 0:
        all_sessions = WorkSession.objects.filter(company=logged_user.company, user=user)
        all_session_seconds = sum(
            (ws.total_work_time.total_seconds() if ws.clock_out else (timezone.now() - ws.clock_in).total_seconds() if ws.clock_in else 0)
            for ws in all_sessions
        )
        all_base = max(all_session_seconds, total_task_seconds)
        if all_base > 0:
            productive_percentage = round(min(100.0, (total_task_seconds / all_base) * 100), 2)
            unproductive_percentage = 0.0
            neutral_percentage = max(0.0, round(100.0 - productive_percentage, 2))
        else:
            productive_percentage = 0.0
            unproductive_percentage = 0.0
            neutral_percentage = 0.0
    else:
        productive_percentage = 0.0
        unproductive_percentage = 0.0
        neutral_percentage = 0.0

    # ==========================================
    # RECENT TASKS
    # ==========================================

    recent_tasks = [
        {
            "task_name": t.task_name,
            "status": t.status,
            "due_date": (
                t.due_date.strftime("%Y-%m-%d")
                if t.due_date
                else ""
            ),
        }
        for t in tasks[:5]
    ]

    # ==========================================
    # FULL TASK LIST
    # ==========================================

    task_list = TaskSerializer(
        tasks,
        many=True
    ).data

    # ==========================================
    # TODAY'S WORK SESSIONS
    # ==========================================

    today_sessions = WorkSession.objects.filter(
        company=logged_user.company,
        user=user,
        work_date=date.today()
    ).order_by("-clock_in")

    attendance_list = []
    idle_list = []
    app_list = []
    screenshot_list = []
    website_list = []

    # ==========================================
    # SESSION DETAILS
    # ==========================================

    for ws in today_sessions:

        attendance_list.append({
            "id": ws.id,
            "clock_in": ws.clock_in,
            "clock_out": ws.clock_out,
            "total_work_time": (
                str(ws.total_work_time)
                if ws.total_work_time
                else "-"
            ),
            "work_date": (
                ws.work_date.strftime("%Y-%m-%d")
                if ws.work_date
                else ""
            ),
        })

        # --------------------------------------
        # IDLE SESSIONS
        # --------------------------------------

        idles = IdleSession.objects.filter(
            work_session=ws
        ).order_by("-idle_start_time")

        for idle in idles:

            idle_list.append({
                "id": idle.id,
                "start_time": idle.idle_start_time,
                "end_time": idle.idle_end_time,
                "duration": (
                    str(idle.duration)
                    if idle.duration
                    else "-"
                ),
            })

        # --------------------------------------
        # APPLICATION USAGE
        # --------------------------------------

        apps = ApplicationUsage.objects.filter(
            work_session=ws
        ).order_by("-start_time")

        for app in apps:

            app_list.append({
                "id": app.id,
                "name": app.application_name,
                "start_time": app.start_time,
                "end_time": app.end_time,
                "duration": (
                    str(app.duration)
                    if app.duration
                    else "-"
                ),
            })

        # --------------------------------------
        # SCREENSHOTS
        # --------------------------------------

        scr = Screenshot.objects.filter(
            work_session=ws
        ).order_by("-captured_at")

        for s in scr:
            s_img_url = None
            if s.image:
                raw_img = str(s.image)
                if raw_img.startswith("http://") or raw_img.startswith("https://"):
                    s_img_url = raw_img
                else:
                    try:
                        import cloudinary.utils
                        s_img_url, _ = cloudinary.utils.cloudinary_url(
                            raw_img.lstrip("/"),
                            resource_type="image",
                            secure=True
                        )
                    except Exception:
                        s_img_url = getattr(s.image, "url", raw_img)

            screenshot_list.append({
                "id": s.id,
                "image": s_img_url,
                "captured_at": s.captured_at,
                "reason": s.reason,
            })

        # --------------------------------------
        # WEBSITE USAGE
        # --------------------------------------

        webs = WebsiteUsage.objects.filter(
            work_session=ws
        ).order_by("-start_time")

        for w in webs:

            website_list.append({
                "id": w.id,
                "url": w.website,
                "website": w.website,
                "page_title": w.page_title,
                "browser_name": w.browser_name,
                "start_time": w.start_time,
                "end_time": w.end_time,
                "duration": (
                    str(w.duration)
                    if w.duration
                    else "-"
                ),
            })

    # ==========================================
    # PROFILE IMAGE
    # ==========================================

    profile_img_url = None

    if hasattr(user, "profile_picture") and user.profile_picture:

        try:
            profile_img_url = user.profile_picture.url

        except Exception:

            profile_img_url = str(
                user.profile_picture
            )

    # ==========================================
    # TEAM
    # ==========================================

    team_name = (
        user.team.team_name
        if hasattr(user, "team") and user.team
        else "No Team"
    )

    # ==========================================
    # RESPONSE
    # ==========================================

    data = {

        "user": {

            "id": user.id,

            "name": (
                user.first_name
                or user.username
            ),

            "email": user.email,

            "profile_picture": (
                profile_img_url
                or "/employee pic.svg"
            ),

            "team_name": team_name,

            "active_projects": total_tasks,

            "in_progress": inprogress_tasks,

            "completed": completed_tasks,

            "idle_today": round(
                idle_seconds / 60
            ),

            "today_tasks": today_tasks,

            "worked_hours": actual_worked_hours_str,
            "time_spent": actual_worked_hours_str,

            "recent_tasks": recent_tasks,
        },

        "productivity": {

            "productive": productive_percentage,

            "neutral": neutral_percentage,

            "unproductive": unproductive_percentage,
        },

        "tasks": task_list,

        "attendance": attendance_list,

        "idle_sessions": idle_list,

        "applications": app_list,

        "screenshots": screenshot_list,

        "websites": website_list,
    }

    return Response(
        data,
        status=status.HTTP_200_OK
    )

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def View_Employees_Productivity(request):

    logged_user = request.user
    company = logged_user.company

    # ==========================================
    # Optional date filter from ?date=YYYY-MM-DD
    # ==========================================

    date_str = request.GET.get("date")
    filter_date = None

    if date_str:
        try:
            from datetime import date as date_cls, datetime
            filter_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            filter_date = None

    # ==========================================
    # RBAC
    # ==========================================

    if logged_user.role == "admin":
        # Admin → all active employees and project leads
        users = User.objects.filter(
            company=company,
            is_active=True
        ).exclude(
            role="admin"
        )

    elif logged_user.role == "project_lead" or Team.objects.filter(company=company, team_lead=logged_user).exists():
        # Project Leads & Team Leads → members under their assigned teams or projects (plus themselves)
        teams_led = Team.objects.filter(
            company=company,
            team_lead=logged_user
        )
        lead_projects = Project.objects.filter(
            company=company,
            assigned_to=logged_user
        )

        # 1. Users in teams led by this user
        team_user_ids = User.objects.filter(
            company=company,
            team__in=teams_led
        ).values_list("id", flat=True)

        # 2. Users assigned to tasks in projects led by this user
        task_user_ids = Task.objects.filter(
            company=company,
            project__in=lead_projects
        ).values_list(
            "assigned_to__id",
            flat=True
        )

        # 3. Users in teams assigned to projects led by this user
        proj_team_user_ids = User.objects.filter(
            company=company,
            team__in=lead_projects.filter(team__isnull=False).values_list("team_id", flat=True)
        ).values_list("id", flat=True)

        accessible_ids = set(team_user_ids) | set(task_user_ids) | set(proj_team_user_ids) | {logged_user.id}

        users = User.objects.filter(
            company=company,
            is_active=True,
            id__in=accessible_ids
        )

    else:
        # Regular Employee → only themselves
        users = User.objects.filter(
            id=logged_user.id,
            company=company,
            is_active=True
        )

    data = []

    # ==========================================
    # BUILD EMPLOYEE DATA
    # ==========================================

    for user in users:

        tasks = Task.objects.filter(
            company=company,
            assigned_to=user
        ).distinct()

        total_tasks = tasks.count()

        completed_tasks = tasks.filter(
            status__iexact="Completed"
        ).count()

        pending_tasks = tasks.exclude(
            status__iexact="Completed"
        ).count()

        # ==========================================
        # TASK TIME (optionally filtered by date)
        # ==========================================

        task_times_qs = TaskTime.objects.filter(
            company=company,
            user=user
        )

        if filter_date:
            task_times_qs = task_times_qs.filter(
                start_time__date=filter_date
            )

        total_seconds = 0

        for tt in task_times_qs:

            if tt.duration:

                total_seconds += tt.duration.total_seconds()

            elif tt.start_time and tt.end_time:

                total_seconds += (
                    tt.end_time - tt.start_time
                ).total_seconds()

            elif tt.start_time:

                total_seconds += (
                    timezone.now() - tt.start_time
                ).total_seconds()

        hours = int(total_seconds // 3600)

        minutes = int(
            (total_seconds % 3600) // 60
        )

        # ==========================================
        # NAME
        # ==========================================

        full_name = (
            f"{user.first_name} {user.last_name}"
        ).strip()

        employee_name = (
            full_name
            or user.username
            or user.email
            or "Employee"
        )

        # ==========================================
        # PROFILE PICTURE
        # ==========================================

        profile_picture = None

        if user.profile_picture:

            try:
                profile_picture = user.profile_picture.url
            except Exception:
                profile_picture = str(
                    user.profile_picture
                )

        # ==========================================
        # RESPONSE
        # ==========================================

        data.append({

            "id": user.id,

            "name": employee_name,

            "email": user.email,

            "role": user.role,

            "team_name": user.team.team_name if user.team else None,

            "profile_picture": (
                profile_picture
                or "/employee pic.svg"
            ),

            "total_tasks": total_tasks,

            "completed_tasks": completed_tasks,

            "pending_tasks": pending_tasks,

            "time_spent": (
                f"{hours:02d}h {minutes:02d}m"
            ),

            "total_seconds": int(
                total_seconds
            ),
        })

    return Response(
        {
            "count": len(data),
            "employees": data
        },
        status=status.HTTP_200_OK
    )
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def kanban_tasks(request):

    user_id = request.GET.get("user")
    status_filter = request.GET.get("status")

    if request.user.role in ("admin", "super_admin"):
        tasks = Task.objects.filter(company=request.user.company).prefetch_related("assigned_to")
    elif request.user.team:
        tasks = Task.objects.filter(
            company=request.user.company
        ).filter(
            Q(team=request.user.team) |
            Q(project__team=request.user.team) |
            Q(assigned_to=request.user)
        ).distinct().prefetch_related("assigned_to")
    else:
        tasks = Task.objects.filter(
            company=request.user.company,
            assigned_to=request.user
        ).prefetch_related("assigned_to")

    # Filter by assigned user
    if user_id and request.user.role in ("admin", "super_admin"):
        tasks = tasks.filter(
            assigned_to__id=user_id
        )

    # Filter by status
    if status_filter and status_filter != "All":
        tasks = tasks.filter(
            status=status_filter
        )

    serializer = TaskSerializer(tasks, many=True)

    return Response(
        serializer.data,
        status=status.HTTP_200_OK
    )

@api_view(["POST", "PATCH"])
@permission_classes([IsAuthenticated])
def update_task_status(request, task_id=None):
    # Support both task_id in URL or in POST data
    tid = task_id or request.data.get("task_id")
    new_status = request.data.get("status") or request.data.get("new_status")
    
    if not tid or not new_status:
        return Response({"error": "task_id and status required"}, status=status.HTTP_400_BAD_REQUEST)
        
    task = get_object_or_404(Task, id=tid,company=request.user.company)
    
    # Optional: if role is user, ensure they are assigned to this task
    if request.user.role == "user" and not task.assigned_to.filter(id=request.user.id).exists():
        return Response(
        {"error": "Unauthorized"},
        status=status.HTTP_403_FORBIDDEN,
    )

    valid_statuses = [choice[0] for choice in Task.STATUS_CHOICES]
    if new_status not in valid_statuses:
        return Response({"error": f"Invalid status. Must be one of {valid_statuses}"}, status=status.HTTP_400_BAD_REQUEST)



    old_status = task.status
    if old_status == new_status:
        return Response(
        {
            "message": "Task status is already up to date.",
            "task_id": tid,
            "status": task.status,
        },
        status=status.HTTP_200_OK,
    )

    task.status = new_status
    # task.save()
    task.save(update_fields=["status"])


    title = "Task Updated"
    message = f"The status of '{task.task_name}' has been changed to '{new_status}'."

    if new_status == "In Progress":
        title = "Task Started"
        message = f"You have started working on '{task.task_name}'."

    elif new_status == "Completed":
        title = "Task Completed"
        message = f"Congratulations! You have completed '{task.task_name}'."

    elif new_status == "Pending":
        title = "Task Pending"
        message = f"The task '{task.task_name}' has been moved to Pending."

    elif new_status == "To Do":
        title = "Task To Do"
        message = f"The task '{task.task_name}' is now in To Do."

    for user in task.assigned_to.all():
        send_notification(
            company=request.user.company,
            user=user,
            title=title,
            message=message,
            notification_type="task",
        )
        
    return Response({
        "message": "Task status updated successfully",
        "task_id": tid,
        "status": task.status
    }, status=status.HTTP_200_OK)




@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start_task(request, task_id):

    print("USER:", request.user)
    print("AUTH:", request.user.is_authenticated)

    # Admins manage tasks — only the assigned employee can start a task timer.
    if request.user.role == "admin":
        return Response(
            {"error": "You do not have permission to start this task. Only the assigned employee can track task time."},
            status=status.HTTP_403_FORBIDDEN
        )

    task = get_object_or_404(
        Task,
        id=task_id,
        company=request.user.company,
        assigned_to=request.user
    )

    if TaskTime.objects.filter(
        company=request.user.company,
        task=task,
        user=request.user,
        end_time__isnull=True
    ).exists():
        return Response(
            {"error": "Task already running"},
            status=status.HTTP_400_BAD_REQUEST
        )

    TaskTime.objects.create(
        company=request.user.company,
        task=task,
        user=request.user
    )

    return Response(
        {"message": "Task started"},
        status=status.HTTP_201_CREATED
    )



@api_view(["POST"])
@permission_classes([IsAuthenticated])
def stop_task(request, task_id):

    session = TaskTime.objects.filter(
        company=request.user.company,
        task_id=task_id,
        user=request.user,
        end_time__isnull=True
    ).first()

    if not session:
        return Response(
            {"error": "No running task"},
            status=status.HTTP_400_BAD_REQUEST
        )

    session.stop()

    return Response(
        {
            "message": "Task stopped",
            "duration_seconds": int(session.duration.total_seconds())
        },
        status=status.HTTP_200_OK
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_running_task_session(request, task_id):
    session = TaskTime.objects.filter(
        company=request.user.company, 
        task_id=task_id,
        user=request.user,
        end_time__isnull=True
    ).first()

    if not session:
        return Response({"running": False}, status=status.HTTP_200_OK)

    elapsed_seconds = int((timezone.now() - session.start_time).total_seconds())
    return Response({
        "running": True,
        "start_time": session.start_time.isoformat(),
        "elapsed_seconds": elapsed_seconds
    }, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_active_task(request):
    session = TaskTime.objects.filter(
        company=request.user.company, 
        user=request.user,
        end_time__isnull=True
    ).first()

    active_tasks_count = Task.objects.filter(
        company=request.user.company, 
        assigned_to=request.user,
        status="In Progress"
    ).count()

    if not session:
        return Response({"running": False,
                         "active_tasks_count": active_tasks_count})

    elapsed_seconds = int(
        (timezone.now() - session.start_time).total_seconds()
    )

    return Response({
        "running": True,
        "task_id": session.task_id,
        "elapsed_seconds": elapsed_seconds,
        "active_tasks_count": active_tasks_count
    })




# @api_view(["GET"])
# @permission_classes([IsAdminUser])
# def Task_Summary(request):
#     tasks = Task.objects.all()
#     data = []
#     for t in tasks:
#         data.append({
#             "id": t.id,
#             "task_name": t.task_name,
#             "total_time": str(t.total_time),
#             "sessions": t.sessions.count()
#         })
#     return Response({"tasks": data}, status=status.HTTP_200_OK)




from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def Task_Summary(request):

    if request.user.role == "admin":
        tasks = Task.objects.all().order_by("-id")
    else:
        tasks = Task.objects.filter(
            assigned_to=request.user
        ).order_by("-id")

    serializer = TaskSerializer(
        tasks,
        many=True
    )

    return Response(
        {
            "tasks": serializer.data
        },
        status=status.HTTP_200_OK
    )







from django.db.models import Sum
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response






# @api_view(["POST"])
# @permission_classes([IsAuthenticated])
# def upload_screenshot(request):

#     try:

#         image_base64 = request.data.get("image")
#         reason = request.data.get("reason", "periodic")

#         if not image_base64:
#             return Response(
#                 {"error": "Image required"},
#                 status=400
#             )

#         username = request.user.email

#         image_data = base64.b64decode(image_base64)

#         folder = os.path.join(
#             "media",
#             "screenshots",
#             username
#         )

#         os.makedirs(folder, exist_ok=True)

#         filename = (
#             f"{datetime.now():%Y%m%d_%H%M%S}_{reason}.png"
#         )

#         filepath = os.path.join(folder, filename)

#         with open(filepath, "wb") as f:
#             f.write(image_data)

#         return Response({
#             "success": True,
#             "filename": filename
#         })

#     except Exception as e:

#         return Response(
#             {
#                 "error": str(e)
#             },
#             status=500
#         )





@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_notifications(request):
    logged_user = request.user
    company = logged_user.company

    if logged_user.role == "admin":
        # Admin can view all notifications across the company
        notifications = Notification.objects.filter(
            company=company
        ).select_related("user").order_by("-created_at")
    elif logged_user.role == "project_lead" or Team.objects.filter(company=company, team_lead=logged_user).exists():
        # Project Leads & Team Leads: notifications addressed to them + assigned team members / projects
        teams_led = Team.objects.filter(company=company, team_lead=logged_user)
        lead_projects = Project.objects.filter(company=company, assigned_to=logged_user)

        team_user_ids = User.objects.filter(company=company, team__in=teams_led).values_list("id", flat=True)
        task_user_ids = Task.objects.filter(company=company, project__in=lead_projects).values_list("assigned_to__id", flat=True)
        proj_team_user_ids = User.objects.filter(
            company=company,
            team__in=lead_projects.filter(team__isnull=False).values_list("team_id", flat=True)
        ).values_list("id", flat=True)

        accessible_ids = set(team_user_ids) | set(task_user_ids) | set(proj_team_user_ids) | {logged_user.id}

        notifications = Notification.objects.filter(
            company=company,
            user__id__in=accessible_ids
        ).select_related("user").order_by("-created_at")
    else:
        # Regular Employees: strictly their own notifications
        notifications = Notification.objects.filter(
            company=company,
            user=logged_user
        ).select_related("user").order_by("-created_at")

    serializer = NotificationSerializer(notifications, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["PUT", "PATCH", "POST"])
@permission_classes([IsAuthenticated])
def mark_notification_read(request, id):
    notification = Notification.objects.filter(
        id=id,
        company=request.user.company
    )

    if request.user.role != "admin":
        notification = notification.filter(user=request.user)

    target_notif = notification.first()

    if not target_notif:
        return Response(
            {"error": "Notification not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    target_notif.is_read = True
    target_notif.save(update_fields=["is_read"])

    serializer = NotificationSerializer(target_notif)

    return Response(
        {
            "success": True,
            "message": "Notification marked as read.",
            "notification": serializer.data
        },
        status=status.HTTP_200_OK
    )


@api_view(["PUT", "PATCH", "POST"])
@permission_classes([IsAuthenticated])
def mark_all_notifications_read(request):
    notifs = Notification.objects.filter(
        company=request.user.company,
        user=request.user,
        is_read=False
    )
    notifs.update(is_read=True)

    return Response(
        {
            "success": True,
            "message": "All notifications marked as read."
        },
        status=status.HTTP_200_OK
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def unread_notification_count(request):
    logged_user = request.user
    company = logged_user.company

    # Total unread notifications for this user
    unread_count = Notification.objects.filter(
        company=company,
        user=logged_user,
        is_read=False
    ).count()

    # Unread leave-related notifications for this user
    leave_unread_count = Notification.objects.filter(
        company=company,
        user=logged_user,
        is_read=False,
        notification_type__in=[
            "leave_request",
            "leave_approved",
            "leave_rejected",
            "leave_cancelled"
        ]
    ).count()

    return Response(
        {
            "unread_count": unread_count,
            "leave_unread_count": leave_unread_count
        },
        status=status.HTTP_200_OK
    )


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_notification(request, id):

    notification = get_object_or_404(
        Notification,
        id=id,
        company=request.user.company,
        user=request.user     #Suppose:User A owns Notification 5 User B tries:
    )

    notification.delete()

    return Response(
        {
            "message": "Notification deleted successfully."
        },
        status=status.HTTP_200_OK
    )




@api_view(["GET"])
@permission_classes([IsAuthenticated])
def all_screenshots(request):
    import cloudinary.utils

    screenshots = Screenshot.objects.filter(
        company=request.user.company
    ).select_related("user", "work_session")

    # Only admins can view all employees' screenshots.
    # Employees and project leads can only view their own.
    if request.user.role != "admin":
        screenshots = screenshots.filter(user=request.user)

    date = request.GET.get("date")
    user_id = request.GET.get("user")
    reason = request.GET.get("reason")

    if date:
        screenshots = screenshots.filter(
            work_session__work_date=date
        )

    # Admins may filter by a specific employee; non-admins ignore this param
    if user_id and request.user.role == "admin":
        screenshots = screenshots.filter(
            user__id=user_id
        )

    if reason:
        screenshots = screenshots.filter(
            reason=reason
        )

    screenshots = screenshots.order_by("-captured_at")
    limit = request.GET.get("limit")
    if limit and limit.isdigit():
        screenshots = screenshots[:int(limit)]
    elif not date and not user_id and not reason:
        screenshots = screenshots[:100]

    data = []

    for screenshot in screenshots:
        # Build full Cloudinary HTTPS URL from the stored public_id/field.
        # CloudinaryField.url only returns the public_id path for some configs;
        # using cloudinary.utils.cloudinary_url ensures a proper https URL.
        image_url = None
        if screenshot.image:
            raw = str(screenshot.image)
            if raw.startswith("http://") or raw.startswith("https://"):
                image_url = raw
            else:
                # raw is either a public_id or a relative path
                public_id = raw.lstrip("/")
                image_url, _ = cloudinary.utils.cloudinary_url(
                    public_id,
                    resource_type="image",
                    secure=True,
                )

        data.append({
            "id": screenshot.id,
            "employee_name": screenshot.user.get_full_name() or screenshot.user.email,
            "email": screenshot.user.email,
            "image": image_url,
            "reason": screenshot.reason,
            "captured_at": screenshot.captured_at,
            "work_date": screenshot.work_session.work_date,
            "session_status": screenshot.work_session.status,
        })

    return Response(data, status=status.HTTP_200_OK)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def attendance_list(request):
    """
    Returns attendance summary cards (Present, Absent, Late, On Leave) and log details.
    Role-based permissions:
    - Admin / Super Admin: sees company-wide employee attendance
    - Employee / Team Lead: sees their team's attendance (or own if no team)
    """
    user = request.user
    company = user.company
    is_admin = user.role in ["admin", "super_admin"]

    date_str = request.GET.get("date")
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            target_date = timezone.localdate()
    else:
        target_date = timezone.localdate()

    branch_filter = request.GET.get("branch")
    status_filter = request.GET.get("status")
    user_id_filter = request.GET.get("user_id") or request.GET.get("user")

    # Fetch users
    if is_admin:
        users_qs = User.objects.filter(company=company, is_active=True).exclude(role="admin")
        if user_id_filter:
            users_qs = users_qs.filter(id=user_id_filter)
    elif user.team:
        users_qs = User.objects.filter(company=company, team=user.team, is_active=True).exclude(role="admin")
        if user_id_filter:
            users_qs = users_qs.filter(id=user_id_filter)
    else:
        users_qs = User.objects.filter(id=user.id, company=company, is_active=True)

    if branch_filter and branch_filter not in ["All Branches", "All"]:
        users_qs = users_qs.filter(
            Q(team__team_name=branch_filter) | Q(id=user.id if not is_admin else 0)
        )

    users_list = list(users_qs.select_related("team"))

    # Fetch work sessions for target_date
    sessions = WorkSession.objects.filter(
        company=company,
        work_date=target_date
    ).select_related("user")
    session_map = {s.user_id: s for s in sessions}

    # Fetch approved leave requests covering target_date
    leaves = LeaveRequest.objects.filter(
        company=company,
        status="approved",
        start_date__lte=target_date,
        end_date__gte=target_date
    ).select_related("employee")
    leave_user_ids = set(leaves.values_list("employee_id", flat=True))

    present_count = 0
    absent_count = 0
    late_count = 0
    on_leave_count = 0

    logs = []

    for u in users_list:
        full_name = f"{u.first_name} {u.last_name}".strip() or u.username or u.email
        name_parts = full_name.split()
        initials = (name_parts[0][0] + (name_parts[1][0] if len(name_parts) > 1 else "")).upper() if name_parts else "U"
        branch_name = u.team.team_name if u.team else "HQ"

        session = session_map.get(u.id)
        is_on_leave = u.id in leave_user_ids

        check_in_str = "-"
        check_out_str = "-"
        duration_str = "-"
        break_str = "0h 0m"
        break_sec = 0
        status_val = "Absent"

        if is_on_leave:
            status_val = "On Leave"
            on_leave_count += 1
        elif session:
            if session.clock_in:
                check_in_dt = timezone.localtime(session.clock_in)
                check_in_str = check_in_dt.strftime("%H:%M")
                
                # Check if checked in after 09:30 AM -> Late
                if check_in_dt.time() > datetime.strptime("09:30", "%H:%M").time():
                    status_val = "Late"
                    late_count += 1
                else:
                    status_val = "Present"
                    present_count += 1
            else:
                status_val = "Present"
                present_count += 1

            break_sec = 0
            break_str = "0h 0m"
            idles = IdleSession.objects.filter(work_session=session)
            for idle in idles:
                if idle.duration:
                    break_sec += int(idle.duration.total_seconds())
                elif idle.idle_end_time:
                    break_sec += max(0, int((idle.idle_end_time - idle.idle_start_time).total_seconds()))
                elif not idle.idle_end_time and not session.clock_out:
                    break_sec += max(0, int((timezone.now() - idle.idle_start_time).total_seconds()))

            b_hours = max(0, break_sec // 3600)
            b_mins = max(0, (break_sec % 3600) // 60)
            break_str = f"{b_hours}h {b_mins}m"

            if session.clock_out:
                check_out_dt = timezone.localtime(session.clock_out)
                check_out_str = check_out_dt.strftime("%H:%M")
                dur_seconds = int((session.clock_out - session.clock_in).total_seconds())
            else:
                dur_seconds = int((timezone.now() - session.clock_in).total_seconds())

            net_dur_seconds = max(0, dur_seconds - break_sec)
            hours = max(0, net_dur_seconds // 3600)
            mins = max(0, (net_dur_seconds % 3600) // 60)
            duration_str = f"{hours}h {mins}m"
        else:
            status_val = "Absent"
            absent_count += 1
            break_str = "0h 0m"
            break_sec = 0

        if status_filter and status_filter != "All" and status_val.lower() != status_filter.lower():
            continue

        profile_img_url = None
        if hasattr(u, "profile_picture") and u.profile_picture:
            try:
                profile_img_url = u.profile_picture.url
            except Exception:
                profile_img_url = str(u.profile_picture)

        logs.append({
            "id": session.id if session else f"absent-{u.id}",
            "user_id": u.id,
            "employee_name": full_name,
            "initials": initials,
            "email": u.email,
            "profile_picture": profile_img_url,
            "role": u.role,
            "branch": branch_name,
            "check_in": check_in_str,
            "check_out": check_out_str,
            "duration": duration_str,
            "break_time": break_str,
            "break_seconds": break_sec,
            "status": status_val,
            "work_date": str(target_date)
        })

    summary = {
        "present": present_count,
        "absent": absent_count,
        "late": late_count,
        "on_leave": on_leave_count
    }

    return Response({
        "date": str(target_date),
        "summary": summary,
        "logs": logs
    }, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def attendance_calendar(request):
    """
    Returns monthly attendance status map for calendar view.
    """
    user = request.user
    company = user.company
    is_admin = user.role in ["admin", "super_admin"]

    month = int(request.GET.get("month", timezone.localdate().month))
    year = int(request.GET.get("year", timezone.localdate().year))
    target_user_id = request.GET.get("user_id")

    if not is_admin:
        if target_user_id:
            if str(target_user_id) != str(user.id):
                if user.team:
                    if not User.objects.filter(id=target_user_id, company=company, team=user.team).exists():
                        target_user_id = user.id
                else:
                    target_user_id = user.id
        else:
            target_user_id = user.id

    num_days = calendar.monthrange(year, month)[1]
    days_data = {}

    start_d = date(year, month, 1)
    end_d = date(year, month, num_days)

    sessions = WorkSession.objects.filter(
        company=company,
        user_id=target_user_id,
        work_date__gte=start_d,
        work_date__lte=end_d
    )
    session_days = {s.work_date: s for s in sessions}

    leaves = LeaveRequest.objects.filter(
        company=company,
        employee_id=target_user_id,
        status="approved",
        start_date__lte=end_d,
        end_date__gte=start_d
    )

    leave_dates = set()
    for l in leaves:
        curr = max(l.start_date, start_d)
        end_l = min(l.end_date, end_d)
        while curr <= end_l:
            leave_dates.add(curr)
            curr += timedelta(days=1)

    for day_num in range(1, num_days + 1):
        d = date(year, month, day_num)
        if d in session_days:
            s = session_days[d]
            if s.clock_in and timezone.localtime(s.clock_in).time() > datetime.strptime("09:30", "%H:%M").time():
                status_str = "late"
            else:
                status_str = "present"
        elif d in leave_dates:
            status_str = "on_leave"
        elif d.weekday() in [5, 6]:
            status_str = "weekend"
        else:
            status_str = "absent"

        days_data[day_num] = status_str

    return Response({
        "year": year,
        "month": month,
        "user_id": target_user_id,
        "days": days_data
    }, status=status.HTTP_200_OK)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def attendance_corrections(request):
    """
    GET: List attendance correction requests (Admin sees all; User sees own).
    POST: Submit a correction request.
    """
    user = request.user
    company = user.company
    is_admin = user.role in ["admin", "super_admin"]

    if request.method == "GET":
        if is_admin:
            corrections = AttendanceCorrection.objects.filter(company=company).select_related("user", "approved_by")
        elif user.team:
            corrections = AttendanceCorrection.objects.filter(company=company, user__team=user.team).select_related("user", "approved_by")
        else:
            corrections = AttendanceCorrection.objects.filter(company=company, user=user).select_related("user", "approved_by")
        serializer = AttendanceCorrectionSerializer(corrections, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == "POST":
        data = request.data.copy()
        serializer = AttendanceCorrectionSerializer(data=data)
        if serializer.is_valid():
            serializer.save(company=company, user=user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST", "PATCH"])
@permission_classes([IsAuthenticated])
def attendance_correction_action(request, pk):
    """
    Action on attendance correction:
    - Admin / Project Lead: approve or reject
    """
    user = request.user
    is_admin_or_project_lead = user.role in [
        "admin",
        "super_admin",
        "project_lead",
    ]
    if not is_admin_or_project_lead:
        return Response({"error": "Only admins and project leads can approve or reject attendance corrections."}, status=status.HTTP_403_FORBIDDEN)

    correction = get_object_or_404(AttendanceCorrection, pk=pk, company=user.company)
    action = request.data.get("action")
    rejection_reason = request.data.get("rejection_reason", "")

    if action == "approve":
        correction.status = "approved"
        correction.approved_by = user
        correction.save()

        # Update or create WorkSession for target user on work_date
        session, _ = WorkSession.objects.get_or_create(
            company=user.company,
            user=correction.user,
            work_date=correction.work_date
        )
        if correction.check_in:
            check_in_time = correction.check_in
            session.clock_in = timezone.make_aware(datetime.combine(correction.work_date, check_in_time))
        if correction.check_out:
            check_out_time = correction.check_out
            session.clock_out = timezone.make_aware(datetime.combine(correction.work_date, check_out_time))
            if correction.check_in and session.clock_in and session.clock_out:
                session.total_work_time = session.clock_out - session.clock_in
            session.status = "completed"
        session.save()

        return Response({"message": "Correction approved successfully"}, status=status.HTTP_200_OK)

    elif action == "reject":
        correction.status = "rejected"
        correction.approved_by = user
        correction.rejection_reason = rejection_reason
        correction.save()
        return Response({"message": "Correction rejected"}, status=status.HTTP_200_OK)

    return Response({"error": "Invalid action specified"}, status=status.HTTP_400_BAD_REQUEST)



@api_view(["GET"])
@permission_classes([IsAuthenticated, IsAdminRole])
def idle_report(request):


    idle_sessions = IdleSession.objects.filter(company=request.user.company).select_related(
        "user",
        "work_session"
    )

    # Get query parameters
    date = request.GET.get("date")
    user_id = request.GET.get("user")

    # Filter by date
    if date:
        idle_sessions = idle_sessions.filter(
            work_session__work_date=date
        )

    # Filter by user
    if user_id:
        idle_sessions = idle_sessions.filter(
            user__id=user_id
        )

    idle_sessions = idle_sessions.order_by("-idle_start_time")

    data = []

    for idle in idle_sessions:

        data.append({
            "id": idle.id,
            "employee_name": idle.user.get_full_name(),
            # "employee_name": screenshot.user.get_full_name() or screenshot.user.username,
            "email": idle.user.email,
            "idle_start": idle.idle_start_time,
            "idle_end": idle.idle_end_time,
            "duration": str(idle.duration),
            "work_date": idle.work_session.work_date,
        })

    return Response(data, status=status.HTTP_200_OK)

@api_view(["GET"])
@permission_classes([IsAuthenticated, IsAdminRole])
def application_report(request):
    applications = ApplicationUsage.objects.filter(company=request.user.company).select_related(
        "user",
        "work_session"
    )

    date = request.GET.get("date")
    user_id = request.GET.get("user")


    if date:
        applications = applications.filter(
            work_session__work_date=date
        )

    if user_id:
        applications = applications.filter(
            user__id=user_id
        )

    applications = applications.order_by("-start_time")

    data =[]


    for app in applications:

        data.append({
            "id": app.id,

            "employee_name": app.user.get_full_name(),

            "email": app.user.email,

            "application_name": app.application_name,

            "window_title": app.window_title,

            "start_time": app.start_time,

            "end_time": app.end_time,

            "duration": str(app.duration),

            "productive": app.is_productive,

            "work_date": app.work_session.work_date,
        })
    return Response(data)

@api_view(["GET"])
@permission_classes([IsAuthenticated, IsAdminRole])
def website_report(request):


    websites = WebsiteUsage.objects.filter(company=request.user.company).select_related(
        "user",
        "work_session"
    )

    date = request.GET.get("date")
    user_id = request.GET.get("user")

    if date:
        websites = websites.filter(
            work_session__work_date=date
        )

    if user_id:
        websites = websites.filter(
            user__id=user_id
        )

    serializer = WebsiteUsageSerializer(
        websites,
        many=True
    )

    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def all_reports(request):
    """
    Returns comprehensive employee tracking reports including:
    Total Working Hours, Clock In, Clock Out, Break Duration, Task Time, and daily row details.
    """
    user = request.user
    company = user.company
    is_admin_or_project_lead = user.role in [
        "admin",
        "super_admin",
        "project_lead",
    ]

    date_str = request.GET.get("date")
    team_param = request.GET.get("team")
    user_param = request.GET.get("user")
    search_query = request.GET.get("search", "").strip()

    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            target_date = timezone.localdate()
    else:
        target_date = timezone.localdate()

    # Filter users
    users_qs = User.objects.filter(company=company, is_active=True)
    if not is_admin_or_project_lead:
        users_qs = users_qs.filter(id=user.id)
    elif user_param and user_param not in ["All Users", "All"]:
        users_qs = users_qs.filter(id=user_param)

    if team_param and team_param not in ["All Teams", "All"]:
        if team_param.isdigit():
            users_qs = users_qs.filter(team_id=team_param)
        else:
            users_qs = users_qs.filter(team__team_name=team_param)

    if search_query:
        users_qs = users_qs.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query)
        )

    users_list = list(users_qs.select_related("team"))

    # Fetch WorkSessions for target_date
    sessions = WorkSession.objects.filter(
        company=company,
        work_date=target_date
    ).select_related("user")
    session_map = {s.user_id: s for s in sessions}

    # Fetch IdleSessions for target_date
    idle_sessions = IdleSession.objects.filter(
        company=company,
        idle_start_time__date=target_date
    )
    idle_map = {}
    for idle in idle_sessions:
        if idle.user_id not in idle_map:
            idle_map[idle.user_id] = []
        idle_map[idle.user_id].append(idle)

    # Fetch TaskTimes for target_date
    task_times = TaskTime.objects.filter(
        company=company,
        start_time__date=target_date
    )
    task_time_map = {}
    for tt in task_times:
        if tt.user_id not in task_time_map:
            task_time_map[tt.user_id] = []
        task_time_map[tt.user_id].append(tt)

    reports = []
    total_work_seconds_all = 0
    total_break_seconds_all = 0
    total_task_seconds_all = 0
    clock_in_times = []
    clock_out_times = []

    for u in users_list:
        full_name = f"{u.first_name} {u.last_name}".strip() or u.username or u.email
        session = session_map.get(u.id)

        clock_in_str = "-"
        clock_out_str = "-"
        break_in_str = "-"
        break_out_str = "-"
        total_break_str = "0 min"
        task_time_str = "0 min"
        total_hours_str = "00h 00min"

        work_seconds = 0
        break_seconds = 0
        task_seconds = 0

        if session:
            if session.clock_in:
                ci_local = timezone.localtime(session.clock_in)
                clock_in_str = ci_local.strftime("%I:%M %p")
                clock_in_times.append(ci_local)

            if session.clock_out:
                co_local = timezone.localtime(session.clock_out)
                clock_out_str = co_local.strftime("%I:%M %p")
                clock_out_times.append(co_local)
                work_seconds = int(session.total_work_time.total_seconds()) if session.total_work_time else int((session.clock_out - session.clock_in).total_seconds())
            elif session.clock_in:
                work_seconds = int((timezone.now() - session.clock_in).total_seconds())

        # Idle / Break details
        u_idles = idle_map.get(u.id, [])
        if u_idles:
            earliest_idle = min(u_idles, key=lambda x: x.idle_start_time)
            latest_idle = max(u_idles, key=lambda x: x.idle_end_time or x.idle_start_time)

            break_in_str = timezone.localtime(earliest_idle.idle_start_time).strftime("%I:%M %p")
            if latest_idle.idle_end_time:
                break_out_str = timezone.localtime(latest_idle.idle_end_time).strftime("%I:%M %p")

            for idle in u_idles:
                if idle.duration:
                    break_seconds += int(idle.duration.total_seconds())
                elif idle.idle_end_time:
                    break_seconds += max(0, int((idle.idle_end_time - idle.idle_start_time).total_seconds()))
                elif not idle.idle_end_time and (not session or not session.clock_out):
                    break_seconds += max(0, int((timezone.now() - idle.idle_start_time).total_seconds()))

        # Task Time details
        u_tasks = task_time_map.get(u.id, [])
        for tt in u_tasks:
            if tt.duration:
                task_seconds += int(tt.duration.total_seconds())
            elif tt.end_time:
                task_seconds += max(0, int((tt.end_time - tt.start_time).total_seconds()))
            elif tt.start_time:
                task_seconds += max(0, int((timezone.now() - tt.start_time).total_seconds()))

        # Format row strings
        b_hours = max(0, break_seconds // 3600)
        b_mins = max(0, (break_seconds % 3600) // 60)
        total_break_str = f"{b_hours}h {b_mins}min" if b_hours > 0 else f"{b_mins} min"

        t_hours = max(0, task_seconds // 3600)
        t_mins = max(0, (task_seconds % 3600) // 60)
        task_time_str = f"{t_hours}h {t_mins}min" if t_hours > 0 else f"{t_mins}min"

        net_work_seconds = max(0, work_seconds - break_seconds)
        w_hours = max(0, net_work_seconds // 3600)
        w_mins = max(0, (net_work_seconds % 3600) // 60)
        total_hours_str = f"{w_hours:02d}h {w_mins:02d}min"

        total_work_seconds_all += net_work_seconds
        total_break_seconds_all += break_seconds
        total_task_seconds_all += task_seconds

        formatted_date_str = target_date.strftime("%d %b %Y")

        reports.append({
            "id": u.id,
            "employee_name": full_name,
            "date": formatted_date_str,
            "clock_in": clock_in_str,
            "clock_out": clock_out_str,
            "break_in": break_in_str,
            "break_out": break_out_str,
            "total_break": total_break_str,
            "task_time": task_time_str,
            "total_hours": total_hours_str,
            "team": u.team.team_name if u.team else "HQ"
        })

    # Summary Cards values
    tw_h = total_work_seconds_all // 3600
    tw_m = (total_work_seconds_all % 3600) // 60
    summary_working_hours = f"{tw_h:02d}h {tw_m:02d}m"

    summary_clock_in = clock_in_times[0].strftime("%I:%M %p") if clock_in_times else "--:--"
    summary_clock_out = clock_out_times[-1].strftime("%I:%M %p") if clock_out_times else "--:--"

    tb_m = total_break_seconds_all // 60
    summary_break_duration = f"{tb_m} min"

    tt_h = total_task_seconds_all // 3600
    tt_m = (total_task_seconds_all % 3600) // 60
    summary_task_time = f"{tt_h}h {tt_m}m" if tt_h > 0 else f"{tt_m}m"

    summary = {
        "total_working_hours": summary_working_hours,
        "clock_in": summary_clock_in,
        "clock_out": summary_clock_out,
        "break_duration": summary_break_duration,
        "task_time": summary_task_time
    }

    return Response({
        "date": str(target_date),
        "summary": summary,
        "reports": reports
    }, status=status.HTTP_200_OK)





import logging

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_leave_type(request):

    if request.user.role not in ["admin", "super_admin"]:
        return Response(
            {"error": "Only admin can create leave types."},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = LeaveTypeSerializer(data=request.data)

    if serializer.is_valid():
        leave_type = serializer.save(company=request.user.company)

        employees = User.objects.filter(
            company=request.user.company
        ).exclude(role__in=["admin", "super_admin"])

        for employee in employees:
            try:
                send_notification(
                    company=request.user.company,
                    user=employee,
                    title="New Leave Type",
                    message=f"A new leave type '{leave_type.name}' has been added.",
                    notification_type="system",
                )
            except Exception as e:
                logger.exception(
                    "Failed to send leave type notification to user %s: %s",
                    employee.id,
                    e,
                )

        return Response(
            {
                "message": "Leave type created successfully",
                "data": LeaveTypeSerializer(leave_type).data,
            },
            status=status.HTTP_201_CREATED,
        )

    return Response(
        serializer.errors,
        status=status.HTTP_400_BAD_REQUEST,
    )

@api_view(["GET"])      
@permission_classes([IsAuthenticated])
def list_leave_types(request):

    show_all = request.query_params.get("all") == "true" or request.query_params.get("include_inactive") == "true"
    qs = LeaveType.objects.filter(company=request.user.company)
    if not show_all:
        qs = qs.filter(is_active=True)
    leave_types = qs.order_by("name")

    serializer = LeaveTypeSerializer(leave_types, many=True)

    return Response(serializer.data)

from django.shortcuts import get_object_or_404


@api_view(["PUT"])
@permission_classes([IsAuthenticated])
def update_leave_type(request, pk):

    if request.user.role not in ["admin", "super_admin"]:
        return Response(
            {"error": "Only admin can update leave types."},
            status=status.HTTP_403_FORBIDDEN,
        )

    leave_type = get_object_or_404(
        LeaveType,
        id=pk,
        company=request.user.company,
    )

    serializer = LeaveTypeSerializer(
        leave_type,
        data=request.data,
        partial=True,
    )

    if serializer.is_valid():

        leave_type = serializer.save()

        employees = User.objects.filter(
            company=request.user.company
        ).exclude(role__in=["admin", "super_admin"])

        for employee in employees:
            try:
                send_notification(
                    company=request.user.company,
                    user=employee,
                    title="Leave Type Updated",
                    message=f"The leave type '{leave_type.name}' has been updated.",
                    notification_type="system",
                )
            except Exception as e:
                logger.exception(
                    "Failed to send leave type update notification to user %s: %s",
                    employee.id,
                    e,
                )

        return Response(
            {
                "message": "Leave type updated successfully",
                "data": LeaveTypeSerializer(leave_type).data,
            },
            status=status.HTTP_200_OK,
        )

    return Response(
        serializer.errors,
        status=status.HTTP_400_BAD_REQUEST,
    )

@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_leave_type(request, pk):

    if request.user.role not in ["admin", "super_admin"]:
        return Response(
            {"error": "Only admin can delete leave types."},
            status=status.HTTP_403_FORBIDDEN,
        )

    leave_type = get_object_or_404(
        LeaveType,
        id=pk,
        company=request.user.company,
    )

    leave_type.is_active = False
    leave_type.status = "inactive"

    leave_type.save(
        update_fields=["is_active", "status"]
    )

    employees = User.objects.filter(
        company=request.user.company
    ).exclude(role__in=["admin", "super_admin"])

    for employee in employees:
        try:
            send_notification(
                company=request.user.company,
                user=employee,
                title="Leave Type Removed",
                message=f"The leave type '{leave_type.name}' is no longer available.",
                notification_type="system",
            )
        except Exception as e:
            logger.exception(
                "Failed to send leave type removal notification to user %s: %s",
                employee.id,
                e,
            )

    return Response(
        {
            "message": "Leave type deleted successfully."
        },
        status=status.HTTP_200_OK,
    )
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def leave_requests(request):

    if request.user.role not in ["admin", "super_admin", "project_lead"]:
        return Response(
            {"error": "Only admins and project leads can view leave requests."},
            status=status.HTTP_403_FORBIDDEN
        )

    leave_requests = LeaveRequest.objects.filter(
        company=request.user.company
    ).order_by("-created_at")

    serializer = LeaveRequestSerializer(
        leave_requests,
        many=True
    )

    return Response(serializer.data)



@api_view(["PUT"])
@permission_classes([IsAuthenticated])
def approve_leave(request, pk):
    if request.user.role not in ["admin", "super_admin", "project_lead"]:
        return Response({"error": "Only admins and project leads can approve leave."}, status=403)

    leave_request = get_object_or_404(
        LeaveRequest,
        id=pk,
        company=request.user.company
    )

    if leave_request.status != "pending":
        return Response({"error": "Not pending"}, status=400)
    
    leave_request.status = "approved"
    leave_request.approved_by = request.user
    leave_request.approved_at = timezone.now()
    leave_request.save()
    send_notification(
        company=request.user.company,
        user=leave_request.employee,
        title="Leave Approved",
        message=f"Your {leave_request.leave_type.name} leave request has been approved.",
        notification_type="leave_approved",
    )
    try:
        employee = leave_request.employee
        full_name = f"{employee.first_name} {employee.last_name}".strip()

        send_email_notification(
            company=request.user.company,
            subject="Leave Request Approved",
            message=(
                f"Hello {full_name or employee.username},\n\n"
                f"Your leave request has been approved.\n\n"
                f"Leave Type: {leave_request.leave_type.name}\n"
                f"From: {leave_request.start_date}\n"
                f"To: {leave_request.end_date}\n"
                f"Approved By: {request.user.first_name or request.user.username}\n\n"
                f"You may proceed according to the approved leave schedule."
            ),
            recipient_email=employee.email,
        )

    except Exception as e:
        print(f"Email sending failed for {employee.email}: {e}")


    return Response({"message": "Approved"})



@api_view(["PUT"])
@permission_classes([IsAuthenticated])
def reject_leave(request, pk):

    if request.user.role not in ["admin", "super_admin", "project_lead"]:
        return Response(
            {"error": "Only admins and project leads can reject leave."},
            status=status.HTTP_403_FORBIDDEN
        )

    leave_request = get_object_or_404(
        LeaveRequest,
        id=pk,
        company=request.user.company
    )

    if leave_request.status != "pending":
        return Response(
            {"error": "Only pending leave requests can be rejected."},
            status=status.HTTP_400_BAD_REQUEST
        )

    rejection_reason = request.data.get("rejection_reason")

    if not rejection_reason:
        return Response(
            {"error": "Rejection reason is required."},
            status=status.HTTP_400_BAD_REQUEST
        )

    leave_request.status = "rejected"
    leave_request.rejection_reason = rejection_reason
    leave_request.approved_by = request.user
    leave_request.approved_at = timezone.now()
    leave_request.save()
    send_notification(
        company=request.user.company,
        user=leave_request.employee,
        title="Leave Rejected",
        message=f"Your {leave_request.leave_type.name} leave request has been rejected. Reason: {rejection_reason}",
        notification_type="leave_rejected",
    )
    try:
        employee = leave_request.employee
        full_name = f"{employee.first_name} {employee.last_name}".strip()

        send_email_notification(
            company=request.user.company,
            subject="Leave Request Rejected",
            message=(
                f"Hello {full_name or employee.username},\n\n"
                f"We regret to inform you that your leave request has been rejected.\n\n"
                f"Leave Type: {leave_request.leave_type.name}\n"
                f"From: {leave_request.start_date}\n"
                f"To: {leave_request.end_date}\n"
                f"Reason: {rejection_reason}\n"
                f"Rejected By: {request.user.first_name or request.user.username}\n\n"
                f"If you have any questions, please contact your administrator."
            ),
            recipient_email=employee.email,
        )
    except Exception as e:
        print(f"Email sending failed for {employee.email}: {e}")

    return Response(
        {"message": "Leave rejected successfully."},
        status=status.HTTP_200_OK
    )

@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminRole])
def reset_employee_password(request, user_id):
    employee = get_object_or_404(
        User,
        id=user_id,
        company=request.user.company,
    )

    # Prevent resetting another admin's password
    if employee.role == "admin":
        return Response(
            {"error": "Admin passwords cannot be reset using this endpoint."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    new_password = request.data.get("new_password")

    if not new_password:
        return Response(
            {"error": "New password is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        validate_password(new_password, employee)
    except ValidationError as e:
        return Response(
            {"error": e.messages},
            status=status.HTTP_400_BAD_REQUEST,
        )   
    employee.set_password(new_password)
    employee.save(update_fields=["password"])

    send_notification(
        company=request.user.company,
        user=employee,
        title="Password Reset",
        message="Your password has been reset by the administrator. Please log in using the new password.",
        notification_type="system",
    )

    return Response(
        {
            "message": "Employee password reset successfully."
        },
        status=status.HTTP_200_OK,
    )


import traceback

@api_view(["GET"])
@permission_classes([IsAdminOrProjectLead])
def export_employees_excel(request):
    try:
        team_id = request.query_params.get("team_id") or request.query_params.get("team")
        if request.user.role in ("admin", "super_admin"):
            employees = User.objects.filter(
                company=request.user.company
            ).order_by("id")
            if team_id and str(team_id).lower() != "all":
                employees = employees.filter(team_id=team_id)
        elif request.user.team:
            employees = User.objects.filter(
                company=request.user.company,
                team=request.user.team
            ).order_by("id")
        else:
            employees = User.objects.filter(
                id=request.user.id,
                company=request.user.company
            ).order_by("id")

        headers = [
            "ID",
            "Full Name",
            "Email",
            "Role",
            "Mobile",
            "Status",
        ]

        rows = []

        for idx, employee in enumerate(employees, start=1):
            full_name = f"{employee.first_name} {employee.last_name}".strip() or employee.first_name
            status_text = "Active" if employee.is_active else "Inactive"
            rows.append([
                idx,
                full_name,
                employee.email,
                employee.role,
                employee.mobile or "-",
                status_text,
            ])

        return export_to_excel(
            filename="employees",
            headers=headers,
            rows=rows,
        )

    except Exception:
        traceback.print_exc()
        raise



@api_view(["GET"])
@permission_classes([IsAdminOrProjectLead])
def export_employees_pdf(request):

    team_id = request.query_params.get("team_id") or request.query_params.get("team")
    if request.user.role in ("admin", "super_admin"):
        employees = User.objects.filter(
            company=request.user.company
        ).order_by("id")
        if team_id and str(team_id).lower() != "all":
            employees = employees.filter(team_id=team_id)
    elif request.user.team:
        employees = User.objects.filter(
            company=request.user.company,
            team=request.user.team
        ).order_by("id")
    else:
        employees = User.objects.filter(
            id=request.user.id,
            company=request.user.company
        ).order_by("id")

    headers = [
        "ID",
        "Name",
        "Email",
        "Role",
        "Mobile",
        "Status",
    ]

    rows = []

    for idx, employee in enumerate(employees, start=1):
        full_name = f"{employee.first_name} {employee.last_name}".strip() or employee.first_name
        status_text = "Active" if employee.is_active else "Inactive"
        rows.append([
            idx,
            full_name,
            employee.email,
            employee.role,
            employee.mobile or "-",
            status_text,
        ])

    return export_to_pdf(
        filename="employees",
        title="Employee Report",
        headers=headers,
        rows=rows,
    )


@api_view(["GET"])
@permission_classes([IsAdminOrProjectLead])
def export_reports_excel(request):
    try:
        user = request.user
        company = user.company
        is_admin_or_project_lead = user.role in [
            "admin",
            "super_admin",
            "project_lead",
        ]

        date_str = request.GET.get("date")
        team_param = request.GET.get("team")
        user_param = request.GET.get("user")
        search_query = request.GET.get("search", "").strip()

        if date_str:
            try:
                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                target_date = timezone.localdate()
        else:
            target_date = timezone.localdate()

        users_qs = User.objects.filter(company=company, is_active=True)
        if not is_admin_or_project_lead:
            users_qs = users_qs.filter(id=user.id)
        elif user_param and user_param not in ["All Users", "All"]:
            users_qs = users_qs.filter(id=user_param)

        if team_param and team_param not in ["All Teams", "All"]:
            if team_param.isdigit():
                users_qs = users_qs.filter(team_id=team_param)
            else:
                users_qs = users_qs.filter(team__team_name=team_param)

        if search_query:
            users_qs = users_qs.filter(
                Q(first_name__icontains=search_query) |
                Q(last_name__icontains=search_query) |
                Q(username__icontains=search_query) |
                Q(email__icontains=search_query)
            )

        users_list = list(users_qs.select_related("team"))
        sessions = WorkSession.objects.filter(company=company, work_date=target_date)
        session_map = {s.user_id: s for s in sessions}

        idle_sessions = IdleSession.objects.filter(company=company, idle_start_time__date=target_date)
        idle_map = {}
        for idle in idle_sessions:
            if idle.user_id not in idle_map:
                idle_map[idle.user_id] = []
            idle_map[idle.user_id].append(idle)

        task_times = TaskTime.objects.filter(company=company, start_time__date=target_date)
        task_time_map = {}
        for tt in task_times:
            if tt.user_id not in task_time_map:
                task_time_map[tt.user_id] = []
            task_time_map[tt.user_id].append(tt)

        headers = [
            "Employee",
            "Date",
            "Clock In",
            "Clock Out",
            "Break In",
            "Break Out",
            "Total Break",
            "Task Time",
            "Total Hours"
        ]

        rows = []
        for u in users_list:
            full_name = f"{u.first_name} {u.last_name}".strip() or u.username or u.email
            session = session_map.get(u.id)

            clock_in_str = "-"
            clock_out_str = "-"
            break_in_str = "-"
            break_out_str = "-"
            work_seconds = 0
            break_seconds = 0
            task_seconds = 0

            if session:
                if session.clock_in:
                    clock_in_str = timezone.localtime(session.clock_in).strftime("%I:%M %p")
                if session.clock_out:
                    clock_out_str = timezone.localtime(session.clock_out).strftime("%I:%M %p")
                    work_seconds = int(session.total_work_time.total_seconds()) if session.total_work_time else int((session.clock_out - session.clock_in).total_seconds())
                elif session.clock_in:
                    work_seconds = int((timezone.now() - session.clock_in).total_seconds())

            u_idles = idle_map.get(u.id, [])
            if u_idles:
                earliest_idle = min(u_idles, key=lambda x: x.idle_start_time)
                latest_idle = max(u_idles, key=lambda x: x.idle_end_time or x.idle_start_time)
                break_in_str = timezone.localtime(earliest_idle.idle_start_time).strftime("%I:%M %p")
                if latest_idle.idle_end_time:
                    break_out_str = timezone.localtime(latest_idle.idle_end_time).strftime("%I:%M %p")
                for idle in u_idles:
                    if idle.duration:
                        break_seconds += int(idle.duration.total_seconds())
                    elif idle.idle_end_time:
                        break_seconds += int((idle.idle_end_time - idle.idle_start_time).total_seconds())

            u_tasks = task_time_map.get(u.id, [])
            for tt in u_tasks:
                if tt.duration:
                    task_seconds += int(tt.duration.total_seconds())
                elif tt.end_time:
                    task_seconds += int((tt.end_time - tt.start_time).total_seconds())
                elif tt.start_time:
                    task_seconds += int((timezone.now() - tt.start_time).total_seconds())

            b_mins = max(0, break_seconds // 60)
            total_break_str = f"{b_mins} min"
            t_hours = max(0, task_seconds // 3600)
            t_mins = max(0, (task_seconds % 3600) // 60)
            task_time_str = f"{t_hours}h {t_mins}min" if t_hours > 0 else f"{t_mins}min"
            w_hours = max(0, work_seconds // 3600)
            w_mins = max(0, (work_seconds % 3600) // 60)
            total_hours_str = f"{w_hours:02d}h {w_mins:02d}min"

            rows.append([
                full_name,
                target_date.strftime("%d %b %Y"),
                clock_in_str,
                clock_out_str,
                break_in_str,
                break_out_str,
                total_break_str,
                task_time_str,
                total_hours_str
            ])

        return export_to_excel(
            filename=f"all_reports_{target_date}",
            headers=headers,
            rows=rows
        )
    except Exception:
        traceback.print_exc()
        raise


@api_view(["GET"])
@permission_classes([IsAdminOrProjectLead])
def export_reports_pdf(request):
    try:
        user = request.user
        company = user.company
        is_admin_or_project_lead = user.role in [
                "admin",
                "super_admin",
                "project_lead",
            ]

        date_str = request.GET.get("date")
        team_param = request.GET.get("team")
        user_param = request.GET.get("user")
        search_query = request.GET.get("search", "").strip()

        if date_str:
            try:
                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                target_date = timezone.localdate()
        else:
            target_date = timezone.localdate()

        users_qs = User.objects.filter(company=company, is_active=True)
        if not is_admin_or_project_lead:
            users_qs = users_qs.filter(id=user.id)
        elif user_param and user_param not in ["All Users", "All"]:
            users_qs = users_qs.filter(id=user_param)

        if team_param and team_param not in ["All Teams", "All"]:
            if team_param.isdigit():
                users_qs = users_qs.filter(team_id=team_param)
            else:
                users_qs = users_qs.filter(team__team_name=team_param)

        if search_query:
            users_qs = users_qs.filter(
                Q(first_name__icontains=search_query) |
                Q(last_name__icontains=search_query) |
                Q(username__icontains=search_query) |
                Q(email__icontains=search_query)
            )

        users_list = list(users_qs.select_related("team"))
        sessions = WorkSession.objects.filter(company=company, work_date=target_date)
        session_map = {s.user_id: s for s in sessions}

        idle_sessions = IdleSession.objects.filter(company=company, idle_start_time__date=target_date)
        idle_map = {}
        for idle in idle_sessions:
            if idle.user_id not in idle_map:
                idle_map[idle.user_id] = []
            idle_map[idle.user_id].append(idle)

        task_times = TaskTime.objects.filter(company=company, start_time__date=target_date)
        task_time_map = {}
        for tt in task_times:
            if tt.user_id not in task_time_map:
                task_time_map[tt.user_id] = []
            task_time_map[tt.user_id].append(tt)

        headers = [
            "Employee",
            "Date",
            "Clock In",
            "Clock Out",
            "Break In",
            "Break Out",
            "Total Break",
            "Task Time",
            "Total Hours"
        ]

        rows = []
        for u in users_list:
            full_name = f"{u.first_name} {u.last_name}".strip() or u.username or u.email
            session = session_map.get(u.id)

            clock_in_str = "-"
            clock_out_str = "-"
            break_in_str = "-"
            break_out_str = "-"
            work_seconds = 0
            break_seconds = 0
            task_seconds = 0

            if session:
                if session.clock_in:
                    clock_in_str = timezone.localtime(session.clock_in).strftime("%I:%M %p")
                if session.clock_out:
                    clock_out_str = timezone.localtime(session.clock_out).strftime("%I:%M %p")
                    work_seconds = int(session.total_work_time.total_seconds()) if session.total_work_time else int((session.clock_out - session.clock_in).total_seconds())
                elif session.clock_in:
                    work_seconds = int((timezone.now() - session.clock_in).total_seconds())

            u_idles = idle_map.get(u.id, [])
            if u_idles:
                earliest_idle = min(u_idles, key=lambda x: x.idle_start_time)
                latest_idle = max(u_idles, key=lambda x: x.idle_end_time or x.idle_start_time)
                break_in_str = timezone.localtime(earliest_idle.idle_start_time).strftime("%I:%M %p")
                if latest_idle.idle_end_time:
                    break_out_str = timezone.localtime(latest_idle.idle_end_time).strftime("%I:%M %p")
                for idle in u_idles:
                    if idle.duration:
                        break_seconds += int(idle.duration.total_seconds())
                    elif idle.idle_end_time:
                        break_seconds += int((idle.idle_end_time - idle.idle_start_time).total_seconds())

            u_tasks = task_time_map.get(u.id, [])
            for tt in u_tasks:
                if tt.duration:
                    task_seconds += int(tt.duration.total_seconds())
                elif tt.end_time:
                    task_seconds += int((tt.end_time - tt.start_time).total_seconds())
                elif tt.start_time:
                    task_seconds += int((timezone.now() - tt.start_time).total_seconds())

            b_mins = max(0, break_seconds // 60)
            total_break_str = f"{b_mins} min"
            t_hours = max(0, task_seconds // 3600)
            t_mins = max(0, (task_seconds % 3600) // 60)
            task_time_str = f"{t_hours}h {t_mins}min" if t_hours > 0 else f"{t_mins}min"
            w_hours = max(0, work_seconds // 3600)
            w_mins = max(0, (work_seconds % 3600) // 60)
            total_hours_str = f"{w_hours:02d}h {w_mins:02d}min"

            rows.append([
                full_name,
                target_date.strftime("%d %b %Y"),
                clock_in_str,
                clock_out_str,
                break_in_str,
                break_out_str,
                total_break_str,
                task_time_str,
                total_hours_str
            ])

        return export_to_pdf(
            filename=f"all_reports_{target_date}",
            title=f"All Reports - {target_date.strftime('%d %b %Y')}",
            headers=headers,
            rows=rows
        )
    except Exception:
        traceback.print_exc()
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Shared helper to build per-day rows for a date range
# ─────────────────────────────────────────────────────────────────────────────

def _build_report_rows_for_range(company, users_list, start_date, end_date):
    """Return (headers, rows) for every work-day in [start_date, end_date]."""
    from datetime import timedelta as td

    sessions = WorkSession.objects.filter(
        company=company,
        work_date__range=(start_date, end_date)
    )
    # {(user_id, work_date): session}
    session_map = {(s.user_id, s.work_date): s for s in sessions}

    idle_sessions = IdleSession.objects.filter(
        company=company,
        idle_start_time__date__range=(start_date, end_date)
    )
    idle_map = {}
    for idle in idle_sessions:
        key = (idle.user_id, idle.idle_start_time.date())
        idle_map.setdefault(key, []).append(idle)

    task_times = TaskTime.objects.filter(
        company=company,
        start_time__date__range=(start_date, end_date)
    )
    task_time_map = {}
    for tt in task_times:
        key = (tt.user_id, tt.start_time.date())
        task_time_map.setdefault(key, []).append(tt)

    headers = [
        "Employee", "Date", "Clock In", "Clock Out",
        "Break In", "Break Out", "Total Break", "Task Time", "Total Hours"
    ]

    rows = []
    current = start_date
    while current <= end_date:
        for u in users_list:
            full_name = f"{u.first_name} {u.last_name}".strip() or u.username or u.email
            session = session_map.get((u.id, current))

            clock_in_str = "-"
            clock_out_str = "-"
            break_in_str = "-"
            break_out_str = "-"
            work_seconds = 0
            break_seconds = 0
            task_seconds = 0

            if session:
                if session.clock_in:
                    clock_in_str = timezone.localtime(session.clock_in).strftime("%I:%M %p")
                if session.clock_out:
                    clock_out_str = timezone.localtime(session.clock_out).strftime("%I:%M %p")
                    work_seconds = int(session.total_work_time.total_seconds()) if session.total_work_time else int((session.clock_out - session.clock_in).total_seconds())
                elif session.clock_in:
                    work_seconds = int((timezone.now() - session.clock_in).total_seconds())

            u_idles = idle_map.get((u.id, current), [])
            if u_idles:
                earliest = min(u_idles, key=lambda x: x.idle_start_time)
                latest = max(u_idles, key=lambda x: x.idle_end_time or x.idle_start_time)
                break_in_str = timezone.localtime(earliest.idle_start_time).strftime("%I:%M %p")
                if latest.idle_end_time:
                    break_out_str = timezone.localtime(latest.idle_end_time).strftime("%I:%M %p")
                for idle in u_idles:
                    if idle.duration:
                        break_seconds += int(idle.duration.total_seconds())
                    elif idle.idle_end_time:
                        break_seconds += int((idle.idle_end_time - idle.idle_start_time).total_seconds())

            u_tasks = task_time_map.get((u.id, current), [])
            for tt in u_tasks:
                if tt.duration:
                    task_seconds += int(tt.duration.total_seconds())
                elif tt.end_time:
                    task_seconds += int((tt.end_time - tt.start_time).total_seconds())
                elif tt.start_time:
                    task_seconds += int((timezone.now() - tt.start_time).total_seconds())

            b_mins = max(0, break_seconds // 60)
            t_h = max(0, task_seconds // 3600)
            t_m = max(0, (task_seconds % 3600) // 60)
            w_h = max(0, work_seconds // 3600)
            w_m = max(0, (work_seconds % 3600) // 60)

            rows.append([
                full_name,
                current.strftime("%d %b %Y"),
                clock_in_str,
                clock_out_str,
                break_in_str,
                break_out_str,
                f"{b_mins} min",
                f"{t_h}h {t_m}min" if t_h > 0 else f"{t_m}min",
                f"{w_h:02d}h {w_m:02d}min",
            ])

        current += td(days=1)

    return headers, rows


def _get_filtered_users(request):
    """Return (company, users_qs) applying team/user/search params."""
    user = request.user
    company = user.company
    is_admin = user.role in ["admin", "super_admin"]
    team_param = request.GET.get("team")
    user_param = request.GET.get("user")
    search_query = request.GET.get("search", "").strip()

    users_qs = User.objects.filter(company=company, is_active=True)
    if not is_admin:
        users_qs = users_qs.filter(id=user.id)
    elif user_param and user_param not in ["All Users", "All"]:
        users_qs = users_qs.filter(id=user_param)

    if team_param and team_param not in ["All Teams", "All"]:
        if team_param.isdigit():
            users_qs = users_qs.filter(team_id=team_param)
        else:
            users_qs = users_qs.filter(team__team_name=team_param)

    if search_query:
        users_qs = users_qs.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    return company, list(users_qs.select_related("team"))


# ─────────────────────────────────────────────────────────────────────────────
# Monthly exports
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAdminOrProjectLead])
def export_monthly_excel(request):
    """
    Export monthly report as Excel.
    Query param: month=YYYY-MM  (defaults to current month)
    """
    try:
        from datetime import date
        import calendar

        month_str = request.GET.get("month")
        if month_str:
            try:
                year, month = int(month_str.split("-")[0]), int(month_str.split("-")[1])
            except (ValueError, IndexError):
                today = timezone.localdate()
                year, month = today.year, today.month
        else:
            today = timezone.localdate()
            year, month = today.year, today.month

        start_date = date(year, month, 1)
        end_date = date(year, month, calendar.monthrange(year, month)[1])
        label = start_date.strftime("%B %Y")

        company, users_list = _get_filtered_users(request)
        headers, rows = _build_report_rows_for_range(company, users_list, start_date, end_date)

        return export_to_excel(
            filename=f"monthly_report_{year}_{month:02d}",
            headers=headers,
            rows=rows
        )
    except Exception:
        traceback.print_exc()
        raise


@api_view(["GET"])
@permission_classes([IsAdminOrProjectLead])
def export_monthly_pdf(request):
    """
    Export monthly report as PDF.
    Query param: month=YYYY-MM  (defaults to current month)
    """
    try:
        from datetime import date
        import calendar

        month_str = request.GET.get("month")
        if month_str:
            try:
                year, month = int(month_str.split("-")[0]), int(month_str.split("-")[1])
            except (ValueError, IndexError):
                today = timezone.localdate()
                year, month = today.year, today.month
        else:
            today = timezone.localdate()
            year, month = today.year, today.month

        start_date = date(year, month, 1)
        end_date = date(year, month, calendar.monthrange(year, month)[1])
        label = start_date.strftime("%B %Y")

        company, users_list = _get_filtered_users(request)
        headers, rows = _build_report_rows_for_range(company, users_list, start_date, end_date)

        return export_to_pdf(
            filename=f"monthly_report_{year}_{month:02d}",
            title=f"Monthly Report - {label}",
            headers=headers,
            rows=rows
        )
    except Exception:
        traceback.print_exc()
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Yearly exports
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAdminOrProjectLead])
def export_yearly_excel(request):
    """
    Export yearly report as Excel.
    Query param: year=YYYY  (defaults to current year)
    """
    try:
        from datetime import date

        year_str = request.GET.get("year")
        try:
            year = int(year_str) if year_str else timezone.localdate().year
        except (ValueError, TypeError):
            year = timezone.localdate().year

        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)

        company, users_list = _get_filtered_users(request)
        headers, rows = _build_report_rows_for_range(company, users_list, start_date, end_date)

        return export_to_excel(
            filename=f"yearly_report_{year}",
            headers=headers,
            rows=rows
        )
    except Exception:
        traceback.print_exc()
        raise


@api_view(["GET"])
@permission_classes([IsAdminOrProjectLead])
def export_yearly_pdf(request):
    """
    Export yearly report as PDF.
    Query param: year=YYYY  (defaults to current year)
    """
    try:
        from datetime import date

        year_str = request.GET.get("year")
        try:
            year = int(year_str) if year_str else timezone.localdate().year
        except (ValueError, TypeError):
            year = timezone.localdate().year

        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)

        company, users_list = _get_filtered_users(request)
        headers, rows = _build_report_rows_for_range(company, users_list, start_date, end_date)

        return export_to_pdf(
            filename=f"yearly_report_{year}",
            title=f"Yearly Report - {year}",
            headers=headers,
            rows=rows
        )
    except Exception:
        traceback.print_exc()
        raise


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsAdminRole])
def test_email(request):
    try:
        send_email_notification(
            company=request.user.company,
            subject="SMTP Test  - Work Track Management",
            message="Congratulations! Your SMTP configuration is working successfully.",
            recipient_email=request.user.email
        )
        return Response(
            {
                "success" : True,
                "message" : "Test email sent successfully."
            },
            status=status.HTTP_200_OK
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response(
            {
                "success" : False,
                "message" : str(e)
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated, IsAdminRole])
def company_smtp_settings(request):

    company = request.user.company

    if request.method == "GET":
        serializer = CompanySMTPSerializer(company)
        return Response(serializer.data)

    serializer = CompanySMTPSerializer(
        company,
        data=request.data,
        partial=True
    )

    print("Reached serializer")

    if serializer.is_valid():
        print("Serializer Valid")

        if "smtp_password" in serializer.validated_data:
            print("Original Password:", serializer.validated_data["smtp_password"])

            encrypted = encrypt_password(serializer.validated_data["smtp_password"])

            print("Encrypted Password:", encrypted)

            serializer.save(
                smtp_password=encrypted
            )
        else:
            serializer.save()

        print("Saved Successfully")

        return Response(
            {
                "success": True,
                "message": "SMTP settings updated successfully.",
                "data": CompanySMTPSerializer(company).data
            }
        )

    print(serializer.errors)
    return Response(serializer.errors, status=400)

@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminRole])
def create_leave_policy(request):

    serializer = LeavePolicySerializer(data=request.data)

    if serializer.is_valid():

        policy_name = serializer.validated_data["policy_name"]

        if LeavePolicy.objects.filter(
            company=request.user.company,
            policy_name=policy_name
        ).exists():
            return Response(
                {"error": "Leave policy already exists."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer.save(company=request.user.company)

        return Response(
            {
                "message": "Leave policy created successfully.",
                "data": serializer.data
            },
            status=status.HTTP_201_CREATED
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def view_leave_policies(request):

    policies = LeavePolicy.objects.filter(
        company=request.user.company
    ).order_by("-created_at")

    serializer = LeavePolicySerializer(
        policies,
        many=True
    )

    return Response(serializer.data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def view_leave_policy(request, policy_id):

    try:
        policy = LeavePolicy.objects.get(
            id=policy_id,
            company=request.user.company
        )

    except LeavePolicy.DoesNotExist:
        return Response(
            {"error": "Leave policy not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = LeavePolicySerializer(policy)

    return Response(serializer.data)
@api_view(["PUT"])
@permission_classes([IsAuthenticated, IsAdminRole])
def update_leave_policy(request, policy_id):

    try:
        policy = LeavePolicy.objects.get(
            id=policy_id,
            company=request.user.company
        )

    except LeavePolicy.DoesNotExist:
        return Response(
            {"error": "Leave policy not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = LeavePolicySerializer(
        policy,
        data=request.data,
        partial=True
    )

    if serializer.is_valid():
        serializer.save()

        return Response(
            {
                "message": "Leave policy updated successfully.",
                "data": serializer.data
            }
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(["DELETE"])
@permission_classes([IsAuthenticated, IsAdminRole])
def delete_leave_policy(request, policy_id):

    try:
        policy = LeavePolicy.objects.get(
            id=policy_id,
            company=request.user.company
        )

    except LeavePolicy.DoesNotExist:
        return Response(
            {"error": "Leave policy not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    if policy.employees.exists():
        return Response(
            {
                "error": "This policy is assigned to employees and cannot be deleted."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    policy.delete()

    return Response(
        {"message": "Leave policy deleted successfully."},
        status=status.HTTP_200_OK
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminRole])
def create_team(request):

    serializer = TeamSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    team_name = serializer.validated_data["team_name"]

    # Check duplicate team name
    if Team.objects.filter(
        company=request.user.company,
        team_name=team_name
    ).exists():
        return Response(
            {"error": "Team already exists."},
            status=status.HTTP_400_BAD_REQUEST
        )

    team_lead = serializer.validated_data.get("team_lead")

    # Validate team lead company
    if team_lead and team_lead.company != request.user.company:
        return Response(
            {"error": "Team lead must belong to your company."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Validate team lead role
    if team_lead and team_lead.role not in ["admin", "project_lead"]:
        return Response(
            {
                "error": "Only Admin or Project Lead can be assigned as Team Lead."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # Validate active status
    if team_lead and not team_lead.is_active:
        return Response(
            {
                "error": "Inactive users cannot be assigned as Team Lead."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    print("===================================")
    print("Request User:", request.user)
    print("Company:", request.user.company)
    print("Company ID:", request.user.company_id)
    print("Validated Data:", serializer.validated_data)
    print("===================================")

    # CREATE TEAM
    team = serializer.save(
        company=request.user.company
    )

    # Notifications should NOT make team creation fail
    try:

        send_notification(
            company=request.user.company,
            user=request.user,
            title="Team Created",
            message=f"Team '{team.team_name}' has been created successfully.",
            notification_type="team"
        )

        send_email_notification(
            company=request.user.company,
            subject="Team Created",
            message=f"The team '{team.team_name}' has been created successfully.",
            recipient_email=request.user.email
        )

    except Exception as e:

        print(f"Team notification/email error: {e}")

    return Response(
        {
            "message": "Team created successfully.",
            "data": TeamSerializer(team).data
        },
        status=status.HTTP_201_CREATED
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def view_teams(request):

    if request.user.role in ("admin", "super_admin"):
        teams = Team.objects.filter(
            company=request.user.company
        ).order_by("team_name")
    else:
        if request.user.team:
            teams = Team.objects.filter(
                id=request.user.team.id,
                company=request.user.company
            )
        else:
            teams = Team.objects.none()

    serializer = TeamSerializer(teams, many=True)

    return Response(
        {
            "message": "Teams retrieved successfully.",
            "data": serializer.data
        },
        status=status.HTTP_200_OK
    )

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def view_team(request, team_id):

    try:
        team = Team.objects.get(
            id=team_id,
            company=request.user.company
        )

    except Team.DoesNotExist:
        return Response(
            {"error": "Team not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    if request.user.role not in ("admin", "super_admin"):
        if not request.user.team or request.user.team.id != team.id:
            return Response(
                {"error": "You do not have permission to view this team."},
                status=status.HTTP_403_FORBIDDEN
            )

    serializer = TeamSerializer(team)

    return Response(
        {
            "message": "Team retrieved successfully.",
            "data": serializer.data
        },
        status=status.HTTP_200_OK
    )

@api_view(["PUT"])
@permission_classes([IsAuthenticated,IsAdminRole])
def update_team(request, team_id):
    try:
        team = Team.objects.get(
            id=team_id,
            company=request.user.company
        )

    except Team.DoesNotExist:
        return Response(
            {"error": "Team not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = TeamSerializer(
        team,
        data=request.data,
        partial=True
    )

    if serializer.is_valid():

        team_lead = serializer.validated_data.get("team_lead")

        if team_lead and team_lead.company != request.user.company:
            return Response(
                {"error": "Team lead must belong to your company."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if team_lead and team_lead.role not in ["admin", "project_lead"]:
            return Response(
                {"error": "Only Admin or Project Lead can be assigned as Team Lead."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if team_lead and not team_lead.is_active:
            return Response(
                {"error": "Inactive users cannot be assigned as Team Lead."},
                status=status.HTTP_400_BAD_REQUEST
            )

        team_name = serializer.validated_data.get("team_name")

        if (
            team_name
            and Team.objects.filter(
                company=request.user.company,
                team_name=team_name
            ).exclude(id=team.id).exists()
        ):
            return Response(
                {"error": "Team already exists."},
                status=status.HTTP_400_BAD_REQUEST
            )
        


        team = serializer.save()
        try:

            send_notification(
                company=request.user.company,
                user=request.user,
                title="Team Updated",
                message=f"Team '{team.team_name}' has been updated successfully.",
                notification_type="team"
            )

            send_email_notification(
                company=request.user.company,
                subject="Team Updated",
                message=f"The team '{team.team_name}' has been updated successfully.",
                recipient_email=request.user.email
            )
        except Exception as e:
            print(f"Notification Error: {e}")
        return Response(
            {
                "message": "Team updated successfully.",
                "data": serializer.data
            },
            status=status.HTTP_200_OK
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(["DELETE"])
@permission_classes([IsAuthenticated, IsAdminRole])
def delete_team(request, team_id):

    try:
        team = Team.objects.get(
            id=team_id,
            company=request.user.company
        )

    except Team.DoesNotExist:
        return Response(
            {"error": "Team not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    # Don't allow deletion if employees are assigned
    if team.members.exists():
        return Response(
            {
                "error": "This team has employees assigned and cannot be deleted."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    team_name = team.team_name

    # Delete team first
    team.delete()

    # In-app notification
    try:
        send_notification(
            company=request.user.company,
            user=request.user,
            title="Team Deleted",
            message=f"Team '{team_name}' has been deleted successfully.",
            notification_type="team"
        )
    except Exception as e:
        print(f"Team deletion notification error: {e}")

    # Email notification
    try:
        send_email_notification(
            company=request.user.company,
            subject="Team Deleted",
            message=f"Team '{team_name}' has been deleted successfully.",
            recipient_email=request.user.email
        )
    except Exception as e:
        print(f"Team deletion email error: {e}")

    return Response(
        {
            "message": "Team deleted successfully."
        },
        status=status.HTTP_200_OK
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def active_teams(request):
    
    user_company = request.user.company
    teams = Team.objects.filter(
        company=user_company,
        status__iexact="active"
    ).order_by("team_name")

    serializer = TeamSerializer(teams, many=True)

    return Response(
        {
            "message": "Active teams retrieved successfully.",
            "data": serializer.data
        },
        status=status.HTTP_200_OK
    )

@api_view(["GET"])
@permission_classes([IsAuthenticated, IsAdminRole])
def team_lead_list(request):
    users = User.objects.filter(
        company=request.user.company,
        role__in=["admin", "project_lead"],
        is_active=True
    ).select_related("company", "team")  # Prevent N+1 via UserSerializer

    serializer = UserSerializer(users, many=True)

    return Response(serializer.data)


# ─── Company Info Settings ────────────────────────────────────────────────────

@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated, IsAdminRole])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def company_info_settings(request):
    company = request.user.company
    if not company:
        return Response({"error": "Company not found."}, status=404)

    if request.method == "GET":
        serializer = CompanySerializer(company)
        return Response(serializer.data)

    serializer = CompanySerializer(company, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response({
            "success": True,
            "message": "Company settings updated successfully.",
            "data": CompanySerializer(company).data
        })
    return Response(serializer.errors, status=400)


# ─── Security Settings ────────────────────────────────────────────────────────

@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated, IsAdminRole])
def security_settings(request):
    company = request.user.company
    if not company:
        return Response({"error": "Company not found."}, status=404)

    settings_obj, _ = SecuritySettings.objects.get_or_create(company=company)

    if request.method == "GET":
        serializer = SecuritySettingsSerializer(settings_obj)
        return Response(serializer.data)

    serializer = SecuritySettingsSerializer(settings_obj, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response({
            "success": True,
            "message": "Security settings updated successfully.",
            "data": SecuritySettingsSerializer(settings_obj).data
        })
    return Response(serializer.errors, status=400)


# ─── Monitoring Settings (Admin Read + Write) ─────────────────────────────────

@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated, IsAdminRole])
def admin_monitoring_settings(request):
    company = request.user.company
    if not company:
        return Response({"error": "Company not found."}, status=404)

    settings_obj, _ = MonitoringSettings.objects.get_or_create(company=company)

    if request.method == "GET":
        serializer = MonitoringSettingsSerializer(settings_obj)
        return Response(serializer.data)

    serializer = MonitoringSettingsSerializer(settings_obj, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response({
            "success": True,
            "message": "Monitoring settings updated successfully.",
            "data": MonitoringSettingsSerializer(settings_obj).data
        })
    return Response(serializer.errors, status=400)


# ─── Account Settings (Profile update + Password change) ─────────────────────

@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def account_settings(request):
    user = request.user

    if request.method == "GET":
        serializer = UserSerializer(user)
        data = serializer.data
        # Include extra readable fields
        data["employee_id"] = f"EMP{str(user.id).zfill(3)}"
        data["company_name"] = user.company.company_name if user.company else ""
        data["team_name"] = user.team.team_name if user.team else ""
        return Response(data)

    # Handle profile photo upload and info update
    serializer = UserSerializer(user, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    updated_user = serializer.save()

    # Handle password change if provided
    current_password = request.data.get("currentPassword")
    new_password = request.data.get("newPassword")
    confirm_password = request.data.get("confirmPassword")

    if current_password or new_password or confirm_password:
        if not current_password:
            return Response({"error": "Current password is required to change password."}, status=400)
        if not updated_user.check_password(current_password):
            return Response({"error": "Current password is incorrect."}, status=400)
        if new_password != confirm_password:
            return Response({"error": "New passwords do not match."}, status=400)
        if len(new_password) < 6:
            return Response({"error": "New password must be at least 6 characters."}, status=400)
        updated_user.set_password(new_password)
        updated_user.save()

    return Response({
        "success": True,
        "message": "Account updated successfully.",
        "data": UserSerializer(updated_user).data
    })


# ─── Global Search ─────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def global_search(request):
    query = request.GET.get("q", "").strip()
    if not query:
        return Response({
            "employees": [],
            "projects": [],
            "tasks": [],
            "teams": []
        })

    company = request.user.company

    # 1. Employees
    emp_qs = User.objects.filter(is_active=True)
    if company:
        emp_qs = emp_qs.filter(company=company)

    employees = emp_qs.filter(
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query) |
        Q(email__icontains=query) |
        Q(username__icontains=query)
    )[:6]

    emp_data = []
    for emp in employees:
        pic = None
        if emp.profile_picture:
            try:
                pic = emp.profile_picture.url
            except Exception:
                pic = None
        full_name = f"{emp.first_name} {emp.last_name}".strip() or emp.username or emp.email
        emp_data.append({
            "id": emp.id,
            "name": full_name,
            "email": emp.email,
            "role": emp.role,
            "profile_picture": pic
        })

    # 2. Projects
    proj_qs = Project.objects.all()
    if company:
        proj_qs = proj_qs.filter(company=company)

    projects = proj_qs.filter(
        Q(project_name__icontains=query) |
        Q(description__icontains=query)
    )[:6]

    proj_data = [{
        "id": p.id,
        "name": p.project_name,
        "status": p.status,
        "priority": p.priority
    } for p in projects]

    # 3. Tasks
    task_qs = Task.objects.all()
    if company:
        task_qs = task_qs.filter(company=company)

    tasks = task_qs.filter(
        Q(task_name__icontains=query) |
        Q(description__icontains=query)
    )[:6]

    task_data = [{
        "id": t.id,
        "name": t.task_name,
        "status": t.status,
        "priority": t.priority,
        "project_id": t.project.id if t.project else None
    } for t in tasks]

    # 4. Teams
    team_qs = Team.objects.all()
    if company:
        team_qs = team_qs.filter(company=company)

    teams = team_qs.filter(
        Q(team_name__icontains=query) |
        Q(description__icontains=query)
    )[:6]

    team_data = [{
        "id": tm.id,
        "name": tm.team_name,
        "status": tm.status
    } for tm in teams]

    return Response({
        "employees": emp_data,
        "projects": proj_data,
        "tasks": task_data,
        "teams": team_data
    })


from rest_framework.renderers import BaseRenderer, JSONRenderer, BrowsableAPIRenderer
from rest_framework.decorators import renderer_classes


class ProductivityPDFRenderer(BaseRenderer):
    media_type = "application/pdf"
    format = "pdf"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


class ProductivityExcelRenderer(BaseRenderer):
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    format = "excel"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@renderer_classes([JSONRenderer, BrowsableAPIRenderer, ProductivityPDFRenderer, ProductivityExcelRenderer])
def export_employee_productivity(
    request,
    user_id
):

    logged_user = request.user
    company = logged_user.company

    # =====================================================
    # EMPLOYEE
    # =====================================================

    employee = get_object_or_404(
        User,
        id=user_id,
        company=company,
        is_active=True
    )

    # =====================================================
    # RBAC
    # =====================================================

    if logged_user.role == "admin":

        allowed = True

    elif logged_user.id == employee.id:

        allowed = True

    else:

        allowed = False

        # Teams led by current user
        teams_led = Team.objects.filter(
            company=company,
            team_lead=logged_user
        )

        if User.objects.filter(
            company=company,
            id=employee.id,
            team__in=teams_led
        ).exists():

            allowed = True

        # Projects led by current user
        if not allowed:

            lead_projects = Project.objects.filter(
                company=company,
                assigned_to=logged_user
            )

            if Task.objects.filter(
                company=company,
                project__in=lead_projects,
                assigned_to=employee
            ).exists():

                allowed = True

        # Project team
        if not allowed:

            lead_projects = Project.objects.filter(
                company=company,
                assigned_to=logged_user,
                team__isnull=False
            )

            team_ids = lead_projects.values_list(
                "team_id",
                flat=True
            )

            if User.objects.filter(
                company=company,
                id=employee.id,
                team__in=team_ids
            ).exists():

                allowed = True

    if not allowed:

        return Response(
            {
                "detail":
                "You do not have permission "
                "to export this employee's "
                "productivity."
            },
            status=status.HTTP_403_FORBIDDEN
        )

    # =====================================================
    # PARAMETERS
    # =====================================================

    period = (
        request.GET.get("period")
        or "daily"
    ).lower()

    export_format = (
        request.GET.get("format")
        or request.GET.get("export_format")
        or request.GET.get("file_format")
        or "excel"
    ).lower()

    date_str = request.GET.get(
        "date"
    )

    # =====================================================
    # VALIDATION
    # =====================================================

    if period not in (
        "daily",
        "weekly",
        "monthly"
    ):

        return Response(
            {
                "detail":
                "Invalid period. "
                "Use daily, weekly or monthly."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    if export_format not in (
        "excel",
        "pdf"
    ):

        return Response(
            {
                "detail":
                "Invalid format. "
                "Use excel or pdf."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # =====================================================
    # SELECTED DATE
    # =====================================================

    if date_str:

        try:

            selected_date = datetime.strptime(
                date_str,
                "%Y-%m-%d"
            ).date()

        except ValueError:

            return Response(
                {
                    "detail":
                    "Invalid date. "
                    "Use YYYY-MM-DD."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    else:

        selected_date = timezone.localdate()

    # =====================================================
    # DATE RANGE
    # =====================================================

    start_date, end_date = (
        get_report_date_range(
            period,
            selected_date
        )
    )

    # =====================================================
    # BUILD DATA
    # =====================================================

    report_data = (
        build_productivity_data(
            employee=employee,
            company=company,
            start_date=start_date,
            end_date=end_date
        )
    )

    # =====================================================
    # FILENAME
    # =====================================================

    employee_name = (
        employee.get_full_name()
        or employee.username
        or employee.email
    )

    safe_name = "".join(
        character
        if character.isalnum()
        else "_"
        for character in employee_name
    )

    filename = (
        f"{safe_name}_"
        f"productivity_"
        f"{period}_"
        f"{start_date}_"
        f"{end_date}"
    )

    # =====================================================
    # EXPORT
    # =====================================================

    if export_format == "excel":

        return generate_productivity_excel(
            report_data,
            filename
        )

    return generate_productivity_pdf(
        report_data,
        filename
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def team_details(request, team_id):

    company = request.user.company

    team = get_object_or_404(
        Team,
        id=team_id,
        company=company
    )

    if request.user.role not in ("admin", "super_admin"):
        if not request.user.team or request.user.team.id != team.id:
            return Response(
                {"error": "You do not have permission to view details for this team."},
                status=status.HTTP_403_FORBIDDEN
            )

    # ==========================================
    # MEMBERS
    # ==========================================

    members = User.objects.filter(
        company=company,
        team=team,
        is_active=True
    ).exclude(
        id=team.team_lead.id if team.team_lead else None
    )

    member_data = []

    for member in members:

        full_name = (
            f"{member.first_name} {member.last_name}"
        ).strip()

        name = (
            full_name
            or member.username
            or member.email
        )

        profile_picture = None

        if member.profile_picture:

            try:
                profile_picture = member.profile_picture.url
            except Exception:
                profile_picture = str(
                    member.profile_picture
                )

        member_data.append({
            "id": member.id,
            "name": name,
            "email": member.email,
            "role": member.role,
            "profile_picture": (
                profile_picture
                or "/employee pic.svg"
            )
        })

    # ==========================================
    # PROJECTS
    # ==========================================

    projects = Project.objects.filter(
        company=company,
        team=team
    ).order_by("-id")

    project_data = []

    for project in projects:

        tasks = Task.objects.filter(
            company=company,
            project=project
        )

        total_tasks = tasks.count()

        completed_tasks = tasks.filter(
            status__iexact="Completed"
        ).count()

        project_data.append({
            "id": project.id,
            "project_name": project.project_name,
            "description": project.description,
            "due_date": project.due_date,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "pending_tasks": (
                total_tasks - completed_tasks
            )
        })

    # ==========================================
    # TASKS
    # ==========================================

    tasks = Task.objects.filter(
        company=company,
        project__team=team
    ).distinct().order_by("-id")

    task_data = []

    for task in tasks:

        assigned_users = []

        for employee in task.assigned_to.all():

            full_name = (
                f"{employee.first_name} "
                f"{employee.last_name}"
            ).strip()

            assigned_users.append({
                "id": employee.id,
                "name": (
                    full_name
                    or employee.username
                    or employee.email
                )
            })

        task_data.append({
            "id": task.id,
            "task_name": task.task_name,
            "status": task.status,
            "priority": task.priority,
            "due_date": task.due_date,
            "project_name": (
                task.project.project_name
                if task.project
                else None
            ),
            "assigned_to": assigned_users
        })

    # ==========================================
    # TEAM LEAD
    # ==========================================

    team_lead = None

    if team.team_lead:

        lead = team.team_lead

        full_name = (
            f"{lead.first_name} {lead.last_name}"
        ).strip()

        profile_picture = None

        if lead.profile_picture:
            try:
                profile_picture = lead.profile_picture.url
            except Exception:
                profile_picture = str(lead.profile_picture)

        team_lead = {
            "id": lead.id,
            "name": (
                full_name
                or lead.username
                or lead.email
            ),
            "email": lead.email,
            "profile_picture": (
                profile_picture
                or "/employee pic.svg"
            )
        }

    # ==========================================
    # COUNTS
    # ==========================================

    total_tasks = len(task_data)

    completed_tasks = sum(
        1
        for task in task_data
        if str(task["status"]).lower() == "completed"
    )

    return Response({

        "team": {
            "id": team.id,
            "team_name": team.team_name,
            "description": team.description,
            "status": team.status,
            "team_lead": team_lead
        },

        "summary": {
            "members": len(member_data),
            "projects": len(project_data),
            "tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "pending_tasks": (
                total_tasks - completed_tasks
            )
        },

        "members": member_data,

        "projects": project_data,

        "tasks": task_data

    }, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([])
def health_check(request):
    """
    Lightweight health check endpoint for monitoring services and Render keep-alive pings.
    Does not perform heavy database queries.
    """
    return Response({
        "status": "healthy",
        "timestamp": timezone.now().isoformat()
    }, status=status.HTTP_200_OK)