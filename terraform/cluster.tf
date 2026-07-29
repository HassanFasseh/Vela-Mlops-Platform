resource "oci_containerengine_cluster" "cluster" {
  compartment_id     = var.compartment_ocid
  kubernetes_version = var.kubernetes_version
  name               = "mlops-poc"
  vcn_id             = oci_core_vcn.vcn.id

  endpoint_config {
    is_public_ip_enabled = true
    subnet_id            = oci_core_subnet.subnet.id
  }
}

data "oci_containerengine_node_pool_option" "node_options" {
  node_pool_option_id = "all"
  compartment_id      = var.compartment_ocid
}

resource "oci_containerengine_node_pool" "nodepool" {
  cluster_id         = oci_containerengine_cluster.cluster.id
  compartment_id     = var.compartment_ocid
  kubernetes_version = var.kubernetes_version
  name               = "mlops-poc-pool"
  node_shape         = "VM.Standard.A1.Flex"

  node_shape_config {
    ocpus         = 2
    memory_in_gbs = 12
  }

  node_config_details {
    size = 1
    placement_configs {
      availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
      subnet_id            = oci_core_subnet.subnet.id
    }
  }

  node_source_details {
    source_type = "IMAGE"
    image_id = [for s in data.oci_containerengine_node_pool_option.node_options.sources : s.image_id if length(regexall("Oracle-Linux", s.source_name)) > 0 && length(regexall(replace(var.kubernetes_version, "v", ""), s.source_name)) > 0][0]
  }

  lifecycle {
    ignore_changes = [node_source_details]
  }
}