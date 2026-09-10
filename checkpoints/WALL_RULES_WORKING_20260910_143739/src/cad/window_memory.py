from __future__ import annotations


class WindowMemory:
    def has_trusted_seed(self) -> bool:
        return False

    def get_trusted_descriptor(self):
        return None

    def learn_trusted_seed(self, descriptor: dict) -> bool:
        return False

    def trusted_similarity(self, descriptor: dict) -> float:
        return 0.0

    def best_similarity(self, descriptor: dict) -> float:
        return 0.0

    def learn(self, descriptor: dict) -> bool:
        return False
