from email.mime import application

from django.shortcuts import render

from django.utils import timezone
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
import traceback

from work_track_admin.models import WebsiteUsage, WorkSession,Screenshot,ApplicationUsage
from work_track_admin.serializers import WebsiteUsageSerializer, WorkSessionSerializer,ApplicationUsageSerializer
import base64
import cloudinary.uploader
from django.core.files.base import ContentFile

from work_track_admin.serializers import ScreenshotSerializer
from datetime import datetime
from work_track_admin.models import MonitoringSettings,IdleSession,Notification,LeaveRequest, LeaveType,User
from work_track_admin.serializers import MonitoringSettingsSerializer,IdleSessionSerializer,LeaveRequestSerializer
from work_track_admin.permissions import (IsEmployeeRole)
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from work_track_admin.notification_service import send_notification
from work_track_admin.email_service import send_email_notification



# Create your views here.
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsEmployeeRole])
def clock_in(request):

    # Check if user already has an active work session
    active_session = WorkSession.objects.filter(
        company=request.user.company,
        user=request.user,
        clock_out__isnull=True
    ).first()

    if active_session:
        return Response(
            {
                "success": False,
                "message": "You are already clocked in."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    session = WorkSession.objects.create(
        company=request.user.company,
        user=request.user
    )

    serializer = WorkSessionSerializer(session)

    send_notification(
        company=request.user.company,
        user=request.user,
        title="Clock In",
        message="You have successfully clocked in.",
        notification_type="attendance",
    )

    return Response(
        {
            "success": True,
            "message": "Clock In Successful",
            "data": serializer.data
        },
        status=status.HTTP_201_CREATED
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsEmployeeRole])
def current_session(request):

    session = WorkSession.objects.filter(
        company=request.user.company,
        user=request.user,
        clock_out__isnull=True
    ).first()

    if not session:
        return Response(
            {
                "clocked_in": False
            },
            status=status.HTTP_200_OK
        )

    elapsed = timezone.now() - session.clock_in

    serializer = WorkSessionSerializer(session)

    return Response(
        {
            "clocked_in": True,
            "elapsed_seconds": int(elapsed.total_seconds()),
            "data": serializer.data
        },
        status=status.HTTP_200_OK
    )

@api_view(["POST"])
@permission_classes([IsAuthenticated, IsEmployeeRole])
def clock_out(request):

    session = WorkSession.objects.filter(
        company=request.user.company,
        user=request.user,
        clock_out__isnull=True
    ).first()

    if not session:
        return Response(
            {
                "success": False,
                "message": "No active work session found."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    session.stop()

    serializer = WorkSessionSerializer(session)

    send_notification(
        company=request.user.company,
        user=request.user,
        title="Clock Out",
        message="You have successfully clocked out.",
        notification_type="attendance",
    )

    return Response(
        {
            "success": True,
            "message": "Clock Out Successful",
            "data": serializer.data
        },
        status=status.HTTP_200_OK
    )



@api_view(["GET"])
@permission_classes([IsAuthenticated, IsEmployeeRole])
def monitor_status(request):

    session = WorkSession.objects.filter(
        company=request.user.company,
        user=request.user,
        clock_out__isnull=True
    ).first()

    if session:
        return Response({
            "working": True
        })

    return Response({
        "working": False
    })

@api_view(["POST"])
@permission_classes([IsAuthenticated, IsEmployeeRole])
def upload_screenshot(request):

    image = request.data.get("image")
    reason = request.data.get("reason", "periodic")

    if not image:
        return Response(
            {"error": "Image is required"},
            status=400
        )

    session = WorkSession.objects.filter(
        company=request.user.company,
        user=request.user,
        clock_out__isnull=True
    ).first()

    if not session:
        return Response(
            {"error": "User is not clocked in"},
            status=400
        )

    try:
        format, imgstr = image.split(";base64,")
    except ValueError:
        return Response(
            {"error": "Invalid image format"},
            status=status.HTTP_400_BAD_REQUEST
        )

    filename = f"{request.user.id}_{timezone.now():%Y%m%d_%H%M%S}.png"

    file = ContentFile(
        base64.b64decode(imgstr),
        name=filename
    )

    screenshot = Screenshot.objects.create(
        company=request.user.company,
        user=request.user,
        work_session=session,
        image=file,
        reason=reason
    )

    serializer = ScreenshotSerializer(screenshot)

    send_notification(
        company=request.user.company,
        user=request.user,
        title="Screenshot Uploaded",
        message="A new screenshot has been uploaded.",
        notification_type="screenshot",
    )

    return Response(
        {
            "success": True,
            "data": serializer.data
        },
        status=201
    )

@api_view(["GET"])
@permission_classes([IsAuthenticated, IsEmployeeRole])
def my_screenshots(request):

    screenshots = Screenshot.objects.filter(
        company=request.user.company,
        user=request.user
    ).order_by("-captured_at")

    serializer = ScreenshotSerializer(
        screenshots,
        many=True
    )

    return Response(serializer.data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def monitoring_settings(request):

    # settings = MonitoringSettings.objects.filter(company=request.user.company,).first()
    settings = get_object_or_404(
        MonitoringSettings,
        company=request.user.company
    )
    serializer = MonitoringSettingsSerializer(settings)
    return Response(serializer.data)

    # if not settings:
    #     return Response(
    #         {"error": "Monitoring settings not found"},
    #         status=status.HTTP_404_NOT_FOUND
    #     )

    # serializer = MonitoringSettingsSerializer(settings)

    # return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsEmployeeRole])
def start_idle(request):

    # Check if user has an active work session
    work_session = WorkSession.objects.filter(
        company=request.user.company,   
        user=request.user,
        clock_out__isnull=True
    ).first()

    if not work_session:
        return Response(
            {
                "success": False,
                "message": "User is not clocked in."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # Check if idle session already exists
    idle = IdleSession.objects.filter(
        company=request.user.company,
        user=request.user,
        idle_end_time__isnull=True
    ).first()

    if idle:
        return Response(
            {
                "success": False,
                "message": "Idle session already running."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    idle = IdleSession.objects.create(
        company=request.user.company,
        user=request.user,
        work_session=work_session
    )

    serializer = IdleSessionSerializer(idle)

    send_notification(
        company=request.user.company,
        user=request.user,
        title="Idle Started",
        message="You have become idle.",
        notification_type="idle",
    )

    return Response(
        {
            "success": True,
            "message": "Idle Started",
            "data": serializer.data
        },
        status=status.HTTP_201_CREATED
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsEmployeeRole])
def end_idle(request):

    idle = IdleSession.objects.filter(
        company=request.user.company,
        user=request.user,
        idle_end_time__isnull=True
    ).first()

    if not idle:
        return Response(
            {
                "success": False,
                "message": "No active idle session."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    idle.stop()

    serializer = IdleSessionSerializer(idle)
    send_notification(
        company=request.user.company,
        user=request.user,
        title="Idle Ended",
        message="You are active again.",
        notification_type="idle",
    )

    return Response(
        {
            "success": True,
            "message": "Idle Ended",
            "data": serializer.data
        },
        status=status.HTTP_200_OK
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsEmployeeRole])
def my_idle_sessions(request):

    idle_sessions = IdleSession.objects.filter(
        company=request.user.company,
        user=request.user
    ).order_by("-idle_start_time")

    serializer = IdleSessionSerializer(
        idle_sessions,
        many=True
    )

    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsEmployeeRole])
def start_application(request):

    application_name = request.data.get("application_name")
    window_title = request.data.get("window_title","")


    if not application_name:
        return Response(
            {
                "success": False,
                "message": "Application name is required."
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    work_session = WorkSession.objects.filter(
        company=request.user.company,
        user=request.user,
        clock_out__isnull=True
    ).first()

    if not work_session:
        return Response(
            {
                "success": False,
                "message": "User is not clocked in."
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    active_application = ApplicationUsage.objects.filter(
        company=request.user.company,
        user=request.user,
        end_time__isnull=True
    ).first()


    if active_application:

        if(
            active_application.application_name == application_name and
            active_application.window_title == window_title
        ):
            return Response(
                {
                    "success": True,
                    "message": "Application already active."
                },
                status=status.HTTP_200_OK
            )
        active_application.stop()

    application_name = ApplicationUsage.objects.create(
        company=request.user.company,
        user=request.user,
        work_session=work_session,
        application_name=application_name,
        window_title=window_title
    )

    serializer = ApplicationUsageSerializer(application_name)

    return Response(
        {
            "success": True,
            "message": "Application started.",
            "data": serializer.data
        },
        status=status.HTTP_201_CREATED
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsEmployeeRole])
def end_application(request):

    application_name = ApplicationUsage.objects.filter(
        company=request.user.company,
        user=request.user,
        end_time__isnull=True
    ).first()

    if not application_name:
        return Response(
            {
                "success": False,
                "message": "No active application session."
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    application_name.stop()

    serializer = ApplicationUsageSerializer(application_name)

    return Response({
        "success": True,
        "message": "Application Ended.",
        "data": serializer.data
    },
    status=status.HTTP_200_OK
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsEmployeeRole])
def my_application_usage(request):

    applications = ApplicationUsage.objects.filter(
        company=request.user.company,
        user=request.user
    ).order_by("-start_time")

    serializer = ApplicationUsageSerializer(
        applications,
        many=True
    )

    return Response(serializer.data)



@api_view(["POST"])
@permission_classes([IsAuthenticated, IsEmployeeRole])
def start_website(request):

    browser_name = request.data.get("browser_name")
    website = request.data.get("website")
    page_title = request.data.get("page_title", "")

    if not browser_name or not website:
        return Response(
            {
                "success": False,
                "message": "Browser name and website are required."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    work_session = WorkSession.objects.filter(
        company=request.user.company,
        user=request.user,
        clock_out__isnull=True
    ).first()

    if not work_session:
        return Response(
            {
                "success": False,
                "message": "User is not clocked in."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    application = ApplicationUsage.objects.filter(
        company=request.user.company,
        user=request.user,
        end_time__isnull=True
    ).first()

    active_website = WebsiteUsage.objects.filter(
        company=request.user.company,
        user=request.user,
        end_time__isnull=True
    ).first()

    if active_website:

        if (
            active_website.website == website
            and
            active_website.page_title == page_title
        ):
            return Response(
                {
                    "success": True,
                    "message": "Website already active."
                }
            )

        active_website.stop()

    website_usage = WebsiteUsage.objects.create(
        company=request.user.company,
        user=request.user,
        work_session=work_session,
        application_usage=application,
        browser_name=browser_name,
        website=website,
        page_title=page_title
    )

    serializer = WebsiteUsageSerializer(website_usage)

    return Response(
        {
            "success": True,
            "message": "Website Started",
            "data": serializer.data
        },
        status=status.HTTP_201_CREATED
    )

@api_view(["POST"])
@permission_classes([IsAuthenticated, IsEmployeeRole])
def end_website(request):

    website = WebsiteUsage.objects.filter(
        company=request.user.company,
        user=request.user,
        end_time__isnull=True
    ).first()

    if not website:

        return Response(
            {
                "success": False,
                "message": "No active website."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    website.stop()

    serializer = WebsiteUsageSerializer(website)

    return Response(
        {
            "success": True,
            "message": "Website Ended",
            "data": serializer.data
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsEmployeeRole])
def my_websites(request):

    websites = WebsiteUsage.objects.filter(
        company=request.user.company,
        user=request.user
    ).order_by("-start_time")

    serializer = WebsiteUsageSerializer(
        websites,
        many=True
    )

    return Response(serializer.data)



@api_view(["POST"])
@permission_classes([IsAuthenticated])
def apply_leave(request):

    serializer = LeaveRequestSerializer(data=request.data)

    if serializer.is_valid():

        leave_type = get_object_or_404(
            LeaveType,
            # id=request.data.get("leave_type"),
            id=serializer.validated_data["leave_type"].id,
            company=request.user.company,
            status="active"
        )

        start_date = serializer.validated_data["start_date"]
        end_date = serializer.validated_data["end_date"]

        today = timezone.now().date()

        if start_date < today:
            return Response(
                {"error": "You cannot apply for leave in the past."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if end_date < start_date:
            return Response(
                {"error": "End date cannot be before start date."},
                status=status.HTTP_400_BAD_REQUEST
            )

        total_days = (end_date - start_date).days + 1



        existing_leave = LeaveRequest.objects.filter(
            company=request.user.company,
            employee=request.user,
            start_date__lte=end_date,
            end_date__gte=start_date,
            status__in=["pending", "approved"]
        ).exists()


        if existing_leave:
            return Response(
                {"error": "You already have a leave request for these dates."},
                status=status.HTTP_400_BAD_REQUEST
            )

        leave_request = serializer.save(
            company=request.user.company,
            employee=request.user,
            leave_type=leave_type,
            total_days=total_days,
            status="pending"
        )

        admins = User.objects.filter(
            company=request.user.company,
            role="admin"
        )

        for admin in admins:
            try:
                print(f"Sending notification to {admin.email}")

                send_notification(
                    company=request.user.company,
                    user=admin,
                    title="New Leave Request",
                    message=f"{request.user.email} applied for {leave_type.name} leave.",
                    notification_type="leave_request",
                )

                full_name = f"{admin.first_name} {admin.last_name}".strip()

                send_email_notification(
                    company=request.user.company,
                    subject="New Leave Request",
                    message=(
                        f"Hello {full_name or admin.username},\n\n"
                        f"A new leave request has been submitted.\n\n"
                        f"Employee: {request.user.first_name or request.user.username}\n"
                        f"Email: {request.user.email}\n"
                        f"Leave Type: {leave_type.name}\n"
                        f"From: {start_date}\n"
                        f"To: {end_date}\n"
                        f"Total Days: {total_days}\n\n"
                        f"Please log in to Work Track Management to review and approve or reject the request."
                    ),
                    recipient_email=admin.email,
                )

                print("Notification and email sent successfully")

            except Exception as e:
                print(f"Notification/Email failed for {admin.email}: {e}")
                traceback.print_exc()

                print("Notification sent successfully")

            except Exception as e:
                print("ERROR INSIDE send_notification()")
                traceback.print_exc()
                raise
        return Response(
            {
                "message": "Leave request submitted successfully.",
                "data": serializer.data
            },
            status=status.HTTP_201_CREATED
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_leave_requests(request):

    leave_requests = LeaveRequest.objects.filter(
        company=request.user.company,
        employee=request.user
    ).order_by("-created_at")

    serializer = LeaveRequestSerializer(
        leave_requests,
        many=True
    )

    return Response(serializer.data)

@api_view(["PUT"])
@permission_classes([IsAuthenticated])
def cancel_leave(request, pk):

    leave_request = get_object_or_404(
        LeaveRequest,
        id=pk,
        company=request.user.company,
        employee=request.user
    )

    if leave_request.status != "pending":
        return Response(
            {
                "error": "Only pending leave requests can be cancelled."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    leave_request.status = "cancelled"
    leave_request.save(update_fields=["status"])
    User = get_user_model()

    admins = User.objects.filter(
        company=request.user.company,
        role="admin"
    )

    for admin in admins:
        try:
            send_notification(
                company=request.user.company,
                user=admin,
                title="Leave Request Cancelled",
                message=f"{request.user.email} cancelled the leave request from "
                        f"{leave_request.start_date} to {leave_request.end_date}.",
                notification_type="leave_cancelled",
            )
            full_name = f"{admin.first_name} {admin.last_name}".strip()

            send_email_notification(
                company=request.user.company,
                subject="Leave Request Cancelled",
                message=(
                    f"Hello {full_name or admin.username},\n\n"
                    f"An employee has cancelled a leave request.\n\n"
                    f"Employee: {request.user.first_name or request.user.username}\n"
                    f"Email: {request.user.email}\n"
                    f"Leave Type: {leave_request.leave_type.name}\n"
                    f"From: {leave_request.start_date}\n"
                    f"To: {leave_request.end_date}\n"
                    f"Total Days: {leave_request.total_days}\n\n"
                    f"The leave request has been cancelled and no further action is required."
                ),
                recipient_email=admin.email,
            )

        except Exception as e:
            print(f"Email sending failed for {admin.email}: {e}")



    return Response(
        {
            "message": "Leave request cancelled successfully."
        },
        status=status.HTTP_200_OK
    )