"""Проверка LDAPS и хранение настроек первого запуска."""
import ipaddress
import json
import os
import re
import ssl
import tempfile
from pathlib import Path

from ldap3 import ALL, BASE, Connection, Server, Tls

import ad_utils

_dns = re.compile(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', re.I)


def parse_settings(data):
    host = str(data.get('host') or '').strip().lower().rstrip('.')
    domain = str(data.get('domain') or '').strip().lower().rstrip('.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if len(host) > 253 or not _dns.fullmatch(host):
            raise ValueError('Укажите IP-адрес или полное DNS-имя контроллера')
    if len(domain) > 253 or not _dns.fullmatch(domain):
        raise ValueError('Укажите DNS-имя домена, например corp.example')
    user = str(data.get('domain_user') or '').strip()
    password = data.get('domain_password')
    ca = str(data.get('ca') or '').strip()
    if not user or len(user) > 256 or not isinstance(password, str) or not password or len(password) > 1024:
        raise ValueError('Укажите логин и пароль сервисной учётки AD')
    if len(ca) > 65536 or (ca and ('-----BEGIN CERTIFICATE-----' not in ca or 'PRIVATE KEY' in ca)):
        raise ValueError('Укажите сертификат CA в формате PEM')
    return {'host': host, 'domain': domain, 'user': user, 'password': password, 'ca': ca,
            'base_dn': ','.join(f'DC={part}' for part in domain.split('.'))}


def check_connection(settings):
    host = settings['host']
    tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_data=settings['ca'] or None, valid_names=[host])
    server = Server(host, port=636, use_ssl=True, tls=tls, get_info=ALL, connect_timeout=6)
    conn = Connection(server, user=settings['user'], password=settings['password'], receive_timeout=8,
                      auto_referrals=False)
    try:
        if not conn.bind():
            raise ValueError('AD отклонил вход сервисной учётки')
        context = (server.info.other.get('defaultNamingContext') or [''])[0] if server.info else ''
        if context.lower() != settings['base_dn'].lower() or not conn.search(
                settings['base_dn'], '(objectClass=domain)', search_scope=BASE, attributes=[]):
            raise ValueError('Проверьте DNS-имя домена и права чтения сервисной учётки')
    finally:
        conn.unbind()


def apply_settings(app, settings):
    host = settings['host']
    ad_utils.AD_SERVER = f'ldaps://[{host}]' if ':' in host else f'ldaps://{host}'
    ad_utils.AD_USER = settings['user']
    ad_utils.AD_PASSWORD = settings['password']
    ad_utils.AD_DOMAIN = settings['domain']
    ad_utils.BASE_DN = settings['base_dn']
    ad_utils.USERS_OU = f'OU=NewUsers,{ad_utils.BASE_DN}'
    ad_utils.GROUPS_OU = f'OU=Groups,{ad_utils.BASE_DN}'
    ad_utils.DISABLED_OU = f'OU=Disabled,{ad_utils.BASE_DN}'
    ad_utils.AD_CA_CERTS_FILE = None
    ad_utils.AD_CA_CERTS_DATA = settings['ca'] or None
    ad_utils.DRY_RUN = False
    app.config['AD_SYNC_CHANGES'] = True


def save_settings(app, settings):
    cipher = app.extensions.get('employee_password_cipher')
    if cipher is None:
        raise RuntimeError('Сначала настройте ключ шифрования EMPLOYEE_PASSWORD_KEY')
    folder = Path(os.environ.get('DOMAIN_SETUP_DIR') or app.instance_path)
    folder.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='ad-setup-', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(cipher.encrypt(json.dumps(settings).encode()))
        os.replace(temp, folder / 'ad-setup.enc')
    finally:
        Path(temp).unlink(missing_ok=True)


def load_settings(app):
    path = Path(os.environ.get('DOMAIN_SETUP_DIR') or app.instance_path) / 'ad-setup.enc'
    if path.is_file():
        cipher = app.extensions['employee_password_cipher']
        apply_settings(app, json.loads(cipher.decrypt(path.read_bytes())))
