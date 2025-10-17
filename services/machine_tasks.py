#TODO:完善异常处理机制
from ..repositories.machine_repo import *
from pydantic import BaseModel
#######################################
#API Definition
class machine_bref_information(BaseModel):
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
    gpu_type:int
    memory_size_gb:int
    disk_size_gb:int
    machine_description:str
    containers:list[str] #容器id
#######################################


#######################################
# 添加一个新的机器到集群
def Add_machine(machinename:str,
                   machineip:str,
                   machine_type:MachineTypes,
                   machine_description:str,
                   cpu_core_number:int,
                   gpu_number:int,
                   gpu_type:int,
                   memory_size:int,
                   disk_size:int)->Machine:
    create_machine(
         machinename=machinename,
         machineip=machineip,
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
        machine_name=machine.machinename,
        machine_ip=machine.machineip,
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
def List_all_machine_bref_information(page_number:int, page_size:int)->list[machine_bref_information]:
    machines = list_machines(limit=page_size, offset=page_number*page_size)
    res = []
    for machine in machines:
        info = machine_bref_information(
            machine_ip=machine.machineip,
            machine_type=machine.machine_type.value,
            machine_status=machine.machine_status.value
        )
        res.append(info)
    return res
#######################################

#######################################
# 重启机器
#TODO:实现重启功能
#######################################

