from flask import jsonify, request, make_response
from . import api_bp
from ..services import user_tasks
from ..repositories import user_repo
from ..schemas.user_schema import user_schema, users_schema


@api_bp.get("/users/list_users")
def list_users():
	pass


@api_bp.post("/register")
def register():
	'''
	通信数据格式：
	发送格式：
	{
		"username":"xxxx",
		"email":"xxxx",
		"password":"xxxx",
		"graduation_year":xxxx
	}
	返回格式：
	{
		"success": [0|1],
		"message": "xxxx",
		"user_id": xxxx,
		"username": "xxxx",
		"email": "xxxx"
	}
	'''
	"""用户注册 API"""
	print("Register Called")
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"success": 0, "message": "invalid json"}), 400
	
	# 直接读取明文字段
	username = recived_data.get("username")
	email = recived_data.get("email")
	password = recived_data.get("password")
	graduation_year = recived_data.get("graduation_year")
	
	if not username or not email or not password:
		return jsonify({"success": 0, "message": "username, email and password required"}), 400
	
	# 调用 service 层注册用户
	success, user_or_reason, _ = user_tasks.Register(username, email, password, graduation_year)
	
	if success:
		return jsonify({
			"success": 1,
			"message": "Registration successful",
			"user_id": user_or_reason.id,
			"username": user_or_reason.username,
			"email": user_or_reason.email
		}), 201
	else:
		# user_or_reason 是错误原因字符串
		error_reason = user_or_reason
		error_messages = {
			"username_exists": "Username already exists",
			"email_exists": "Email already exists"
		}
		message = error_messages.get(error_reason, "Registration failed")
		
		return jsonify({
			"success": 0,
			"message": message,
			"error_reason": error_reason
		}), 400


@api_bp.post("/login")
def login():
	'''
	通信数据格式：
	发送格式：
	{
		"username":"xxxx",
		"password":"xxxx"
	}
	返回格式：
	{
		"success": [0|1],
		"message": "xxxx",
		"user_id": xxxx,
		"username": "xxxx",
		"email": "xxxx",
		"token": "xxxx"
	}
	'''
	"""用户登录 API"""
	print("Login Called")
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"success": 0, "message": "invalid json"}), 400
	
	# 直接读取明文字段
	username = recived_data.get("username")
	password = recived_data.get("password")
	
	if not username or not password:
		return jsonify({"success": 0, "message": "username and password required"}), 400
	
	# 调用 Login 函数，返回结果和错误原因
	success, user_or_reason, token = user_tasks.Login(username, password)
	
	if success:
		# 创建响应
		response = make_response(jsonify({
			"success": 1,
			"message": "Login successful",
			"user_id": user_or_reason.id,
			"username": user_or_reason.username,
			"email": user_or_reason.email,
			"token": token,
		}), 200)
		
		# 设置 cookies
		response.set_cookie(
			'auth_token',
			token,
			max_age=24*3600,  # 24小时
			httponly=True,
			secure=False,  # 内网环境
			samesite='Lax'
		)
		
		return response
	else:
		# user_or_reason 是错误原因字符串
		error_reason = user_or_reason
		error_messages = {
			"user_not_found": "User does not exist",
			"password_incorrect": "Password is incorrect"
		}
		message = error_messages.get(error_reason, "Login failed")
		
		return jsonify({
			"success": 0,
			"message": message,
			"error_reason": error_reason
		}), 401


@api_bp.post("/users/change_password")
def change_password_user():
	pass


@api_bp.post("/users/delete_user")
def delete_user_api():
	pass
