import os, json, requests
from datetime import datetime, timezone
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, abort
from extensions import db

app = Flask("Pulse")
app.config['SECRET_KEY'] = 'rw50YRsSOsuNMZiDLt5jTzZPDfKvfF64jlmkhjeGqT6lIPsez3s'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ipam_uptime.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

APP_VERSION = "v0.3.2"


@app.context_processor
def inject_version():
    return dict(app_version=APP_VERSION)


from models import Subnet, IPAddress, MonitorGroup, Monitor, MonitorCheck, Setting, Event, Webhook
import monitor_engine, ipam_scanner


@app.route('/')
def dashboard():
    events = Event.query.order_by(Event.timestamp.desc()).limit(100).all()
    return render_template('dashboard.html',
                           subnet_count=Subnet.query.count(),
                           monitor_count=Monitor.query.count(),
                           up_count=Monitor.query.filter_by(status='up').count(),
                           down_count=Monitor.query.filter_by(status='down').count(),
                           events=events)


@app.route('/ipam', methods=['GET'])
def ipam():
    subnets = Subnet.query.all()
    selected_id = request.args.get('subnet', type=int)
    selected = Subnet.query.get(selected_id) if selected_id else (subnets[0] if subnets else None)
    ips, stats = [], {}
    if selected:
        import ipaddress
        ips = IPAddress.query.filter_by(subnet_id=selected.id).all()
        ips.sort(key=lambda x: int(ipaddress.ip_address(x.address)))
        counts = {}
        for ip in ips:
            counts[ip.status] = counts.get(ip.status, 0) + 1
        used = len(ips) - counts.get('free', 0)
        stats = {'total': len(ips), 'used': used, 'counts': counts}
    return render_template('ipam.html', subnets=subnets, selected=selected, ips=ips, stats=stats)


@app.route('/api/subnets', methods=['POST'])
def add_subnet():
    data = request.get_json() or request.form
    network = data.get('network')
    if not network:
        os.system('echo "[Pulse] Subnet Create Failed: Network required"')
        return jsonify({'error': 'Network required'}), 400
    try:
        import ipaddress
        net = ipaddress.ip_network(network, strict=False)
        s = Subnet(network=str(net), description=data.get('description', ''), vlan_tags=data.get('vlan_tags', ''))
        db.session.add(s)
        db.session.commit()
        os.system('echo "[Pulse] Subnet Created: {0} (ID {1})"'.format(str(net), s.id))
        for host in net.hosts():
            db.session.add(IPAddress(subnet_id=s.id, address=str(host), status='free'))
        db.session.commit()
        os.system('echo "[Pulse] Instant Subnet Scan Triggered: {0}"'.format(str(net)))
        monitor_engine.run_single_subnet_scan(app, s.id)
        return jsonify({'id': s.id, 'network': str(net)})
    except Exception as e:
        os.system('echo "[Pulse] Subnet Create Error: {0}"'.format(str(e).replace('"', "'")))
        return jsonify({'error': str(e)}), 400


@app.route('/api/subnets/<int:id>', methods=['POST'])
def update_subnet(id):
    s = db.session.get(Subnet, id)
    if s is None:
        abort(404)
    data = request.get_json() or request.form
    s.description = data.get('description', s.description)
    s.vlan_tags = data.get('vlan_tags', s.vlan_tags)
    db.session.commit()
    os.system('echo "[Pulse] Subnet Updated: {0} (ID {1})"'.format(s.network, id))
    return jsonify({'ok': True})


@app.route('/api/subnets/<int:id>/delete', methods=['POST'])
def delete_subnet(id):
    s = db.session.get(Subnet, id)
    if s is None:
        abort(404)
    os.system('echo "[Pulse] Subnet Deleted: {0} (ID {1})"'.format(s.network, id))
    db.session.delete(s)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/subnets/<int:id>/scan', methods=['POST'])
def scan_subnet_api(id):
    s = db.session.get(Subnet, id)
    if s is None:
        abort(404)
    os.system('echo "[Pulse] Manual Subnet Scan Requested: {0} (ID {1})"'.format(s.network, id))
    monitor_engine.run_single_subnet_scan(app, s.id)
    flash('Subnet scanned.', 'success')
    return redirect(url_for('ipam', subnet=s.id))


@app.route('/api/ip/<int:id>', methods=['POST'])
def update_ip(id):
    obj = db.session.get(IPAddress, id)
    if obj is None:
        abort(404)
    data = request.get_json() or request.form
    obj.hostname = data.get('hostname', obj.hostname)
    obj.status = data.get('status', obj.status)
    obj.description = data.get('description', obj.description)
    obj.tags = data.get('tags', obj.tags)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/monitors')
def monitors():
    groups = MonitorGroup.query.filter_by(parent_id=None).order_by(MonitorGroup.sort_order).all()
    ungrouped = Monitor.query.filter_by(group_id=None).order_by(Monitor.sort_order).all()

    mids = [m.id for m in ungrouped]

    def collect(g):
        mids.extend([m.id for m in g.monitors])
        for c in g.children:
            collect(c)

    for g in groups:
        collect(g)

    recent = {}
    for mid in mids:
        checks = MonitorCheck.query.filter_by(monitor_id=mid).order_by(MonitorCheck.timestamp.desc()).limit(40).all()
        recent[mid] = list(reversed(checks))
    return render_template('monitors.html', groups=groups, ungrouped=ungrouped, recent=recent)


@app.route('/monitors/<int:id>')
def monitor_detail(id):
    monitor = db.session.get(Monitor, id)
    if monitor is None:
        abort(404)
    checks = MonitorCheck.query.filter_by(monitor_id=id).order_by(MonitorCheck.timestamp.desc()).limit(50).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cert_days = None
    domain_days = None
    if monitor.cert_expiry_date:
        cert_days = max(0, (monitor.cert_expiry_date - now).days)
    if monitor.domain_expiry_date:
        domain_days = max(0, (monitor.domain_expiry_date - now).days)
    return render_template('monitor_detail.html', monitor=monitor, checks=checks,
                           checks_chart=list(reversed(checks)),
                           cert_days=cert_days, domain_days=domain_days)


@app.route('/monitors/new', methods=['GET', 'POST'])
def monitor_new():
    groups = MonitorGroup.query.order_by(MonitorGroup.sort_order).all()
    webhooks = Webhook.query.filter_by(active=True).all()
    clone = db.session.get(Monitor, request.args.get('clone', type=int)) if request.args.get('clone') else None
    prefill_ip = request.args.get('ip')
    if request.method == 'POST':
        data = request.form
        m = Monitor(
            group_id=data.get('group_id', type=int) or None,
            name=data.get('name'),
            monitor_type=data.get('monitor_type'),
            target=data.get('target'),
            port=data.get('port', type=int) or None,
            interval_seconds=data.get('interval_seconds', type=int) or 60,
            retries=data.get('retries', type=int) or 0,
            timeout_seconds=data.get('timeout_seconds', type=int) or 10,
            http_method=data.get('http_method') or 'GET',
            http_body=data.get('http_body'),
            http_headers=data.get('http_headers'),
            cert_expiry_notification=data.get('cert_expiry') == '1',
            domain_expiry_notification=data.get('domain_expiry') == '1',
            webhook_ids=','.join(request.form.getlist('webhook_ids'))
        )
        db.session.add(m)
        db.session.commit()
        os.system('echo "[Pulse] Monitor Created: {0} (ID {1}) | Type: {2} | Target: {3}"'.format(m.name, m.id,
                                                                                                  m.monitor_type,
                                                                                                  m.target))
        if not m.webhook_ids:
            default_hooks = Webhook.query.filter_by(active=True, is_default=True).all()
            if default_hooks:
                m.webhook_ids = ','.join(str(h.id) for h in default_hooks)
                db.session.commit()
                os.system('echo "[Pulse] Default webhooks attached: {0}"'.format(m.name))
        os.system('echo "[Pulse] Instant Monitor Check Triggered: {0} (ID {1})"'.format(m.name, m.id))
        monitor_engine.run_single_check(app, m.id)
        return redirect(url_for('monitor_detail', id=m.id))
    monitor_webhook_ids = []
    if clone and clone.webhook_ids:
        monitor_webhook_ids = [x for x in clone.webhook_ids.split(',') if x]
    return render_template('monitor_form.html', monitor=clone, groups=groups, prefill_ip=prefill_ip,
                           webhooks=webhooks, monitor_webhook_ids=monitor_webhook_ids)


@app.route('/monitors/<int:id>/edit', methods=['GET', 'POST'])
def monitor_edit(id):
    monitor = db.session.get(Monitor, id)
    if monitor is None:
        abort(404)
    groups = MonitorGroup.query.order_by(MonitorGroup.sort_order).all()
    webhooks = Webhook.query.filter_by(active=True).all()
    if request.method == 'POST':
        data = request.form
        old_target = monitor.target
        old_type = monitor.monitor_type
        monitor.group_id = data.get('group_id', type=int) or None
        monitor.name = data.get('name')
        monitor.monitor_type = data.get('monitor_type')
        monitor.target = data.get('target')
        monitor.port = data.get('port', type=int) or None
        monitor.interval_seconds = data.get('interval_seconds', type=int) or 60
        monitor.retries = data.get('retries', type=int) or 0
        monitor.timeout_seconds = data.get('timeout_seconds', type=int) or 10
        monitor.http_method = data.get('http_method') or 'GET'
        monitor.http_body = data.get('http_body')
        monitor.http_headers = data.get('http_headers')
        monitor.cert_expiry_notification = data.get('cert_expiry') == '1'
        monitor.domain_expiry_notification = data.get('domain_expiry') == '1'
        monitor.webhook_ids = ','.join(request.form.getlist('webhook_ids'))
        db.session.commit()
        os.system('echo "[Pulse] Monitor Updated: {0} (ID {1})"'.format(monitor.name, id))
        if old_target != monitor.target or old_type != monitor.monitor_type:
            os.system('echo "[Pulse] Target changed, instant check: {0}"'.format(monitor.name))
            monitor_engine.run_single_check(app, monitor.id)
        return redirect(url_for('monitor_detail', id=monitor.id))
    monitor_webhook_ids = []
    if monitor.webhook_ids:
        monitor_webhook_ids = [x for x in monitor.webhook_ids.split(',') if x]
    return render_template('monitor_form.html', monitor=monitor, groups=groups, prefill_ip=None,
                           webhooks=webhooks, monitor_webhook_ids=monitor_webhook_ids)


@app.route('/monitors/<int:id>/delete', methods=['POST'])
def monitor_delete(id):
    monitor = db.session.get(Monitor, id)
    if monitor is None:
        abort(404)
    os.system('echo "[Pulse] Monitor Deleted: {0} (ID {1})"'.format(monitor.name, id))
    db.session.delete(monitor)
    db.session.commit()
    return redirect(url_for('monitors'))


@app.route('/monitors/<int:id>/pause', methods=['POST'])
def monitor_pause(id):
    monitor = db.session.get(Monitor, id)
    if monitor is None:
        abort(404)
    monitor.is_paused = not monitor.is_paused
    db.session.commit()
    os.system(
        'echo "[Pulse] Monitor {0}: {1} (ID {2})"'.format('Paused' if monitor.is_paused else 'Resumed', monitor.name,
                                                          id))
    return redirect(url_for('monitor_detail', id=id))


@app.route('/api/monitors/<int:id>/clear', methods=['POST'])
def monitor_clear(id):
    m = db.session.get(Monitor, id)
    if m is None:
        abort(404)
    count = MonitorCheck.query.filter_by(monitor_id=id).count()
    MonitorCheck.query.filter_by(monitor_id=id).delete()
    db.session.commit()
    os.system('echo "[Pulse] Monitor History Cleared: ID {0} ({1} records)"'.format(id, count))
    return jsonify({'ok': True})


@app.route('/api/monitors/status')
def api_monitors_status():
    monitors = Monitor.query.all()
    out = []
    for m in monitors:
        checks = MonitorCheck.query.filter_by(monitor_id=m.id).order_by(MonitorCheck.timestamp.desc()).limit(40).all()
        last = checks[0] if checks else None
        out.append({
            'id': m.id,
            'status': m.status,
            'effective_status': last.status if last else m.status,
            'uptime_24h': m.uptime_24h,
            'checks': [{'status': c.status, 'timestamp': c.timestamp.isoformat()} for c in reversed(checks)]
        })
    return jsonify(out)


@app.route('/api/monitors/<int:id>/status')
def api_monitor_detail_status(id):
    m = db.session.get(Monitor, id)
    if m is None:
        abort(404)
    checks = MonitorCheck.query.filter_by(monitor_id=id).order_by(MonitorCheck.timestamp.desc()).limit(50).all()
    up_checks = [c.response_time_ms for c in checks if c.status == 'up' and c.response_time_ms is not None]
    avg_24h = round(sum(up_checks) / len(up_checks), 2) if up_checks else None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cert_days = None
    domain_days = None
    if m.cert_expiry_date:
        cert_days = max(0, (m.cert_expiry_date - now).days)
    if m.domain_expiry_date:
        domain_days = max(0, (m.domain_expiry_date - now).days)
    return jsonify({
        'id': m.id,
        'status': m.status,
        'effective_status': checks[0].status if checks else m.status,
        'last_response_time_ms': m.last_response_time_ms,
        'avg_24h': avg_24h,
        'uptime_24h': m.uptime_24h,
        'uptime_30d': m.uptime_30d,
        'cert_days': cert_days,
        'domain_days': domain_days,
        'checks': [{'status': c.status, 'response_time_ms': c.response_time_ms, 'timestamp': c.timestamp.isoformat()}
                   for c in reversed(checks)]
    })


@app.route('/api/groups', methods=['POST'])
def add_group():
    name = request.form.get('name')
    parent_id = request.form.get('parent_id', type=int) or None
    color = request.form.get('color', '#3b82f6')
    if name:
        g = MonitorGroup(name=name, parent_id=parent_id, color=color)
        db.session.add(g)
        db.session.commit()
        os.system('echo "[Pulse] Group Created: {0} (parent={1}, color={2})"'.format(name, parent_id, color))
    return redirect(url_for('monitors'))


@app.route('/api/groups/<int:id>', methods=['POST'])
def edit_group(id):
    g = db.session.get(MonitorGroup, id)
    if g is None:
        abort(404)
    data = request.form
    g.name = data.get('name', g.name)
    g.color = data.get('color', g.color)
    parent_id = data.get('parent_id')
    if parent_id == '' or parent_id is None:
        g.parent_id = None
    else:
        pid = int(parent_id)
        if pid == id:
            flash('Cannot set group as its own parent', 'error')
            return redirect(url_for('monitors'))
        g.parent_id = pid
    db.session.commit()
    os.system('echo "[Pulse] Group Updated: {0} (ID {1})"'.format(g.name, id))
    return redirect(url_for('monitors'))


@app.route('/api/groups/<int:id>/delete', methods=['POST'])
def delete_group(id):
    g = db.session.get(MonitorGroup, id)
    if g is None:
        abort(404)
    name = g.name
    for m in g.monitors:
        m.group_id = None
    for child in g.children:
        child.parent_id = None
    db.session.delete(g)
    db.session.commit()
    os.system('echo "[Pulse] Group Deleted: {0} (ID {1})"'.format(name, id))
    flash('Group deleted', 'success')
    return redirect(url_for('monitors'))


@app.route('/api/groups/reorder', methods=['POST'])
def reorder_groups():
    data = request.get_json()
    ids = data.get('ids', [])
    parent_id = data.get('parent_id')
    for idx, gid in enumerate(ids):
        g = db.session.get(MonitorGroup, int(gid))
        if g and (parent_id is None or g.parent_id == parent_id or str(g.parent_id) == str(parent_id)):
            g.sort_order = idx
    db.session.commit()
    os.system('echo "[Pulse] Groups Reordered: {0} items at level {1}"'.format(len(ids), parent_id))
    return jsonify({'ok': True})


@app.route('/api/monitors/reorder', methods=['POST'])
def reorder_monitors():
    data = request.get_json()
    ids = data.get('ids', [])
    for idx, mid in enumerate(ids):
        m = db.session.get(Monitor, int(mid))
        if m:
            m.sort_order = idx
    db.session.commit()
    os.system('echo "[Pulse] Monitors Reordered: {0} items"'.format(len(ids)))
    return jsonify({'ok': True})


@app.route('/api/webhooks', methods=['POST'])
def add_webhook():
    data = request.form
    wh = Webhook(
        name=data.get('name'),
        url=data.get('url'),
        active=True,
        trigger_monitor=bool(data.get('trigger_monitor')),
        trigger_ip_found=bool(data.get('trigger_ip_found')),
        trigger_cert_expiry=bool(data.get('trigger_cert_expiry')),
        trigger_domain_expiry=bool(data.get('trigger_domain_expiry')),
        is_default=bool(data.get('is_default'))
    )
    db.session.add(wh)
    db.session.commit()
    if bool(data.get('apply_existing')):
        monitors = Monitor.query.all()
        for m in monitors:
            ids = [x for x in (m.webhook_ids or '').split(',') if x]
            if str(wh.id) not in ids:
                ids.append(str(wh.id))
                m.webhook_ids = ','.join(ids)
        db.session.commit()
        os.system('echo "[Pulse] Webhook applied to all existing monitors: {0}"'.format(wh.name))
    os.system('echo "[Pulse] Webhook Created: {0} -> {1}"'.format(wh.name, wh.url))
    flash('Webhook added', 'success')
    return redirect(url_for('settings'))


@app.route('/api/webhooks/<int:id>/test', methods=['POST'])
def test_webhook(id):
    wh = db.session.get(Webhook, id)
    if wh is None:
        abort(404)
    os.system('echo "[Pulse] Webhook Test: {0} -> {1}"'.format(wh.name, wh.url))
    try:
        payload = {
            'event': 'test',
            'webhook_name': wh.name,
            'url': wh.url,
            'timestamp': datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        }
        r = requests.post(wh.url, json=payload, timeout=5)
        if r.status_code < 400:
            os.system('echo "[Pulse] Webhook Test OK: {0} ({1})"'.format(wh.name, r.status_code))
            return jsonify({'ok': True, 'status': r.status_code})
        os.system('echo "[Pulse] Webhook Test Failed: {0} ({1})"'.format(wh.name, r.status_code))
        return jsonify({'ok': False, 'error': 'HTTP {}'.format(r.status_code)}), 502
    except Exception as e:
        os.system('echo "[Pulse] Webhook Test Exception: {0} | {1}"'.format(wh.name, str(e).replace('"', "'")))
        return jsonify({'ok': False, 'error': str(e)}), 502


@app.route('/api/webhooks/<int:id>/delete', methods=['POST'])
def delete_webhook(id):
    wh = db.session.get(Webhook, id)
    if wh is None:
        abort(404)
    os.system('echo "[Pulse] Webhook Deleted: {0} ({1})"'.format(wh.name, wh.url))
    db.session.delete(wh)
    db.session.commit()
    flash('Webhook removed', 'success')
    return redirect(url_for('settings'))


@app.route('/api/events/clear', methods=['POST'])
def clear_events():
    count = Event.query.count()
    Event.query.delete()
    db.session.commit()
    os.system('echo "[Pulse] Events Cleared: {0} records"'.format(count))
    return jsonify({'ok': True})


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        Setting.set('retention_days', request.form.get('retention_days', 30))
        Setting.set('subnet_scan_minutes', request.form.get('subnet_scan_minutes', 30))
        os.system('echo "[Pulse] Settings Updated: retention={0}, scan_interval={1}"'.format(
            request.form.get('retention_days'), request.form.get('subnet_scan_minutes')))
        flash('Settings saved', 'success')
        return redirect(url_for('settings'))
    return render_template('settings.html',
                           retention=Setting.get('retention_days', '30'),
                           scan_min=Setting.get('subnet_scan_minutes', '30'),
                           webhooks=Webhook.query.all())


@app.route('/api/prune', methods=['POST'])
def api_prune():
    monitor_engine.prune_old_checks(app)
    return jsonify({'ok': True})


if __name__ == '__main__':
    import migrate

    migrate.migrate()

    with app.app_context():
        db.create_all()
        if not Setting.query.filter_by(key='retention_days').first():
            Setting.set('retention_days', '30')
        if not Setting.query.filter_by(key='subnet_scan_minutes').first():
            Setting.set('subnet_scan_minutes', '30')
    import threading

    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        t = threading.Thread(target=monitor_engine.engine_loop, args=(app,), daemon=True)
        t.start()
        os.system('echo "[Pulse] Background Engine Thread Started"')

    import logging

    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    log.disabled = True

    app.run(debug=False, host='0.0.0.0', port=5000)