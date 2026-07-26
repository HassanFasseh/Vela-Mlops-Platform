terraform {
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 5.0"
    }
  }
}

provider "oci" {
  config_file_profile = "DEFAULT"
  region               = var.region
}

provider "oci" {
  alias                = "home"
  config_file_profile  = "DEFAULT"
  region               = var.home_region
}