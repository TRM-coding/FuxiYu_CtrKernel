from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

# 生成A的私钥
private_key_A = rsa.generate_private_key(public_exponent=65537, key_size=2048)
public_key_A = private_key_A.public_key()

# 保存私钥到文件
with open("./private_A.pem", "wb") as f:
    f.write(
        private_key_A.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,   # 通用私钥格式
            encryption_algorithm=serialization.NoEncryption()
        )
    )

# 保存公钥到文件
with open("./public_A.pem", "wb") as f:
    f.write(
        public_key_A.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo  # 标准公钥格式
        )
    )
