from flask import Blueprint, jsonify, request, make_response
from functools import wraps
from ..services import user_tasks
from ..repositories import user_repo
from ..schemas.user_schema import user_schema, users_schema
from ..utils.Authentication import Authentication
from ..models.user import User

api_bp = Blueprint("api", __name__, url_prefix="/api")

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
	"message": "xxxx"
}
'''
@api_bp.post("/login")
def login():
	print("Login Called")
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"error":"invalid json"}), 400
	
	# 直接读取明文字段
	username = recived_data.get("username")
	password = recived_data.get("password")
	
	if not username or not password:
		return jsonify({"error": "username and password required"}), 400
	
	# 调用 service 层验证用户
	if user_tasks.Login(username, password):
		# 获取用户信息
		user = User.query.filter_by(username=username).first()
		
		# 生成认证token
		auth = Authentication.create_token(user.id, expires_in_hours=24)
		
		# 创建响应
		response = make_response(jsonify({
			"success": 1,
			"message": "Login successful",
			"user_id": user.id,
			"username": user.username,
			"email": user.email,
			"token": auth.token,
			"expires_at": auth.expires_at.isoformat()
		}), 200)
		
		# 设置cookies
		response.set_cookie(
			'auth_token',
			auth.token,
			max_age=24*3600,  # 24小时
			httponly=False,  
			secure=False, 
			samesite='Lax'  # CSRF保护
		)
		
		return response
	else:
		return jsonify({
			"success": 0,
			"message": "Invalid credentials"
		}), 401


'''
通信数据格式：
发送格式：
{
	"username":"xxxx",
	"email":"xxxx",
	"password":"xxxx",
	"graduation_year": xxxx
}
返回格式：
{
	"success": [0|1],
	"message": "xxxx",
	"user": {...}
}
'''
@api_bp.post("/register")
def register():
	print("Register Called")
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"error":"invalid json"}), 400
	
	# 直接读取明文字段
	username = recived_data.get("username")
	email = recived_data.get("email")
	password = recived_data.get("password")
	graduation_year = recived_data.get("graduation_year")
	
	if not username or not email or not password:
		return jsonify({"error": "username, email and password required"}), 400
	
	# 调用 service 层注册用户
	user = user_tasks.Register(username, email, password, graduation_year)
	
	if user:
		return jsonify({
			"success": 1,
			"message": "Registration successful",
			"user": user_schema.dump(user)
		}), 201
	else:
		return jsonify({
			"success": 0,
			"message": "Username or email already exists"
		}), 400


def register_blueprints(app):
	app.register_blueprint(api_bp)

