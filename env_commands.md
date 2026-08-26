# Daily Environment Commands - Startup & Shutdown

**Remember:** your Kubernetes cluster runs on Oracle Cloud, not your laptop. Turning your PC off never stops it - these commands only manage your *local* tools and your *connection* to it.

---

## Startup - run in order

```bash
# 1. Confirm Docker is running (start Docker Desktop from Windows first if this errors)
docker info

# 2. Go to the project and activate the Python environment
cd ~/AI-Operated-Model-Deployment-Platform
source .venv/bin/activate

# 3. Confirm the cluster is reachable
kubectl get nodes
```
If step 3 errors instead of showing a `Ready` node, your kubeconfig has likely expired - regenerate it:
```bash
oci ce cluster create-kubeconfig --cluster-id ocid1.cluster.oc1.af-casablanca-1.aaaaaaaa477tvpo66pqa3ljsd2u2hnkcq5ymfzfv5d7qfips4cr5pw3x3cna --file ~/.kube/config --region af-casablanca-1 --token-version 2.0.0
```

```bash
# 4. Confirm OCI auth still works
oci iam region list

# 5. Check for infrastructure drift (optional but good habit)
cd terraform
terraform plan
cd ..
```
`terraform plan` should say **"No changes"**. If it shows changes you didn't make, something drifted outside Terraform (e.g. a manual console edit) - investigate before applying anything.

---

## Shutdown - safe, local-only

```bash
# 1. Deactivate the Python environment
deactivate
```

**2. Docker Desktop** - optional, only if you want to free up RAM/CPU on your laptop. Quit it from the Windows system tray (right-click the icon → Quit Docker Desktop). Not required - leaving it running does no harm.

**3. Fully shut down WSL2** - optional, frees the most resources. Run this from **PowerShell on Windows**, not from inside your Ubuntu terminal:
```powershell
wsl --shutdown
```

---

## ⚠️ What NOT to do when "shutting down"

**Never run `terraform destroy` as part of a normal shutdown routine.** It's tempting to think "shutting down" means tearing infrastructure down too - it doesn't. `terraform destroy` deletes your actual cluster, VCN, and node pool, and you'd have to wait through the full ~10-15 minute provisioning process again to get it back. Your Always Free tier resources don't cost anything while idle, so there's no reason to destroy them between sessions. Only run `destroy` if you're deliberately and permanently tearing the project down - not as a daily habit.
