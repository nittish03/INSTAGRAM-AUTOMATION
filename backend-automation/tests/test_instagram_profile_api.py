"""Per-user Instagram profile API tests.

Covers the multi-tenant rules for ``/api/instagram-profiles/``:

- A user only sees and acts on profiles they own.
- A user can own multiple profiles (the model is now a FK, not OneToOne).
- Toggle and delete on someone else's profile returns 404 (not 403, so we don't
  leak existence) and never mutates anything.
- Create attributes the new profile to ``request.user`` regardless of any
  ``userId`` the client sends, and rejects duplicate ``instagram_username`` for
  the same owner.
"""
from __future__ import annotations

import os

os.environ.setdefault("LEADPILOT_ENCRYPTION_KEY", "a" * 32)

import json

from django.contrib.auth.models import User
from django.test import Client, TestCase

from linkedin.models import InstagramProfile


class InstagramProfileApiTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="pw1234567890")
        self.bob = User.objects.create_user(username="bob", password="pw1234567890")

        self.alice_profile_1 = InstagramProfile.objects.create(
            user=self.alice,
            instagram_username="alice-1@example.com",
            instagram_password="secret",
        )
        self.alice_profile_2 = InstagramProfile.objects.create(
            user=self.alice,
            instagram_username="alice-2@example.com",
            instagram_password="secret",
        )
        self.bob_profile = InstagramProfile.objects.create(
            user=self.bob,
            instagram_username="bob-1@example.com",
            instagram_password="secret",
        )

        self.client = Client()

    def _login(self, user: User) -> None:
        self.assertTrue(self.client.login(username=user.username, password="pw1234567890"))

    def test_instagram_canonical_path_lists_owned_profiles(self):
        self._login(self.alice)
        response = self.client.get("/api/instagram-profiles/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        item = data["items"][0]
        self.assertIn("username", item)
        self.assertIn("instagramUsername", item)
        self.assertEqual(item["username"], item["instagramUsername"])

    def test_list_returns_only_owned_profiles(self):
        self._login(self.alice)
        response = self.client.get("/api/instagram-profiles/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        ids = {item["id"] for item in data["items"]}
        self.assertEqual(
            ids,
            {self.alice_profile_1.id, self.alice_profile_2.id},
            "alice must only see her own profiles",
        )
        for item in data["items"]:
            self.assertEqual(item["djangoUser"], "alice")

    def test_other_user_sees_only_their_own_profiles(self):
        self._login(self.bob)
        response = self.client.get("/api/instagram-profiles/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["id"], self.bob_profile.id)

    def test_unauthenticated_get_redirects_to_login(self):
        response = self.client.get("/api/instagram-profiles/")
        # @login_required redirects unauthenticated requests
        self.assertIn(response.status_code, {302, 401, 403})

    def test_create_attributes_profile_to_request_user(self):
        self._login(self.alice)
        payload = {
            "instagramUsername": "alice-3@example.com",
            "instagramPassword": "secret",
            # Adversarial: client tries to plant the profile on bob.
            "userId": self.bob.id,
            "user": "bob",
            "dmDailyLimit": 12,
        }
        response = self.client.post(
            "/api/instagram-profiles/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        item = response.json()["item"]
        self.assertEqual(item["djangoUser"], "alice")
        self.assertEqual(item["instagramUsername"], "alice-3@example.com")
        self.assertEqual(item["dmDailyLimit"], 12)
        # Follow limits are unused (DM-only); omitted payload uses model defaults.
        self.assertEqual(
            item["followDailyLimit"],
            InstagramProfile._meta.get_field("follow_daily_limit").default,
        )
        self.assertEqual(
            item["followWeeklyLimit"],
            InstagramProfile._meta.get_field("follow_weekly_limit").default,
        )

        created = InstagramProfile.objects.get(pk=item["id"])
        self.assertEqual(created.user, self.alice)

    def test_create_rejects_duplicate_username_for_same_user(self):
        self._login(self.alice)
        payload = {
            "instagramUsername": "alice-1@example.com",  # already owned by alice
            "instagramPassword": "secret",
        }
        response = self.client.post(
            "/api/instagram-profiles/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json()["ok"])

    def test_different_users_can_register_same_username(self):
        # Bob is allowed to register a Instagram handle alice already owns.
        self._login(self.bob)
        payload = {
            "instagramUsername": "alice-1@example.com",
            "instagramPassword": "secret",
        }
        response = self.client.post(
            "/api/instagram-profiles/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        bobs_new = InstagramProfile.objects.get(
            user=self.bob, instagram_username="alice-1@example.com"
        )
        self.assertNotEqual(bobs_new.id, self.alice_profile_1.id)

    def test_create_rejects_missing_required_fields(self):
        self._login(self.alice)
        response = self.client.post(
            "/api/instagram-profiles/",
            data=json.dumps({"instagramUsername": ""}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_toggle_only_works_on_owned_profile(self):
        self._login(self.alice)
        response = self.client.post(
            f"/api/instagram-profiles/{self.bob_profile.id}/toggle/",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404, "must not leak others' profiles")

        self.bob_profile.refresh_from_db()
        self.assertTrue(self.bob_profile.active, "bob's profile must remain untouched")

    def test_toggle_flips_active_for_owner(self):
        self._login(self.alice)
        response = self.client.post(
            f"/api/instagram-profiles/{self.alice_profile_1.id}/toggle/",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.alice_profile_1.refresh_from_db()
        self.assertFalse(self.alice_profile_1.active)

    def test_delete_only_works_on_owned_profile(self):
        self._login(self.alice)
        response = self.client.delete(
            f"/api/instagram-profiles/{self.bob_profile.id}/",
        )
        self.assertEqual(response.status_code, 404)

        # Bob's profile is intact.
        self.assertTrue(InstagramProfile.objects.filter(pk=self.bob_profile.id).exists())

    def test_delete_owner_succeeds_and_removes_record(self):
        self._login(self.alice)
        target_id = self.alice_profile_2.id
        response = self.client.delete(f"/api/instagram-profiles/{target_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertFalse(InstagramProfile.objects.filter(pk=target_id).exists())

    def test_user_can_own_multiple_profiles(self):
        # Sanity: the schema must allow >1 InstagramProfile per Django user.
        # (Was OneToOneField pre-migration; now ForeignKey.)
        self.assertEqual(self.alice.instagram_profiles.count(), 2)
        # Adding a third still works.
        InstagramProfile.objects.create(
            user=self.alice,
            instagram_username="alice-x@example.com",
            instagram_password="secret",
        )
        self.assertEqual(self.alice.instagram_profiles.count(), 3)
