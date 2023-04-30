import oci
import os
import shutil
import time
import random
from oci.core.models.shape import Shape
from dotenv import load_dotenv, dotenv_values, set_key
from helpers import *
from datetime import datetime

load_dotenv()

def prompt_select(msg, lst1, lst2, create_fn = None):
    print(msg)
    justify = len(str(len(lst1)))
    lst_msg = lst1[:]
    if create_fn != None:
        lst_msg.append("Create new")
    for i, component in enumerate(lst_msg):
        print(f"[{str(i+1).rjust(justify)}] {component}")
    selected_i = int(input(">> "))
    if create_fn != None and selected_i == len(lst_msg):
        return create_fn()
    elif selected_i < 1 or selected_i > len(lst1):
        raise Exception("Invalid selection")
    return lst2[selected_i-1]

def prompt_list(env_name, object_name, object_list, name_property = "name", id_property = "id", create_fn = None):
    # if object_name == 'image': print(object_list)
    object_env = os.getenv(env_name, "")
    if object_env != "":
        tmp = [x for x in object_list if getattr(x, id_property) == object_env]
        if len(tmp) < 1: exit(f"Unknown {object_name}: {object_env}")
        return tmp[0]
    else:
        return prompt_select(
            f"Select {object_name}:", 
            [getattr(x, name_property) for x in object_list],
            object_list,
            create_fn
        )
    
def prompt_parse(env_name, object_name, parse_fn, default = None):
    value = os.getenv(env_name, "")
    result = None
    try:
        result = parse_fn(value)
    except:
        msg = f"Input {object_name}"
        if default != None:
            msg += f" [{default}]"
        value = input(f"{msg}: ")
        if value == "": 
            value = default
        result = parse_fn(value)
    return result

def launch_loop(instance_detail, min_wait = 180, max_wait = 300):
    instance = None
    exit_on_unexpected = os.getenv("EXIT_ON_UNEXPECTED_ERROR") != None
    print("Instance detail:")
    print(instance_detail)
    print()
    while instance == None:
        work_request_response = None
        try:
            work_request_response = compute_client_composite_operations.launch_instance_and_wait_for_work_request(
                instance_detail
            )
        except oci.exceptions.ServiceError as e:
            if e.message != "Out of host capacity." and exit_on_unexpected:
                print(f"Got unexpected error!")
                print(f"{e.message}")
                print(f"Variable EXIT_ON_UNEXPECTED_ERROR is set, exiting...")
                break
            print(f"{e.message}")
            wait_sec = random.randrange(min_wait, max_wait)
            print(f"Sleeping for {wait_sec} seconds")
            time.sleep(wait_sec)
            continue
        work_request = work_request_response.data

        # Now retrieve the instance details from the information in the work request resources
        instance_id = work_request.resources[0].identifier
        get_instance_response = compute_client_composite_operations.client.get_instance(instance_id)
        instance = get_instance_response.data
        print(instance)

def print_justified(dic):
    justify = max(list(map(len, dic.keys())))
    for k,v in dic.items():
        print(f"{k.ljust(justify)}  : {v}")

if __name__ == "__main__":
    config = oci.config.from_file()
    
    identity_client = oci.identity.IdentityClient(config)
    compute_client = oci.core.ComputeClient(config)
    compute_client_composite_operations = oci.core.ComputeClientCompositeOperations(compute_client)
    virtual_network_client = oci.core.VirtualNetworkClient(config)
    virtual_composite_client = oci.core.VirtualNetworkClientCompositeOperations(virtual_network_client)
    tenancy_id = config["tenancy"]

    compartment = prompt_list(
        "COMPARTMENT_ID",
        "compartment",
        get_compartments(identity_client, tenancy_id)
    )

    availability_domain = prompt_list(
        "AVAILABILITY_DOMAIN",
        "availability domain",
        get_availability_domains(identity_client, compartment.id),
        id_property="name"
    )

    shape = prompt_list(
        "SHAPE",
        "shape",
        get_shapes(compute_client, compartment.id, availability_domain.name),
        name_property="shape",
        id_property="shape"
    )

    image = prompt_list(
        "IMAGE",
        "image",
        get_images(compute_client, compartment.id, shape.shape),
        name_property="display_name",
        id_property="display_name"
    )

    vcn = prompt_list(
        "VCN",
        "vcn",
        get_vcns(virtual_network_client, compartment.id),
        name_property="display_name",
        id_property="display_name",
        create_fn=lambda: create_vcn(virtual_composite_client, compartment.id)
    )

    subnet = prompt_list(
        "SUBNET",
        "subnet",
        get_subnets(virtual_network_client, compartment.id, vcn.id),
        name_property="display_name",
        id_property="display_name",
        create_fn=lambda: create_subnet(virtual_composite_client, vcn, availability_domain)
    )

    gateway = prompt_list(
        "INTERNET_GATEWAY",
        "internet gateway",
        get_gateways(virtual_network_client, compartment.id, vcn.id),
        name_property="display_name",
        id_property="display_name",
        create_fn=lambda: create_gateway(virtual_composite_client, vcn)
    )
    add_internet_route(virtual_network_client, virtual_composite_client, vcn, gateway)

    ocpus = prompt_parse("OCPU", "ocpu ammount (cores)", int, int(shape.ocpus))

    ram = prompt_parse("RAM", "vm memmory (GB)", int, int(shape.memory_in_gbs))

    disk_size = prompt_parse("DISK_SIZE", "disk size (GB)", int, 50)

    def check_str(v):
        if v == "":
            raise ValueError("Value must not be empty!")
        return v

    name = prompt_parse("NAME", "instance name", check_str, datetime.now().strftime("vm-%Y%m%d-%H%M"))
    if name == "": 
        exit("Name must not be empty!")

    pub_key = prompt_parse("PUB_KEY", "public key", check_str)
    if pub_key == "" or pub_key == None: 
        exit("Public key must not be empty!")

    old_settings = dict(dotenv_values())
    new_settings = {
        "NAME": name,
        "OCPU": str(ocpus),
        "RAM": str(ram),
        "DISK_SIZE": str(disk_size),
        "SHAPE": shape.shape,
        "IMAGE": image.display_name,
        "COMPARTMENT_ID": compartment.id,
        "AVAILABILITY_DOMAIN": availability_domain.name,
        "VCN": vcn.display_name,
        "SUBNET": subnet.display_name,
        "INTERNET_GATEWAY": gateway.display_name,
        "PUB_KEY": pub_key,
    }
    
    if old_settings != new_settings:
        i = 0
        while os.path.exists(".env.bak.%s" % i):
            i += 1
        shutil.move(".env", f".env.bak.{i}")
        set_key(".env", "NAME", name)
        set_key(".env", "OCPU", str(ocpus))
        set_key(".env", "RAM", str(ram))
        set_key(".env", "DISK_SIZE", str(disk_size))
        set_key(".env", "SHAPE", shape.shape)
        set_key(".env", "IMAGE", image.display_name)
        set_key(".env", "COMPARTMENT_ID", compartment.id)
        set_key(".env", "AVAILABILITY_DOMAIN", availability_domain.name)
        set_key(".env", "VCN", vcn.display_name)
        set_key(".env", "SUBNET", subnet.display_name)
        set_key(".env", "INTERNET_GATEWAY", gateway.display_name)
        set_key(".env", "PUB_KEY", pub_key)
        

    print_justified(new_settings)
    confirm = input("Confirm? [Y/n]: ").lower()
    if confirm == "n":
        exit("Canceled")

    print("\nLaunching...")
    instance_detail = get_launch_instance_details(name, compartment.id, availability_domain, shape, image, subnet, ocpus, ram, disk_size, pub_key)
    launch_loop(instance_detail, int(os.getenv("MIN_WAIT", "180")), int(os.getenv("MAX_WAIT", "300")))