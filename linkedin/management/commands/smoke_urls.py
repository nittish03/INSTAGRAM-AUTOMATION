"""GET-smoke-test staff URLs (admin + custom routes). Run: DEBUG=true python manage.py smoke_urls"""

from django.contrib import admin
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.test import Client, RequestFactory
from django.urls import reverse, NoReverseMatch


class Command(BaseCommand):
    help = "GET key admin and custom pages; exits 1 on 5xx or broken 4xx (not permission-denied add)."

    def handle(self, *args, **options):
        user, _ = User.objects.get_or_create(
            username="_smoke_tester",
            defaults={
                "email": "smoke@test.local",
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password("_smoke_urls_")
        user.save()

        factory = RequestFactory()
        base_request = factory.get("/admin/")
        base_request.user = user

        client = Client()
        client.force_login(user)

        failures = []

        def ok(code: int) -> bool:
            return code in (200, 302)

        def check(label: str, path: str) -> None:
            r = client.get(path)
            if r.status_code >= 500:
                failures.append(f"{label} {path} -> {r.status_code}")
            elif r.status_code == 404:
                failures.append(f"{label} {path} -> 404")
            elif r.status_code == 403:
                failures.append(f"{label} {path} -> 403")
            elif r.status_code == 400 and b"DisallowedHost" in r.content:
                failures.append(f"{label} {path} -> 400 DisallowedHost")
            elif not ok(r.status_code) and r.status_code not in (405,):
                failures.append(f"{label} {path} -> {r.status_code}")

        check("admin index", "/admin/")
        check("analytics", "/admin/analytics/")
        check("google connect", "/admin/google/")
        check("google sheets list", "/admin/google/sheets/")
        r_auth = client.get("/admin/google/auth/start/")
        if r_auth.status_code not in (302, 303, 307, 308, 400):
            failures.append(f"google auth start -> {r_auth.status_code}")

        for model, model_admin in admin.site._registry.items():
            opts = model._meta
            key = f"{opts.app_label}.{opts.model_name}"
            try:
                check(f"{key} changelist", reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist"))
            except NoReverseMatch as e:
                failures.append(f"{key} changelist reverse: {e}")

            if model_admin.has_add_permission(base_request):
                try:
                    check(f"{key} add", reverse(f"admin:{opts.app_label}_{opts.model_name}_add"))
                except NoReverseMatch:
                    pass

            obj = model.objects.order_by("pk").first()
            if obj is not None:
                try:
                    check(
                        f"{key} change",
                        reverse(f"admin:{opts.app_label}_{opts.model_name}_change", args=[obj.pk]),
                    )
                except NoReverseMatch as e:
                    failures.append(f"{key} change reverse: {e}")

        from linkedin.models import Campaign

        c0 = Campaign.objects.order_by("pk").first()
        if c0:
            try:
                check(
                    "campaign import leads",
                    reverse("admin:linkedin_campaign_import_leads_single", args=[c0.pk]),
                )
            except NoReverseMatch as e:
                failures.append(f"campaign import reverse: {e}")

        if failures:
            for line in failures:
                self.stderr.write(line)
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("smoke_urls: all checks passed"))
