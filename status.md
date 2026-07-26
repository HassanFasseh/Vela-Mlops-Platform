# Project Status

**Last Updated:** 26 July 2026

## ✅ Completed

### Development Environment

* Configured the development environment using **WSL2**.
* Installed and verified the required tooling:

  * Git
  * Docker
  * Terraform
  * kubectl
  * Helm
  * OCI CLI
* Confirmed all tools are working correctly.

### Cloud Infrastructure

* Provisioned the Oracle Cloud infrastructure using **Terraform**.
* Infrastructure currently includes:

  * Virtual Cloud Network (VCN)
  * Networking resources (subnets, gateways, security rules)
  * Oracle Kubernetes Engine (OKE) cluster
  * One Kubernetes worker node
* Successfully deployed and validated the cluster (`kubectl get nodes` reports the node as **Ready**).

> **Note:** The deployment required updating several Terraform/provider configurations due to version differences from the original documentation. The configuration has now been adapted and is fully reproducible.

### Repository

* Reorganized the repository structure.
* Moved `terraform/` and `.github/workflows/` to the project root.
* Renamed the Pydantic schema file from `models.py` to `schemas.py` to avoid conflicts with `db/models.py`.
* Added a `.gitignore` to exclude Terraform state files, credentials, Python cache, and other generated files.

---

## 🚧 In Progress

* Preparing the first application for containerization.
* Setting up the initial Kubernetes deployment workflow.

---

## 🎯 Next Steps

* Containerize the first model/API.
* Deploy the container manually to the Kubernetes cluster.
* Verify the application is serving requests successfully.
* Automate the deployment process using GitHub Actions (CI/CD).

---

## Progress Overview

| Task                     | Status         |
| ------------------------ | -------------- |
| Development Environment  | ✅ Complete     |
| Terraform Infrastructure | ✅ Complete     |
| Kubernetes Cluster       | ✅ Complete     |
| Repository Cleanup       | ✅ Complete     |
| Containerization         | 🚧 In Progress |
| Manual Deployment        | ⏳ Pending      |
| CI/CD Pipeline           | ⏳ Pending      |
