from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from work_track_admin.models import Screenshot


class Command(BaseCommand):
    help = "Delete screenshots older than the retention period"

    def handle(self, *args, **kwargs):

        retention_days = 30

        cutoff_date = timezone.now() - timedelta(days=retention_days)

        screenshots = Screenshot.objects.filter(
            captured_at__lt=cutoff_date
        )

        deleted_count = 0

        for screenshot in screenshots:

            if screenshot.image:
                screenshot.image.delete(save=False)

            screenshot.delete()
            deleted_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"{deleted_count} screenshots deleted successfully."
            )
        )