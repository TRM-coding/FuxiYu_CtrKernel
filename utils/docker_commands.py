import json
from pydantic import BaseModel
class Container:
    class Config_info(BaseModel):
        gpu_list:list
        cpu_number:int
        memory:int
        user_name:str
    #gpu_list:显卡编号，cpu_number:需要用到的cpu核数，memory:申请的内存大小（GB）
    def __init__(self,gpu_list:list,cpu_number:int,memory:int,user_name:str):
        self.GPU_LIST=gpu_list
        self.CPU_NUMBER=cpu_number
        self.MEMORY=memory
        self.USER_NAME=user_name
        return
    
    def tostr(self):
        res : Container.Config_info ={
            "gpu_list":self.GPU_LIST,
            "cpu_number":self.CPU_NUMBER,
            "memory":self.MEMORY,
            "user_name":self.USER_NAME
        }
        return json.dumps(res)
    
