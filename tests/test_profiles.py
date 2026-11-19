"""Document profile persistence and rules."""

from __future__ import annotations

import pytest

from database.connection import DatabaseError
from database.models import DocumentProfile


def test_default_profiles_are_seeded(repository) -> None:
    profiles = repository.list_profiles()
    names = {profile.name for profile in profiles}
    assert {
        "Iqama",
        "Driving License",
        "Istimara",
        "Passport",
        "Custom Card",
    } <= names
    assert len(profiles) == 5
    assert all(profile.builtin for profile in profiles)
    assert sum(1 for profile in profiles if profile.is_default) == 1


def test_create_update_and_delete_custom_profile(repository) -> None:
    profile_id = repository.create_profile(
        DocumentProfile(
            name="My Measured Card",
            description="Measured with a ruler",
            width_mm=100.0,
            height_mm=60.0,
            dpi=600,
            format="PNG",
            quality=90,
            orientation="landscape",
            filename_prefix="measured",
        )
    )
    created = repository.get_profile(profile_id)
    assert created is not None
    assert created.width_mm == pytest.approx(100.0)
    assert created.builtin is False

    created.height_mm = 61.5
    created.dpi = 400
    repository.update_profile(created)
    updated = repository.get_profile(profile_id)
    assert updated.height_mm == pytest.approx(61.5)
    assert updated.dpi == 400

    repository.delete_profile(profile_id)
    assert repository.get_profile(profile_id) is None


def test_duplicate_profile_keeps_measurements(repository) -> None:
    default = repository.default_profile()
    assert default is not None
    clone_id = repository.duplicate_profile(default.id)
    clone = repository.get_profile(clone_id)
    assert clone is not None
    assert clone.name == f"{default.name} copy"
    assert clone.width_mm == default.width_mm
    assert clone.builtin is False
    assert clone.is_default is False


def test_names_must_be_unique_and_non_empty(repository) -> None:
    with pytest.raises(DatabaseError):
        repository.create_profile(
            DocumentProfile(name="Iqama", width_mm=85.6, height_mm=54.0)
        )
    with pytest.raises(DatabaseError):
        repository.create_profile(DocumentProfile(name="   ", width_mm=85.6, height_mm=54.0))


def test_builtin_profiles_cannot_be_deleted(repository) -> None:
    builtin = next(profile for profile in repository.list_profiles() if profile.builtin)
    with pytest.raises(DatabaseError):
        repository.delete_profile(builtin.id)


def test_only_one_default_profile(repository) -> None:
    profiles = repository.list_profiles()
    target = next(profile for profile in profiles if not profile.is_default)
    repository.set_default_profile(target.id)
    defaults = [profile.id for profile in repository.list_profiles() if profile.is_default]
    assert defaults == [target.id]


def test_restore_default_profiles(repository) -> None:
    restored = repository.restore_default_profiles()
    assert restored >= 5
    assert repository.get_profile_by_name("Iqama") is not None
    default = repository.default_profile()
    assert default is not None


def test_repository_rejects_unusable_measurements(repository) -> None:
    with pytest.raises(DatabaseError):
        repository.create_profile(DocumentProfile(name="Zero width", width_mm=0, height_mm=54.0))
    with pytest.raises(DatabaseError):
        repository.create_profile(DocumentProfile(name="Huge", width_mm=5000, height_mm=54.0))
    with pytest.raises(DatabaseError):
        repository.create_profile(DocumentProfile(name="Bad DPI", width_mm=85.6, height_mm=54.0, dpi=10))

    profile = repository.get_profile_by_name("Custom Card")
    assert profile is not None
    profile.width_mm = -1
    with pytest.raises(DatabaseError):
        repository.update_profile(profile)


def test_inactive_profiles_can_be_filtered(repository) -> None:
    profile = repository.get_profile_by_name("Custom Card")
    assert profile is not None
    profile.active = False
    repository.update_profile(profile)
    active_names = {item.name for item in repository.list_profiles(active_only=True)}
    assert "Custom Card" not in active_names
    assert "Iqama" in active_names
