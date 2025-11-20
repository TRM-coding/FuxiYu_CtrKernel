from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from cryptography.hazmat.primitives.asymmetric import rsa
from ..config import KeyConfig
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
import json
# 加载公钥和私钥，返回公钥和私钥对象
def load_keys(private_key_path:str,pub_key_path:str,pub_key_node_path)->tuple[RSAPrivateKey,RSAPublicKey,RSAPublicKey]:
    with open(private_key_path, "rb") as f:
        private_key_A = serialization.load_pem_private_key(
            f.read(),
            password=None,   # 如果加密过，就填密码
        )

    # 加载公钥
    with open(pub_key_path, "rb") as f:
        public_key_A = serialization.load_pem_public_key(f.read())
    with open(pub_key_node_path,"rb") as f:
        public_node = serialization.load_pem_public_key(f.read())

    return (private_key_A,public_key_A,public_node)

def generate_keys()->tuple[RSAPrivateKey,RSAPublicKey]:
    private_key_A = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_A = private_key_A.public_key()
    return (private_key_A,public_key_A)

def write_keys(path:str,key):
    # 保存私钥到文件
    if type(key)==RSAPrivateKey:
        with open(path, "wb") as f:
            f.write(
                key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,   # 通用私钥格式
                    encryption_algorithm=serialization.NoEncryption()
                )
            )
    elif type(key)==RSAPublicKey:
        with open(path, "wb") as f:
            f.write(
                key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo  # 标准公钥格式
                )
            )

#加密信息
def encryption(message:str)->bytes:
    _,_,PUBLIC_KEY_B=load_keys(KeyConfig.PRIVATE_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH)
    if isinstance(message, str):
        message = message.encode('utf-8')
    ciphertext = PUBLIC_KEY_B.encrypt(
        message,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None)
    )
    return ciphertext

#签名信息
def signature(message:str)->bytes:
    PRIVATE_KEY_A,_,_=load_keys(KeyConfig.PRIVATE_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH)
    # 将字符串编码为 bytes
    message_bytes = message.encode('utf-8') if isinstance(message, str) else message
    signature = PRIVATE_KEY_A.sign(
        message_bytes,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256()
    )
    return signature

#解密信息
def decryption(ciphertext:bytes)->bytes:
    PRIVATE_KEY_A,_,_=load_keys(KeyConfig.PRIVATE_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH)
    plaintext = PRIVATE_KEY_A.decrypt(
        ciphertext,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None)
    )
    return plaintext

#验证签名
def verify_signature(message:bytes, signature:bytes)->bool:
    _,_,PUBLIC_KEY_B=load_keys(KeyConfig.PRIVATE_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH)
    try:
        PUBLIC_KEY_B.verify(
            signature,
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                       salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256()
        )
        return True
    except Exception:
        return False
    
def get_verified_msg(recived_message:dict)->dict:
    """
    解密并验证签名的消息
    :param recived_message: 包含加密消息和签名的字典 {"message": bytes/str, "signature": bytes/str}
    :return: 验证成功返回解密后的字典，失败返回空字典
    """
    try:
        # 提取加密消息和签名
        encrypted_msg = recived_message.get("message")
        signature_data = recived_message.get("signature")
        
        if not encrypted_msg or not signature_data:
            return {}
        
        # 确保是 bytes 类型
        if isinstance(encrypted_msg, str):
            encrypted_msg = encrypted_msg.encode()
        if isinstance(signature_data, str):
            signature_data = signature_data.encode()
        
        # 解密消息
        decrypted_msg = decryption(encrypted_msg)
        
        # 验证签名
        if not verify_signature(decrypted_msg, signature_data):
            return {}
        
        # 将解密后的消息转换为字典
        message_dict = json.loads(decrypted_msg.decode('utf-8'))
        
        return message_dict
    except Exception as e:
        # 任何异常都返回空字典
        return {}