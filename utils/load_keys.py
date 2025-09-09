from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

# 加载公钥和私钥，返回公钥和私钥对象
def load_keys(private_key_path:str,pub_key_path:str)->tuple[RSAPrivateKey,RSAPublicKey]:
    with open(private_key_path, "rb") as f:
        private_key_A = serialization.load_pem_private_key(
            f.read(),
            password=None,   # 如果加密过，就填密码
        )

    # 加载公钥
    with open(pub_key_path, "rb") as f:
        public_key_A = serialization.load_pem_public_key(f.read())

    # print(private_key_A)
    # print(public_key_A)
    return (private_key_A,public_key_A)

if __name__=="__main__":
    load_keys("private_A.pem")
    load_keys("public_A.pem")
