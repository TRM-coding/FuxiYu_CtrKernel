#TODO:继续完成实现

from ..repositories import containers_repo
from ..constant import *
from pydantic import BaseModel
from config import KeyConfig
from ..utils.load_keys import load_keys
from ..utils.docker_commands import Container
from ..repositories import containers_repo
import requests
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey


#Load Public And Private Keys
####################################################
PRIVATE_KEY_A,PUBLIC_KEY_A=load_keys(KeyConfig.PRIVATE_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH)
####################################################

####################################################
#控制指令格式：
'''
{
    "type":['create'|'delete'|'shutdown'|'restart'|'update'],#选一个
    "config":
    {
        "gpu_list":[0,1,2,...],
        "cpu_number":20,
        "memory":16,#GB
        "user_name":'example',
    }
}
'''
####################################################



####################################################
#加密控制指令
def encryption(message:str,public_key_B:RSAPublicKey)->bytes:
    ciphertext = public_key_B.encrypt(
        message,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None)
    )
    return ciphertext

#生成控制指令签名
def signature(message:str)->bytes:
    signature = PRIVATE_KEY_A.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256()
    )
    return signature

#发送指令到集群实体机
def send(ciphertext:bytes,signature:bytes,mechine_ip:str):
    requests.post(mechine_ip, json={
            "ciphertext": ciphertext.hex(),
            "signature": signature.hex()
    })

####################################################




#Type Definition
####################################################
class container_bref_information(BaseModel):
    container_name:str
    container_image:str
    machine_ip:str
    container_status:str

class container_detail_information(BaseModel):
    container_name:str
    container_image:str
    user_id: int
    user_name: str
    role: str
####################################################



#Function Implementation
####################################################

# 将user_id作为admin，创建新容器
def create_container(user_name:str,machine_ip:str,container:Container)->bool:
    container_info=container.tostr()
    raise NotImplementedError

#删除容器并删除其所有者记录
def remove_container(container_id)->bool:
    raise NotImplementedError

#将container_id对应的容器新增user_id作为collaborator,其权限为role
def add_collaborator(container_id:int,user_id:int,role:ROLE)->bool:
    raise NotImplementedError

#从container_id中移除user_id对应的用户访问权
def remove_collaborator(container_id:int,user_id:int)->bool:
    raise NotImplementedError

#修改user_id对container_id的访问权
def update_role(container_id:int,user_id:int,updated_role:ROLE)->bool:
    raise NotImplementedError

#返回user_id用户在container_id容器中的权限
def show_user_container_role(container_id:int,user_id:int)->ROLE:
    raise NotImplementedError

#返回容器的细节信息
def get_container_detail_information(container_id:int)->container_detail_information:
    raise NotImplementedError

#返回一页容器的概要信息
def list_all_container_bref_information(page_number:int,page_size:int)->list[container_bref_information]:
    raise NotImplementedError

####################################################
