import requests

url = "http://172.17.0.6:5000/api/create_container"  # 目标URL
data = {
    "username": "user1",
    "password": "123456"
}

response = requests.post(url, data=data)

print("状态码:", response.status_code)
print("响应内容:", response.text)
