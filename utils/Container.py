import json
from pydantic import BaseModel
class Container:
    class Config_info(BaseModel):
        gpu_list:list
        cpu_number:int
        memory:int
        user_name:str
        port:int
        image:str
    #gpu_list:显卡编号，cpu_number:需要用到的cpu核数，memory:申请的内存大小（GB）
    def __init__(self,gpu_list:list,cpu_number:int,memory:int,user_name:str,image:str,port:int=0):
        self.GPU_LIST=gpu_list
        self.CPU_NUMBER=cpu_number
        self.MEMORY=memory
        self.USER_NAME=user_name
        self.__PORT=port
        self.image=image
        return
    
    def set_port(self,port:int):
        if type(port) != int:
            raise TypeError
        if port>49151 or port<1024:
            raise ValueError
        self.__PORT=port
    
    def get_config(self)->Config_info:
        res : Container.Config_info ={
            "gpu_list":self.GPU_LIST,
            "cpu_number":self.CPU_NUMBER,
            "memory":self.MEMORY,
            "user_name":self.USER_NAME,
            "port":self.__PORT,
            "image":self.image
        }
        return res
    
    @classmethod
    def toContainer(cls,config:str)->Config_info:
        data=json.loads(config)
        cfg=Container.Config_info(**data)
        return cfg
    
