#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2016, Guillaume Grossetie <ggrossetie@yuzutech.fr>
# Copyright: (c) 2021, quidame <quidame@poivron.org>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


DOCUMENTATION = '''
---
module: java_keystore
short_description: Create a Java keystore in JKS format
description:
  - Bundle a x509 certificate and its private key into a Java Keystore in JKS format.
options:
  name:
    description:
      - Name of the certificate in the keystore.
      - If the provided name does not exist in the keystore, the module
        will re-create the keystore. This behavior changed in community.general 3.0.0,
        before that the module would fail when the name did not match.
    type: str
    required: true
  certificate:
    description:
      - Content of the certificate used to create the keystore.
      - If the fingerprint of the provided certificate does not match the
        fingerprint of the certificate bundled in the keystore, the keystore
        is regenerated with the provided certificate.
      - Exactly one of I(certificate) or I(certificate_path) is required.
    type: str
  certificate_path:
    description:
      - Location of the certificate used to create the keystore.
      - If the fingerprint of the provided certificate does not match the
        fingerprint of the certificate bundled in the keystore, the keystore
        is regenerated with the provided certificate.
      - Exactly one of I(certificate) or I(certificate_path) is required.
    type: path
    version_added: '3.0.0'
  private_key:
    description:
      - Content of the private key used to create the keystore.
      - Exactly one of I(private_key) or I(private_key_path) is required.
    type: str
  private_key_path:
    description:
      - Location of the private key used to create the keystore.
      - Exactly one of I(private_key) or I(private_key_path) is required.
    type: path
    version_added: '3.0.0'
  private_key_passphrase:
    description:
      - Passphrase used to read the private key, if required.
    type: str
    version_added: '0.2.0'
  password:
    description:
      - Password that should be used to secure the keystore.
      - If the provided password fails to unlock the keystore, the module
        will re-create the keystore with the new passphrase. This behavior
        changed in community.general 3.0.0, before that the module would fail
        when the password did not match.
    type: str
    required: true
  dest:
    description:
      - Absolute path of the generated keystore.
    type: path
    required: true
  force:
    description:
      - Keystore is created even if it already exists.
    type: bool
    default: 'no'
  owner:
    description:
      - Name of the user that should own jks file.
    required: false
  group:
    description:
      - Name of the group that should own jks file.
    required: false
  mode:
    description:
      - Mode the file should be.
    required: false
  ssl_backend:
    description:
      - Backend for loading private keys and certificates.
    type: str
    default: openssl
    choices:
      - openssl
      - cryptography
    version_added: 3.1.0
requirements:
  - openssl in PATH (when I(ssl_backend=openssl))
  - keytool in PATH
  - cryptography >= 3.0 (when I(ssl_backend=cryptography))
author:
  - Guillaume Grossetie (@Mogztter)
  - quidame (@quidame)
extends_documentation_fragment:
  - files
seealso:
  - module: community.general.java_cert
notes:
  - I(certificate) and I(private_key) require that their contents are available
    on the controller (either inline in a playbook, or with the C(file) lookup),
    while I(certificate_path) and I(private_key_path) require that the files are
    available on the target host.
'''

EXAMPLES = '''
- name: Create a keystore for the given certificate/private key pair (inline)
  community.general.java_keystore:
    name: example
    certificate: |
      -----BEGIN CERTIFICATE-----
      h19dUZ2co2fI/ibYiwxWk4aeNE6KWvCaTQOMQ8t6Uo2XKhpL/xnjoAgh1uCQN/69
      MG+34+RhUWzCfdZH7T8/qDxJw2kEPKluaYh7KnMsba+5jHjmtzix5QIDAQABo4IB
      -----END CERTIFICATE-----
    private_key: |
      -----BEGIN RSA PRIVATE KEY-----
      DBVFTEVDVFJJQ0lURSBERSBGUkFOQ0UxFzAVBgNVBAsMDjAwMDIgNTUyMDgxMzE3
      GLlDNMw/uHyME7gHFsqJA7O11VY6O5WQ4IDP3m/s5ZV6s+Nn6Lerz17VZ99
      -----END RSA PRIVATE KEY-----
    password: changeit
    dest: /etc/security/keystore.jks

- name: Create a keystore for the given certificate/private key pair (with files on controller)
  community.general.java_keystore:
    name: example
    certificate: "{{ lookup('file', '/path/to/certificate.crt') }}"
    private_key: "{{ lookup('file', '/path/to/private.key') }}"
    password: changeit
    dest: /etc/security/keystore.jks

- name: Create a keystore for the given certificate/private key pair (with files on target host)
  community.general.java_keystore:
    name: snakeoil
    certificate_path: /etc/ssl/certs/ssl-cert-snakeoil.pem
    private_key_path: /etc/ssl/private/ssl-cert-snakeoil.key
    password: changeit
    dest: /etc/security/keystore.jks
'''

RETURN = '''
msg:
  description: Output from stdout of keytool/openssl command after execution of given command or an error.
  returned: changed and failure
  type: str
  sample: "Unable to find the current certificate fingerprint in ..."

rc:
  description: keytool/openssl command execution return value
  returned: changed and failure
  type: int
  sample: "0"

cmd:
  description: Executed command to get action done
  returned: changed and failure
  type: str
  sample: "/usr/bin/openssl x509 -noout -in /tmp/user/1000/tmp8jd_lh23 -fingerprint -sha256"
'''


import os
import re
import tempfile

from ansible.module_utils.six import PY2
from ansible.module_utils.basic import AnsibleModule, missing_required_lib
from ansible.module_utils.common.text.converters import to_bytes, to_native, to_text

try:
    from cryptography.hazmat.primitives.serialization.pkcs12 import serialize_key_and_certificates
    from cryptography.hazmat.primitives.serialization import (
        BestAvailableEncryption,
        NoEncryption,
        load_pem_private_key,
        load_der_private_key,
    )
    from cryptography.x509 import (
        load_pem_x509_certificate,
        load_der_x509_certificate,
    )
    from cryptography.hazmat.primitives import hashes
    from cryptography.exceptions import UnsupportedAlgorithm
    from cryptography.hazmat.backends.openssl import backend
    HAS_CRYPTOGRAPHY_PKCS12 = True
except ImportError:
    HAS_CRYPTOGRAPHY_PKCS12 = False


class JavaKeystore:
    def __init__(self, module):
        self.module = module

        self.keytool_bin = module.get_bin_path('keytool', True)

        self.certificate = module.params['certificate']
        self.keypass = module.params['private_key_passphrase']
        self.keystore_path = module.params['dest']
        self.name = module.params['name']
        self.password = module.params['password']
        self.private_key = module.params['private_key']
        self.ssl_backend = module.params['ssl_backend']

        if self.ssl_backend == 'openssl':
            self.openssl_bin = module.get_bin_path('openssl', True)
        else:
            if not HAS_CRYPTOGRAPHY_PKCS12:
                self.module.fail_json(msg=missing_required_lib('cryptography >= 3.0'))

        if module.params['certificate_path'] is None:
            self.certificate_path = create_file(self.certificate)
            self.module.add_cleanup_file(self.certificate_path)
        else:
            self.certificate_path = module.params['certificate_path']

        if module.params['private_key_path'] is None:
            self.private_key_path = create_file(self.private_key)
            self.module.add_cleanup_file(self.private_key_path)
        else:
            self.private_key_path = module.params['private_key_path']

    def update_permissions(self):
        try:
            file_args = self.module.load_file_common_arguments(self.module.params, path=self.keystore_path)
        except TypeError:
            # The path argument is only supported in Ansible-base 2.10+. Fall back to
            # pre-2.10 behavior for older Ansible versions.
            self.module.params['path'] = self.keystore_path
            file_args = self.module.load_file_common_arguments(self.module.params)
        return self.module.set_fs_attributes_if_different(file_args, False)

    def read_certificate_fingerprint(self, cert_format='PEM'):
        if self.ssl_backend == 'cryptography':
            if cert_format == 'PEM':
                cert_loader = load_pem_x509_certificate
            else:
                cert_loader = load_der_x509_certificate

            try:
                with open(self.certificate_path, 'rb') as cert_file:
                    cert = cert_loader(
                        cert_file.read(),
                        backend=backend
                    )
            except (OSError, ValueError) as e:
                self.module.fail_json(msg="Unable to read the provided certificate: %s" % to_native(e))

            fp = hex_decode(cert.fingerprint(hashes.SHA256())).upper()
            fingerprint = ':'.join([fp[i:i + 2] for i in range(0, len(fp), 2)])
        else:
            current_certificate_fingerprint_cmd = [
                self.openssl_bin, "x509", "-noout", "-in", self.certificate_path, "-fingerprint", "-sha256"
            ]
            (rc, current_certificate_fingerprint_out, current_certificate_fingerprint_err) = self.module.run_command(
                current_certificate_fingerprint_cmd,
                environ_update=None,
                check_rc=False
            )
            if rc != 0:
                return self.module.fail_json(
                    msg=current_certificate_fingerprint_out,
                    err=current_certificate_fingerprint_err,
                    cmd=current_certificate_fingerprint_cmd,
                    rc=rc
                )

            current_certificate_match = re.search(r"=([\w:]+)", current_certificate_fingerprint_out)
            if not current_certificate_match:
                return self.module.fail_json(
                    msg="Unable to find the current certificate fingerprint in %s" % (
                        current_certificate_fingerprint_out
                    ),
                    cmd=current_certificate_fingerprint_cmd,
                    rc=rc
                )

            fingerprint = current_certificate_match.group(1)
        return fingerprint

    def read_stored_certificate_fingerprint(self):
        stored_certificate_fingerprint_cmd = [
            self.keytool_bin, "-list", "-alias", self.name, "-keystore",
            self.keystore_path, "-storepass:env", "STOREPASS", "-v"
        ]
        (rc, stored_certificate_fingerprint_out, stored_certificate_fingerprint_err) = self.module.run_command(
            stored_certificate_fingerprint_cmd, environ_update=dict(STOREPASS=self.password), check_rc=False)
        if rc != 0:
            if "keytool error: java.lang.Exception: Alias <%s> does not exist" % self.name \
                    in stored_certificate_fingerprint_out:
                return "alias mismatch"
            if re.match(
                    r'keytool error: java\.io\.IOException: ' +
                    '[Kk]eystore( was tampered with, or)? password was incorrect',
                    stored_certificate_fingerprint_out
            ):
                return "password mismatch"
            return self.module.fail_json(
                msg=stored_certificate_fingerprint_out,
                err=stored_certificate_fingerprint_err,
                cmd=stored_certificate_fingerprint_cmd,
                rc=rc
            )

        stored_certificate_match = re.search(r"SHA256: ([\w:]+)", stored_certificate_fingerprint_out)
        if not stored_certificate_match:
            return self.module.fail_json(
                msg="Unable to find the stored certificate fingerprint in %s" % stored_certificate_fingerprint_out,
                cmd=stored_certificate_fingerprint_cmd,
                rc=rc
            )

        return stored_certificate_match.group(1)

    def cert_changed(self):
        current_certificate_fingerprint = self.read_certificate_fingerprint()
        stored_certificate_fingerprint = self.read_stored_certificate_fingerprint()
        return current_certificate_fingerprint != stored_certificate_fingerprint

    def cryptography_create_pkcs12_bundle(self, keystore_p12_path, key_format='PEM', cert_format='PEM'):
        if key_format == 'PEM':
            key_loader = load_pem_private_key
        else:
            key_loader = load_der_private_key

        if cert_format == 'PEM':
            cert_loader = load_pem_x509_certificate
        else:
            cert_loader = load_der_x509_certificate

        try:
            with open(self.private_key_path, 'rb') as key_file:
                private_key = key_loader(
                    key_file.read(),
                    password=to_bytes(self.keypass),
                    backend=backend
                )
        except TypeError:
            # Re-attempt with no password to match existing behavior
            try:
                with open(self.private_key_path, 'rb') as key_file:
                    private_key = key_loader(
                        key_file.read(),
                        password=None,
                        backend=backend
                    )
            except (OSError, TypeError, ValueError, UnsupportedAlgorithm) as e:
                self.module.fail_json(
                    msg="The following error occurred while loading the provided private_key: %s" % to_native(e)
                )
        except (OSError, ValueError, UnsupportedAlgorithm) as e:
            self.module.fail_json(
                msg="The following error occurred while loading the provided private_key: %s" % to_native(e)
            )
        try:
            with open(self.certificate_path, 'rb') as cert_file:
                cert = cert_loader(
                    cert_file.read(),
                    backend=backend
                )
        except (OSError, ValueError, UnsupportedAlgorithm) as e:
            self.module.fail_json(
                msg="The following error occurred while loading the provided certificate: %s" % to_native(e)
            )

        if self.password:
            encryption = BestAvailableEncryption(to_bytes(self.password))
        else:
            encryption = NoEncryption()

        pkcs12_bundle = serialize_key_and_certificates(
            name=to_bytes(self.name),
            key=private_key,
            cert=cert,
            cas=None,
            encryption_algorithm=encryption
        )

        with open(keystore_p12_path, 'wb') as p12_file:
            p12_file.write(pkcs12_bundle)

    def openssl_create_pkcs12_bundle(self, keystore_p12_path):
        export_p12_cmd = [self.openssl_bin, "pkcs12", "-export", "-name", self.name, "-in", self.certificate_path,
                          "-inkey", self.private_key_path, "-out", keystore_p12_path, "-passout", "stdin"]

        # when keypass is provided, add -passin
        cmd_stdin = ""
        if self.keypass:
            export_p12_cmd.append("-passin")
            export_p12_cmd.append("stdin")
            cmd_stdin = "%s\n" % self.keypass
        cmd_stdin += "%s\n%s" % (self.password, self.password)

        (rc, export_p12_out, dummy) = self.module.run_command(
            export_p12_cmd, data=cmd_stdin, environ_update=None, check_rc=False
        )

        if rc != 0:
            self.module.fail_json(msg=export_p12_out, cmd=export_p12_cmd, rc=rc)

    def create(self):
        if self.module.check_mode:
            return {'changed': True}

        if os.path.exists(self.keystore_path):
            os.remove(self.keystore_path)

        keystore_p12_path = create_path()
        self.module.add_cleanup_file(keystore_p12_path)

        if self.ssl_backend == 'cryptography':
            self.cryptography_create_pkcs12_bundle(keystore_p12_path)
        else:
            self.openssl_create_pkcs12_bundle(keystore_p12_path)

        import_keystore_cmd = [self.keytool_bin, "-importkeystore",
                               "-destkeystore", self.keystore_path,
                               "-srckeystore", keystore_p12_path,
                               "-srcstoretype", "pkcs12",
                               "-alias", self.name,
                               "-deststorepass:env", "STOREPASS",
                               "-srcstorepass:env", "STOREPASS",
                               "-noprompt"]

        (rc, import_keystore_out, dummy) = self.module.run_command(
            import_keystore_cmd, data=None, environ_update=dict(STOREPASS=self.password), check_rc=False
        )
        if rc != 0:
            return self.module.fail_json(msg=import_keystore_out, cmd=import_keystore_cmd, rc=rc)

        self.update_permissions()
        return {
            'changed': True,
            'msg': import_keystore_out,
            'cmd': import_keystore_cmd,
            'rc': rc
        }

    def exists(self):
        return os.path.exists(self.keystore_path)


# Utility functions
def create_path():
    dummy, tmpfile = tempfile.mkstemp()
    os.remove(tmpfile)
    return tmpfile


def create_file(content):
    tmpfd, tmpfile = tempfile.mkstemp()
    with os.fdopen(tmpfd, 'w') as f:
        f.write(content)
    return tmpfile


def hex_decode(s):
    if PY2:
        return s.decode('hex')
    else:
        return s.hex()


class ArgumentSpec(object):
    def __init__(self):
        self.supports_check_mode = True
        self.add_file_common_args = True
        argument_spec = dict(
            name=dict(type='str', required=True),
            dest=dict(type='path', required=True),
            certificate=dict(type='str', no_log=True),
            certificate_path=dict(type='path'),
            private_key=dict(type='str', no_log=True),
            private_key_path=dict(type='path', no_log=False),
            private_key_passphrase=dict(type='str', no_log=True),
            password=dict(type='str', required=True, no_log=True),
            ssl_backend=dict(type='str', default='openssl', choices=['openssl', 'cryptography']),
            force=dict(type='bool', default=False),
        )
        choose_between = (
            ['certificate', 'certificate_path'],
            ['private_key', 'private_key_path'],
        )
        self.argument_spec = argument_spec
        self.required_one_of = choose_between
        self.mutually_exclusive = choose_between


def main():
    spec = ArgumentSpec()
    module = AnsibleModule(
        argument_spec=spec.argument_spec,
        required_one_of=spec.required_one_of,
        mutually_exclusive=spec.mutually_exclusive,
        supports_check_mode=spec.supports_check_mode,
        add_file_common_args=spec.add_file_common_args,
    )
    module.run_command_environ_update = dict(LANG='C', LC_ALL='C', LC_MESSAGES='C')

    result = dict()
    jks = JavaKeystore(module)

    if jks.exists():
        if module.params['force'] or jks.cert_changed():
            result = jks.create()
        else:
            result['changed'] = jks.update_permissions()
    else:
        result = jks.create()

    module.exit_json(**result)


if __name__ == '__main__':
    main()
