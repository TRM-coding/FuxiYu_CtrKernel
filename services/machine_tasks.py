#TODO:完善异常处理机制
from ..repositories.machine_repo import *
from pydantic import BaseModel
from typing import Optional
#######################################
#API Definition
class machine_bref_information(BaseModel):
    id: int  #没想到更好的解决办法。主要作为各种操作的映射。
    machine_name:str
    machine_ip:str
    machine_type:str
    machine_status:str

class machine_detail_information(BaseModel):
    machine_name:str
    machine_ip:str
    machine_type:str
    machine_status:str
    cpu_core_number:int
    gpu_number:int
    gpu_type: Optional[str] # 部分sql数据会出现此字段是NULL的情况，因此暂时用这个方法解决
    memory_size_gb:int
    disk_size_gb:int
    machine_description:str
    containers:list[int] #容器id
#######################################


#######################################
# 添加一个新的机器到集群
def Add_machine(machine_name:str,
                   machine_ip:str,
                   machine_type:MachineTypes,
                   machine_description:str,
                   cpu_core_number:int,
                   gpu_number:int,
                   gpu_type:str,
                   memory_size:int,
                   disk_size:int)->bool:
    create_machine(
         machinename=machine_name,
         machine_ip=machine_ip,
         machine_type=machine_type,
         machine_description=machine_description,
         cpu_core_number=cpu_core_number,
         gpu_number=gpu_number,
         gpu_type=gpu_type,
         memory_size=memory_size,
         disk_size=disk_size
    )
    return True

#######################################


#######################################
# 删除集群中的一个（一组）机器
def Remove_machine(machine_id:list[int])->bool:
    for id in machine_id:
        delete_machine(id)
    return True
#######################################


#######################################
# 更新机器的信息
def Update_machine(machine_id: int, **fields) -> bool:
    update_machine(machine_id, **fields)
    return True    
#######################################


#######################################
# 根据机器ID获取机器的详细信息
def Get_detail_information(machine_id:int)->machine_detail_information|None:
    machine=get_by_id(machine_id)
    if not machine:
        return None

    return machine_detail_information(
        machine_name=machine.machine_name,
        machine_ip=machine.machine_ip,
        machine_type=machine.machine_type.value,
        machine_status=machine.machine_status.value,
        cpu_core_number=machine.cpu_core_number,
        gpu_number=machine.gpu_number,
        gpu_type=machine.gpu_type,
        memory_size_gb=machine.memory_size_gb,
        disk_size_gb=machine.disk_size_gb,
        machine_description=machine.machine_description,
        containers=[container.id for container in machine.containers]
    )
#######################################

#######################################
# 获取一批机器的概要信息
def List_all_machine_bref_information(page_number:int, page_size:int)->tuple[list[machine_bref_information], int]:
    machines = list_machines(limit=page_size, offset=page_number*page_size)
    res = []
    for machine in machines:
        info = machine_bref_information(
            id=machine.id,
            machine_name=machine.machine_name,
            machine_ip=machine.machine_ip,
            machine_type=machine.machine_type.value,
            machine_status=machine.machine_status.value
        )
        res.append(info)
    # 这里增加了总数字段 方便分页器判断显示多少
    total_count = count_machines()
    total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 0
    return res, total_pages
#######################################

#######################################
# 重启机器
#TODO:实现重启功能
#######################################

