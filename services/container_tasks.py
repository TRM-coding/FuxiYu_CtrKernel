import json
import requests
import time
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from pydantic import BaseModel

from ..config import CommsConfig
from ..constant import *
from sqlalchemy.exc import IntegrityError
from ..repositories import containers_repo, machine_repo
from ..repositories import containers_repo as container_repo
from .machine_tasks import is_machine_online_remote
from ..repositories.machine_repo import *
from ..repositories.user_repo import *
from ..utils.CheckKeys import *
from ..utils.Container import Container_info
from ..repositories.containers_repo import *
from ..repositories.usercontainer_repo import *
from ..utils.heartbeat import (
    container_starting_status_heartbeat,
    container_stopping_status_heartbeat,
    container_restart_status_heartbeat,
)
from ..models.containers import Container
import math
import re
from ..utils import sanitizer as _sanitizer

####################################################
# 辅助工具
def _ensure_machine_online_for_operation(machine_id: int, operation: str = ''):
    """
    这里检查机器在线状态的主要目的是为了在执行诸如创建/删除/修改容器等操作之前，先验证目标机器是否在线，以避免不必要的远程调用和更快地反馈给用户。虽然最终的远程调用也会有类似的检查，但这个预检查可以节省资源并提供更即时的错误响应。
    """
    try:
        m = machine_repo.get_by_id(machine_id)
    except Exception:
        m = None
    if not m:
        raise NodeServiceError(f"MACHINE {operation} failed: machine {machine_id} not found", reason="machine_not_found")
    try:
        machine_status = m.machine_status.value.lower() if hasattr(m.machine_status, 'value') else str(m.machine_status).lower()
    except Exception:
        machine_status = str(getattr(m, 'machine_status', '')).lower()
    if machine_status == 'maintenance':
        raise NodeServiceError(f"MACHINE {operation} aborted: machine is maintenance", reason="machine_maintenance")
    ok = is_machine_online_remote(machine_id)
    if not ok:
        raise NodeServiceError(f"MACHINE {operation} aborted: remote node not reachable or not online", reason="machine_offline")


####################################################
#发送指令到集群实体机


def send(ciphertext:bytes,signature:bytes,mechine_ip:str, timeout:float=5.0)->dict:
    """
    发送 POST 并返回解析后的响应（优先 JSON），出现错误时返回包含 error 字段的 dict。
    """
    try:
        resp = requests.post(mechine_ip, json={
            "message": base64.b64encode(ciphertext).decode('utf-8'),
            "signature": base64.b64encode(signature).decode('utf-8')
        }, timeout=timeout)

        # 尝试解析为 JSON（即使是 4xx/5xx，也优先解析 body 中的 JSON，以保留 Node 返回的 error_reason）
        try:
            j = resp.json()
            if isinstance(j, dict):
                j.setdefault('status_code', resp.status_code)
            return j
        except ValueError:
            return {"status_code": resp.status_code, "text": resp.text}

    except requests.RequestException as e:
        # 网络/超时/连接等错误
        print(f"Request error: {e}")
        return {"error": str(e)}

#这个纯粹是为了方便统一异常处置流程
def _raise_on_node_error(res: dict, action: str):
    '''
    检查远端（Node）提供的响应的具体内容
    
    '''
    
    if not isinstance(res, dict):
        raise NodeServiceError(f"NODE {action} unexpected response: {res}", reason="unexpected_response")
    # network-level error
    if 'error' in res:
        err = res.get('error')
        err_reason = res.get('error_reason')
        raise NodeServiceError(f"NODE {action} failed: {err}", reason=err_reason or "NODE_error")
    # Node may include error_reason even without 'error'
    if 'error_reason' in res and res.get('success') != 1:
        raise NodeServiceError(f"NODE {action} failed: reason={res.get('error_reason')}", reason=res.get('error_reason'))


class NodeServiceError(Exception):
    '''
    提高一些Node侧错误上下文。只是为了z增加可读性
    '''
    
    def __init__(self, message: str, reason: str | None = None):
        super().__init__(message)
        self.reason = reason

def get_full_url(machine_ip:str, endpoint:str)->str:
    return f"http://{machine_ip}{CommsConfig.NODE_URL_MIDDLE}{endpoint}"


def get_container_status(machine_ip: str, container_name: str, timeout: float = 5.0) -> dict:
    """
    这个方法主要是为了在服务端调用 Node 的 /container_status API 来验证容器状态的。但是这个方法不被heartbeat使用。
    """
    url = get_full_url(machine_ip, "/container_status")
    payload = json.dumps({"config": {"container_name": container_name}})
    sig = signature(payload)
    enc = encryption(payload)

    last_exc = None
    for attempt in range(2):
        try:
            resp = requests.post(url, json={
                "message": base64.b64encode(enc).decode('utf-8'),
                "signature": base64.b64encode(sig).decode('utf-8')
            }, timeout=timeout)
            # Do not raise_for_status() here; inspect status code
            try:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        return {"status_code": resp.status_code, "text": resp.text}
                elif resp.status_code == 404:
                    return {"status_code": 404, "error": "not found", "text": resp.text}
                else:
                    return {"status_code": resp.status_code, "text": resp.text}
            except Exception as e:
                return {"error": str(e)}
        except requests.RequestException as e:
            last_exc = e
            print(f"get_container_status request error (attempt {attempt+1}): {e}")
            # short backoff before retrying
            if attempt == 0:
                time.sleep(0.5)
            continue

    # both attempts failed due to network/request errors
    return {"error": str(last_exc) if last_exc is not None else "unknown error"}

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
    # ensure machine is online before attempting creation
    _ensure_machine_online_for_operation(machine_id, 'create')
    machine_ip=get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/create_container")


    free_port = get_the_first_free_port(machine_id=machine_id)
    container.set_port(free_port)
    

    ### 参数检查 (delegated to repositories.container_repo helpers) ###
    # 存在性检查
    print(f"DEBUG: ensuring machine {machine_id} exists for container {container.NAME}")
    machine = container_repo.ensure_machine_exists(machine_id)
    # GPU 参数检查 
    print(f"DEBUG: validating GPU request for machine {machine_id} and container {container.NAME}")
    container_repo.validate_gpu_request(machine, container)
    # swap 参数检查
    print(f"DEBUG: validating swap request for machine {machine_id} and container {container.NAME}")
    requested_swap = container_repo.validate_swap_request(machine, container)
    # cpu 参数检查
    print(f"DEBUG: validating CPU request for machine {machine_id} and container {container.NAME}")
    requested_cpus = container_repo.validate_cpu_request(machine, container)
    # memory 参数检查
    print(f"DEBUG: validating memory request for machine {machine_id} and container {container.NAME}")
    requested_memory = container_repo.validate_memory_request(machine, container)
    # name/image/public_key length and format checks
    container_repo.validate_names_and_lengths(container, public_key)
    # duplicate name check (may raise IntegrityError)
    container_repo.check_duplicate_container_name(container_name=container.NAME, machine_id=machine_id)

    ### container构建 ###

    container_info=dict()
    container_info['owner_name']=owner_name
    container_info['config']=container.get_config()
    if public_key:
        container_info['public_key']=public_key
    container_info=json.dumps(container_info)
    # 防御性检查：限制字段长度，防止过长输入导致数据库异常或远程调用异常
    if container.NAME and len(container.NAME) > 115:
        raise ValueError(f"container name too long (max 115): length={len(container.NAME)}")
    if container.image and len(container.image) > 195:
        raise ValueError(f"container image name too long (max 195): length={len(container.image)}")
    if public_key and len(public_key) > 495:
        raise ValueError(f"public_key too long (max 495): length={len(public_key)}")
    # 只允许字母数字下划线
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
    

    encryptioned_message=encryption(container_info)
    res=send(encryptioned_message,signatured_message,full_url)
    print(f"Create_container: NODE response: {res}")
    # 检查Node是否返回错误，如果有则抛出异常；如果没有则继续后续流程（写DB记录、建立绑定、启动心跳等）
    _raise_on_node_error(res, 'create')
    if res.get('success') != 1:
        # unexpected response from Node; abort to avoid DB inconsistency
        raise NodeServiceError(f"NODE create returned failure or unexpected response: {res}", reason=res.get('error_reason') or "unexpected_response")

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
    if not machine_id:
        raise ValueError("Container not found or not associated with any machine")
    # 使得只在机器在线时执行
    _ensure_machine_online_for_operation(machine_id, 'remove')
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
    print(f"remove_container: NODE response: {res}")
    # 先看看远程调用层面是否有错误（网络/请求/远程处理错误等），如果有则抛出异常；如果没有则根据 Node 的返回内容来决定是否继续本地删除（Node 返回 NOTFOUND 则本地也删除，Node 返回 FAILED 则不删除并抛出异常）
    _raise_on_node_error(res, 'remove')
    # Node remove_container currently returns numeric code in 'success': 0=SUCCESS,1=NOTFOUND,2=FAILED
    NODE_code = res.get('success')
    if NODE_code is None:
        raise Exception(f"NODE remove returned unexpected response: {res}")
    if NODE_code == 2:
        # FAILED
        raise NodeServiceError(f"NODE remove reported failure: {res}", reason=res.get('error_reason') or 'remove_failed')
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
            print(f"远程调用失败: {res['error']}")
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
    if not machine_id:
        raise ValueError("Container not found or not associated with any machine")
    machine_ip=get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/add_collaborator")

    container_name = get_by_id(container_id).name
    # operation guard: machine must be online
    _ensure_machine_online_for_operation(machine_id, 'add_collaborator')
    # Ensure container is online before attempting collaborator changes
    container_obj = get_by_id(container_id)
    if not container_obj:
        raise ValueError("Container not found")
    if container_obj.container_status != ContainerStatus.ONLINE:
        raise NodeServiceError(f"Container {container_id} is not online", reason="container_offline")

    user_name=get_name_by_id(user_id)
    # validate inputs to avoid passing unsafe values to Node
    try:
        _sanitizer.validate_username(user_name)
    except Exception as e:
        raise ValueError(f"unsafe user_name: {e}")
    # Do not allow adding a collaborator as ROOT via this API/task
    if role == ROLE.ROOT:
        # Reject silently (caller/API will return failure)
        return False
    data={
        "config":{
            "container_name":container_name,
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
        _raise_on_node_error(res, 'add_collaborator')
        if res.get('success') not in (1, True):
            raise NodeServiceError(f"NODE add_collaborator returned failure: {res}", reason=res.get('error_reason') or 'add_failed')
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
    if not machine_id:
        raise ValueError("Container not found or not associated with any machine")
    machine_ip=get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/remove_collaborator")

    container_name = get_by_id(container_id).name
    # operation guard: machine must be online
    _ensure_machine_online_for_operation(machine_id, 'remove_collaborator')
    # Ensure container is online before attempting collaborator changes
    container_obj = get_by_id(container_id)
    if not container_obj:
        raise ValueError("Container not found")
    if container_obj.container_status != ContainerStatus.ONLINE:
        raise NodeServiceError(f"Container {container_id} is not online", reason="container_offline")
    user_name = get_name_by_id(user_id)
    try:
        _sanitizer.validate_username(user_name)
    except Exception as e:
        raise ValueError(f"unsafe user_name: {e}")

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
            "container_name":container_name,
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
        _raise_on_node_error(res, 'remove_collaborator')
        if res.get('success') not in (1, True):
            raise NodeServiceError(f"NODE remove_collaborator returned failure: {res}", reason=res.get('error_reason') or 'remove_failed')
        Key=True
    # 仅删除绑定
    remove_binding(user_id,container_id)
    
    if Key:
        return True
    return False

#修改user_id对container_id的访问权

def update_role(container_id:int,user_id:int,updated_role:ROLE,debug=False)->bool:
    machine_id = get_machine_id_by_container_id(container_id)
    if not machine_id:
        raise ValueError("Container not found or not associated with any machine")
    machine_ip=get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/update_role")

    container_name = get_by_id(container_id).name

    # Ensure container is online before attempting role updates
    # operation guard: machine must be online
    _ensure_machine_online_for_operation(machine_id, 'update_role')
    container_obj = get_by_id(container_id)
    if not container_obj:
        raise ValueError("Container not found")
    if container_obj.container_status != ContainerStatus.ONLINE:
        raise NodeServiceError(f"Container {container_id} is not online", reason="container_offline")

    user_name=get_name_by_id(user_id)
    try:
        _sanitizer.validate_username(user_name)
    except Exception as e:
        raise ValueError(f"unsafe user_name: {e}")
    # 远侧处理ROOT相关的角色变更 可能需单独考察
    data={
        "config":{
            "container_name":container_name,
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
        _raise_on_node_error(res, 'update_role')
        if res.get('success') not in (1, True):
            raise NodeServiceError(f"NODE update_role returned failure: {res}", reason=res.get('error_reason') or 'update_failed')
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


def start_container(container_id:int, debug=False)->bool:
    """发送start到对应容器所在node,启动后心跳机制监控状态，直到状态变为ONLINE或失败"""
    machine_id = get_machine_id_by_container_id(container_id)
    if not machine_id:
        raise ValueError("Container not found or not associated with any machine")
    _ensure_machine_online_for_operation(machine_id, 'start')
    machine_ip = get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/start_container")

    container_name = get_by_id(container_id).name
    data = {"config": {"container_name": container_name}}
    container_info = json.dumps(data)
    signatured_message = signature(container_info)
    encryptioned_message = encryption(container_info)

    res = send(encryptioned_message, signatured_message, full_url)
    print(f"start_container: NODE response: {res}")

    # Check node-level errors
    _raise_on_node_error(res, 'start')
    # Expect success truthy
    if res.get('success') in (1, True):
        # start controller-side heartbeat to watch for ONLINE
        try:
            container_starting_status_heartbeat(machine_ip, container_name, container_id=container_id)
        except Exception as e:
            print(f"Failed to start start-heartbeat: {e}")
        return True
    # Treat other responses as failure
    raise NodeServiceError(f"NODE start returned failure: {res}", reason=res.get('error_reason') or 'start_failed')


def stop_container(container_id:int, debug=False)->bool:
    """发送stop到对应容器所在node,停止后心跳机制监控状态，直到状态变为OFFLINE或失败"""
    machine_id = get_machine_id_by_container_id(container_id)
    if not machine_id:
        raise ValueError("Container not found or not associated with any machine")
    _ensure_machine_online_for_operation(machine_id, 'stop')
    machine_ip = get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/stop_container")

    container_name = get_by_id(container_id).name
    data = {"config": {"container_name": container_name}}
    container_info = json.dumps(data)
    signatured_message = signature(container_info)
    encryptioned_message = encryption(container_info)

    res = send(encryptioned_message, signatured_message, full_url)
    print(f"stop_container: NODE response: {res}")

    _raise_on_node_error(res, 'stop')
    if res.get('success') in (1, True):
        # start controller-side heartbeat to watch for OFFLINE
        try:
            container_stopping_status_heartbeat(machine_ip, container_name, container_id=container_id)
        except Exception as e:
            print(f"Failed to start stop-heartbeat: {e}")
        return True
    raise NodeServiceError(f"NODE stop returned failure: {res}", reason=res.get('error_reason') or 'stop_failed')


def restart_container(container_id:int, debug=False)->bool:
    """发送restart到对应容器所在node,重启后心跳机制监控状态，直到状态变为ONLINE或失败"""
    machine_id = get_machine_id_by_container_id(container_id)
    if not machine_id:
        raise ValueError("Container not found or not associated with any machine")
    _ensure_machine_online_for_operation(machine_id, 'restart')
    machine_ip = get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/restart_container")

    container_name = get_by_id(container_id).name
    data = {"config": {"container_name": container_name}}
    container_info = json.dumps(data)
    signatured_message = signature(container_info)
    encryptioned_message = encryption(container_info)

    res = send(encryptioned_message, signatured_message, full_url)
    print(f"restart_container: NODE response: {res}")

    _raise_on_node_error(res, 'restart')
    if res.get('success') in (1, True):
        #先t finished
        try:
            update_container(container_id, container_status=ContainerStatus.OFFLINE)
        except Exception as e:
            print(f"Warning: failed to mark container {container_id} as OFFLINE before restart-heartbeat: {e}")
        # start controller-side heartbeat to watch for ONLINE after restart
        try:
            container_restart_status_heartbeat(machine_ip, container_name, container_id=container_id)
        except Exception as e:
            print(f"Failed to start restart-heartbeat: {e}")
        return True
    raise NodeServiceError(f"NODE restart returned failure: {res}", reason=res.get('error_reason') or 'restart_failed')

#返回容器的细节信息
def get_container_detail_information(container_id:int)->container_detail_information:
    container=get_by_id(container_id)
    if not container:
        raise ValueError("Container not found")
    # 这个状态查询主要是为了验证容器是否真的存在于 Node 上，如果 Node 返回 404 则说明容器实际上已经不存在了，这时本地也应该删除记录并返回 not found 错误
    # 这个方法不处理从未放入数据库的容器（因为它们不应该有 container_id），也不处理网络/其他错误（因为它们不应该阻止返回数据库中的信息）。
    # 这里先检查机器状态，如果机器离线或维护中，则跳过 Node 检查直接返回数据库内容；如果机器在线，则进行 Node 检查以验证容器状态并尝试更新数据库中的状态信息。无论如何，如果 Node 检查失败（网络错误、超时等），都应该忽略错误并继续返回数据库内容，而不是阻止整个请求失败。
    try:
        m = machine_repo.get_by_id(container.machine_id)
    except Exception:
        m = None
    do_node_check = True
    if m is not None:
        try:
            status_val = m.machine_status.value.lower() if hasattr(m.machine_status, 'value') else str(m.machine_status).lower()
        except Exception:
            status_val = str(getattr(m, 'machine_status', '')).lower()
        if status_val in ('offline', 'maintenance'):
            do_node_check = False

    st = None
    if do_node_check:
        try:
            machine_ip = get_machine_ip_by_id(container.machine_id)
            st = get_container_status(machine_ip, container.name)
            # 找不到容器（Node 返回 404）时，删除本地记录并返回 not found 错误；其他错误（网络错误、超时、解析错误等）则忽略并继续返回数据库内容
            if isinstance(st, dict) and st.get('status_code') == 404:
                try:
                    remove_binding(0, container_id, all=True)
                except Exception as e:
                    print(f"Warning: failed to remove bindings for {container_id}: {e}")
                try:
                    delete_container(container_id)
                except Exception as e:
                    print(f"Warning: failed to delete container {container_id} from DB: {e}")
                raise ValueError("Container not found")
        except Exception as e:
            # 如果是 ValueError（通常是因为 Node 返回 404 导致的），则需要抛出以终止并返回 not found；如果是其他类型的异常（网络错误、超时、解析错误等），则应该捕获并忽略，以继续返回数据库中的信息。
            if isinstance(e, ValueError):
                raise
            print(f"get_container_detail_information: ignored NODE check error: {e}")

    # If Node returned a status payload, and it's not a 404, try to persist container_status to DB
    try:
        if st and isinstance(st, dict) and st.get('status_code') != 404:
            status_str = st.get('container_status')
            if status_str:
                try:
                    new_status = ContainerStatus(status_str)
                except Exception:
                    # try case-insensitive match of enum values
                    try:
                        new_status = next(s for s in ContainerStatus if s.value.lower() == str(status_str).lower())
                    except StopIteration:
                        new_status = None
                if new_status:
                    try:
                        update_container(container.id, container_status=new_status)
                    except Exception as e:
                        print(f"Warning: failed to update container status for {container.id}: {e}")
    except Exception as e:
        print(f"Warning: error while attempting to persist Node status for {container.id if 'container' in locals() and container else '?'}: {e}")

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
        # For information calls: if machine is offline or maintenance, skip node checks for containers on that machine
        do_node_check = True
        try:
            m = machine_repo.get_by_id(container.machine_id)
        except Exception:
            m = None
        if m is not None:
            try:
                status_val = m.machine_status.value.lower() if hasattr(m.machine_status, 'value') else str(m.machine_status).lower()
            except Exception:
                status_val = str(getattr(m, 'machine_status', '')).lower()
            if status_val in ('offline', 'maintenance'):
                do_node_check = False

        st = None
        if do_node_check:
            try:
                machine_ip = get_machine_ip_by_id(container.machine_id)
            except Exception:
                machine_ip = None
            if machine_ip:
                st = get_container_status(machine_ip, container.name)
                # If Node reports 404, delete local record (existing behavior)
                if isinstance(st, dict) and st.get('status_code') == 404:
                    try:
                        remove_binding(0, container.id, all=True)
                    except Exception as e:
                        print(f"Warning: failed to remove bindings for {container.id}: {e}")
                    try:
                        delete_container(container.id)
                    except Exception as e:
                        print(f"Warning: failed to delete container {container.id} from DB: {e}")
                    # skip adding this container to result
                    continue
                else:
                    # If Node returned a status payload (not 404), persist container_status to DB when possible
                    try:
                        if st and isinstance(st, dict) and st.get('status_code') is None or (isinstance(st, dict) and st.get('status_code') != 404):
                            status_str = st.get('container_status')
                            if status_str:
                                try:
                                    new_status = ContainerStatus(status_str)
                                except Exception:
                                    try:
                                        new_status = next(s for s in ContainerStatus if s.value.lower() == str(status_str).lower())
                                    except StopIteration:
                                        new_status = None
                                if new_status:
                                    try:
                                        update_container(container.id, container_status=new_status)
                                    except Exception as e:
                                        print(f"Warning: failed to update container status for {container.id}: {e}")
                    except Exception as e:
                        print(f"list_all_container_bref_information: ignored error while persisting status for {container.name}: {e}")

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
