"""示例业务服务层"""

from ..repositories import user_repo


def register_user(username: str, email: str, password_plain: str):
	# 真实项目中应使用 werkzeug.security generate_password_hash
	password_hash = f"hashed:{password_plain}"  # 简化示例
	return user_repo.create_user(username, email, password_hash)

