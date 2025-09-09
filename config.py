"""应用配置模块

提供不同环境的配置类，支持通过环境变量覆盖默认值。
"""

import os


class SqlConfig:
    SQLNAME='CLUSTER'

class KeyConfig:
    PUBLIC_KEY_PATH='public_A.pem'
    PRIVATE_KEY_PATH='private_A.pem'



