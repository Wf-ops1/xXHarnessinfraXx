"""Gerenciamento de trava (Lease Lock) e Fencing Tokens para concorrência de índice."""


class LeaseManager:
    """Garante concorrência segura com trava de leitor/escritor via fencing token."""

    def __init__(self) -> None:
        self._current_lease: str | None = None
        self._token_counter: int = 0

    def acquire_lease(self, client_id: str) -> int:
        self._token_counter += 1
        self._current_lease = client_id
        return self._token_counter

    def release_lease(self, client_id: str) -> bool:
        if self._current_lease == client_id:
            self._current_lease = None
            return True
        return False
