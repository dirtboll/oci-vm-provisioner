import oci
from datetime import datetime

def get_compartments(identity_client, tenancy_id):
    return [identity_client.get_compartment(tenancy_id).data] + oci.pagination.list_call_get_all_results(
        identity_client.list_compartments,
        tenancy_id,
        compartment_id_in_subtree=True,
        access_level="ANY"
    ).data

def get_availability_domains(identity_client, compartment_id):
    return oci.pagination.list_call_get_all_results(
        identity_client.list_availability_domains,
        compartment_id
    ).data

def get_shapes(compute_client, compartment_id, availability_domain):
    list_shapes = oci.pagination.list_call_get_all_results(
        compute_client.list_shapes,
        compartment_id,
        availability_domain=availability_domain
    ).data
    return list(filter(lambda shape: shape.shape.startswith("VM"), list_shapes))

def get_images(compute_client, compartment_id, shape):
    return oci.pagination.list_call_get_all_results(
        compute_client.list_images,
        compartment_id,
        shape=shape
    ).data

def get_vcns(virtual_network_client, compartment_id):
    return oci.pagination.list_call_get_all_results(
        virtual_network_client.list_vcns,
        compartment_id
    ).data

def create_vcn(virtual_composite_client, compartment_id):
    default_name = datetime.now().strftime("vcn-%Y%m%d-%H%M")
    default_cidr = "10.0.0.0/16"
    name = input(f"Name [{default_name}]: ")
    name = default_name if name == "" else name
    cidr = input(f"CIDR blocks [{default_cidr}]: ")
    cidr = default_cidr if cidr == "" else cidr
    cidr_blocks = cidr.split(",")
    create_vcn_details = oci.core.models.CreateVcnDetails(
        cidr_blocks=cidr_blocks,
        display_name=name,
        compartment_id=compartment_id
    )
    create_vcn_response = virtual_composite_client.create_vcn_and_wait_for_state(
        create_vcn_details,
        wait_for_states=[oci.core.models.Vcn.LIFECYCLE_STATE_AVAILABLE]
    )
    vcn = create_vcn_response.data
    print('Created VCN: {}'.format(vcn.id))
    print('{}'.format(vcn))
    return vcn


def get_subnets(virtual_network_client, compartment_id, vcn_id):
    return oci.pagination.list_call_get_all_results(
        virtual_network_client.list_subnets,
        compartment_id,
        vcn_id=vcn_id
    ).data

def create_subnet(virtual_composite_client, vcn, availability_domain):
    default_name = datetime.now().strftime("subnet-%Y%m%d-%H%M")
    name = input(f"Name [{default_name}]: ")
    name = default_name if name == "" else name
    create_subnet_details = oci.core.models.CreateSubnetDetails(
        compartment_id=vcn.compartment_id,
        availability_domain=availability_domain.name,
        display_name=name,
        vcn_id=vcn.id,
        cidr_block=vcn.cidr_block
    )
    create_subnet_response = virtual_composite_client.create_subnet_and_wait_for_state(
        create_subnet_details,
        wait_for_states=[oci.core.models.Subnet.LIFECYCLE_STATE_AVAILABLE]
    )
    subnet = create_subnet_response.data
    print('Created Subnet: {}'.format(subnet.id))
    print('{}'.format(subnet))
    return subnet


def get_gateways(virtual_network_client, compartment_id, vcn_id):
    return oci.pagination.list_call_get_all_results(
        virtual_network_client.list_internet_gateways,
        compartment_id,
        vcn_id=vcn_id
    ).data

def create_gateway(virtual_composite_client, vcn):
    default_name = "Internet Gateway for " + vcn.display_name
    name = input(f"Name [{default_name}]: ")
    name = default_name if name == "" else name
    create_internet_gateway_details = oci.core.models.CreateInternetGatewayDetails(
        display_name=name,
        compartment_id=vcn.compartment_id,
        is_enabled=True,
        vcn_id=vcn.id
    )
    create_internet_gateway_response = virtual_composite_client.create_internet_gateway_and_wait_for_state(
        create_internet_gateway_details,
        wait_for_states=[oci.core.models.InternetGateway.LIFECYCLE_STATE_AVAILABLE]
    )
    gateway = create_internet_gateway_response.data

    print('Created internet gateway: {}'.format(gateway.id))
    print('{}'.format(gateway))
    print()
    return gateway

# This makes sure that we use the internet gateway for accessing the internet. See:
# https://docs.cloud.oracle.com/Content/Network/Tasks/managingIGs.htm
# for more information.
#
# As a convenience, we'll add a route rule to the default route table. However, in your
# own code you may opt to use a different route table
def add_internet_route(
        virtual_network_client, virtual_network_composite_operations, vcn, internet_gateway):
    get_route_table_response = virtual_network_client.get_route_table(vcn.default_route_table_id)
    route_rules = get_route_table_response.data.route_rules

    # Updating route rules will totally replace any current route rules with what we send through.
    # If we wish to preserve any existing route rules, we need to read them out first and then send
    # them back to the service as part of any update
    route_rule = oci.core.models.RouteRule(
        cidr_block=None,
        destination='0.0.0.0/0',
        destination_type='CIDR_BLOCK',
        network_entity_id=internet_gateway.id
    )
    old_rules = route_rules
    route_rules.append(route_rule)
    update_route_table_details = oci.core.models.UpdateRouteTableDetails(route_rules=route_rules)
    try:
        update_route_table_response = virtual_network_composite_operations.update_route_table_and_wait_for_state(
            vcn.default_route_table_id,
            update_route_table_details,
            wait_for_states=[oci.core.models.RouteTable.LIFECYCLE_STATE_AVAILABLE]
        )
    except oci.exceptions.ServiceError as e:
        if e.message.startswith("Duplicate rule found"):
            return old_rules
        raise e
    route_table = update_route_table_response.data

    return route_table

def get_launch_instance_details(instance_name, compartment_id, availability_domain, shape, image, subnet, ocpus, ram, storage, ssh_public_key):

    # We can use instance metadata to specify the SSH keys to be included in the
    # ~/.ssh/authorized_keys file for the default user on the instance via the special "ssh_authorized_keys" key.
    #
    # We can also provide arbitrary string keys and string values. If you are providing these, you should consider
    # whether defined and freeform tags on an instance would better meet your use case. See:
    # https://docs.cloud.oracle.com/Content/Identity/Concepts/taggingoverview.htm for more information
    # on tagging
    instance_metadata = {
        'ssh_authorized_keys': ssh_public_key,
    }

    # We can also provide a user_data key in the metadata that will be used by Cloud-Init
    # to run custom scripts or provide custom Cloud-Init configuration. The contents of this
    # key should be Base64-encoded data and the SDK offers a convenience function to transform
    # a file at a given path to that encoded data
    #
    # See: https://docs.cloud.oracle.com/api/#/en/iaas/20160918/datatypes/LaunchInstanceDetails
    # for more information
    # instance_metadata['user_data'] = oci.util.file_content_as_launch_instance_user_data(
    #     'examples/launch_instance/user_data.sh'
    # )

    # Extended metadata differs from normal metadata in that it can support nested maps/dicts. If you are providing
    # these, you should consider whether defined and freeform tags on an instance would better meet your use case.
    # instance_extended_metadata = {
    #     'string_key_1': 'string_value_1',
    #     'map_key_1': {
    #         'string_key_2': 'string_value_2',
    #         'map_key_2': {
    #             'string_key_3': 'string_value_3'
    #         },
    #         'empty_map_key': {}
    #     }
    # }


    instance_source_via_image_details = oci.core.models.InstanceSourceViaImageDetails(
        image_id=image.id,
        boot_volume_size_in_gbs=storage
    )
    shape_config_detail = oci.core.models.LaunchInstanceShapeConfigDetails(
        memory_in_gbs=ram,
        ocpus=ocpus
    )
    create_vnic_details = oci.core.models.CreateVnicDetails(
        subnet_id=subnet.id
    )
    launch_instance_details = oci.core.models.LaunchInstanceDetails(
        display_name=instance_name,
        compartment_id=compartment_id,
        availability_domain=availability_domain.name,
        shape=shape.shape,
        shape_config=shape_config_detail,
        metadata=instance_metadata,
        source_details=instance_source_via_image_details,
        create_vnic_details=create_vnic_details
    )
    return launch_instance_details

