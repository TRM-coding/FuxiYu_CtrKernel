#TODO:完成实现

from ..repositories import containers_repo
from ..constant import *
from typing import TypedDict
from config import KeyConfig
from ..utils.load_keys import load_keys
import requests
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey


#Load Public And Private Keys
####################################################
PRIVATE_KEY_A,PUBLIC_KEY_A=load_keys(KeyConfig.PRIVATE_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH)

def encryption(message:str,public_key_B:RSAPublicKey)->bytes:
    ciphertext = public_key_B.encrypt(
        message,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None)
    )
    return ciphertext

def signature(message:str)->bytes:
    signature = PRIVATE_KEY_A.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256()
    )
    return signature

####################################################




#Type Definition
####################################################
class container_bref_information(TypedDict):
    container_name:str
    container_image:str
    machine_ip:str
    container_status:str

class container_detail_information(TypedDict):
    container_name:str
    container_image:str
    user_id: int
    user_name: str
    role: str
####################################################



#Function Implementation
####################################################

# 将user_id作为admin，创建新容器
def create_container(user_name:str,machine_ip:str)->bool:
    
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
