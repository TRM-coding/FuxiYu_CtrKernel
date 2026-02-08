from flask import jsonify, request, make_response
from . import api_bp
from ..services import user_tasks
from ..repositories import user_repo, authentications_repo
from ..schemas.user_schema import user_schema, users_schema


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
		["error_reason": "xxxx"],
		"message": "xxxx",
		"user_id": xxxx,
		"username": "xxxx",
		"email": "xxxx",
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
	try:
		success, user_or_reason, _ = user_tasks.Register(username, email, password, graduation_year)
	except Exception as e:
		return jsonify({"success": 0, "message": "registration failed due to server error"}), 500
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

		if error_reason in ["username_exists", "email_exists"]:
			status_code = 409  # Conflict
		else:
			status_code = 400  # Bad Request

		return jsonify({
			"success": 0,
			"message": message,
			"error_reason": error_reason
		}), status_code


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
		["error_reason": "xxxx"],
		"user_id": xxxx,
		"username": "xxxx",
		"email": "xxxx",
		"permission": "[user|operator]",
		"token": "xxxx"
	}
	'''
	"""用户登录 API"""
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
			"permission": user_or_reason.permission.value,
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
		if error_reason == "user_not_found":
			error_code = 404
		elif error_reason == "password_incorrect":
			error_code = 400

		return jsonify({
			"success": 0,
			"message": message,
			"error_reason": error_reason
		}), error_code

@api_bp.get("/users/get_user_detail_information")
def get_user_detail_information_api():
	'''
	通信数据格式：
	发送格式：
	{
		"token",
		"user_id"
	}
	返回格式：
	{
		"success": [0|1],
		"message": "xxxx",
		["error_reason": "xxxx"],
        "user_id",
        "username",
        "email",
        "graduation_year",
		"permission": "[user|operator]",
        "containers", # in IDs
        "amount_of_container",
        "amount_of_functional_container",
        "amount_of_managed_container"
    }
	'''
	# require valid token
	if (not authentications_repo.is_token_valid(request.headers.get("token", ""))):
		return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401

	data = request.get_json(silent=True) or {}
	# support both JSON body and querystring
	user_id = data.get("user_id") or request.args.get("user_id")
	if not user_id:
		return jsonify({"success": 0, "message": "user_id required", "error_reason": "missing_user_id"}), 400

	info = user_tasks.Get_user_detail_information(user_id)
	if not info:
		return jsonify({"success": 0, "message": "user not found", "error_reason": "user_not_found"}), 404

	# if pydantic model, convert to dict
	try:
		payload = info.dict()
	except Exception:
		payload = info

	return jsonify({"success": 1, "user_info": payload}), 200

@api_bp.get("/users/list_all_user_bref_information")
def list_all_user_bref_information_api():
	'''
	通信数据格式：
	发送格式：
	{
		"token",
		"page_number",
		"page_size"
	}
	返回格式：
	{[
        "user_id",
        "username",
        "email",
        "graduation_year",
        "containers",
        "amount_of_container",
        "amount_of_functional_container",
        "amount_of_managed_container"
	], 
	...
	}
	'''
	# require valid token
	if (not authentications_repo.is_token_valid(request.headers.get("token", ""))):
		return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401

	data = request.get_json(silent=True) or {}
	page_number = data.get("page_number") or request.args.get("page_number") or 1
	page_size = data.get("page_size") or request.args.get("page_size") or 10

	try:
		users = user_tasks.List_all_user_bref_information(page_number=int(page_number), page_size=int(page_size))
	except Exception as e:
		return jsonify({"success": 0, "message": "failed to list users", "error_reason": "list_failed"}), 500

	# convert pydantic models to dicts if necessary
	out = []
	for u in users:
		try:
			out.append(u.dict())
		except Exception:
			out.append(u)

	return jsonify({"success": 1, "users": out}), 200

@api_bp.post("/users/change_password")
def change_password_user():
	'''
	通讯数据格式：
	发送格式：
	{
		"token",
		"user_id",
		"old_password",
		"new_password"
	}
	返回格式：
	{
		"success": [0|1],
		"message": "xxxx",
		["error_reason": "xxxx"]
	}
	'''
	if (not authentications_repo.is_token_valid(request.headers.get("token", ""))):
		return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401

	data = request.get_json(silent=True) or {}
	
	user_id = data.get("user_id") or request.args.get("user_id")
	old_password = data.get("old_password")
	new_password = data.get("new_password")

	if not user_id or not old_password or not new_password:
		return jsonify({"success": 0, "message": "user_id, old_password and new_password required", "error_reason": "missing_fields"}), 400

	# fetch user object
	user = user_repo.get_by_id(int(user_id))
	if not user:
		return jsonify({"success": 0, "message": "user not found", "error_reason": "user_not_found"}), 404

	ok = user_tasks.Change_password(user, old_password, new_password)
	if ok:
		return jsonify({"success": 1, "message": "password changed"}), 200
	else:
		return jsonify({"success": 0, "message": "old password incorrect", "error_reason": "old_password_incorrect"}), 400

@api_bp.post("/users/delete_user")
def delete_user_api():
	'''
	通讯数据格式：
	发送格式：
	{
		"token",
		"user_id"
	}
	返回格式：
	{
		"success": [0|1],
		"message": "xxxx",
		["error_reason": "xxxx"],
		"wild_containers": [...]  # 可选字段，仅在存在无主容器阻止删除时返回
	}
	'''
	if (not authentications_repo.is_token_valid(request.headers.get("token", ""))):
		return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401

	data = request.get_json(silent=True) or {}
	user_id = data.get("user_id") or request.args.get("user_id")
	if not user_id:
		return jsonify({"success": 0, "message": "user_id required", "error_reason": "missing_user_id"}), 400

	try:
		ok = user_tasks.Delete_user(int(user_id))
	except Exception as e:
		# 异常时，意味着存在无主容器阻止删除；返回特定错误信息并附加无主容器列表
		payload = {"success": 0, "message": "Wild container NOT allowed. Must remove all affected containers first.", "error_reason": "wild_container"}
		wild = getattr(e, 'wild_containers', None)
		if wild:
			payload['wild_containers'] = wild
		return jsonify(payload), 400

	if ok:
		return jsonify({"success": 1, "message": "user deleted"}), 200
	else:
		return jsonify({"success": 0, "message": "user not found", "error_reason": "user_not_found"}), 404

@api_bp.post("/users/update_user")
def update_user_api():
	'''
	通讯数据格式：
	发送格式：
	{
		"token",
		"user_id",
		"fields": {
			"username": "newname",
			"email": "newemail",
			"graduation_year": 2026
		}
	}
	返回格式：
	{
		"success": [0|1],
		"message": "xxxx",
		["error_reason": "xxxx"],
		"user": { ... updated user data ... }
	}
	'''
	if (not authentications_repo.is_token_valid(request.headers.get("token", ""))):
		return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401

	data = request.get_json(silent=True) or {}
	
	user_id = data.get("user_id") or request.args.get("user_id")
	fields = data.get("fields", {})

	if not user_id or not fields:
		return jsonify({"success": 0, "message": "user_id and fields required", "error_reason": "missing_fields"}), 400

	user = user_tasks.Update_user(int(user_id), **fields)
	if user:
		return jsonify({"success": 1, "message": "user updated", "user": user.username}), 200
	else:
		return jsonify({"success": 0, "message": "user not found", "error_reason": "user_not_found"}), 404

@api_bp.post("/users/reset_password")
def reset_password_api():
	'''
	通讯数据格式：
	发送格式：
	{
		"token",
		"user_id"
	}
	返回格式：
	{
		"success": [0|1],
		"message": "xxxx",
		["error_reason": "xxxx"],
		"new_password": "xxxx"
	}
	'''
	if (not authentications_repo.is_token_valid(request.headers.get("token", ""))):
		return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401

	data = request.get_json(silent=True) or {}
	
	user_id = data.get("user_id") or request.args.get("user_id")

	if not user_id:
		return jsonify({"success": 0, "message": "user_id required", "error_reason": "missing_user_id"}), 400

	new_password = user_tasks.Reset_password(int(user_id))
	if new_password:
		return jsonify({"success": 1, "message": "password reset", "new_password": new_password}), 200
	else:
		return jsonify({"success": 0, "message": "user not found", "error_reason": "user_not_found"}), 404