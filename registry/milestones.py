from django.utils import timezone

from .models import Site

MAX_MILESTONES = 50


def recompute_progress(site):
    """If this site's progress follows its milestones, set it to the share done."""
    if not site.progress_from_milestones:
        return
    total = site.milestones.count()
    done = site.milestones.filter(completed_at__isnull=False).count()
    progress = (100 * done + total // 2) // total if total else 0
    Site.objects.filter(pk=site.pk).update(
        progress=progress, updated_at=timezone.now()
    )