#TODO:完善异常处理
import json
import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from pydantic import BaseModel

from ..config import KeyConfig
from ..constant import *
from ..repositories import containers_repo, machine_repo
from ..repositories.machine_repo import *
from ..repositories.user_repo import *
from ..utils.CheckKeys import *
from ..utils.Container import Container_info
from ..repositories.containers_repo import *
from ..repositories.usercontainer_repo import *


####################################################
#发送指令到集群实体机
def send(ciphertext:bytes,signature:bytes,mechine_ip:str, timeout:float=5.0)->dict:
    """
    发送 POST 并返回解析后的响应（优先 JSON），出现错误时返回包含 error 字段的 dict。
    """
    try:
        resp = requests.post(mechine_ip, json={
                "message": ciphertext.hex(),
                "signature": signature.hex()
        }, timeout=timeout)

        # 抛出 HTTP 错误（4xx/5xx）
        resp.raise_for_status()

        # 尝试解析为 JSON，否则返回原始文本
        try:
            return resp.json()
        except ValueError:
            return {"status_code": resp.status_code, "text": resp.text}

    except requests.RequestException as e:
        # 网络/超时/连接等错误
        return {"error": str(e)}

####################################################

#API Definition
####################################################
class container_bref_information(BaseModel):
    container_name:str
    machine_ip:str
    port:int
    container_status:str

class container_detail_information(BaseModel):
    container_name:str
    container_image:str
    machine_ip:str
    container_status:str
    port:int 
    owners:list[str]
    accounts:list[(str,ROLE)]
####################################################



#Function Implementation
####################################################

# 将user_id作为admin，创建新容器
def Create_container(user_name:str,machine_ip:str,container:Container_info,public_key=None)->bool:
    full_url = "http://172.17.0.6:5000/api/create_container"

    machine_id=get_id_by_ip(machine_ip=machine_ip)
    free_port = get_the_first_free_port(machine_id=machine_id)
    container.set_port(free_port)
    container_info=dict()
    container_info['config']=container.get_config()
    container_info=json.dumps(container_info)
    signatured_message=signature(container_info)
    encryptioned_message=signature(container_info)
    res=send(encryptioned_message,signatured_message,full_url)
    print(res)

    original_plaintext = container_info
    server_decrypted = res.get("decrypted_message")
    Key=False
    if server_decrypted == original_plaintext:
        print("验证成功：服务端返回的解密内容与原始明文一致")
        # （可选）如果验证通过，再执行实际的容器创建逻辑
        # 这里放原有的容器创建、数据库写入等代码
        Key=True
    else:
        print("验证失败：解密内容不一致")


    # 写入容器记录
    create_container(name=container.NAME,
                     image=container.image,
                     machine_id=machine_id,
                     status=ContainerStatus.ONLINE,
                     port=free_port)

    # 建立用户绑定（包含必须的 role/username/public_key）
    container_id=get_id_by_name_machine(container_name=container.NAME, machine_id=machine_id)
    user = get_by_name(user_name)
    add_binding(user_id=user.id,
                container_id=container_id,
                public_key=public_key,
                username=user_name,
                role=ROLE.ADMIN)
    
    if Key:
        return True
    return False

#删除容器并删除其所有者记录
def remove_container(machine_ip:str,container_id:str)->bool:
    full_url = "http://172.17.0.6:5000/api/create_container"

    machine_id=get_id_by_ip(machine_ip=machine_ip)
    data={
        "config":{
            "container_id":container_id
        }
    }        
    
    container_info=json.dumps(data)
    signatured_message=signature(container_info)
    encryptioned_message=signature(container_info)
    res=send(encryptioned_message,signatured_message,full_url)

    original_plaintext = container_info
    server_decrypted = res.get("decrypted_message")
    Key=False
    if server_decrypted == original_plaintext:
        print("验证成功：服务端返回的解密内容与原始明文一致")
        # （可选）如果验证通过，再执行实际的容器创建逻辑
        # 这里放原有的容器创建、数据库写入等代码
        Key=True
    else:
        print("验证失败：解密内容不一致")
    
    # 移除所有绑定并删除容器
    remove_binding(0, container_id, all=True)
    delete_container(container_id)

    if Key:
        return True
    return False
#将container_id对应的容器新增user_id作为collaborator,其权限为role

def add_collaborator(machine_ip,container_id:int,user_id:int,role:ROLE)->bool:
    full_url = "http://172.17.0.6:5000/api/create_container"

    machine_id=get_id_by_ip(machine_ip=machine_ip)
    user_name=get_name_by_id(user_id)
    data={
        "config":{
            "container_id":container_id,
            "user_name":user_name,
            "role":role.value
        }
           
    }
    container_info=json.dumps(data)
    signatured_message=signature(container_info)
    encryptioned_message=signature(container_info)
    res=send(encryptioned_message,signatured_message,full_url)

    original_plaintext = container_info
    server_decrypted = res.get("decrypted_message")
    Key=False
    if server_decrypted == original_plaintext:
        print("验证成功：服务端返回的解密内容与原始明文一致")
        # （可选）如果验证通过，再执行实际的容器创建逻辑
        # 这里放原有的容器创建、数据库写入等代码
        Key=True
    else:
        print("验证失败：解密内容不一致")

    # 直接通过绑定表建立关联
    add_binding(user_id=user_id,
                container_id=container_id,
                username=user_name,
                public_key=None,
                role=role)
    
    if Key:
        return True
    return False
#从container_id中移除user_id对应的用户访问权

def remove_collaborator(machine_ip:str,container_id:int,user_id:int)->bool:
    full_url = "http://172.17.0.6:5000/api/create_container"

    machine_id=get_id_by_ip(machine_ip=machine_ip)
    user_name=get_name_by_id(user_id)
    data={
        "config":{
            "container_id":container_id,
            "user_name":user_name
        }
    }
    container_info=json.dumps(data)
    signatured_message=signature(container_info)
    encryptioned_message=signature(container_info)
    res=send(encryptioned_message,signatured_message,full_url)
    
    original_plaintext = container_info
    server_decrypted = res.get("decrypted_message")
    Key=False
    if server_decrypted == original_plaintext:
        print("验证成功：服务端返回的解密内容与原始明文一致")
        # （可选）如果验证通过，再执行实际的容器创建逻辑
        # 这里放原有的容器创建、数据库写入等代码
        Key=True
    else:
        print("验证失败：解密内容不一致")
    
    # 仅删除绑定
    remove_binding(user_id,container_id)
    
    if Key:
        return True
    return False

#修改user_id对container_id的访问权

def update_role(machine_ip:str,container_id:int,user_id:int,updated_role:ROLE)->bool:
    full_url = "http://172.17.0.6:5000/api/create_container"

    machine_id=get_id_by_ip(machine_ip=machine_ip)
    user_name=get_name_by_id(user_id)
    data={
        "config":{
            "container_id":container_id,
            "user_name":user_name,
            "updated_role":updated_role.value
        }
    }
    container_info=json.dumps(data)
    signatured_message=signature(container_info)
    encryptioned_message=signature(container_info)
    # 使用 machine_ip 发送
    res=send(encryptioned_message,signatured_message,full_url)

    original_plaintext = container_info
    server_decrypted = res.get("decrypted_message")
    Key=False
    if server_decrypted == original_plaintext:
        print("验证成功：服务端返回的解密内容与原始明文一致")
        # （可选）如果验证通过，再执行实际的容器创建逻辑
        # 这里放原有的容器创建、数据库写入等代码
        Key=True
    else:
        print("验证失败：解密内容不一致")
    
    update_binding(user_id,container_id,role=updated_role)
    
    if Key:
        return True
    return False

#返回容器的细节信息
def get_container_detail_information(container_id:int)->container_detail_information:
    container=get_by_id(container_id)
    if not container:
        raise ValueError("Container not found")
    owener_bindings= get_container_bindings(container_id)
    res={
        "container_name":container.name,
        "container_image":container.image,
        "machine_ip":container.machine.machine_ip,
        "container_status":container.container_status.value,
        "port":container.port,
        "owners":[get_name_by_id(binding['user_id']) for binding in owener_bindings],
        "accounts":[(binding['username'],ROLE(binding['role'])) for binding in owener_bindings],
    }
    return res



#返回一页容器的概要信息
def list_all_container_bref_information(machine_ip:str, page_number:int, page_size:int)->list[container_bref_information]:
    machine_id = get_id_by_ip(machine_ip=machine_ip)
    containers = list_containers(machine_id=machine_id, limit=page_size, offset=page_number*page_size)
    res = []
    for container in containers:
        info = container_bref_information(
            container_name=container.name,
            machine_ip=container.machine.machine_ip,
            port=container.port,
            container_status=container.container_status.value
        )
        res.append(info)
    return res

####################################################
