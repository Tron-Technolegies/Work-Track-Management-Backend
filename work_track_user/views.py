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
import os
import cloudinary




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

    # Create initial application usage record
    try:
        ApplicationUsage.objects.create(
            company=request.user.company,
            user=request.user,
            work_session=session,
            application_name="Work Track Web App",
            window_title="Work Track User Dashboard"
        )
    except Exception:
        pass

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
                "clocked_in": False,
                "is_on_break": False,
                "elapsed_seconds": 0,
                "working_seconds": 0,
                "focus_seconds": 0,
                "break_seconds": 0,
                "total_session_seconds": 0,
            },
            status=status.HTTP_200_OK
        )

    now = timezone.now()
    total_session_seconds = max(0, int((now - session.clock_in).total_seconds()))

    # Check for active break/idle session
    active_idle = IdleSession.objects.filter(
        company=request.user.company,
        user=request.user,
        work_session=session,
        idle_end_time__isnull=True
    ).first()
    is_on_break = active_idle is not None

    # Calculate total break seconds for this work session
    completed_idles = IdleSession.objects.filter(
        work_session=session,
        idle_end_time__isnull=False
    )
    completed_break_seconds = sum(
        int(idle.duration.total_seconds()) if idle.duration else max(0, int((idle.idle_end_time - idle.idle_start_time).total_seconds()))
        for idle in completed_idles
    )

    current_active_break_seconds = 0
    if active_idle:
        current_active_break_seconds = max(0, int((now - active_idle.idle_start_time).total_seconds()))

    total_break_seconds = completed_break_seconds + current_active_break_seconds
    working_seconds = max(0, total_session_seconds - total_break_seconds)

    serializer = WorkSessionSerializer(session)

    return Response(
        {
            "clocked_in": True,
            "is_on_break": is_on_break,
            "elapsed_seconds": working_seconds,
            "working_seconds": working_seconds,
            "focus_seconds": working_seconds,
            "break_seconds": total_break_seconds,
            "total_session_seconds": total_session_seconds,
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

    # Cleanly stop any running application, website, or idle sessions
    for app in ApplicationUsage.objects.filter(user=request.user, end_time__isnull=True):
        try:
            app.stop()
        except Exception:
            pass

    for site in WebsiteUsage.objects.filter(user=request.user, end_time__isnull=True):
        try:
            site.stop()
        except Exception:
            pass

    for idle in IdleSession.objects.filter(user=request.user, idle_end_time__isnull=True):
        try:
            idle.stop()
        except Exception:
            pass

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
@permission_classes([IsAuthenticated])
def upload_screenshot(request):

    image = request.data.get("image")
    reason = request.data.get("reason", "periodic")

    # ---------------------------------
    # 1. Check image
    # ---------------------------------
    if not image:
        return Response(
            {
                "success": False,
                "error": "Image is required"
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # ---------------------------------
    # 2. Check active work session
    # ---------------------------------
    session = WorkSession.objects.filter(
        company=request.user.company,
        user=request.user,
        clock_out__isnull=True
    ).first()

    if not session:
        return Response(
            {
                "success": False,
                "error": "User is not clocked in"
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # ---------------------------------
    # 3. Decode Base64
    # ---------------------------------
    try:
        if ";base64," in image:
            _, imgstr = image.split(";base64,", 1)
        else:
            imgstr = image

        imgstr = imgstr.strip()

        # Fix missing Base64 padding
        imgstr += "=" * (-len(imgstr) % 4)

        image_data = base64.b64decode(
            imgstr,
            validate=True
        )

    except Exception as e:
        print("❌ Base64 decode error:", repr(e))

        return Response(
            {
                "success": False,
                "error": f"Invalid image format: {str(e)}"
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # ---------------------------------
    # 4. Upload to Cloudinary
    # ---------------------------------
    try:

        if not os.getenv("CLOUDINARY_CLOUD_NAME"):
            raise Exception(
                "CLOUDINARY_CLOUD_NAME is not configured"
            )

        filename = (
            f"{request.user.id}_"
            f"{timezone.now():%Y%m%d_%H%M%S_%f}"
        )

        upload_result = cloudinary.uploader.upload(
            image_data,
            folder="worktrack/screenshots",
            public_id=filename,
            resource_type="image"
        )

        image_identifier = upload_result.get("public_id")

        if not image_identifier:
            raise Exception(
                "Cloudinary did not return public_id"
            )

        print(
            "✅ Cloudinary upload successful:",
            image_identifier
        )

    except Exception as e:

        print(
            "❌ Cloudinary upload failed:",
            repr(e)
        )

        return Response(
            {
                "success": False,
                "error": f"Cloudinary upload failed: {str(e)}"
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    # ---------------------------------
    # 5. Save Screenshot record
    # ---------------------------------
    try:

        screenshot = Screenshot.objects.create(
            company=request.user.company,
            user=request.user,
            work_session=session,
            image=image_identifier,
            reason=reason
        )

        print(
            "✅ Screenshot saved:",
            screenshot.id
        )

    except Exception as e:

        print(
            "❌ Screenshot database error:",
            repr(e)
        )

        return Response(
            {
                "success": False,
                "error": f"Failed to save screenshot: {str(e)}"
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    # ---------------------------------
    # 6. Serialize response
    # ---------------------------------
    serializer = ScreenshotSerializer(screenshot)

    # ---------------------------------
    # 7. Notification
    # ---------------------------------
    try:

        send_notification(
            company=request.user.company,
            user=request.user,
            title="Screenshot Uploaded",
            message="A new screenshot has been uploaded.",
            notification_type="screenshot",
        )

    except Exception as e:

        print(
            "⚠️ Notification failed:",
            repr(e)
        )

    # ---------------------------------
    # 8. Success
    # ---------------------------------
    return Response(
        {
            "success": True,
            "message": "Screenshot uploaded successfully",
            "data": serializer.data
        },
        status=status.HTTP_201_CREATED
    )

@api_view(["GET"])
@permission_classes([IsAuthenticated, IsEmployeeRole])
def my_screenshots(request):
    limit = request.GET.get("limit")
    screenshots = Screenshot.objects.filter(
        company=request.user.company,
        user=request.user
    ).select_related("user", "work_session").order_by("-captured_at")

    if limit and limit.isdigit():
        screenshots = screenshots[:int(limit)]
    else:
        screenshots = screenshots[:100]

    serializer = ScreenshotSerializer(
        screenshots,
        many=True
    )

    return Response(serializer.data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def monitoring_settings(request):

    company = request.user.company
    if not company:
        from work_track_admin.models import Company
        company = Company.objects.first()

    if not company:
        return Response({"error": "No company associated with user"}, status=400)

    settings, _ = MonitoringSettings.objects.get_or_create(
        company=company
    )
    serializer = MonitoringSettingsSerializer(settings)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def blocked_apps(request):
    """Return the blocked applications config for the current user's company."""
    company = request.user.company
    if not company:
        return Response({
            "blocked_applications": [],
            "screenshot_on_blocked_app": True,
            "screenshot_interval": 300,
            "screenshot_enabled": True,
            "capture_quality": 90,
        })

    settings, _ = MonitoringSettings.objects.get_or_create(company=company)
    return Response({
        "blocked_applications": settings.blocked_applications or [],
        "screenshot_on_blocked_app": settings.screenshot_on_blocked_app,
        "screenshot_interval": settings.screenshot_interval,
        "screenshot_enabled": settings.screenshot_enabled,
        "capture_quality": settings.capture_quality,
    })


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

    # Check if idle/break session already exists
    idle = IdleSession.objects.filter(
        company=request.user.company,
        user=request.user,
        idle_end_time__isnull=True
    ).first()

    if idle:
        serializer = IdleSessionSerializer(idle)
        return Response(
            {
                "success": True,
                "message": "Break session already running.",
                "data": serializer.data
            },
            status=status.HTTP_200_OK
        )

    idle = IdleSession.objects.create(
        company=request.user.company,
        user=request.user,
        work_session=work_session
    )

    # Stop active application/website tracking during break
    for app in ApplicationUsage.objects.filter(user=request.user, end_time__isnull=True):
        try:
            app.stop()
        except Exception:
            pass

    for site in WebsiteUsage.objects.filter(user=request.user, end_time__isnull=True):
        try:
            site.stop()
        except Exception:
            pass

    serializer = IdleSessionSerializer(idle)

    send_notification(
        company=request.user.company,
        user=request.user,
        title="Break Started",
        message="You have started your break.",
        notification_type="idle",
    )

    return Response(
        {
            "success": True,
            "message": "Break session started",
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
                "message": "No active break session."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    idle.stop()

    serializer = IdleSessionSerializer(idle)
    send_notification(
        company=request.user.company,
        user=request.user,
        title="Break Ended",
        message="You have resumed work.",
        notification_type="idle",
    )

    # Calculate updated break and working seconds
    work_session = idle.work_session
    now = timezone.now()
    total_session_seconds = max(0, int((now - work_session.clock_in).total_seconds())) if work_session and work_session.clock_in else 0
    completed_idles = IdleSession.objects.filter(work_session=work_session, idle_end_time__isnull=False)
    total_break_seconds = sum(
        int(i.duration.total_seconds()) if i.duration else max(0, int((i.idle_end_time - i.idle_start_time).total_seconds()))
        for i in completed_idles
    )
    working_seconds = max(0, total_session_seconds - total_break_seconds)

    return Response(
        {
            "success": True,
            "message": "Break session ended",
            "data": serializer.data,
            "break_seconds": total_break_seconds,
            "working_seconds": working_seconds,
            "elapsed_seconds": working_seconds
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
        if (
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

    # Ensure all previous unclosed applications for this user are properly stopped with duration
    for unclosed_app in ApplicationUsage.objects.filter(user=request.user, end_time__isnull=True):
        try:
            unclosed_app.stop()
        except Exception:
            pass

    app_instance = ApplicationUsage.objects.create(
        company=request.user.company,
        user=request.user,
        work_session=work_session,
        application_name=application_name,
        window_title=window_title
    )

    serializer = ApplicationUsageSerializer(app_instance)

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

    active_app = ApplicationUsage.objects.filter(
        company=request.user.company,
        user=request.user,
        end_time__isnull=True
    ).first()

    if not active_app:
        return Response(
            {
                "success": False,
                "message": "No active application session."
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    active_app.stop()

    serializer = ApplicationUsageSerializer(active_app)

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

    # Ensure all previous unclosed websites for this user are properly stopped with duration
    for unclosed_site in WebsiteUsage.objects.filter(user=request.user, end_time__isnull=True):
        try:
            unclosed_site.stop()
        except Exception:
            pass

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
    if request.user.role in ["admin", "super_admin"]:
        return Response(
            {"error": "Administrators cannot apply for leave."},
            status=status.HTTP_403_FORBIDDEN
        )

    serializer = LeaveRequestSerializer(data=request.data)

    if serializer.is_valid():

        leave_type = get_object_or_404(
            LeaveType,
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

        # Notify all company Admins
        admins = User.objects.filter(
            company=request.user.company,
            role="admin"
        )

        applicant_name = request.user.get_full_name() or request.user.first_name or request.user.email

        for admin in admins:
            try:
                send_notification(
                    company=request.user.company,
                    user=admin,
                    title="New Leave Request",
                    message=f"{applicant_name} applied for {leave_type.name} leave ({start_date} to {end_date}).",
                    notification_type="leave_request",
                )

                full_name = f"{admin.first_name} {admin.last_name}".strip()

                send_email_notification(
                    company=request.user.company,
                    subject="New Leave Request",
                    message=(
                        f"Hello {full_name or admin.username},\n\n"
                        f"A new leave request has been submitted.\n\n"
                        f"Employee: {applicant_name}\n"
                        f"Email: {request.user.email}\n"
                        f"Leave Type: {leave_type.name}\n"
                        f"From: {start_date}\n"
                        f"To: {end_date}\n"
                        f"Total Days: {total_days}\n\n"
                        f"Please log in to Work Track Management to review and approve or reject the request."
                    ),
                    recipient_email=admin.email,
                )
            except Exception as e:
                print(f"Admin notification failed: {e}")

        # If employee belongs to a team with a team lead (and team lead is not the applicant)
        if request.user.team and request.user.team.team_lead and request.user.team.team_lead != request.user:
            team_lead = request.user.team.team_lead
            try:
                send_notification(
                    company=request.user.company,
                    user=team_lead,
                    title="Team Member Leave Request",
                    message=f"{applicant_name} ({request.user.team.team_name}) applied for {leave_type.name} leave.",
                    notification_type="leave_request",
                )
            except Exception as e:
                print(f"Team lead notification failed: {e}")

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