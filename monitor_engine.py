import time, subprocess, platform, socket, requests, ssl, os
from datetime import datetime, timedelta

def tcp_connect(target, port, timeout):
    start = time.time()
    try:
        sock = socket.create_connection((target, port), timeout=timeout)
        sock.close()
        return True, (time.time() - start) * 1000, 'TCP OK'
    except Exception as e:
        return False, (time.time() - start) * 1000, str(e)

def check_ping(target, timeout=10):
    system = platform.system().lower()
    if system == 'windows':
        cmd = ['ping', '-n', '1', '-w', str(int(timeout * 1000)), target]
    elif system == 'darwin':
        cmd = ['ping', '-c', '1', '-W', str(int(timeout * 1000)), target]
    else:
        cmd = ['ping', '-c', '1', '-W', str(int(timeout)), target]
    start = time.time()
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout + 2)
        elapsed = (time.time() - start) * 1000
        return (True, elapsed, 'OK') if proc.returncode == 0 else (False, elapsed, 'No reply')
    except Exception as e:
        return False, (time.time() - start) * 1000, str(e)

def check_http(url, method='GET', timeout=48, headers=None, body=None, verify=True):
    start = time.time()
    try:
        resp = requests.request(method, url, timeout=timeout, headers=headers, data=body, verify=verify)
        elapsed = (time.time() - start) * 1000
        if resp.status_code < 400:
            return True, elapsed, resp.status_code
        return False, elapsed, f'HTTP {resp.status_code}'
    except Exception as e:
        return False, (time.time() - start) * 1000, str(e)

def check_docker(container_name, timeout=10):
    try:
        import docker
        client = docker.DockerClient(base_url='unix://var/run/docker.sock')
        start = time.time()
        container = client.containers.get(container_name)
        running = container.attrs['State']['Status'] == 'running'
        elapsed = (time.time() - start) * 1000
        return (True, elapsed, 'Running') if running else (False, elapsed, container.attrs['State']['Status'])
    except Exception as e:
        return False, 0, str(e)

def run_check(monitor):
    mtype, target = monitor.monitor_type, monitor.target
    timeout = monitor.timeout_seconds or 10
    if mtype == 'ping':
        ok, time_ms, msg = check_ping(target, timeout)
        if not ok and monitor.port:
            ok, time_ms, msg = tcp_connect(target, monitor.port, timeout)
        return ok, time_ms, msg
    if mtype in ('http', 'https'):
        url = target if target.startswith('http') else f'{mtype}://{target}'
        hdrs = None
        if monitor.http_headers:
            try:
                import json
                hdrs = json.loads(monitor.http_headers)
            except Exception:
                pass
        return check_http(url, monitor.http_method or 'GET', timeout, hdrs, monitor.http_body, verify=True)
    if mtype == 'docker':
        return check_docker(target, timeout)
    return False, 0, 'Unknown type'

def get_cert_expiry(hostname, port=443):
    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                expiry = cert.get('notAfter')
                if expiry:
                    return datetime.strptime(expiry, '%b %d %H:%M:%S %Y %Z')
    except Exception:
        pass
    return None

def get_domain_expiry(domain):
    try:
        import whois
        w = whois.whois(domain)
        if w.expiration_date:
            exp = w.expiration_date[0] if isinstance(w.expiration_date, list) else w.expiration_date
            return exp
    except Exception:
        pass
    return None

def fire_webhooks(app, event_type, payload):
    with app.app_context():
        from models import Webhook
        webhooks = Webhook.query.filter_by(active=True).all()
        for wh in webhooks:
            should_fire = False
            if event_type == 'monitor' and wh.trigger_monitor:
                should_fire = True
            elif event_type == 'ip_found' and wh.trigger_ip_found:
                should_fire = True
            elif event_type == 'cert_expiry' and wh.trigger_cert_expiry:
                should_fire = True
            elif event_type == 'domain_expiry' and wh.trigger_domain_expiry:
                should_fire = True
            if should_fire:
                try:
                    os.system('echo "[Pulse] Webhook Fire: event={0} -> {1}"'.format(event_type, wh.url))
                    requests.post(wh.url, json=payload, timeout=5)
                except Exception as e:
                    os.system('echo "[Pulse] Webhook Failed: event={0} -> {1} | {2}"'.format(event_type, wh.url, str(e).replace('"', "'")))

def prune_old_checks(app):
    with app.app_context():
        from models import MonitorCheck, Setting
        from extensions import db
        try:
            retention = int(Setting.get('retention_days', 30))
        except Exception:
            retention = 30
        cutoff = datetime.utcnow() - timedelta(days=retention)
        del_count = MonitorCheck.query.filter(MonitorCheck.timestamp < cutoff).count()
        MonitorCheck.query.filter(MonitorCheck.timestamp < cutoff).delete(synchronize_session=False)
        db.session.commit()
        os.system('echo "[Pulse] Pruned {0} old checks (older than {1} days)"'.format(del_count, retention))

def run_single_check(app, monitor_id):
    with app.app_context():
        from models import Monitor, MonitorCheck, Event, Webhook
        from extensions import db
        m = db.session.get(Monitor, monitor_id)
        if not m or m.is_paused:
            if m and m.is_paused:
                os.system('echo "[Pulse] Monitor Check Skipped: {0} (ID {1}) is paused"'.format(m.name, m.id))
            return
        now = datetime.utcnow()
        prev_status = m.status
        os.system('echo "[Pulse] Monitor Check Start: {0} (ID {1}) | Type: {2} | Target: {3}"'.format(m.name, m.id, m.monitor_type, m.target))
        ok, time_ms, msg = run_check(m)
        actual = 'up' if ok else 'down'
        os.system('echo "[Pulse] Monitor Check Result: {0} (ID {1}) | Raw: {2} | Time: {3:.2f}ms | Msg: {4}"'.format(m.name, m.id, actual, time_ms, str(msg).replace('"', "'")))

        if ok:
            m.retry_count = 0
            derived = 'up'
        else:
            m.retry_count = (m.retry_count or 0) + 1
            if m.retries == 0 or m.retry_count > m.retries:
                derived = 'down'
            else:
                derived = 'degraded'

        if derived != prev_status:
            os.system('echo "[Pulse] Monitor State Change: {0} (ID {1}) | {2} -> {3}"'.format(m.name, m.id, prev_status, derived))
        elif derived == 'degraded':
            os.system('echo "[Pulse] Monitor Retrying: {0} (ID {1}) | Retry {2}/{3}"'.format(m.name, m.id, m.retry_count, m.retries))

        m.status = derived
        m.last_check_at = now
        m.last_response_time_ms = round(time_ms, 2) if ok else None

        db.session.add(MonitorCheck(
            monitor_id=m.id, timestamp=now, status=derived,
            response_time_ms=round(time_ms, 2) if time_ms else None,
            message=str(msg)
        ))

        if prev_status != derived and prev_status != 'pending':
            db.session.add(Event(
                source='monitor',
                group_name=m.group.name if m.group else '—',
                name=m.name,
                status=derived,
                message=f'State changed from {prev_status} to {derived}'
            ))
            if m.webhook_ids and derived in ('down', 'up'):
                ids = [int(x) for x in m.webhook_ids.split(',') if x.strip().isdigit()]
                hooks = Webhook.query.filter(Webhook.id.in_(ids)).filter_by(active=True).all()
                for wh in hooks:
                    if wh.trigger_monitor:
                        try:
                            requests.post(wh.url, json={
                                'event': 'monitor_' + derived,
                                'monitor_name': m.name,
                                'monitor_type': m.monitor_type,
                                'target': m.target,
                                'status': derived,
                                'response_time_ms': round(time_ms, 2) if time_ms else None,
                                'timestamp': now.isoformat()
                            }, timeout=5)
                        except Exception:
                            pass
        db.session.commit()

        if m.monitor_type in ('http', 'https'):
            changed = False
            host = m.target.replace('https://', '').replace('http://', '').split('/')[0]

            if m.cert_expiry_notification:
                if m.cert_expiry_date is None or m.last_cert_check is None or (now - m.last_cert_check).total_seconds() > 86400:
                    os.system('echo "[Pulse] Cert Check: {0} (ID {1}) | Host: {2}"'.format(m.name, m.id, host))
                    exp = get_cert_expiry(host)
                    if exp:
                        m.cert_expiry_date = exp
                        m.last_cert_check = now
                        changed = True
                        os.system('echo "[Pulse] Cert Found: {0} | Expiry: {1}"'.format(m.target, exp.strftime('%Y-%m-%d')))
                    else:
                        os.system('echo "[Pulse] Cert Check Failed: {0}"'.format(m.target))

            if m.domain_expiry_notification:
                if m.domain_expiry_date is None or m.last_domain_check is None or (now - m.last_domain_check).total_seconds() > 86400:
                    os.system('echo "[Pulse] Domain Check: {0} (ID {1}) | Host: {2}"'.format(m.name, m.id, host))
                    exp = get_domain_expiry(host)
                    if exp:
                        m.domain_expiry_date = exp
                        m.last_domain_check = now
                        changed = True
                        os.system('echo "[Pulse] Domain Found: {0} | Expiry: {1}"'.format(m.target, exp.strftime('%Y-%m-%d')))
                    else:
                        os.system('echo "[Pulse] Domain Check Failed: {0}"'.format(m.target))

            if changed:
                db.session.commit()

            if m.cert_expiry_date and m.cert_expiry_notification:
                days_left = (m.cert_expiry_date - now).days
                if days_left <= 14:
                    os.system('echo "[Pulse] Cert Alert: {0} | {1} days left"'.format(m.target, days_left))
                    db.session.add(Event(
                        source='cert', group_name=m.name, name=m.target,
                        status='alert', message=f'SSL certificate expires in {days_left} days'
                    ))
                    if m.webhook_ids:
                        ids = [int(x) for x in m.webhook_ids.split(',') if x.strip().isdigit()]
                        hooks = Webhook.query.filter(Webhook.id.in_(ids)).filter_by(active=True).all()
                        for wh in hooks:
                            if wh.trigger_cert_expiry:
                                try:
                                    requests.post(wh.url, json={
                                        'event': 'cert_expiry',
                                        'monitor_name': m.name,
                                        'target': m.target,
                                        'days_left': days_left,
                                        'expiry_date': m.cert_expiry_date.isoformat(),
                                        'timestamp': now.isoformat()
                                    }, timeout=5)
                                except Exception:
                                    pass
                        db.session.commit()

            if m.domain_expiry_date and m.domain_expiry_notification:
                days_left = (m.domain_expiry_date - now).days
                if days_left <= 30:
                    os.system('echo "[Pulse] Domain Alert: {0} | {1} days left"'.format(m.target, days_left))
                    db.session.add(Event(
                        source='domain', group_name=m.name, name=m.target,
                        status='alert', message=f'Domain expires in {days_left} days'
                    ))
                    if m.webhook_ids:
                        ids = [int(x) for x in m.webhook_ids.split(',') if x.strip().isdigit()]
                        hooks = Webhook.query.filter(Webhook.id.in_(ids)).filter_by(active=True).all()
                        for wh in hooks:
                            if wh.trigger_domain_expiry:
                                try:
                                    requests.post(wh.url, json={
                                        'event': 'domain_expiry',
                                        'monitor_name': m.name,
                                        'target': m.target,
                                        'days_left': days_left,
                                        'expiry_date': m.domain_expiry_date.isoformat(),
                                        'timestamp': now.isoformat()
                                    }, timeout=5)
                                except Exception:
                                    pass
                        db.session.commit()

        for label, delta in [
            ('uptime_24h', timedelta(hours=24)),
            ('uptime_30d', timedelta(days=30))
        ]:
            since = now - delta
            total = MonitorCheck.query.filter_by(monitor_id=m.id).filter(MonitorCheck.timestamp >= since).count()
            ups = MonitorCheck.query.filter_by(monitor_id=m.id, status='up').filter(MonitorCheck.timestamp >= since).count()
            setattr(m, label, round((ups / total) * 100, 2) if total else 100.0)
        db.session.commit()

def run_single_subnet_scan(app, subnet_id):
    with app.app_context():
        from models import Subnet, IPAddress, Event
        from extensions import db
        import ipam_scanner
        s = db.session.get(Subnet, subnet_id)
        if not s:
            os.system('echo "[Pulse] Subnet Scan Skipped: ID {0} not found"'.format(subnet_id))
            return
        os.system('echo "[Pulse] Subnet Scan Start: {0} (ID {1})"'.format(s.network, s.id))
        results = ipam_scanner.scan_subnet(s.network)
        found = 0
        offline = 0
        deleted = 0

        for ip_str, ok in results.items():
            obj = IPAddress.query.filter_by(subnet_id=s.id, address=ip_str).first()
            if not obj:
                continue

            if ok:
                obj.last_seen = datetime.utcnow()
                if obj.missed_scans > 0:
                    obj.missed_scans = 0
                    if obj.status in ('offline', 'disappeared'):
                        obj.status = 'device'
                        os.system('echo "[Pulse] IPAM Back Online: {0}"'.format(ip_str))
                elif obj.status == 'free':
                    obj.status = 'device'
                    found += 1
                    os.system('echo "[Pulse] IPAM Detection: {0} in {1}"'.format(ip_str, s.network))
                    db.session.add(Event(
                        source='ipam', group_name=s.network, name=obj.address,
                        status='detected', message='New device discovered on ' + s.network
                    ))
                    fire_webhooks(app, 'ip_found', {
                        'event': 'ip_found', 'subnet': s.network,
                        'ip_address': obj.address, 'timestamp': datetime.utcnow().isoformat()
                    })
            else:
                if obj.status != 'free':
                    obj.missed_scans = (obj.missed_scans or 0) + 1
                    os.system('echo "[Pulse] IPAM Missed: {0} | Count: {1}"'.format(ip_str, obj.missed_scans))
                    if obj.missed_scans == 1:
                        obj.status = 'offline'
                        offline += 1
                        os.system('echo "[Pulse] IPAM Offline: {0}"'.format(ip_str))
                    elif obj.missed_scans >= 5:
                        os.system('echo "[Pulse] IPAM Deleted: {0} (missed {1} scans)"'.format(ip_str, obj.missed_scans))
                        db.session.delete(obj)
                        deleted += 1

        db.session.commit()
        os.system('echo "[Pulse] Subnet Scan Complete: {0} | New: {1} | Offline: {2} | Deleted: {3}"'.format(s.network, found, offline, deleted))

def engine_loop(app):
    with app.app_context():
        from models import Monitor, Setting
        from extensions import db
        os.system('echo "[Pulse] Background Engine Started"')
        last_prune = datetime.utcnow()
        last_subnet_scan = datetime.utcnow()
        while True:
            now = datetime.utcnow()
            if (now - last_prune).total_seconds() > 86400:
                os.system('echo "[Pulse] Scheduled Prune Starting..."')
                prune_old_checks(app)
                last_prune = now

            try:
                scan_min = int(Setting.get('subnet_scan_minutes', 30))
            except Exception:
                scan_min = 30
            if (now - last_subnet_scan).total_seconds() > scan_min * 60:
                os.system('echo "[Pulse] Scheduled Auto-Scan Starting..."')
                subnets = Subnet.query.all()
                for s in subnets:
                    run_single_subnet_scan(app, s.id)
                last_subnet_scan = now

            db.session.expire_all()
            monitors = Monitor.query.filter_by(is_paused=False).all()
            for m in monitors:
                due = m.last_check_at is None or (now - m.last_check_at).total_seconds() >= m.interval_seconds
                if due:
                    run_single_check(app, m.id)
            time.sleep(1)