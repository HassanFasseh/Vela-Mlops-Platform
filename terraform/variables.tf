variable "tenancy_ocid" {
  type = string
}
variable "compartment_ocid" {
  type = string
}
variable "region" {
  type    = string
  default = "af-casablanca-1"
}
variable "kubernetes_version" {
  type    = string
  default = "v1.35.2"
}
