from flask import jsonify, request
from . import api_bp
from ..services import user_tasks as user_service
from ..repositories import user_repo
from ..schemas.user_schema import user_schema, users_schema


@api_bp.get("/users/list_users")
def list_users():
	pass


@api_bp.post("/users/register")
def create_user():
	pass

@api_bp.post("/users/login")
def login_user():
    # 1. 解析请求体 JSON
    data = request.get_json() or {}
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({
            "code": 400,
            "msg": "username and password are required"
        }), 400

    # 2. 调用你自己的登录逻辑
    # 假设 Login 返回 (是否成功, 用户对象/错误信息, token)
    ok, user_or_msg, token = Login(username, password)

    if not ok:
        # 登录失败
        return jsonify({
            "code": 401,
            "msg": user_or_msg  # 比如 “用户名或密码错误”
        }), 401

    # 3. 组织响应数据
    resp_body = {
        "code": 0,
        "msg": "ok",
        "data": {
            "user": {
                "id": user_or_msg.id,
                "username": user_or_msg.username,
                # 其他需要返回的字段
            },
            "token": token
        }
    }

    # 4. 如需设置 cookie（比如保存 token）
    resp = make_response(jsonify(resp_body))
    resp.set_cookie(
        "auth_token",
        token,
        httponly=True,   # 防止 JS 读取，降低 XSS 风险
        secure=True,     # 只在 HTTPS 发送
        samesite="Lax",  # 减少 CSRF
        max_age=7 * 24 * 3600  # 过期时间（秒）
    )

    return resp
	
@api_bp.post("/users/change_password")
def change_password_user():
	pass

@api_bp.post("/users/delete_user")
def delete_user_api():
	pass