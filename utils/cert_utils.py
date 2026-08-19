# utils/cert_utils.py（Ctrl 侧）
"""Ctrl TLS 证书管理：自签 CA + Ctrl 服务端证书。

TOFU 方案中 Ctrl 是「单证书双角色」：
- WSS 服务器证书（Node→Ctrl WSS 连接，Node 校验 Ctrl）
- HTTPS mTLS 客户端证书（Ctrl→Node 操作通道，Node 校验调用者）

Node 侧信任 Ctrl 的方式：保存本模块生成的 Ctrl CA 证书（或 Ctrl 证书指纹），
由部署时人工拷贝到 Node（`NODE_CTRL_CA_FILE`），不在线上流转。

证书默认放在 CtrKernel/certs 下，可用环境变量覆盖路径。
"""
import datetime
import ipaddress
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger(__name__)

# 默认证书目录：本文件上两级的 CtrKernel/certs
_DEFAULT_CERTS_DIR = Path(__file__).resolve().parents[1] / "certs"


@dataclass(frozen=True)
class CtrlCertificateFiles:
    ca_cert: Path
    ca_key: Path
    cert_file: Path
    key_file: Path


def _certs_dir() -> Path:
    return Path(os.getenv("CTRL_CERTS_DIR", str(_DEFAULT_CERTS_DIR)))


def _certificate_files() -> CtrlCertificateFiles:
    d = _certs_dir()
    return CtrlCertificateFiles(
        ca_cert=Path(os.getenv("CTRL_CA_CERT_FILE", str(d / "ctrl_ca.pem"))),
        ca_key=Path(os.getenv("CTRL_CA_KEY_FILE", str(d / "ctrl_ca_key.pem"))),
        cert_file=Path(os.getenv("CTRL_CERT_FILE", str(d / "ctrl_cert.pem"))),
        key_file=Path(os.getenv("CTRL_KEY_FILE", str(d / "ctrl_key.pem"))),
    )


def _generate_self_signed_ca(ca_cert: Path, ca_key: Path, common_name: str) -> None:
    """生成自签 CA（仅本地私有信任域，用于签发 Ctrl 证书）。"""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=int(os.getenv("CTRL_CA_VALID_DAYS", "3650"))))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=True,
            crl_sign=True, encipher_only=False, decipher_only=False,
        ), critical=True)
        .sign(private_key, hashes.SHA256())
    )
    ca_key.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    ca_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _issue_ctrl_cert(ca_cert: Path, ca_key: Path, cert_file: Path, key_file: Path, common_name: str) -> None:
    """用 CA 签发 Ctrl 服务端证书（serverAuth + clientAuth，双角色一张证书）。"""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_cert_obj = x509.load_pem_x509_certificate(ca_cert.read_bytes())
    ca_key_obj = serialization.load_pem_private_key(ca_key.read_bytes(), password=None)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert_obj.subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=int(os.getenv("CTRL_CERT_VALID_DAYS", "3650"))))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage(
                [x509.oid.ExtendedKeyUsageOID.SERVER_AUTH, x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH]
            ),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(ca_key_obj, hashes.SHA256())
    )
    key_file.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def ensure_ctrl_certificates() -> CtrlCertificateFiles:
    """确保 Ctrl 有一套 CA + 服务端证书（缺失即生成，幂等）。"""
    files = _certificate_files()
    if files.cert_file.exists() and files.key_file.exists():
        return files

    files.ca_cert.parent.mkdir(parents=True, exist_ok=True)
    if not (files.ca_cert.exists() and files.ca_key.exists()):
        _generate_self_signed_ca(files.ca_cert, files.ca_key, os.getenv("CTRL_CA_COMMON_NAME", "FuxiYu Ctrl CA"))
        logger.info("generated Ctrl CA: %s", files.ca_cert)
    _issue_ctrl_cert(
        files.ca_cert, files.ca_key, files.cert_file, files.key_file,
        os.getenv("CTRL_CERT_COMMON_NAME", "FuxiYu Ctrl Server"),
    )
    logger.info("generated Ctrl server cert: %s", files.cert_file)
    return files


def ctrl_certificate_paths() -> CtrlCertificateFiles:
    """返回 Ctrl 证书文件路径（不触发生成；缺失时由部署流程先调用 ensure_*）。"""
    return _certificate_files()


def certificate_sha256_fingerprint(cert_file: Path) -> str:
    """计算证书文件的 SHA-256 指纹（十六进制小写冒号分隔）。"""
    cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
    return der_cert_sha256_fingerprint(cert.public_bytes(serialization.Encoding.DER))


def der_cert_sha256_fingerprint(cert_der: bytes) -> str:
    """计算 DER 证书的 SHA-256 指纹（十六进制小写冒号分隔）。TOFU pin 依据。"""
    digest = hashes.Hash(hashes.SHA256())
    digest.update(cert_der)
    return digest.finalize().hex()


def der_cert_to_pem(cert_der: bytes) -> bytes:
    """DER 证书 → PEM（导出对端证书为 pin 文件用）。"""
    return x509.load_der_x509_certificate(cert_der).public_bytes(serialization.Encoding.PEM)
