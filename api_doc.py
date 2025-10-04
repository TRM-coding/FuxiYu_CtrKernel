from flask import Blueprint, jsonify, request
from ..services import user_service
from ..schemas.user_schema import user_schema, users_schema
from ..utils.CheckKeys import *
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from ..config import KeyConfig
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
import requests
import json
from ..services.container_service import *


api_bp = Blueprint("api", __name__, url_prefix="/api")

'''
通信数据格式：
发送格式：
{
	"message":{
		"type":'create',
		"config":
		{
			"gpu_list":[0,1,2,...],
			"cpu_number":20,
			"memory":16,#GB
			"user_name":'example',
			"port":0,
			"image":"ubuntu24.04"
		}
	},
	"signature":"xxxxxx"
}
返回格式：
{
	"container_id": container_id,
	"container_name": container_name
}
'''
@api_bp.get("/create_container")
def Create_container():
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"error":"invalid json"}), 400
	
	# 使用 get_verified_msg 函数解密并验证
	verified_msg = get_verified_msg(recived_data)
	
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed"}), 401
	
	# 提取消息类型和配置
	msg_type = verified_msg.get("type")
	config = verified_msg.get("config")
	
	if msg_type != "create" or not config:
		return jsonify({"error": "invalid message type or config"}), 400
	
	container_id, container_name = create_container(**config)
	
	return jsonify({
		"container_id": container_id,
		"container_name": container_name
	}), 200

'''
通信数据格式：
发送格式：
{
	"message":{
		"type":'remove',
		"config":
		{
			"container_id":"xxxx"
		}
	},
	"signature":"xxxxxx"
}

返回格式：
{
	"success": [0|1],
}
'''
@api_bp.post("/remove_container")
def Remove_container():
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"error":"invalid json"}), 400
	
	# 使用 get_verified_msg 函数解密并验证
	verified_msg = get_verified_msg(recived_data)
	
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed"}), 401
	
	# 提取消息类型和配置
	msg_type = verified_msg.get("type")
	config = verified_msg.get("config")
	
	if msg_type != "remove" or not config:
		return jsonify({"error": "invalid message type or config"}), 400
	
	success = remove_container(**config)
	
	return jsonify({
		"success": success,
	}), 200
	
'''
通信数据格式：
发送格式：
{
	"message":{
		"type":'update',
		"config":
		{
			"container_id":"xxxx",
			"user_name":"xxxx",
			"role":['admin'|'collaborator']
		}
	},
	"signature":"xxxxxx"
}
返回格式：
{
	"success": [0|1],
}
'''
@api_bp.post("/add_collaborator")
def Add_collaborator():
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"error":"invalid json"}), 400
	
	# 使用 get_verified_msg 函数解密并验证
	verified_msg = get_verified_msg(recived_data)
	
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed"}), 401
	
	# 提取消息类型和配置
	msg_type = verified_msg.get("type")
	config = verified_msg.get("config")
	
	if msg_type != "update" or not config:
		return jsonify({"error": "invalid message type or config"}), 400
	
	success = add_collaborator(**config)
	
	return jsonify({
		"success": success,
	}), 200


'''
通信数据格式：
发送格式：
{
	"message":{
		"type":'update',
		"config":
		{
			"container_id":"xxxx",
			"user_name":"xxxx",
		}
	},
	"signature":"xxxxxx"
}
返回格式：
{
	"success": [0|1],
}
'''
@api_bp.post("/remove_collaborator")
def Remove_collaborator():
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"error":"invalid json"}), 400
	
	# 使用 get_verified_msg 函数解密并验证
	verified_msg = get_verified_msg(recived_data)
	
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed"}), 401
	
	# 提取消息类型和配置
	msg_type = verified_msg.get("type")
	config = verified_msg.get("config")
	
	if msg_type != "update" or not config:
		return jsonify({"error": "invalid message type or config"}), 400
	
	success = remove_collaborator(**config)
	
	return jsonify({
		"success": success,
	}), 200


'''
通信数据格式：
发送格式：
{
	"message":{
		"type":'update',
		"config":
		{
			"container_id":"xxxx",
			"user_name":"xxxx",
			"updated_role":"xxxx"
		}
	},
	"signature":"xxxxxx"
}
返回格式：
{
	"success": 0|1,
}
'''
@api_bp.post("/update_role")
def Update_role():
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"error":"invalid json"}), 400
	
	# 使用 get_verified_msg 函数解密并验证
	verified_msg = get_verified_msg(recived_data)
	
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed"}), 401
	
	# 提取消息类型和配置
	msg_type = verified_msg.get("type")
	config = verified_msg.get("config")
	
	if msg_type != "update" or not config:
		return jsonify({"error": "invalid message type or config"}), 400
	
	success = update_role(**config)
	
	return jsonify({
		"success": success,
	}), 200


def register_blueprints(app):
	app.register_blueprint(api_bp)

