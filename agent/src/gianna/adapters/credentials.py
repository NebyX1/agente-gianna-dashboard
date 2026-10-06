"""Only OS secure keyrings; otherwise memory-only, never a plaintext fallback."""

import keyring


class Credentials:
    def __init__(self):
        backend = keyring.get_keyring()
        name = type(backend).__module__ + "." + type(backend).__name__
        self.secure = name in {
            "keyring.backends.Windows.WinVaultKeyring",
            "keyring.backends.macOS.Keyring",
            "keyring.backends.SecretService.Keyring",
        }
        self.backend_name = name
        self.memory = {}

    def put(self, actor, token):
        from uuid import uuid4

        ref = f"idl.tickets.actor.{actor}.{uuid4()}"
        if self.secure:
            keyring.set_password("Gianna", ref, token)
        else:
            self.memory[ref] = token
        return ref

    def get(self, ref):
        return keyring.get_password("Gianna", ref) if self.secure else self.memory.get(ref)

    def delete(self, ref):
        self.memory.pop(ref, None)
        if self.secure:
            try:
                keyring.delete_password("Gianna", ref)
            except keyring.errors.PasswordDeleteError:
                pass
