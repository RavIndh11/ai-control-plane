# Ubuntu 24.04 Kubernetes Cluster Installation Guide

This guide details how to install the required container runtimes, Kubernetes binaries, and cluster network to set up your 3-node Ubuntu 24.04 LTS (Noble Numbat) cluster.

---

## 🛠️ Step 1: Host Configurations (Run on ALL 3 Nodes)

Configure kernel modules, networking bridge rules, and disable swap.

```bash
# 1. Disable swap (Required by Kubernetes)
sudo swapoff -a
sudo sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab

# 2. Configure kernel modules for Containerd
cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF

sudo modprobe overlay
sudo modprobe br_netfilter

# 3. Configure sysctl networking bridging parameters
cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF

sudo sysctl --system
```

---

## 📦 Step 2: Install Containerd Runtime & K8s Repos (Run on ALL 3 Nodes)

Set up the Docker repository to fetch the latest `containerd.io` and the official Kubernetes apt packages.

```bash
# 1. Add Docker's official GPG key & repository
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 2. Install Containerd
sudo apt-get update
sudo apt-get install -y containerd.io

# 3. Configure containerd to use SystemdCgroup (Required by K8s)
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml > /dev/null
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/g' /etc/containerd/config.toml
sudo systemctl restart containerd

# 4. Add Kubernetes GPG key & repository (stable v1.29)
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.29/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.29/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list

# 5. Install Kubernetes node binaries
sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl
```

---

## 🐳 Step 3: Install Docker Engine (Run on MASTER Node Only)

Your master node needs Docker Engine to build and push container images using the `./deploy.sh` script.

```bash
# Install Docker Engine and CLI tools on the Master node
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Configure your user to run Docker commands without sudo
sudo usermod -aG docker $USER
newgrp docker
```

---

## 🔒 Step 4: Configure HTTP Insecure Registry (Run on ALL 3 Nodes)

Allows nodes to pull images from the master's registry (`http://<MASTER-IP>:5000`) without SSL/TLS certificates.

1. Open `/etc/containerd/config.toml` in your editor:
   ```bash
   sudo nano /etc/containerd/config.toml
   ```
2. Scroll down to `[plugins."io.containerd.grpc.v1.cri".registry.mirrors]` and add the mapping:
   ```toml
   [plugins."io.containerd.grpc.v1.cri".registry.mirrors."<MASTER-NODE-IP>:5000"]
     endpoint = ["http://<MASTER-NODE-IP>:5000"]
   ```
3. Restart containerd:
   ```bash
   sudo systemctl restart containerd
   ```

---

## 🚀 Step 5: Initialize the Cluster (On MASTER Node Only)

```bash
# 1. Initialize control plane (Replace <MASTER-NODE-IP> with Master VM IP)
sudo kubeadm init --pod-network-cidr=10.244.0.0/16 --apiserver-advertise-address=<MASTER-NODE-IP>

# 2. Set up local kubectl configs
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config

# 3. Deploy Flannel CNI (Pod network)
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml
```

---

## 🔗 Step 6: Join Worker Nodes (On WORKER 1 & WORKER 2 Nodes Only)

Run the join command copied from the master node init step:
```bash
sudo kubeadm join <MASTER-NODE-IP>:6443 --token <token> \
    --discovery-token-ca-cert-hash sha256:<ca-hash>
```

Verify that all 3 nodes are online by running `kubectl get nodes` on the master node.
