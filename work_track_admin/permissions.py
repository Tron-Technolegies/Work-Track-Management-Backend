from rest_framework.permissions import BasePermission

class IsAdminRole(BasePermission):
    """
    Allows access only to users with the admin role.
    """
    message = "Admin access only."

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role in ['admin', 'super_admin']
        )
    
class IsProjectLeadRole(BasePermission):
    """
    Allows access only to users with the project lead role.
    """
    message = "Project Lead access only."
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and 
            request.user.role == "project_lead"
        )

class IsEmployeeRole(BasePermission):
    """
    Allows access to users with the employee or project lead role.
    """
    message = "Employee access only."
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and 
            request.user.role in ["user", "employee", "project_lead"]
        )


class IsAdminOrProjectLead(BasePermission):
    """
    Allows access only to users with the admin or project lead role.
    """
    message = "Admin or Project Lead access only."
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role in ['admin', 'super_admin', 'project_lead']
        )
    
class IsAdminOrOwner(BasePermission):
    """
    Allows access only to users with the admin or owner role.
    """
    message = "You don't have permission to access this resource."

    def has_object_permission(self, request, view, obj):
        if request.user.role == "admin":
            return True

        return obj.user == request.user