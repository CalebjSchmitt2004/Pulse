from extensions import db
from datetime import datetime

class Subnet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    network = db.Column(db.String(64), nullable=False, unique=True)
    description = db.Column(db.String(256))
    vlan_tags = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    ips = db.relationship('IPAddress', backref='subnet', lazy=True, cascade='all, delete-orphan')

class IPAddress(db.Model):
    __table_args__ = (db.UniqueConstraint('subnet_id', 'address', name='uq_ip_address'),)
    id = db.Column(db.Integer, primary_key=True)
    subnet_id = db.Column(db.Integer, db.ForeignKey('subnet.id'), nullable=False)
    address = db.Column(db.String(64), nullable=False)
    hostname = db.Column(db.String(256))
    status = db.Column(db.String(32), default='free')
    description = db.Column(db.String(256))
    tags = db.Column(db.String(256))
    missed_scans = db.Column(db.Integer, default=0)
    last_seen = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class MonitorGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('monitor_group.id'), nullable=True)
    color = db.Column(db.String(32), default='#3b82f6')
    sort_order = db.Column(db.Integer, default=0)
    children = db.relationship('MonitorGroup', backref=db.backref('parent', remote_side=[id]), lazy=True)
    monitors = db.relationship('Monitor', backref='group', lazy=True)

class Monitor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('monitor_group.id'), nullable=True)
    name = db.Column(db.String(128), nullable=False)
    monitor_type = db.Column(db.String(32), nullable=False)
    target = db.Column(db.String(512), nullable=False)
    port = db.Column(db.Integer, nullable=True)
    interval_seconds = db.Column(db.Integer, default=60)
    retries = db.Column(db.Integer, default=0)
    retry_count = db.Column(db.Integer, default=0)
    timeout_seconds = db.Column(db.Integer, default=10)
    http_method = db.Column(db.String(16), default='GET')
    http_body = db.Column(db.Text)
    http_headers = db.Column(db.Text)
    cert_expiry_notification = db.Column(db.Boolean, default=False)
    domain_expiry_notification = db.Column(db.Boolean, default=False)
    cert_expiry_date = db.Column(db.DateTime)
    domain_expiry_date = db.Column(db.DateTime)
    last_cert_check = db.Column(db.DateTime)
    last_domain_check = db.Column(db.DateTime)
    webhook_ids = db.Column(db.String(256))
    is_paused = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(16), default='pending')
    last_check_at = db.Column(db.DateTime)
    last_response_time_ms = db.Column(db.Float)
    uptime_24h = db.Column(db.Float, default=100.0)
    uptime_30d = db.Column(db.Float, default=100.0)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    checks = db.relationship('MonitorCheck', backref='monitor', lazy=True, cascade='all, delete-orphan')

class MonitorCheck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    monitor_id = db.Column(db.Integer, db.ForeignKey('monitor.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    status = db.Column(db.String(16), nullable=False)
    response_time_ms = db.Column(db.Float)
    message = db.Column(db.Text)

class Webhook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    url = db.Column(db.String(512), nullable=False)
    active = db.Column(db.Boolean, default=True)
    trigger_monitor = db.Column(db.Boolean, default=True)
    trigger_ip_found = db.Column(db.Boolean, default=False)
    trigger_cert_expiry = db.Column(db.Boolean, default=False)
    trigger_domain_expiry = db.Column(db.Boolean, default=False)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    source = db.Column(db.String(32))
    group_name = db.Column(db.String(128))
    name = db.Column(db.String(256))
    status = db.Column(db.String(16))
    message = db.Column(db.Text)

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    value = db.Column(db.Text)

    @staticmethod
    def get(key, default=None):
        s = Setting.query.filter_by(key=key).first()
        return s.value if s else default

    @staticmethod
    def set(key, value):
        s = Setting.query.filter_by(key=key).first()
        if not s:
            s = Setting(key=key, value=str(value))
            db.session.add(s)
        else:
            s.value = str(value)
        db.session.commit()