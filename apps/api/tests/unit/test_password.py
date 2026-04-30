from __future__ import annotations

from app.core.security import hash_password, verify_password


def test_bcrypt_hash_and_verify_roundtrip() -> None:
    hashed = hash_password("correct-horse-battery")

    assert hashed != "correct-horse-battery"
    assert verify_password("correct-horse-battery", hashed)


def test_bcrypt_cost_is_12() -> None:
    hashed = hash_password("correct-horse-battery")

    assert hashed.split("$")[2] == "12"


def test_wrong_password_fails() -> None:
    hashed = hash_password("correct-horse-battery")

    assert not verify_password("wrong-horse-battery", hashed)


def test_long_passwords_are_prehash_disambiguated() -> None:
    password = "a" * 100
    truncated_collision = ("a" * 72) + ("b" * 28)

    hashed = hash_password(password)

    assert verify_password(password, hashed)
    assert not verify_password(truncated_collision, hashed)
