import subprocess, platform, socket, ipaddress, os
from concurrent.futures import ThreadPoolExecutor

def ping_ip(ip, timeout=1):
    system = platform.system().lower()
    if system == 'windows':
        cmd = ['ping', '-n', '1', '-w', str(int(timeout * 1000)), str(ip)]
    elif system == 'darwin':
        cmd = ['ping', '-c', '1', '-W', str(int(timeout * 1000)), str(ip)]
    else:
        cmd = ['ping', '-c', '1', '-W', str(int(timeout)), str(ip)]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout + 2)
        return str(ip), proc.returncode == 0
    except Exception:
        return str(ip), False

def tcp_probe(ip, ports=None, timeout=1):
    if ports is None:
        ports = [80, 443, 22, 445, 8080, 8443, 3389, 53]
    for port in ports:
        try:
            s = socket.create_connection((str(ip), port), timeout=timeout)
            s.close()
            return True
        except Exception:
            continue
    return False

def scan_host(ip, timeout=1):
    _, icmp_ok = ping_ip(ip, timeout)
    if icmp_ok:
        return str(ip), True
    return str(ip), tcp_probe(ip)

def scan_subnet(network_cidr, max_workers=200):
    net = ipaddress.ip_network(network_cidr, strict=False)
    hosts = list(net.hosts())
    os.system('echo "[Pulse] IPAM Scan Started: {0} ({1} hosts, {2} workers)"'.format(network_cidr, len(hosts), max_workers))
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for ip, ok in ex.map(scan_host, hosts):
            results[ip] = ok
            if ok:
                os.system('echo "[Pulse] IPAM Host Up: {0}"'.format(ip))
    up_count = sum(1 for v in results.values() if v)
    os.system('echo "[Pulse] IPAM Scan Complete: {0} | Up: {1} / {2}"'.format(network_cidr, up_count, len(hosts)))
    return results