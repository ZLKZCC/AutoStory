from config.store import conf
from cryptography.fernet import Fernet


def get_cipher_suite():
    if not conf.KEY_FILE_PATH.exists():
        # 第一次启动：生成密钥
        key = Fernet.generate_key()
        with open(conf.KEY_FILE_PATH, "wb") as f:
            f.write(key)
    else:
        # 后续启动：读取密钥
        # 如果文件存在，建议检查权限是否符合安全要求（此处省略检查逻辑）
        with open(conf.KEY_FILE_PATH, "rb") as f:
            key = f.read()

    return Fernet(key)


def encrypt_text(plain_text: str) -> str:
    if not plain_text:
        return plain_text
    cipher = get_cipher_suite()
    return cipher.encrypt(plain_text.encode()).decode()


def decrypt_text(cipher_text: str) -> str:
    if not cipher_text:
        return cipher_text
    cipher = get_cipher_suite()
    return cipher.decrypt(cipher_text.encode()).decode()
