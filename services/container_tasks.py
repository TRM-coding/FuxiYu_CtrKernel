#TODO:完善异常处理
import json
import requests
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from pydantic import BaseModel

from ..config import CommsConfig
from ..constant import *
from sqlalchemy.exc import IntegrityError
from ..repositories import containers_repo, machine_repo
from ..repositories.machine_repo import *
from ..repositories.user_repo import *
from ..utils.CheckKeys import *
from ..utils.Container import Container_info
from ..repositories.containers_repo import *
from ..repositories.usercontainer_repo import *
from ..utils.heartbeat import container_starting_status_heartbeat
from ..models.containers import Container
import math
import re


####################################################
#发送指令到集群实体机


def send(ciphertext:bytes,signature:bytes,mechine_ip:str, timeout:float=5.0)->dict:
    """
    发送 POST 并返回解析后的响应（优先 JSON），出现错误时返回包含 error 字段的 dict。
    """
    try:
        print(f"DEBUG: Sending request to {mechine_ip} with ciphertext={ciphertext} and signature={signature}")
        resp = requests.post(mechine_ip, json={
            "message": base64.b64encode(ciphertext).decode('utf-8'),
            "signature": base64.b64encode(signature).decode('utf-8')
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
        print(f"Request error: {e}")
        return {"error": str(e)}

def get_full_url(machine_ip:str, endpoint:str)->str:
    return f"http://{machine_ip}{CommsConfig.NODE_URL_MIDDLE}{endpoint}"

####################################################

#API Definition
####################################################
class container_bref_information(BaseModel):
    container_id: int # 加入这个 只是为了方便调取详细信息
    container_name:str
    machine_id:int
    port:int
    container_status:str

class container_detail_information(BaseModel):
    container_id: int # 与上方结构对称
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
def Create_container(owner_name:str,machine_id:int,container:Container_info,public_key=None, debug=False)->bool:
    machine_ip=get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/create_container")


    free_port = get_the_first_free_port(machine_id=machine_id)
    container.set_port(free_port)
    container_info=dict()
    container_info['owner_name']=owner_name
    container_info['config']=container.get_config()
    if public_key:
        container_info['public_key']=public_key
    container_info=json.dumps(container_info)
    # validate container name: only letters, digits and underscore allowed
    if not re.fullmatch(r'[A-Za-z0-9_]+', container.NAME):
        raise ValueError(f"invalid container name: '{container.NAME}'. Allowed characters: A-Z a-z 0-9 _")

    # check duplicate container name on this machine before sending to Node
    try:
        existing_id = get_id_by_name_machine(container_name=container.NAME, machine_id=machine_id)
        if existing_id:
            # raise IntegrityError so callers can handle duplicate-name consistently
            orig_msg = f"container name '{container.NAME}' already exists on machine {machine_id} (id={existing_id})"
            raise IntegrityError(orig_msg, params=None, orig=orig_msg)
    except IntegrityError:
        # re-raise IntegrityError to propagate
        raise
    except Exception as e:
        # If the check fails unexpectedly, log and continue to avoid blocking creation due to DB issues
        print(f"Warning: failed to check existing container name: {e}")
    signatured_message=signature(container_info)
    
    # TODO 提前做重名检查

    encryptioned_message=encryption(container_info)
    res=send(encryptioned_message,signatured_message,full_url)
    print(f"Create_container: remote response: {res}")

    # verify remote accepted the create request
    if 'error' in res:
        raise Exception(f"remote create failed: {res['error']}")
    if res.get('success') != 1:
        # unexpected response from Node; abort to avoid DB inconsistency
        raise Exception(f"remote create returned failure or unexpected response: {res}")

    if debug:
        #######
        # DEBUG PURPOSE
        Key=False
        original_dict = json.loads(container_info)  # 把原始 JSON 字符串解析成 dict
        server_decrypted_dict = res.get('decrypted_message')  # 直接取解密后的 dict
        if server_decrypted_dict == original_dict:
            print("验证成功：服务端返回的解密内容与原始明文一致")
            # （可选）如果验证通过，再执行实际的容器创建逻辑
            # 这里放原有的容器创建、数据库写入等代码
            Key=True
        else:
            raise Exception("验证失败：解密内容不一致: \n原始："+ str(original_dict)
                            + "\n回应：" + str(res))
        # DEBUG PURPOSE
        #######
    else:
        if 'error' in res:
            raise Exception(f"远程调用失败: {res['error']}")
        Key=True
    
    
    # 写入容器记录 
    create_container(name=container.NAME,
                     image=container.image,
                     machine_id=machine_id,
                     status=ContainerStatus.CREATING,
                     port=free_port)

    # 建立用户绑定（包含必须的 role/username/public_key）
    container_id=get_id_by_name_machine(container_name=container.NAME, machine_id=machine_id)
    user = get_by_name(owner_name)
    add_binding(user_id=user.id,
                container_id=container_id,
                public_key=public_key,
                username='root', # 强制使用 root 作为用户名
                role=ROLE.ROOT) # 这里在创建时，自动变成 ROOT
    
    # start heartbeat in background (non-blocking)
    try:
        container_starting_status_heartbeat(machine_ip, container.NAME, container_id=container_id,
                                         timeout=180, interval=3)
    except Exception:
        print(f"Warning: Heartbeat for container {container_id} failed to start or encountered an error. Container may be stuck in CREATING status.")
        return False

    if Key:
        return True
    return False

#删除容器并删除其所有者记录
def remove_container(container_id:int, debug=False)->bool:
    machine_id = get_machine_id_by_container_id(container_id)
    machine_ip=get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/remove_container")

    container_name = get_by_id(container_id).name
    data={
        "config":{
            "container_name":container_name
        }
    }        
    
    container_info=json.dumps(data)
    signatured_message=signature(container_info)
    encryptioned_message=encryption(container_info)
    res=send(encryptioned_message,signatured_message,full_url)
    print(f"remove_container: remote response: {res}")

    # check remote delete result before mutating local DB
    if 'error' in res:
        raise Exception(f"remote remove failed: {res['error']}")
    # Node remove_container currently returns numeric code in 'success': 0=SUCCESS,1=NOTFOUND,2=FAILED
    remote_code = res.get('success')
    if remote_code is None:
        raise Exception(f"remote remove returned unexpected response: {res}")
    if remote_code == 2:
        # FAILED
        raise Exception(f"remote remove reported failure: {res}")
    # treat 0 (SUCCESS) and 1 (NOTFOUND) as acceptable success for local cleanup

    if debug:
        #######
        # DEBUG PURPOSE
        Key=False
        original_dict = json.loads(container_info)  # 把原始 JSON 字符串解析成 dict
        server_decrypted_dict = res.get('decrypted_message')  # 直接取解密后的 dict
        if server_decrypted_dict == original_dict:
            print("验证成功：服务端返回的解密内容与原始明文一致")
            # （可选）如果验证通过，再执行实际的容器创建逻辑
            # 这里放原有的容器创建、数据库写入等代码
            Key=True
        else:
            raise Exception("验证失败：解密内容不一致: \n原始："+ str(original_dict)
                            + "\n回应：" + str(res))
        # DEBUG PURPOSE
        #######
    else:
        if 'error' in res:
            raise Exception(f"远程调用失败: {res['error']}")
        Key=True
    
    # 移除所有绑定并删除容器
    remove_binding(0, container_id, all=True)
    delete_container(container_id)

    if Key:
        return True
    return False
#将container_id对应的容器新增user_id作为collaborator,其权限为role

def add_collaborator(container_id:int,user_id:int,role:ROLE, debug=False)->bool:
    machine_id = get_machine_id_by_container_id(container_id)
    machine_ip=get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/add_collaborator")

    user_name=get_name_by_id(user_id)
    # Do not allow adding a collaborator as ROOT via this API/task
    if role == ROLE.ROOT:
        # Reject silently (caller/API will return failure)
        return False
    data={
        "config":{
            "container_id":container_id,
            "user_name":user_name,
            "role":role.value
        }
           
    }
    container_info=json.dumps(data)
    signatured_message=signature(container_info)
    encryptioned_message=encryption(container_info)
    res=send(encryptioned_message,signatured_message,full_url)

    if debug:
        #######
        # DEBUG PURPOSE
        Key=False
        original_dict = json.loads(container_info)  # 把原始 JSON 字符串解析成 dict
        server_decrypted_dict = res.get('decrypted_message')  # 直接取解密后的 dict
        if server_decrypted_dict == original_dict:
            print("验证成功：服务端返回的解密内容与原始明文一致")
            # （可选）如果验证通过，再执行实际的容器创建逻辑
            # 这里放原有的容器创建、数据库写入等代码
            Key=True
        else:
            raise Exception("验证失败：解密内容不一致: \n原始："+ str(original_dict)
                            + "\n回应：" + str(res))
        # DEBUG PURPOSE
        #######
    else:
        Key=True
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

def remove_collaborator(container_id:int,user_id:int,debug=False)->bool:
    machine_id = get_machine_id_by_container_id(container_id)
    machine_ip=get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/remove_collaborator")

    # prevent removing ROOT owners
    try:
        binding = get_binding(user_id, container_id)
    except Exception:
        binding = None
    if binding:
        role_val = binding.get('role')
        # stored role is usually the enum value string
        if role_val is not None and str(role_val).upper() == str(ROLE.ROOT.value).upper():
            # 不可移除 ROOT 用户
            return False

    user_name=get_name_by_id(user_id)
    data={
        "config":{
            "container_id":container_id,
            "user_name":user_name
        }
    }
    container_info=json.dumps(data)
    signatured_message=signature(container_info)
    encryptioned_message=encryption(container_info)
    res=send(encryptioned_message,signatured_message,full_url)
    
    if debug:
        #######
        # DEBUG PURPOSE
        Key=False
        original_dict = json.loads(container_info)  # 把原始 JSON 字符串解析成 dict
        server_decrypted_dict = res.get('decrypted_message')  # 直接取解密后的 dict
        if server_decrypted_dict == original_dict:
            print("验证成功：服务端返回的解密内容与原始明文一致")
            # （可选）如果验证通过，再执行实际的容器创建逻辑
            # 这里放原有的容器创建、数据库写入等代码
            Key=True
        else:
            raise Exception("验证失败：解密内容不一致: \n原始："+ str(original_dict)
                            + "\n回应：" + str(res))
        # DEBUG PURPOSE
        #######
    else:
        Key=True
    # 仅删除绑定
    remove_binding(user_id,container_id)
    
    if Key:
        return True
    return False

#修改user_id对container_id的访问权

def update_role(container_id:int,user_id:int,updated_role:ROLE,debug=False)->bool:
    machine_id = get_machine_id_by_container_id(container_id)
    machine_ip=get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/update_role")

    user_name=get_name_by_id(user_id)
    # 远侧处理ROOT相关的角色变更 可能需单独考察
    data={
        "config":{
            "container_id":container_id,
            "user_name":user_name,
            "updated_role":updated_role.value
        }
    }
    container_info=json.dumps(data)
    signatured_message=signature(container_info)
    encryptioned_message=encryption(container_info)
    # 使用 machine_ip 发送
    res=send(encryptioned_message,signatured_message,full_url)

    if debug:
        #######
        # DEBUG PURPOSE
        Key=False
        original_dict = json.loads(container_info)  # 把原始 JSON 字符串解析成 dict
        server_decrypted_dict = res.get('decrypted_message')  # 直接取解密后的 dict
        if server_decrypted_dict == original_dict:
            print("验证成功：服务端返回的解密内容与原始明文一致")
            # （可选）如果验证通过，再执行实际的容器创建逻辑
            # 这里放原有的容器创建、数据库写入等代码
            Key=True
        else:
            raise Exception("验证失败：解密内容不一致: \n原始："+ str(original_dict)
                            + "\n回应：" + str(res))
        # DEBUG PURPOSE
        #######
    else:
        Key=True
    if updated_role == ROLE.ROOT:
        # 强制使用 root 作为用户名
        username = 'root'
    else:
        username = user_name

    # 更新绑定时同时传入 username 和 role，确保数据库中的 username 在变更为 ROOT 时被设置为 'root'
    update_binding(user_id, container_id, username=username, role=updated_role)
    
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
        "container_id": container.id,
        "container_name": container.name,
        "container_image": container.image,
        "machine_id": container.machine_id,
        "container_status": container.container_status.value,
        "port": container.port,
        # 备忘：owners才是系统对应的用户名列表
        "owners": [get_name_by_id(binding['user_id']) for binding in owener_bindings],
        # 这里的变动是为了
        # 1. 语句写法 - 防止报错（针对API提取时的格式问题）
        # 2. username -> user_id 使得在页面层对应性更强，并避免可能存在的 user_name与username不同
        "accounts": [
            {"user_id": binding.get('user_id'), "username": binding.get("username"), "role": (ROLE(binding.get('role')).value if binding.get('role') is not None else None)}
            for binding in owener_bindings
        ],
    }
    return res



#返回一页容器的概要信息
def list_all_container_bref_information(machine_id:int, user_id:int, page_number:int, page_size:int)->dict:
    containers = list_containers(limit=page_size, offset=page_number*page_size, machine_id=machine_id, user_id=user_id)
    res = []
    for container in containers:
        info = container_bref_information(
            container_id=container.id,
            container_name=container.name,
            machine_id=container.machine_id,
            port=container.port,
            container_status=container.container_status.value
        )
        res.append(info)

    # 这里计算总页数
    try: # 理论不会报错 但是被建议保留
        total_count = count_containers(machine_id=machine_id)
        total_page = max(1, math.ceil(total_count / page_size))
    except Exception:
        total_page = 1

    return {"containers": res, "total_page": total_page}

####################################################
