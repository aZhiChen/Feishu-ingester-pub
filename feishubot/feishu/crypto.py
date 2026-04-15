# -*- coding: utf-8 -*-
"""飞书事件加解密与签名校验"""
import base64
import hashlib

from Crypto.Cipher import AES


def verify_signature(timestamp: str, nonce: str, encrypt_key: str, body: str, signature: str) -> bool:
    """校验飞书请求签名"""
    content = timestamp + nonce + encrypt_key + body
    calculated = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return calculated == signature


def decrypt_event(encrypt_key: str, encrypted_content: str) -> str:
    """
    解密飞书事件
    - Key = SHA256(encrypt_key)
    - IV = 密文前 16 字节
    - AES-256-CBC
    """
    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
    buf = base64.b64decode(encrypted_content)
    if len(buf) < AES.block_size:
        raise ValueError("密文过短")

    iv = buf[:AES.block_size]
    ciphertext = buf[AES.block_size:]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(ciphertext)

    # PKCS7 去填充
    pad_len = decrypted[-1]
    if isinstance(pad_len, int) and 1 <= pad_len <= AES.block_size:
        decrypted = decrypted[:-pad_len]
    plain = decrypted.decode("utf-8")
    # 飞书解密后可能含前后多余字节，提取 JSON 部分
    start = plain.find("{")
    end = plain.rfind("}")
    if start >= 0 and end > start:
        plain = plain[start : end + 1]
    return plain
