"""认证模块核心逻辑测试。"""
from unittest.mock import patch

from services.auth import hash_password, verify_password, make_token, read_token


class TestPasswordHashing:
    def test_hash_and_verify(self):
        hashed = hash_password("test123")
        assert verify_password("test123", hashed) is True
        assert verify_password("wrong", hashed) is False

    def test_different_hashes(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # salt 不同

    def test_bad_format(self):
        assert verify_password("test", "not_a_valid_hash") is False


class TestTokens:
    def test_make_and_read(self, patch_db):
        conn = patch_db
        conn.execute(
            "INSERT INTO users (id, username, display_name, password_hash, role, is_active, created_at, updated_at) VALUES (1, 'admin', '管理员', 'x', 'admin', 1, '2025-01-01', '2025-01-01')"
        )
        conn.commit()
        user = {"id": 1, "username": "admin", "display_name": "管理员", "role": "admin", "permissions": {}}
        token = make_token(user)
        assert "." in token
        result = read_token(f"Bearer {token}")
        assert result is not None
        assert result["username"] == "admin"
        assert result["role"] == "admin"

    def test_invalid_signature(self):
        assert read_token("Bearer abc.def") is None

    def test_expired_token(self, patch_db):
        conn = patch_db
        conn.execute(
            "INSERT INTO users (id, username, display_name, password_hash, role, is_active, created_at, updated_at) VALUES (1, 'admin', '管理员', 'x', 'admin', 1, '2025-01-01', '2025-01-01')"
        )
        conn.commit()
        user = {"id": 1, "username": "admin", "display_name": "管理员", "role": "admin", "permissions": {}}
        with patch("services.auth.TOKEN_TTL_SECONDS", -10):
            token = make_token(user)
        assert read_token(f"Bearer {token}") is None

    def test_no_header(self):
        assert read_token(None) is None
        assert read_token("") is None
        assert read_token("Basic abc") is None
